import os
import re
import tempfile
import unittest

from app import security
from app.config import Config


class CsrfSecurityHelpersTests(unittest.TestCase):
    """Unit tests for the itsdangerous-based CSRF token helpers in app/security.py."""

    def test_generate_csrf_token_returns_a_signed_string(self):
        token = security.generate_csrf_token("test-secret")

        self.assertIsInstance(token, str)
        self.assertTrue(security.csrf_token_signature_valid("test-secret", token))

    def test_generate_csrf_token_is_unique_per_call(self):
        first = security.generate_csrf_token("test-secret")
        second = security.generate_csrf_token("test-secret")

        self.assertNotEqual(first, second)

    def test_csrf_token_signature_rejects_tampered_token(self):
        token = security.generate_csrf_token("test-secret")

        self.assertFalse(security.csrf_token_signature_valid("test-secret", token + "tampered"))

    def test_csrf_token_signature_rejects_token_signed_with_different_secret(self):
        token = security.generate_csrf_token("test-secret")

        self.assertFalse(security.csrf_token_signature_valid("other-secret", token))

    def test_csrf_token_signature_rejects_garbage_input(self):
        self.assertFalse(security.csrf_token_signature_valid("test-secret", "not-a-real-token"))


class CsrfProtectionIntegrationTests(unittest.TestCase):
    """End-to-end coverage of the CSRF hook wired into the Flask app (app/__init__.py)."""

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self._original_db_path = Config.DATABASE_PATH
        Config.DATABASE_PATH = self.db_path

        from app import create_app

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        Config.DATABASE_PATH = self._original_db_path
        os.close(self.db_fd)
        os.remove(self.db_path)

    def _get_login_page_and_token(self):
        response = self.client.get("/login")
        html = response.get_data(as_text=True)
        match = re.search(r'name="csrf_token" value="([^"]+)"', html)
        self.assertIsNotNone(match, "csrf_token hidden field missing from the /login form")
        return html, match.group(1)

    def test_login_form_renders_a_csrf_hidden_field(self):
        self._get_login_page_and_token()

    def test_post_without_csrf_token_is_rejected(self):
        self.client.get("/login")  # establishes a session (and a csrf token in it)

        response = self.client.post("/login", data={"username": "alice", "password": "whatever"})

        self.assertEqual(response.status_code, 403)
        self.assertIn("error", response.get_json())

    def test_post_with_wrong_csrf_token_is_rejected(self):
        self.client.get("/login")

        response = self.client.post(
            "/login",
            data={"username": "alice", "password": "whatever", "csrf_token": "not-the-right-token"},
        )

        self.assertEqual(response.status_code, 403)

    def test_post_with_valid_csrf_token_reaches_the_view(self):
        _, token = self._get_login_page_and_token()

        response = self.client.post(
            "/login",
            data={"username": "alice", "password": "whatever", "csrf_token": token},
        )

        # Passes the CSRF check and reaches business logic (invalid credentials,
        # not a CSRF rejection).
        self.assertEqual(response.status_code, 200)
        self.assertIn("Invalid username or password", response.get_data(as_text=True))

    def test_post_with_csrf_token_in_header_is_accepted_for_json_requests(self):
        _, token = self._get_login_page_and_token()

        response = self.client.post(
            "/login",
            json={"username": "alice", "password": "whatever"},
            headers={"X-CSRFToken": token},
        )

        self.assertEqual(response.status_code, 200)

    def test_csrf_token_from_another_session_is_rejected(self):
        _, token = self._get_login_page_and_token()

        other_client = self.app.test_client()
        response = other_client.post(
            "/login",
            data={"username": "alice", "password": "whatever", "csrf_token": token},
        )

        self.assertEqual(response.status_code, 403)

    def test_get_requests_are_never_csrf_protected(self):
        response = self.client.get("/login")

        self.assertEqual(response.status_code, 200)

    def test_register_form_renders_a_csrf_hidden_field(self):
        response = self.client.get("/register")
        html = response.get_data(as_text=True)

        self.assertRegex(html, r'name="csrf_token" value="[^"]+"')

    def test_forgot_password_form_renders_a_csrf_hidden_field(self):
        response = self.client.get("/password-reset/request")
        html = response.get_data(as_text=True)

        self.assertRegex(html, r'name="csrf_token" value="[^"]+"')

    def test_register_post_without_csrf_token_is_rejected(self):
        self.client.get("/register")

        response = self.client.post(
            "/register",
            data={
                "email": "new@example.com",
                "username": "newuser",
                "first_name": "New",
                "last_name": "User",
                "password": "StrongPass123!",
            },
        )

        self.assertEqual(response.status_code, 403)


class CsrfProtectedAuthenticatedFormsTests(unittest.TestCase):
    """Covers logged-in POST forms (profile edit, report) rather than just anonymous auth
    forms, to make sure `csrf_protect()` also runs correctly once `g.current_user` is set."""

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self._original_db_path = Config.DATABASE_PATH
        Config.DATABASE_PATH = self.db_path

        from app import create_app

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        with self.app.app_context():
            from app.db import execute

            for username in ("reporter", "reported"):
                execute(
                    """
                    INSERT INTO users (email, username, last_name, first_name, password_hash, email_verified)
                    VALUES (?, ?, 'Doe', 'Jane', ?, 1)
                    """,
                    (f"{username}@example.com", username, security.hash_password("StrongPass123!")),
                )
                execute(
                    "INSERT INTO profiles (user_id, sexual_preference, bio) VALUES ((SELECT id FROM users WHERE username = ?), 'everyone', '')",
                    (username,),
                )

    def tearDown(self):
        Config.DATABASE_PATH = self._original_db_path
        os.close(self.db_fd)
        os.remove(self.db_path)

    def _login_and_get_token(self, username):
        html = self.client.get("/login").get_data(as_text=True)
        token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        self.client.post(
            "/login",
            data={"username": username, "password": "StrongPass123!", "csrf_token": token},
        )
        # A fresh token is bound to the (now authenticated) session on the next render.
        html = self.client.get("/profile/edit").get_data(as_text=True)
        return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    def test_profile_edit_post_without_csrf_token_is_rejected(self):
        self._login_and_get_token("reporter")

        response = self.client.post("/profile/edit", data={"bio": "hacked via csrf"})

        self.assertEqual(response.status_code, 403)

    def test_profile_edit_post_with_valid_csrf_token_is_accepted(self):
        token = self._login_and_get_token("reporter")

        response = self.client.post(
            "/profile/edit",
            data={"bio": "hello world", "csrf_token": token},
        )

        self.assertEqual(response.status_code, 302)

    def test_report_profile_post_without_csrf_token_is_rejected(self):
        self._login_and_get_token("reporter")

        with self.app.app_context():
            from app.db import query_one

            reported_id = query_one("SELECT id FROM users WHERE username = 'reported'")["id"]

        response = self.client.post(f"/profile/{reported_id}/report")

        self.assertEqual(response.status_code, 403)
        with self.app.app_context():
            from app.db import query_one

            report = query_one(
                "SELECT 1 FROM reports WHERE reporter_id = (SELECT id FROM users WHERE username = 'reporter') AND reported_id = ?",
                (reported_id,),
            )
        self.assertIsNone(report)


if __name__ == "__main__":
    unittest.main()
