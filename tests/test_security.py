import json
import unittest
from datetime import datetime, timezone

from app import security


class SecurityHelpersTests(unittest.TestCase):
    def test_hash_and_verify_password(self):
        password = "StrongPass123!"
        password_hash = security.hash_password(password)

        self.assertNotEqual(password_hash, password)
        self.assertTrue(security.verify_password(password_hash, password))
        self.assertFalse(security.verify_password(password_hash, "WrongPass123!"))

    def test_validate_password_strength_accepts_valid_password(self):
        ok, message = security.validate_password_strength("StrongPass123!")

        self.assertTrue(ok)
        self.assertIsNone(message)

    def test_validate_password_strength_rejects_short_password(self):
        ok, message = security.validate_password_strength("Sh0rt!")

        self.assertFalse(ok)
        self.assertEqual(message, "Password must be at least 10 characters long")

    def test_validate_password_strength_rejects_common_password(self):
        password = "UniquePass123!"
        security.COMMON_ENGLISH_PASSWORDS.add(password.lower())
        try:
            ok, message = security.validate_password_strength(password)
        finally:
            security.COMMON_ENGLISH_PASSWORDS.discard(password.lower())

        self.assertFalse(ok)
        self.assertEqual(message, "Password cannot be a common English word")

    def test_signed_token_roundtrip(self):
        token = security.issue_signed_token("test-secret", "verify-email", 42)

        user_id = security.read_signed_token("test-secret", token, "verify-email", 60)

        self.assertEqual(user_id, 42)

    def test_signed_token_rejects_wrong_purpose(self):
        token = security.issue_signed_token("test-secret", "verify-email", 42)

        with self.assertRaises(ValueError):
            security.read_signed_token("test-secret", token, "reset-password", 60)

    def test_build_notification_payload(self):
        payload = security.build_notification_payload(type="match", from_user_id=8)

        self.assertEqual(json.loads(payload), {"type": "match", "from_user_id": 8})

    def test_iso_plus_minutes_creates_future_timestamp(self):
        value = security.iso_plus_minutes(1)

        parsed = datetime.fromisoformat(value)
        self.assertGreater(parsed, datetime.now(timezone.utc))
        self.assertTrue(security.is_future_iso(value))


if __name__ == "__main__":
    unittest.main()
