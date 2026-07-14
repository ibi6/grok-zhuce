import unittest
import threading
from unittest.mock import Mock

from proxy_pool import (
    NoProxyAvailable,
    ProxyPoolManager,
    normalize_proxy_url,
    parse_proxy_text,
    redact_proxy_url,
    is_proxy_connection_error,
)


class ProxyPoolTests(unittest.TestCase):
    def test_import_ignores_comments_and_deduplicates(self):
        entries = parse_proxy_text(
            "# local\n127.0.0.1:7897\nhttp://127.0.0.1:7897\nsocks5://127.0.0.1:1080\n"
        )
        self.assertEqual([entry["url"] for entry in entries], [
            "http://127.0.0.1:7897",
            "socks5://127.0.0.1:1080",
        ])

    def test_rejects_unsupported_or_authenticated_proxy(self):
        with self.assertRaises(ValueError):
            normalize_proxy_url("vmess://example")
        with self.assertRaises(ValueError):
            normalize_proxy_url("http://user:pass@example.com:8080")

    def test_manual_selection_wins(self):
        manager = ProxyPoolManager(
            ["http://127.0.0.1:7897", "http://127.0.0.1:7898"],
            selected_url="http://127.0.0.1:7898",
        )
        manager.mark_success("http://127.0.0.1:7897", latency_ms=5)
        self.assertEqual(manager.select(), "http://127.0.0.1:7898")

    def test_healthy_low_latency_selection(self):
        manager = ProxyPoolManager([
            "http://127.0.0.1:7897",
            "http://127.0.0.1:7898",
        ])
        manager.mark_success("http://127.0.0.1:7897", latency_ms=80)
        manager.mark_success("http://127.0.0.1:7898", latency_ms=20)
        self.assertEqual(manager.select(), "http://127.0.0.1:7898")

    def test_runtime_health_snapshot_is_used(self):
        manager = ProxyPoolManager.from_config(
            {
                "proxy_pool": [
                    {"url": "http://127.0.0.1:7897"},
                    {"url": "http://127.0.0.1:7898"},
                ]
            },
            runtime_states={
                "http://127.0.0.1:7897": {"healthy": True, "latency_ms": 90},
                "http://127.0.0.1:7898": {"healthy": True, "latency_ms": 12},
            },
        )
        self.assertEqual(manager.select(), "http://127.0.0.1:7898")

    def test_failure_enters_cooldown_and_is_not_selected(self):
        manager = ProxyPoolManager(
            ["http://127.0.0.1:7897", "http://127.0.0.1:7898"],
            failure_threshold=1,
            cooldown_seconds=60,
        )
        manager.mark_failure("http://127.0.0.1:7897", "connection refused", now=100)
        self.assertEqual(manager.select(now=101), "http://127.0.0.1:7898")

    def test_all_unavailable_never_falls_back_direct(self):
        manager = ProxyPoolManager(["http://127.0.0.1:7897"], failure_threshold=1)
        manager.mark_failure("http://127.0.0.1:7897", "connection refused", now=100)
        with self.assertRaises(NoProxyAvailable):
            manager.select(now=101)

    def test_proxy_is_retried_after_cooldown(self):
        manager = ProxyPoolManager(
            ["http://127.0.0.1:7897"], failure_threshold=1, cooldown_seconds=60
        )
        manager.mark_failure("http://127.0.0.1:7897", "connection refused", now=100)
        self.assertEqual(manager.select(now=161), "http://127.0.0.1:7897")

    def test_single_proxy_can_retry_before_failure_threshold(self):
        manager = ProxyPoolManager(
            ["http://127.0.0.1:7897"], failure_threshold=2, cooldown_seconds=60
        )
        self.assertEqual(
            manager.next_after_failure("http://127.0.0.1:7897", "connection refused"),
            "http://127.0.0.1:7897",
        )

    def test_health_check_treats_http_response_as_reachable(self):
        response = Mock(status_code=403)
        session = Mock()
        session.get.return_value = response
        manager = ProxyPoolManager(["http://127.0.0.1:7897"])
        state = manager.check("http://127.0.0.1:7897", session=session)
        self.assertTrue(state.healthy)
        self.assertIsNotNone(state.latency_ms)

    def test_proxy_redaction_hides_password(self):
        self.assertEqual(
            redact_proxy_url("http://user:secret@example.com:8080"),
            "http://user:***@example.com:8080",
        )

    def test_target_connection_error_is_not_misclassified_as_proxy_error(self):
        self.assertFalse(
            is_proxy_connection_error(
                "connection refused by api.example.com:443",
                "http://127.0.0.1:7897",
            )
        )
        self.assertTrue(
            is_proxy_connection_error(
                "Failed to connect to 127.0.0.1:7897",
                "http://127.0.0.1:7897",
            )
        )

    def test_check_all_runs_enabled_proxies_concurrently(self):
        barrier = threading.Barrier(2)
        lock = threading.Lock()
        active = 0
        max_active = 0

        class ConcurrentSession:
            @staticmethod
            def get(*args, **kwargs):
                nonlocal active, max_active
                with lock:
                    active += 1
                    max_active = max(max_active, active)
                try:
                    barrier.wait(timeout=1)
                    return Mock(status_code=200)
                finally:
                    with lock:
                        active -= 1

        manager = ProxyPoolManager([
            "http://127.0.0.1:7897",
            "http://127.0.0.1:7898",
        ])
        states = manager.check_all(session=ConcurrentSession(), timeout=1, max_workers=2)

        self.assertEqual(max_active, 2)
        self.assertTrue(all(state.healthy for state in states.values()))

    def test_check_all_skips_disabled_proxies(self):
        session = Mock()
        session.get.return_value = Mock(status_code=200)
        manager = ProxyPoolManager([
            {"url": "http://127.0.0.1:7897", "enabled": True},
            {"url": "http://127.0.0.1:7898", "enabled": False},
        ])

        states = manager.check_all(session=session)

        self.assertEqual(session.get.call_count, 1)
        self.assertTrue(states["http://127.0.0.1:7897"].healthy)
        self.assertIsNone(states["http://127.0.0.1:7898"].healthy)

    def test_check_all_isolates_individual_proxy_failures(self):
        class MixedSession:
            @staticmethod
            def get(url, *, proxies, **kwargs):
                if proxies["https"].endswith(":7897"):
                    raise OSError("connection refused")
                return Mock(status_code=403)

        manager = ProxyPoolManager([
            "http://127.0.0.1:7897",
            "http://127.0.0.1:7898",
        ])

        states = manager.check_all(session=MixedSession(), max_workers=2)

        self.assertFalse(states["http://127.0.0.1:7897"].healthy)
        self.assertTrue(states["http://127.0.0.1:7898"].healthy)


if __name__ == "__main__":
    unittest.main()
