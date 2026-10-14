from unittest.mock import patch

import email_validator

from app.db import query_one
from app.security import read_signed_token, validate_password_strength, verify_password
from scripts.create_user import create_user, generate_password, issue_verification_token, parse_args
from tests.helpers import DBTestCase


class CreateUserScriptTests(DBTestCase):
    def setUp(self):
        super().setUp()
        self.app.config["EMAIL_VERIFY_TOKEN_TTL_SECONDS"] = 3600
        # Skip the DNS deliverability lookup: tests never rely on network access.
        no_dns = patch.object(email_validator, "TEST_ENVIRONMENT", True)
        no_dns.start()
        self.addCleanup(no_dns.stop)

    def test_generated_password_passes_the_app_policy(self):
        self.assertTrue(validate_password_strength(generate_password())[0])

    def test_creates_a_verified_user_whose_password_logs_in(self):
        user = create_user()
        row = query_one("SELECT * FROM users WHERE id = ?", (user["id"],))
        self.assertEqual(row["username"], user["username"])
        self.assertEqual(row["email_verified"], 1)
        self.assertTrue(verify_password(row["password_hash"], user["password"]))
        self.assertNotEqual(row["password_hash"], user["password"])
        self.assertIsNotNone(query_one("SELECT user_id FROM profiles WHERE user_id = ?", (user["id"],)))

    def test_can_create_an_unverified_user(self):
        user = create_user(verified=False)
        row = query_one("SELECT email_verified FROM users WHERE id = ?", (user["id"],))
        self.assertEqual(row["email_verified"], 0)

    def test_uses_the_given_credentials(self):
        user = create_user(username="alice", email="alice@gmail.com", password="Xq7#vRt9!mKz2p")
        self.assertEqual((user["username"], user["email"]), ("alice", "alice@gmail.com"))
        row = query_one("SELECT password_hash FROM users WHERE username = 'alice'")
        self.assertTrue(verify_password(row["password_hash"], "Xq7#vRt9!mKz2p"))

    def test_default_email_uses_a_deliverable_domain(self):
        user = create_user()
        self.assertEqual(user["email"], f"{user['username']}@gmail.com")

    def test_rejects_an_invalid_email(self):
        with self.assertRaises(ValueError):
            create_user(email="not-an-email")

    def test_rejects_a_weak_password(self):
        with self.assertRaises(ValueError):
            create_user(password="password")

    def test_rejects_a_duplicate_username(self):
        create_user(username="alice")
        with self.assertRaises(ValueError):
            create_user(username="alice", email="other@gmail.com")

    def test_verification_token_is_valid_for_the_user(self):
        user = create_user(verified=False)
        token = issue_verification_token(user["id"])
        self.assertEqual(read_signed_token("test-secret", token, "verify_email", 3600), user["id"])
        self.assertIsNotNone(query_one("SELECT id FROM email_verifications WHERE token = ?", (token,)))

    def test_cli_defaults_to_verified(self):
        self.assertTrue(parse_args([]).verified)
        self.assertFalse(parse_args(["--unverified"]).verified)
