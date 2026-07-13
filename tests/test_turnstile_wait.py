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
        fake = FakePage()
        app.page = fake
        try:
            with patch.object(app, "sleep_with_cancel", return_value=None):
                with self.assertRaisesRegex(Exception, "Turnstile 获取 token 失败"):
                    app.getTurnstileToken()
        finally:
            app.page = previous
        combined = "\n".join(fake.scripts)
        self.assertNotIn("turnstile.reset", combined)
        self.assertNotIn("MouseEvent.prototype", combined)
        self.assertNotIn(".click()", combined)

    def test_script_only_is_not_treated_as_active_challenge(self):
        with open(app.__file__, "r", encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn('script[src*="turnstile"]', source)


if __name__ == "__main__":
    unittest.main()
