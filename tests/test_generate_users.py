import importlib
import sqlite3
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

with patch("app.create_app", return_value=MagicMock()):
    generate_users = importlib.import_module("scripts.generate_users")


class GenerateUserTests(unittest.TestCase):
    def test_new_user_id_skips_an_id_used_by_an_orphan_profile(self):
        db = sqlite3.connect(":memory:")
        db.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE,
                username TEXT UNIQUE,
                last_name TEXT,
                first_name TEXT,
                password_hash TEXT,
                email_verified INTEGER,
                created_at TEXT,
                last_seen_at TEXT
            );
            CREATE TABLE profiles (user_id INTEGER PRIMARY KEY);
            INSERT INTO users (id, email, username) VALUES (270, 'old@test', 'old');
            INSERT INTO profiles (user_id) VALUES (330);
            """
        )
        fake = MagicMock()
        fake.first_name.return_value = "New"
        fake.last_name.return_value = "User"
        fake.unique.email.return_value = "new@test"
        fake.unique.user_name.return_value = "new_user"
        fake.sha256.return_value = "hash"
        fake.date_time_between.return_value = datetime(2026, 1, 1)

        with (
            patch.object(generate_users, "execute", side_effect=db.execute),
            patch.object(generate_users, "fake", fake),
        ):
            user = generate_users.generate_user()
            db.execute("INSERT INTO profiles (user_id) VALUES (?)", (user["id"],))

        self.assertEqual(user["id"], 331)
        db.close()


class GeneratePhotosTests(unittest.TestCase):
    @patch("scripts.generate_users.execute")
    @patch("scripts.generate_users.generate_photos")
    def test_stores_one_photo_for_each_requested_user(self, mock_generate, mock_execute):
        users = [{"id": user_id} for user_id in range(1, 4)]
        mock_generate.return_value = [
            "/static/uploads/photo-1.jpg",
            "/static/uploads/photo-2.jpg",
            "/static/uploads/photo-3.jpg",
        ]

        generate_users.create_photos(users, photos_per_user=1)

        self.assertEqual(mock_generate.call_args.args, (len(users),))
        self.assertEqual(mock_execute.call_count, len(users))
        stored_urls = [call.args[1][1] for call in mock_execute.call_args_list]
        self.assertEqual(stored_urls, mock_generate.return_value)

    def test_configured_placeholder_image_exists_under_static_folder(self):
        placeholder_path = (
            Path(generate_users.__file__).resolve().parent
            / generate_users.LOCAL_PLACEHOLDER
        ).resolve()

        self.assertTrue(
            placeholder_path.is_file(),
            f"Configured placeholder image does not exist: {placeholder_path}",
        )


if __name__ == "__main__":
    unittest.main()
