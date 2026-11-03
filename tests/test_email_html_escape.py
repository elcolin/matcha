import os
import re
import tempfile
import unittest
from unittest.mock import patch

from app.config import Config


class VerificationEmailEscapeTests(unittest.TestCase):
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

    def _register_and_get_html(self, first_name):
        response = self.client.get("/register")
        match = re.search(r'name="csrf_token" value="([^"]+)"', response.get_data(as_text=True))
        self.assertIsNotNone(match, "csrf_token hidden field missing from /register")
        with patch("app.auth.routes.send_email") as mock_send_email:
            self.client.post(
                "/register",
                data={
                    "email": "escape@example.com",
                    "username": "escapeuser",
                    "first_name": first_name,
                    "last_name": "Tester",
                    "password": "J8#qL2!vX9@p",
                    "confirm": "J8#qL2!vX9@p",
                    "csrf_token": match.group(1),
                },
            )
        mock_send_email.assert_called_once()
        return mock_send_email.call_args[0][2]

    def test_first_name_html_is_escaped(self):
        html = self._register_and_get_html('</p><a href="https://evil.example">x</a>')

        self.assertIn("&lt;/p&gt;&lt;a", html)
        self.assertNotIn('<a href="https://evil.example"', html)

    def test_plain_first_name_is_unchanged(self):
        html = self._register_and_get_html("Alice")

        self.assertIn("<p>Thanks for signing up, Alice!</p>", html)

    def test_ampersand_in_first_name_is_escaped(self):
        html = self._register_and_get_html("Tom & Jerry")

        self.assertIn("Tom &amp; Jerry", html)


if __name__ == "__main__":
    unittest.main()
