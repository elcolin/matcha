import os
import re
import tempfile
import unittest

from app import security
from app.config import Config


class ProfileReportTestCase(unittest.TestCase):
    """Runs the real app (blueprints, CSRF hook, login_required) against a temp DB."""

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self._original_db_path = Config.DATABASE_PATH
        Config.DATABASE_PATH = self.db_path

        from app import create_app

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        self.ids = {}
        for username in ("reporter", "reported", "liker"):
            self.ids[username] = self._create_user(username)

    def tearDown(self):
        Config.DATABASE_PATH = self._original_db_path
        os.close(self.db_fd)
        os.remove(self.db_path)

    def _sql(self, sql, params=()):
        with self.app.app_context():
            from app.db import execute

            execute(sql, params)

    def _one(self, sql, params=()):
        with self.app.app_context():
            from app.db import query_one

            row = query_one(sql, params)
            return dict(row) if row else None

    def _create_user(self, username):
        with self.app.app_context():
            from app.db import execute

            cur = execute(
                """
                INSERT INTO users (email, username, last_name, first_name, password_hash, email_verified)
                VALUES (?, ?, 'Doe', 'Jane', ?, 1)
                """,
                (f"{username}@example.com", username, security.hash_password("StrongPass123!")),
            )
            user_id = cur.lastrowid
            execute(
                "INSERT INTO profiles (user_id, sexual_preference, bio) VALUES (?, 'everyone', '')",
                (user_id,),
            )
            return user_id

    def _login_and_get_token(self, username):
        html = self.client.get("/login").get_data(as_text=True)
        token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        self.client.post(
            "/login",
            data={"username": username, "password": "StrongPass123!", "csrf_token": token},
        )
        html = self.client.get("/profile/edit").get_data(as_text=True)
        return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    def _give_reported_some_popularity(self):
        self._sql(
            "INSERT INTO likes (from_user_id, to_user_id) VALUES (?, ?)",
            (self.ids["liker"], self.ids["reported"]),
        )
        with self.app.app_context():
            from app.utils import update_popularity

            return update_popularity(self.ids["reported"])

    def _popularity(self, user_id):
        return self._one("SELECT popularity_score FROM profiles WHERE user_id = ?", (user_id,))[
            "popularity_score"
        ]

    def _report_rows(self):
        with self.app.app_context():
            from app.db import query_all

            return [
                dict(r)
                for r in query_all(
                    "SELECT * FROM reports WHERE reporter_id = ? AND reported_id = ?",
                    (self.ids["reporter"], self.ids["reported"]),
                )
            ]

    def _post_json_report(self, token, target_id):
        return self.client.post(
            f"/profile/{target_id}/report",
            json={},
            headers={"X-CSRFToken": token},
        )


class ReportProfileRouteTests(ProfileReportTestCase):
    def test_json_report_creates_row_and_lowers_popularity(self):
        before = self._give_reported_some_popularity()
        token = self._login_and_get_token("reporter")

        response = self._post_json_report(token, self.ids["reported"])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"reported": True})
        rows = self._report_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reason"], "fake_account")
        self.assertEqual(self._popularity(self.ids["reported"]), max(0, before - 15))
        self.assertGreater(before, 0)

    def test_form_report_redirects_to_profile_with_flash(self):
        token = self._login_and_get_token("reporter")

        response = self.client.post(
            f"/profile/{self.ids['reported']}/report", data={"csrf_token": token}
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith(f"/profile/{self.ids['reported']}"))
        with self.client.session_transaction() as sess:
            messages = [m for _, m in sess.get("_flashes", [])]
        self.assertIn("Profile reported.", messages)
        self.assertEqual(len(self._report_rows()), 1)

    def test_duplicate_report_is_idempotent(self):
        self._give_reported_some_popularity()
        token = self._login_and_get_token("reporter")
        self._post_json_report(token, self.ids["reported"])
        first_row = self._report_rows()[0]
        score_after_first = self._popularity(self.ids["reported"])

        response = self._post_json_report(token, self.ids["reported"])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"reported": True})
        rows = self._report_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], first_row["id"])
        self.assertEqual(rows[0]["created_at"], first_row["created_at"])
        self.assertEqual(self._popularity(self.ids["reported"]), score_after_first)

    def test_self_report_is_rejected(self):
        token = self._login_and_get_token("reporter")

        response = self._post_json_report(token, self.ids["reporter"])

        self.assertEqual(response.status_code, 400)
        self.assertIsNone(
            self._one("SELECT 1 FROM reports WHERE reporter_id = ?", (self.ids["reporter"],))
        )

    def test_report_of_nonexistent_profile_returns_404(self):
        token = self._login_and_get_token("reporter")

        response = self._post_json_report(token, 999999)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json(), {"error": "Profile not found"})
        self.assertIsNone(self._one("SELECT 1 FROM reports"))

    def test_report_requires_login(self):
        html = self.client.get("/login").get_data(as_text=True)
        token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

        response = self._post_json_report(token, self.ids["reported"])

        self.assertEqual(response.status_code, 401)
        self.assertIsNone(self._one("SELECT 1 FROM reports"))

    def test_report_allowed_between_blocked_users(self):
        self._sql(
            "INSERT INTO blocks (blocker_id, blocked_id) VALUES (?, ?)",
            (self.ids["reporter"], self.ids["reported"]),
        )
        token = self._login_and_get_token("reporter")

        response = self._post_json_report(token, self.ids["reported"])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self._report_rows()), 1)


class ReportedByMeTests(ProfileReportTestCase):
    def test_json_payload_reported_by_me_false_before_report(self):
        self._login_and_get_token("reporter")

        payload = self.client.get(f"/profile/{self.ids['reported']}?format=json").get_json()

        self.assertIs(payload["reported_by_me"], False)

    def test_json_payload_reported_by_me_true_after_report(self):
        token = self._login_and_get_token("reporter")
        self._post_json_report(token, self.ids["reported"])

        payload = self.client.get(f"/profile/{self.ids['reported']}?format=json").get_json()

        self.assertIs(payload["reported_by_me"], True)

    def test_reported_by_me_is_per_viewer(self):
        self._sql(
            "INSERT INTO reports (reporter_id, reported_id, reason) VALUES (?, ?, 'fake_account')",
            (self.ids["liker"], self.ids["reported"]),
        )
        self._login_and_get_token("reporter")

        payload = self.client.get(f"/profile/{self.ids['reported']}?format=json").get_json()

        self.assertIs(payload["reported_by_me"], False)


class ReportButtonRenderTests(ProfileReportTestCase):
    def _report_action(self):
        return f'action="/profile/{self.ids["reported"]}/report"'

    def test_report_form_with_confirm_shown_when_not_reported(self):
        self._login_and_get_token("reporter")

        html = self.client.get(f"/profile/{self.ids['reported']}").get_data(as_text=True)

        self.assertIn(self._report_action(), html)
        self.assertIn("return confirm('Report this profile as a fake account?');", html)
        self.assertNotIn(">Reported<", html)

    def test_disabled_reported_button_shown_after_report(self):
        token = self._login_and_get_token("reporter")
        self._post_json_report(token, self.ids["reported"])

        html = self.client.get(f"/profile/{self.ids['reported']}").get_data(as_text=True)

        self.assertNotIn(self._report_action(), html)
        self.assertRegex(html, r'<button[^>]*\bdisabled\b[^>]*aria-disabled="true"[^>]*>Reported</button>')


if __name__ == "__main__":
    unittest.main()
