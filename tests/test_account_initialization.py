import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import grok_register_ttk as app
from cpa_xai.mint import mint_and_export


class FakeSession:
    headers = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class AccountInitializationTests(unittest.TestCase):
    def test_initialization_retries_before_success(self):
        with (
            patch.object(app.requests, "Session", return_value=FakeSession()),
            patch.object(app, "set_tos_accepted", side_effect=[(False, "timeout"), (True, "ok")]) as tos,
            patch.object(app, "set_birth_date", return_value=(True, "ok")) as birth,
            patch.object(app, "update_nsfw_settings", return_value=(True, "ok")) as nsfw,
            patch.object(app, "sleep_with_cancel", return_value=None),
        ):
            ok, message = app.initialize_account_for_api("sso", enable_nsfw=True)
        self.assertTrue(ok)
        self.assertIn("初始化完成", message)
        self.assertEqual(tos.call_count, 2)
        birth.assert_called_once()
        nsfw.assert_called_once()

    def test_initialization_stops_before_birth_when_tos_fails(self):
        with (
            patch.object(app.requests, "Session", return_value=FakeSession()),
            patch.object(app, "set_tos_accepted", return_value=(False, "timeout")) as tos,
            patch.object(app, "set_birth_date", return_value=(True, "ok")) as birth,
            patch.object(app, "sleep_with_cancel", return_value=None),
        ):
            ok, message = app.initialize_account_for_api("sso", retries=3)
        self.assertFalse(ok)
        self.assertIn("接受服务条款失败", message)
        self.assertEqual(tos.call_count, 3)
        birth.assert_not_called()

    def test_locked_birth_date_is_treated_as_initialized(self):
        response = Mock(
            status_code=429,
            text='{"message":"Birth date is locked once set. [WKE=account:birth-date-change-limit-reached]"}',
            headers={"server": "cloudflare", "content-type": "application/json"},
        )
        session = Mock()
        session.post.return_value = response
        ok, message = app.set_birth_date(session)
        self.assertTrue(ok)
        self.assertEqual(message, "birth date already set")

    def test_failed_chat_probe_disables_credential(self):
        tokens = {
            "access_token": "not-a-jwt",
            "refresh_token": "refresh",
            "expires_in": 3600,
        }
        denied = {
            "ok": False,
            "status": 403,
            "error": '{"code":"permission-denied"}',
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch("cpa_xai.mint.mint_with_browser", return_value=tokens),
                patch("cpa_xai.mint.probe_models", return_value={"ok": True, "has_grok_45": True, "model_ids": ["grok-4.5"]}),
                patch("cpa_xai.mint.probe_mini_response", return_value=denied) as chat,
                patch("cpa_xai.mint.time.sleep", return_value=None),
            ):
                result = mint_and_export(
                    email="user@example.com",
                    password="password",
                    auth_dir=temp_dir,
                    probe=True,
                )
            self.assertFalse(result["ok"])
            self.assertEqual(chat.call_count, 3)
            payload = __import__("json").loads(next(Path(temp_dir).glob("xai-*.json")).read_text(encoding="utf-8"))
            self.assertTrue(payload["disabled"])
            self.assertIn("permission-denied", payload["probe_error"])


if __name__ == "__main__":
    unittest.main()
