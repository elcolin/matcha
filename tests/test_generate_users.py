import importlib
import sqlite3
import tempfile
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
    @patch("scripts.generate_users.generate_photos", return_value=[])
    def test_skips_photo_inserts_when_no_photos_are_available(
        self, mock_generate, mock_execute
    ):
        generate_users.create_photos([{"id": 1}], photos_per_user=1)

        mock_generate.assert_called_once_with(1)
        mock_execute.assert_not_called()

    @patch("scripts.generate_users.generate_photos", return_value=[])
    @patch("scripts.generate_users.execute")
    def test_skips_photo_inserts_when_image_directory_has_no_images(
        self, mock_execute, mock_generate
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            scripts_dir = Path(temp_dir) / "scripts"
            scripts_dir.mkdir()
            with (
                patch.object(generate_users, "__file__", str(scripts_dir / "generate_users.py")),
                patch.object(generate_users, "PLACEHOLDER_PATH", "/static/images/"),
            ):
                generate_users.create_photos([{"id": 1}], photos_per_user=1)

        mock_execute.assert_not_called()

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

    def test_generate_photos_uses_all_images_in_configured_static_directory(self):
        static_directory = (
            Path(generate_users.__file__).resolve().parent.parent
            / "app"
            / "static"
            / "images"
        )
        image_names = {
            path.name
            for path in static_directory.iterdir()
            if path.is_file()
            and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp"}
        }

        urls = generate_users.get_placeholder(len(image_names))

        self.assertEqual(len(urls), len(image_names))
        self.assertEqual(
            {url.rsplit("/", 1)[-1] for url in urls},
            image_names,
        )
        self.assertTrue(all(url.startswith("/static/images/") for url in urls))

    @patch("scripts.generate_users.requests.get")
    def test_uses_api_photos_when_api1_returns_images(self, mock_get):
        response = MagicMock()
        response.json.return_value = {
            "results": [
                {"photos": [{"url": "https://example.test/square/bird.jpg"}]},
                {"photos": [{"url": "https://example.test/square/another.jpg"}]},
            ]
        }
        mock_get.return_value = response
        with patch.object(generate_users, "API_IMAGES1", "https://api.test/photos"):
            urls = generate_users.generate_photos(2)

        self.assertEqual(
            urls,
            [
                "https://example.test/medium/bird.jpg",
                "https://example.test/medium/another.jpg",
            ],
        )

    @patch("scripts.generate_users.get_placeholder", return_value=["/static/images/one.jpg"])
    @patch("scripts.generate_users.requests.get", side_effect=__import__("requests").ConnectionError())
    def test_uses_local_images_when_api1_fails(self, mock_get, mock_placeholder):
        with patch.object(generate_users, "API_IMAGES1", "https://api.test/photos"):
            urls = generate_users.generate_photos(1)

        self.assertEqual(urls, ["/static/images/one.jpg"])
        mock_placeholder.assert_called_once_with(1)


if __name__ == "__main__":
    unittest.main()
