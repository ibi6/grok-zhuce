import unittest

from cpa_xai.schema import DEFAULT_CLIENT_HEADERS, build_cpa_xai_auth


class CpaXaiHeaderTests(unittest.TestCase):
    def test_default_client_headers_are_exported(self):
        payload = build_cpa_xai_auth(
            email="user@example.com",
            access_token="not-a-jwt",
            refresh_token="refresh-token",
        )
        self.assertEqual(payload["headers"], DEFAULT_CLIENT_HEADERS)
        self.assertGreaterEqual(
            tuple(map(int, payload["headers"]["x-grok-client-version"].split("."))),
            (0, 1, 202),
        )

    def test_explicit_headers_can_override_defaults(self):
        payload = build_cpa_xai_auth(
            email="user@example.com",
            access_token="not-a-jwt",
            refresh_token="refresh-token",
            headers={"x-grok-client-version": "9.9.9"},
        )
        self.assertEqual(payload["headers"], {"x-grok-client-version": "9.9.9"})


if __name__ == "__main__":
    unittest.main()
