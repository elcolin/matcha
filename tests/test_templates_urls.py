import os
import re
import secrets
import tempfile
import unittest
from pathlib import Path

from app import config as app_config

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "app" / "templates"

# Hardcoded internal URLs: href/action attributes, fetch/EventSource calls and
# window.location assignments starting with a literal "/".
HARDCODED_URL_PATTERNS = [
    re.compile(r'href="/'),
    re.compile(r'action="/'),
    re.compile(r"fetch\(['`\"]/"),
    re.compile(r"EventSource\(['`\"]/"),
    re.compile(r"window\.location(\.href)?\s*=\s*['`\"]/"),
]


class TemplatesStaticScanTests(unittest.TestCase):
    def _template_lines(self):
        for path in sorted(TEMPLATES_DIR.rglob("*.html")):
            for lineno, line in enumerate(path.read_text().splitlines(), start=1):
                yield path.relative_to(TEMPLATES_DIR), lineno, line

    def test_no_hardcoded_internal_urls_in_templates(self):
        offenders = [
            f"{path}:{lineno}: {line.strip()}"
            for path, lineno, line in self._template_lines()
            if any(p.search(line) for p in HARDCODED_URL_PATTERNS)
        ]
        self.assertEqual(offenders, [], "Hardcoded URLs found:\n" + "\n".join(offenders))

    def test_no_safe_filter_on_generated_urls(self):
        offenders = [
            f"{path}:{lineno}: {line.strip()}"
            for path, lineno, line in self._template_lines()
            if ("url_for" in line or "tojson" in line) and re.search(r"\|\s*safe", line)
        ]
        self.assertEqual(offenders, [])


class TemplatesRenderedUrlsTests(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp()
        app_config.Config.DATABASE_PATH = self.db_path

        from app import create_app

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def _create_user(self, username):
        from app.db import execute, query_one

        with self.app.app_context():
            execute(
                """
                INSERT INTO users (email, username, first_name, last_name, password_hash, email_verified)
                VALUES (?, ?, ?, ?, ?, 1)
                """,
                (f"{username}@example.com", username, "First", "Last", "hash"),
            )
            user_id = query_one("SELECT id FROM users WHERE username = ?", (username,))["id"]
            execute(
                "INSERT INTO profiles (user_id, gender, sexual_preference, age) VALUES (?, 'female', 'everyone', 25)",
                (user_id,),
            )
        return user_id

    def _login_as(self, user_id):
        from app.db import execute

        token = secrets.token_hex(16)
        with self.app.app_context():
            execute(
                "INSERT INTO user_sessions (user_id, session_token) VALUES (?, ?)",
                (user_id, token),
            )
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["session_token"] = token

    def _make_match(self, a_id, b_id):
        from app.db import execute

        with self.app.app_context():
            execute("INSERT INTO likes (from_user_id, to_user_id) VALUES (?, ?)", (a_id, b_id))
            execute("INSERT INTO likes (from_user_id, to_user_id) VALUES (?, ?)", (b_id, a_id))

    def _get_html(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def test_login_page_urls(self):
        html = self._get_html("/login")
        self.assertIn('action="/login"', html)
        self.assertIn('href="/password-reset/request"', html)
        self.assertIn('href="/register"', html)
        self.assertIn('name="csrf_token"', html)

    def test_register_page_urls(self):
        html = self._get_html("/register")
        self.assertIn('action="/register"', html)
        self.assertIn('href="/login"', html)
        self.assertIn('name="csrf_token"', html)

    def test_forgot_password_page_urls(self):
        html = self._get_html("/password-reset/request")
        self.assertIn('action="/password-reset/request"', html)
        self.assertIn('href="/login"', html)
        self.assertIn('name="csrf_token"', html)

    def test_index_anonymous_links_to_register(self):
        html = self._get_html("/")
        # Two CTA links (hero + bottom CTA) plus the navbar Sign Up link.
        self.assertEqual(html.count('href="/register"'), 3)
        self.assertIn("Find Your Feathered Match", html)
        self.assertIn("Create Account", html)

    def test_anonymous_pages_do_not_poll_notifications(self):
        for url in ("/", "/login", "/register", "/password-reset/request"):
            self.assertNotIn("/notifications/unread-count", self._get_html(url), url)

    def test_logged_in_index_polls_notifications(self):
        user_id = self._create_user("alice")
        self._login_as(user_id)
        html = self._get_html("/")
        self.assertIn("/notifications/unread-count", html)
        # Rendered through url_for | tojson, i.e. as a JSON string literal.
        self.assertIn('fetch("/notifications/unread-count")', html)
        self.assertNotIn("Ready to meet someone?", html)
        self.assertNotIn("Join and start matching today.", html)
        self.assertNotIn("Create Account", html)

    def test_chat_view_without_partner_has_no_conversation_script(self):
        user_id = self._create_user("alice")
        self._login_as(user_id)
        html = self._get_html("/chat/view")
        self.assertNotIn("otherUserId", html)
        self.assertNotIn("/chat/stream", html)

    def test_chat_view_with_match_renders_url_templates(self):
        alice = self._create_user("alice")
        bob = self._create_user("bob")
        self._make_match(alice, bob)
        self._login_as(alice)
        html = self._get_html(f"/chat/view/{bob}")
        for url in ("/chat/0", "/chat/0/send", "/chat/0/presence", "/users/0/online-status", "/chat/stream"):
            self.assertIn(f'"{url}"', html)
        self.assertNotIn("`/chat/", html)
        self.assertNotIn("`/users/", html)
        self.assertIn(f"const otherUserId = {bob};", html)

    def test_chat_view_with_non_matched_user_unchanged(self):
        alice = self._create_user("alice")
        carol = self._create_user("carol")
        self._login_as(alice)
        response = self.client.get(f"/chat/view/{carol}")
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("otherUserId", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
