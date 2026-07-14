import unittest
from unittest.mock import patch

import grok_register_ttk as app


class FakePage:
    def __init__(self):
        self.scripts = []

    def run_js(self, script, *args):
        self.scripts.append(script)
        return ""


class TurnstileWaitTests(unittest.TestCase):
    def test_wait_does_not_reset_or_click_challenge(self):
        previous = app.page
        previous_skip = app.config.get("turnstile_auto_skip")
        fake = FakePage()
        app.page = fake
        app.config["turnstile_auto_skip"] = False
        try:
            with patch.object(app, "sleep_with_cancel", return_value=None):
                with self.assertRaisesRegex(Exception, "Turnstile 获取 token 失败"):
                    app.getTurnstileToken()
        finally:
            app.page = previous
            if previous_skip is None:
                app.config.pop("turnstile_auto_skip", None)
            else:
                app.config["turnstile_auto_skip"] = previous_skip
        combined = "\n".join(fake.scripts)
        self.assertNotIn("turnstile.reset", combined)
        self.assertNotIn("MouseEvent.prototype", combined)
        self.assertNotIn(".click()", combined)

    def test_auto_skip_does_not_wait_for_manual_verification(self):
        previous = app.page
        fake = FakePage()
        app.page = fake
        previous_skip = app.config.get("turnstile_auto_skip")
        app.config["turnstile_auto_skip"] = True
        try:
            with self.assertRaisesRegex(Exception, "自动跳过"):
                app.getTurnstileToken()
            self.assertEqual(fake.scripts, [])
        finally:
            app.page = previous
            if previous_skip is None:
                app.config.pop("turnstile_auto_skip", None)
            else:
                app.config["turnstile_auto_skip"] = previous_skip

    def test_script_only_is_not_treated_as_active_challenge(self):
        with open(app.__file__, "r", encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn('script[src*="turnstile"]', source)

    def test_cpa_turnstile_wait_contains_no_simulated_click(self):
        from pathlib import Path

        source = Path(__file__).resolve().parents[1].joinpath("cpa_xai", "browser_confirm.py").read_text(encoding="utf-8")
        segment = source.split("def _wait_turnstile(", 1)[1].split("def _fill(", 1)[0]
        self.assertNotIn("MouseEvent.prototype", segment)
        self.assertNotIn(".click()", segment)


if __name__ == "__main__":
    unittest.main()
