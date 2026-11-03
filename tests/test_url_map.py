import os
import tempfile
import unittest

from app.config import Config

IGNORED_METHODS = {"HEAD", "OPTIONS"}
PREFIXED_BLUEPRINTS = ("profile.", "notifications.", "users.")

EXPECTED_RULES = sorted(
    [
        ("/profile/edit", ("GET",), "profile.edit_profile"),
        ("/profile/edit", ("POST",), "profile.edit_profile_submit"),
        ("/profile/edit/photos", ("DELETE", "POST"), "profile.profile_photos"),
        ("/profile/edit/photos/delete", ("POST",), "profile.profile_photos_delete_form"),
        ("/profile/<int:id>", ("GET",), "profile.detail"),
        ("/profile/<int:id>/like", ("DELETE", "POST"), "profile.like_profile"),
        ("/profile/<int:id>/unlike", ("POST",), "profile.unlike_profile_form"),
        ("/profile/<int:id>/unblock", ("POST",), "profile.unblock_profile"),
        ("/profile/<int:id>/block", ("DELETE", "POST"), "profile.block_profile"),
        ("/profile/<int:id>/report", ("POST",), "profile.report_profile"),
        ("/notifications/unread-count", ("GET",), "notifications.unread_notifications_count"),
        ("/notifications/mark-read", ("POST",), "notifications.mark_notifications_read"),
        ("/notifications/view", ("GET",), "notifications.notifications_view"),
        ("/users", ("GET",), "users.list_users_placeholder"),
        ("/users/<int:id>/online-status", ("GET",), "users.online_status"),
    ]
)


class BlueprintUrlMapTests(unittest.TestCase):
    """Pins public URLs of the profile, notifications and users blueprints."""

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
        os.unlink(self.db_path)

    def test_prefixed_blueprint_rules_are_unchanged(self):
        rules = sorted(
            (rule.rule, tuple(sorted(rule.methods - IGNORED_METHODS)), rule.endpoint)
            for rule in self.app.url_map.iter_rules()
            if rule.endpoint.startswith(PREFIXED_BLUEPRINTS)
        )
        self.assertEqual(rules, EXPECTED_RULES)

    def test_bare_prefix_roots_are_not_routed(self):
        for path in ("/users/", "/profile/", "/notifications/"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)


if __name__ == "__main__":
    unittest.main()
