import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import grok_register_ttk as app
from proxy_pool import ProxyConnectionError


class StabilityIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.config = dict(app.config)

    def tearDown(self):
        app.config.clear()
        app.config.update(self.config)

    def test_browser_options_apply_registration_proxy(self):
        app.config["proxy"] = "http://127.0.0.1:7897"
        options = app.create_browser_options()
        self.assertTrue(
            any("proxy-server=http://127.0.0.1:7897" in arg for arg in options.arguments)
        )

    def test_cloudflare_interstitial_is_detected(self):
        page = type(
            "Page",
            (),
            {
                "url": "https://accounts.x.ai/sign-up",
                "title": "Cloudflare",
                "html": "<title>Just a moment...</title><div id='cf-chl-widget'></div>",
            },
        )()
        self.assertTrue(app.page_has_cloudflare_interstitial(page))

    def test_normal_signup_page_is_not_treated_as_interstitial(self):
        page = type(
            "Page",
            (),
            {
                "url": "https://accounts.x.ai/sign-up",
                "title": "Create your account",
                "html": "<button>Continue with email</button>",
            },
        )()
        self.assertFalse(app.page_has_cloudflare_interstitial(page))

    def test_headless_fallback_switches_to_minimized_mode(self):
        app.config["browser_headless"] = True
        app.config["browser_minimized"] = False
        with patch("grok_register_ttk.restart_browser") as restart:
            app.fallback_from_headless()
        self.assertFalse(app.config["browser_headless"])
        self.assertTrue(app.config["browser_minimized"])
        restart.assert_called_once()

    def test_http_proxy_failure_does_not_retry_direct(self):
        app.config["proxy"] = "http://127.0.0.1:7897"
        with patch("grok_register_ttk.requests.get") as request:
            request.side_effect = RuntimeError("Could not connect to proxy")
            with self.assertRaises(ProxyConnectionError):
                app.http_get("https://example.com")
        self.assertEqual(request.call_count, 1)
        self.assertIn("proxies", request.call_args.kwargs)

    def test_local_token_pool_is_safe_under_concurrency(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "token.json"
            app.config["grok2api_local_token_file"] = str(path)
            app.config["grok2api_pool_name"] = "ssoBasic"
            barrier = threading.Barrier(20)

            def worker(index):
                barrier.wait()
                app.add_token_to_grok2api_local_pool(f"token-{index}")

            threads = [threading.Thread(target=worker, args=(index,)) for index in range(20)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            payload = json.loads(path.read_text(encoding="utf-8"))
            values = {item["token"] for item in payload["ssoBasic"]}
            self.assertEqual(values, {f"token-{index}" for index in range(20)})

    def test_cpa_timeout_requests_cancel_and_waits_for_worker(self):
        cancelled = threading.Event()

        def exporter(email, password, **kwargs):
            cancel = kwargs["cancel_callback"]
            while not cancel():
                time.sleep(0.005)
            cancelled.set()
            return {"ok": False, "error": "cancelled"}

        result = app.run_cpa_export_with_timeout(
            "a@example.com",
            "password",
            timeout=0.03,
            exporter=exporter,
        )
        self.assertTrue(cancelled.is_set())
        self.assertEqual(result["error"], "cancelled")


if __name__ == "__main__":
    unittest.main()
