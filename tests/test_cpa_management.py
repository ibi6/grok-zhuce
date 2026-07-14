import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cpa_management as cpa
import grok_register_ttk as app
from cpa_export import export_cpa_xai_for_account
from modern_ui import ModernUIBuilder


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = {"status": "ok"} if payload is None else payload
        self.headers = headers or {}

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class SequenceSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class CPAManagementTests(unittest.TestCase):
    def tearDown(self):
        cpa.set_session_management_key("")

    def test_normalizes_supported_management_urls(self):
        expected = "https://cpa.example.com/v0/management/auth-files"
        self.assertEqual(cpa.normalize_management_url("https://cpa.example.com"), expected)
        self.assertEqual(cpa.normalize_management_url("https://cpa.example.com/v0/management"), expected)
        self.assertEqual(cpa.normalize_management_url(expected), expected)

    def test_remote_http_is_rejected_but_loopback_is_allowed(self):
        with self.assertRaises(cpa.CPAManagementConfigError):
            cpa.normalize_management_url("http://cpa.example.com")
        self.assertEqual(
            cpa.normalize_management_url("http://127.0.0.1:8317"),
            "http://127.0.0.1:8317/v0/management/auth-files",
        )

    def test_url_rejects_embedded_credentials_and_query(self):
        with self.assertRaises(cpa.CPAManagementConfigError):
            cpa.normalize_management_url("https://user:pass@cpa.example.com")
        with self.assertRaises(cpa.CPAManagementConfigError):
            cpa.normalize_management_url("https://cpa.example.com?key=secret")

    @unittest.skipUnless(os.name == "nt", "DPAPI is Windows-only")
    def test_dpapi_round_trip_does_not_store_plaintext(self):
        encrypted = cpa.protect_secret("management-secret")
        self.assertTrue(encrypted.startswith("dpapi:"))
        self.assertNotIn("management-secret", encrypted)
        self.assertEqual(cpa.unprotect_secret(encrypted), "management-secret")

    def test_management_key_priority_is_env_then_explicit_then_session(self):
        cpa.set_session_management_key("session-key")
        with patch.dict(os.environ, {"CPA_MANAGEMENT_KEY": "env-key"}):
            self.assertEqual(cpa.resolve_management_key({}, explicit_key="field-key"), "env-key")
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(cpa.resolve_management_key({}, explicit_key="field-key"), "field-key")
            self.assertEqual(cpa.resolve_management_key({}), "session-key")

    def test_persisted_config_never_contains_plaintext_key(self):
        cfg = {}
        with patch("cpa_management.protect_secret", return_value="dpapi:encrypted"):
            cpa.persist_management_key(cfg, "plain-management-key", remember=True)
        self.assertEqual(cfg["cpa_management_key_encrypted"], "dpapi:encrypted")
        self.assertNotIn("plain-management-key", json.dumps(cfg))

        cpa.persist_management_key(cfg, "session-only-key", remember=False)
        self.assertEqual(cfg["cpa_management_key_encrypted"], "")

    def test_connection_uses_get_and_bearer_auth(self):
        session = SequenceSession([
            FakeResponse(200, {"files": [{"name": "xai-a.json"}]}, {"X-CPA-VERSION": "7.0"})
        ])
        result = cpa.test_connection(
            "https://cpa.example.com",
            key="secret-key",
            session=session,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["version"], "7.0")
        method, url, kwargs = session.calls[0]
        self.assertEqual(method, "GET")
        self.assertTrue(url.endswith("/v0/management/auth-files"))
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret-key")

    def test_connection_error_never_contains_key(self):
        session = SequenceSession([OSError("network includes secret-key")])
        with self.assertRaises(cpa.CPAManagementError) as caught:
            cpa.test_connection(
                "https://cpa.example.com",
                key="secret-key",
                session=session,
            )
        self.assertNotIn("secret-key", str(caught.exception))

    def _auth_file(self, directory):
        path = Path(directory) / "xai-user@example.com.json"
        path.write_text(json.dumps({"type": "xai", "email": "user@example.com"}), encoding="utf-8")
        return path

    def test_upload_posts_raw_json_with_safe_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._auth_file(tmp)
            session = SequenceSession([FakeResponse(200)])
            result = cpa.upload_auth_file(
                path,
                config={"cpa_management_base_url": "https://cpa.example.com"},
                key="secret-key",
                session=session,
            )
        self.assertTrue(result["ok"])
        method, _, kwargs = session.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(kwargs["params"], {"name": "xai-user@example.com.json"})
        self.assertEqual(json.loads(kwargs["data"]), {"type": "xai", "email": "user@example.com"})
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret-key")

    def test_transient_failures_retry_but_auth_errors_do_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._auth_file(tmp)
            sleep = Mock()
            transient = SequenceSession([FakeResponse(500), FakeResponse(429), FakeResponse(200)])
            result = cpa.upload_auth_file(
                path,
                config={
                    "cpa_management_base_url": "https://cpa.example.com",
                    "cpa_management_retry_count": 3,
                },
                key="secret-key",
                session=transient,
                sleep=sleep,
            )
            self.assertTrue(result["ok"])
            self.assertEqual(len(transient.calls), 3)
            self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])

            for status in (400, 401, 403):
                with self.subTest(status=status):
                    denied = SequenceSession([FakeResponse(status), FakeResponse(200)])
                    result = cpa.upload_auth_file(
                        path,
                        config={
                            "cpa_management_base_url": "https://cpa.example.com",
                            "cpa_management_retry_count": 3,
                        },
                        key="secret-key",
                        session=denied,
                        sleep=Mock(),
                    )
                    self.assertFalse(result["ok"])
                    self.assertEqual(len(denied.calls), 1)

    def test_invalid_json_is_rejected_before_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "xai-invalid.json"
            path.write_text("not-json", encoding="utf-8")
            session = Mock()
            result = cpa.upload_auth_file(
                path,
                config={"cpa_management_base_url": "https://cpa.example.com"},
                key="secret-key",
                session=session,
            )
        self.assertFalse(result["ok"])
        session.post.assert_not_called()

    def test_export_uses_management_api_without_legacy_sftp(self):
        with tempfile.TemporaryDirectory() as tmp:
            auth_path = self._auth_file(tmp)
            cfg = {
                "cpa_auth_dir": tmp,
                "cpa_management_auto_upload": True,
                "cpa_management_base_url": "https://cpa.example.com",
                "cpa_server_host": "legacy.example.com",
                "cpa_probe_after_write": True,
            }
            with (
                patch("cpa_xai.mint_and_export", return_value={"ok": True, "path": str(auth_path)}),
                patch("cpa_export.upload_auth_file", return_value={"ok": True}) as upload,
                patch("grok_register_ttk.upload_to_cpa_server") as legacy_upload,
            ):
                result = export_cpa_xai_for_account(
                    "user@example.com",
                    "password",
                    config=cfg,
                )
        self.assertTrue(result["ok"])
        self.assertTrue(result["management_upload_ok"])
        upload.assert_called_once()
        legacy_upload.assert_not_called()

    def test_upload_failure_keeps_export_successful(self):
        with tempfile.TemporaryDirectory() as tmp:
            auth_path = self._auth_file(tmp)
            cfg = {
                "cpa_auth_dir": tmp,
                "cpa_management_auto_upload": True,
                "cpa_management_base_url": "https://cpa.example.com",
            }
            with (
                patch("cpa_xai.mint_and_export", return_value={"ok": True, "path": str(auth_path)}),
                patch("cpa_export.upload_auth_file", return_value={"ok": False, "error": "offline"}),
            ):
                result = export_cpa_xai_for_account(
                    "user@example.com",
                    "password",
                    config=cfg,
                )
            self.assertTrue(result["ok"])
            self.assertEqual(result["management_upload_error"], "offline")
            self.assertTrue(auth_path.exists())

    def test_unexpected_upload_exception_keeps_export_successful(self):
        with tempfile.TemporaryDirectory() as tmp:
            auth_path = self._auth_file(tmp)
            cfg = {
                "cpa_auth_dir": tmp,
                "cpa_management_auto_upload": True,
                "cpa_management_base_url": "https://cpa.example.com",
            }
            with (
                patch("cpa_xai.mint_and_export", return_value={"ok": True, "path": str(auth_path)}),
                patch("cpa_export.upload_auth_file", side_effect=RuntimeError("secret internal detail")),
            ):
                result = export_cpa_xai_for_account(
                    "user@example.com",
                    "password",
                    config=cfg,
                )
            self.assertTrue(result["ok"])
            self.assertEqual(result["management_upload_error"], "CPA 管理上传发生内部错误")
            self.assertNotIn("secret internal detail", json.dumps(result))

    def test_gui_connection_result_always_restores_button(self):
        builder = object.__new__(ModernUIBuilder)
        builder.cpa_management_test_btn = Mock()
        builder.cpa_management_status_var = Mock()

        builder._apply_cpa_management_error("offline")
        builder.cpa_management_test_btn.configure.assert_called_with(
            state="normal",
            text="测试连接",
        )
        builder.cpa_management_status_var.set.assert_called_with("连接失败：offline")

        builder.cpa_management_test_btn.reset_mock()
        builder._apply_cpa_management_test({"ok": True, "version": "7.0", "count": 3})
        builder.cpa_management_test_btn.configure.assert_called_with(
            state="normal",
            text="测试连接",
        )
        builder.cpa_management_status_var.set.assert_called_with(
            "连接成功 · CPA 7.0 · 已读取 3 个认证条目"
        )

    def test_multiprocessing_worker_receives_session_only_key(self):
        log_queue = Mock()
        with (
            patch("grok_register_ttk.run_registration_cli") as run_cli,
            patch.dict(os.environ, {}, clear=True),
        ):
            app.multiprocessing_worker(
                1,
                0,
                {},
                "accounts.txt",
                log_queue,
                cpa_management_key="child-session-key",
            )
            self.assertEqual(cpa.resolve_management_key({}), "child-session-key")
            run_cli.assert_called_once()


if __name__ == "__main__":
    unittest.main()
