import importlib
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, call, patch

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


class GenerateProfileTests(unittest.TestCase):
    @patch("scripts.generate_users.execute")
    def test_saves_generated_ai_bio_to_profile(self, mock_execute):
        expected_bio = "I love sunny mornings and finding the best branches."
        ai_module = MagicMock()
        ai_module.generate_bio.return_value = expected_bio

        with patch.dict(sys.modules, {"generate_bio": ai_module}):
            generate_users.generate_profile(
                user_id=42,
                created_at=datetime(2025, 1, 1),
                ai=True,
            )

        ai_module.generate_bio.assert_called_once_with()
        saved_profile = mock_execute.call_args.args[1]
        self.assertEqual(saved_profile[0], 42)
        self.assertEqual(saved_profile[3], expected_bio)

    @patch("scripts.generate_users.execute")
    def test_uses_random_bio_when_ai_models_return_no_bio(self, mock_execute):
        fallback_bio = "I enjoy quiet mornings."
        fake = MagicMock()
        fake.paragraph.return_value = fallback_bio
        fake.date_time_between.return_value = datetime(2025, 1, 2)
        fake.local_latlng.return_value = ("48.8", "2.3", "Paris", "France", "Europe/Paris")
        fake.street_name.return_value = "Rue de Rivoli"
        ai_module = MagicMock()
        ai_module.generate_bio.return_value = None

        with (
            patch.dict(sys.modules, {"generate_bio": ai_module}),
            patch.object(generate_users, "fake", fake),
        ):
            generate_users.generate_profile(
                user_id=42,
                created_at=datetime(2025, 1, 1),
                ai=True,
            )

        fake.paragraph.assert_called_once_with(nb_sentences=3)
        saved_profile = mock_execute.call_args.args[1]
        self.assertEqual(saved_profile[3], fallback_bio)


class GenerateBioTests(unittest.TestCase):
    def setUp(self):
        self.bio_generator = importlib.import_module("scripts.generate_bio")
        self.bio_generator._model = None
        self.bio_generator._tokenizer = None
        self.bio_generator._model_index = 0

    def tearDown(self):
        self.bio_generator._model = None
        self.bio_generator._tokenizer = None
        self.bio_generator._model_index = 0

    def test_reuses_loaded_model_across_bio_generations(self):
        expected_bio = "I love warm sunshine and exploring the garden."
        tokenizer = MagicMock()
        model = MagicMock()

        with (
            patch.object(self.bio_generator, "MODELS", ["model-a"]),
            patch.object(
                self.bio_generator.AutoTokenizer,
                "from_pretrained",
                return_value=tokenizer,
            ) as load_tokenizer,
            patch.object(
                self.bio_generator.AutoModelForCausalLM,
                "from_pretrained",
                return_value=model,
            ) as load_model,
            patch.object(
                self.bio_generator, "generate", return_value=expected_bio
            ) as mock_generate,
            patch.object(self.bio_generator, "is_valid", return_value=True),
        ):
            first_bio = self.bio_generator.generate_bio()
            second_bio = self.bio_generator.generate_bio()

        self.assertEqual(first_bio, expected_bio)
        self.assertEqual(second_bio, expected_bio)
        load_tokenizer.assert_called_once_with("model-a")
        load_model.assert_called_once_with("model-a")
        self.assertEqual(mock_generate.call_count, 2)

    def test_tries_next_model_when_generation_raises(self):
        expected_bio = "I love warm sunshine and exploring the garden."
        tokenizer = MagicMock()
        model = MagicMock()

        with (
            patch.object(self.bio_generator, "MODELS", ["model-a", "model-b"]),
            patch.object(
                self.bio_generator.AutoTokenizer,
                "from_pretrained",
                return_value=tokenizer,
            ) as load_tokenizer,
            patch.object(
                self.bio_generator.AutoModelForCausalLM,
                "from_pretrained",
                return_value=model,
            ) as load_model,
            patch.object(
                self.bio_generator,
                "generate",
                side_effect=[RuntimeError("model-a failed"), expected_bio],
            ),
            patch.object(self.bio_generator, "is_valid", return_value=True),
        ):
            bio = self.bio_generator.generate_bio()

        self.assertEqual(bio, expected_bio)
        self.assertEqual(load_tokenizer.call_args_list, [call("model-a"), call("model-b")])
        self.assertEqual(load_model.call_args_list, [call("model-a"), call("model-b")])
        self.assertEqual(self.bio_generator._model_index, 1)
        self.assertIs(self.bio_generator._model, model)

    def test_tries_next_model_when_loading_a_model_raises(self):
        expected_bio = "I love warm sunshine and exploring the garden."
        tokenizer = MagicMock()
        model = MagicMock()

        with (
            patch.object(self.bio_generator, "MODELS", ["model-a", "model-b"]),
            patch.object(
                self.bio_generator.AutoTokenizer,
                "from_pretrained",
                side_effect=[RuntimeError("model-a is unavailable"), tokenizer],
            ) as load_tokenizer,
            patch.object(
                self.bio_generator.AutoModelForCausalLM,
                "from_pretrained",
                return_value=model,
            ) as load_model,
            patch.object(self.bio_generator, "generate", return_value=expected_bio),
            patch.object(self.bio_generator, "is_valid", return_value=True),
        ):
            bio = self.bio_generator.generate_bio()

        self.assertEqual(bio, expected_bio)
        self.assertEqual(load_tokenizer.call_args_list, [call("model-a"), call("model-b")])
        load_model.assert_called_once_with("model-b")


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

    def test_local_jpeg_images_have_valid_file_markers(self):
        static_directory = (
            Path(generate_users.__file__).resolve().parent.parent
            / "app"
            / "static"
            / "images"
        )
        image_files = [
            path
            for path in static_directory.iterdir()
            if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg"}
        ]

        self.assertTrue(image_files, "No local JPEG images found")
        for image_file in image_files:
            with self.subTest(image=image_file.name):
                content = image_file.read_bytes()
                self.assertTrue(content.startswith(b"\xff\xd8\xff"), "Missing JPEG header")
                self.assertTrue(content.endswith(b"\xff\xd9"), "Missing JPEG end marker")

    @patch("scripts.generate_users.execute")
    @patch(
        "scripts.generate_users.requests.get",
        side_effect=__import__("requests").ConnectionError(),
    )
    def test_uploads_local_placeholder_when_api1_fails(self, mock_get, mock_execute):
        with patch.object(generate_users, "API_IMAGES1", "https://api.test/photos"):
            generate_users.create_photos([{"id": 12}], photos_per_user=1)

        mock_get.assert_called_once()
        mock_execute.assert_called_once()
        inserted_photo = mock_execute.call_args.args[1]
        self.assertEqual(inserted_photo[0], 12)
        self.assertTrue(inserted_photo[1].startswith("/static/images/"))
        self.assertIn(inserted_photo[1].rsplit("/", 1)[-1], {
            path.name
            for path in (
                Path(generate_users.__file__).resolve().parent.parent
                / "app"
                / "static"
                / "images"
            ).iterdir()
        })

    @patch("scripts.generate_users.requests.get")
    def test_uses_api_photos_when_api1_returns_images(self, mock_get):
        response = MagicMock()
        response.raise_for_status.return_value = None
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
        response.raise_for_status.assert_called_once()
        mock_get.assert_called_once_with(
            "https://api.test/photos",
            params={
                "taxon_id": 3,
                "has[]": "photos",
                "quality_grade": "research",
                "per_page": 100,
            },
            timeout=5,
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
