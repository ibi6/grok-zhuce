import unittest
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

from outlook_mail import (
    OutlookAccount,
    OutlookAccountPool,
    OutlookAuthError,
    exchange_access_token,
    extract_code,
    load_accounts,
    parse_accounts_text,
    redact_secrets,
)


class OutlookMailTests(unittest.TestCase):
    def test_parse_txt_accounts(self):
        accounts = parse_accounts_text("a@outlook.com----pw----cid----refresh")
        self.assertEqual(accounts[0].email, "a@outlook.com")
        self.assertTrue(accounts[0].usable)

    def test_missing_oauth_is_not_usable(self):
        accounts = parse_accounts_text("a@outlook.com----pw--------")
        self.assertEqual(accounts[0].status, "needs_authorization")

    def test_parse_csv_accounts(self):
        text = "email,password,client_id,refresh_token\na@hotmail.com,p,c,r\n"
        self.assertEqual(parse_accounts_text(text, ".csv")[0].client_id, "c")

    def test_duplicate_email_is_rejected(self):
        text = "a@outlook.com----p----c----r\nA@outlook.com----p2----c2----r2\n"
        with self.assertRaisesRegex(ValueError, "重复邮箱"):
            parse_accounts_text(text)

    def test_redacts_secrets(self):
        self.assertNotIn("secret-value", redact_secrets("refresh_token=secret-value", "secret-value"))

    def test_extracts_xai_code(self):
        self.assertEqual(extract_code({"subject": "ABC-123 xAI verification code"}), "ABC-123")
        self.assertIsNone(extract_code({"subject": "Your bank code is 123456"}))

    def test_pool_locks_account(self):
        account = OutlookAccount("a@outlook.com", client_id="c", refresh_token="r")
        pool = OutlookAccountPool([account])
        self.assertIs(pool.acquire(), account)
        pool.release(account, "success")
        self.assertEqual(account.status, "success")

    def test_token_exchange_classifies_error(self):
        response = Mock(status_code=400)
        response.json.return_value = {"error": "invalid_grant", "error_description": "revoked"}
        session = Mock()
        session.post.return_value = response
        with self.assertRaises(OutlookAuthError):
            exchange_access_token(OutlookAccount("a@outlook.com", client_id="c", refresh_token="r"), session=session)

    def test_token_exchange_keeps_rotated_refresh_token(self):
        response = Mock(status_code=200)
        response.json.return_value = {"access_token": "access", "refresh_token": "rotated"}
        session = Mock()
        session.post.return_value = response
        account = OutlookAccount("a@outlook.com", client_id="c", refresh_token="old")
        self.assertEqual(exchange_access_token(account, session=session), "access")
        self.assertEqual(account.refresh_token, "rotated")

    def test_rotated_refresh_token_persists_to_txt(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "accounts.txt"
            path.write_text(
                "# keep\na@outlook.com----p----c----old\nb@outlook.com----p2----c2----other\n",
                encoding="utf-8",
            )
            pool = OutlookAccountPool(load_accounts(str(path)), path=str(path))
            account = pool.get("a@outlook.com")
            account.refresh_token = "rotated"
            pool.persist_refresh_token(account)
            updated = path.read_text(encoding="utf-8")
            self.assertIn("a@outlook.com----p----c----rotated", updated)
            self.assertIn("b@outlook.com----p2----c2----other", updated)

    def test_rotated_refresh_token_persists_to_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "accounts.csv"
            path.write_text(
                "email,password,client_id,refresh_token\n"
                "a@outlook.com,p,c,old\n"
                "b@outlook.com,p2,c2,other\n",
                encoding="utf-8",
            )
            pool = OutlookAccountPool(load_accounts(str(path)), path=str(path))
            account = pool.get("a@outlook.com")
            account.refresh_token = "rotated"
            pool.persist_refresh_token(account)
            updated = path.read_text(encoding="utf-8")
            self.assertIn("a@outlook.com,p,c,rotated", updated)
            self.assertIn("b@outlook.com,p2,c2,other", updated)

    def test_mail_reader_skips_old_verification_code(self):
        from outlook_mail import wait_for_verification_code

        token_response = Mock(status_code=200)
        token_response.json.return_value = {"access_token": "access"}
        mail_response = Mock(status_code=200)
        old_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        new_time = datetime.now(timezone.utc).isoformat()
        mail_response.json.return_value = {
            "value": [
                {"id": "old", "receivedDateTime": old_time, "subject": "OLD-111 xAI verification code"},
                {"id": "new", "receivedDateTime": new_time, "subject": "NEW-222 xAI verification code"},
            ]
        }
        session = Mock()
        session.post.return_value = token_response
        session.get.return_value = mail_response
        account = OutlookAccount("a@outlook.com", client_id="c", refresh_token="r")
        self.assertEqual(wait_for_verification_code(account, session=session), "NEW-222")


if __name__ == "__main__":
    unittest.main()
