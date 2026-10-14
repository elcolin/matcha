import json
import os
import secrets
import tempfile
import threading
import unittest
import warnings
from io import BytesIO
from pathlib import Path
from unittest import mock

from PIL import Image
from werkzeug.datastructures import FileStorage

from app.config import Config
from app.profile.routes import _reencode_photo, _save_uploaded_photo
from app.security import generate_csrf_token
from app.utils import APIError
from tests.helpers import DBTestCase

def _image_bytes(fmt, mode="RGB", size=(4, 4), color=0, **save_kwargs):
    buf = BytesIO()
    Image.new(mode, size, color).save(buf, format=fmt, **save_kwargs)
    return buf.getvalue()


def _animated_bytes(fmt, frame_count, size=(4, 4)):
    frames = [Image.new("RGB", size, ((i * 100) % 256, i % 256, 0)) for i in range(frame_count)]
    buf = BytesIO()
    frames[0].save(
        buf, format=fmt, save_all=True, append_images=frames[1:], duration=50, loop=0, lossless=True
    )
    return buf.getvalue()


def _noisy_bytes(fmt, size=(64, 64)):
    buf = BytesIO()
    Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3)).save(buf, format=fmt)
    return buf.getvalue()


# Real, fully decodable tiny images for each allowed format.
PNG_BYTES = _image_bytes("PNG")
JPEG_BYTES = _image_bytes("JPEG")
GIF_BYTES = _image_bytes("GIF", mode="P")
WEBP_BYTES = _image_bytes("WEBP")

# Byte sequences carrying a valid magic signature but no decodable image.
FAKE_PNG_HEADER = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
FAKE_JPEG_HEADER = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 20
FAKE_GIF_HEADER = b"GIF89a" + b"\x01\x00\x01\x00" + b"\x00" * 20
FAKE_WEBP_HEADER = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 20


def _photo(content, filename):
    return FileStorage(stream=BytesIO(content), filename=filename)


class SaveUploadedPhotoTests(DBTestCase):
    def _saved_path(self, url):
        return Path(self.app.config["UPLOAD_FOLDER"]) / Path(url).name

    def test_accepts_each_allowed_format_and_saves_under_upload_folder(self):
        cases = [
            ("png", PNG_BYTES, "png"),
            ("jpg", JPEG_BYTES, "jpg"),
            ("jpeg", JPEG_BYTES, "jpg"),
            ("gif", GIF_BYTES, "gif"),
            ("gif", _image_bytes("GIF", mode="L"), "gif"),
            ("webp", WEBP_BYTES, "webp"),
        ]
        for ext, content, stored_ext in cases:
            with self.subTest(ext=ext, content=content[:6]):
                url = _save_uploaded_photo(_photo(content, f"photo.{ext}"))

                self.assertTrue(url.startswith("/static/uploads/"))
                self.assertTrue(url.endswith(f".{stored_ext}"))
                self.assertTrue(self._saved_path(url).exists())

    def test_stored_file_decodes_with_the_same_size_and_format(self):
        cases = [("png", PNG_BYTES, "PNG"), ("jpg", JPEG_BYTES, "JPEG"), ("gif", GIF_BYTES, "GIF"), ("webp", WEBP_BYTES, "WEBP")]
        for ext, content, fmt in cases:
            with self.subTest(fmt=fmt):
                url = _save_uploaded_photo(_photo(content, f"photo.{ext}"))

                with Image.open(self._saved_path(url)) as stored:
                    stored.load()
                    self.assertEqual(stored.format, fmt)
                    self.assertEqual(stored.size, (4, 4))

    def test_valid_uploads_do_not_emit_warnings(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            for ext, content in [("png", PNG_BYTES), ("jpg", JPEG_BYTES), ("gif", GIF_BYTES), ("webp", WEBP_BYTES)]:
                _save_uploaded_photo(_photo(content, f"photo.{ext}"))
            _save_uploaded_photo(_photo(_animated_bytes("GIF", 3), "anim.gif"))

        self.assertEqual([str(w.message) for w in caught], [])

    def test_generates_a_unique_filename_for_repeated_uploads(self):
        first = _save_uploaded_photo(_photo(PNG_BYTES, "photo.png"))
        second = _save_uploaded_photo(_photo(PNG_BYTES, "photo.png"))

        self.assertNotEqual(first, second)

    def test_uppercase_extension_is_accepted_and_stored_lowercase(self):
        url = _save_uploaded_photo(_photo(JPEG_BYTES, "PHOTO.JPG"))

        self.assertTrue(url.endswith(".jpg"))

    def test_stored_extension_follows_detected_content_not_client_filename(self):
        url = _save_uploaded_photo(_photo(JPEG_BYTES, "photo.png"))

        self.assertTrue(url.endswith(".jpg"))

    def test_double_extension_with_image_content_gets_a_safe_random_name(self):
        url = _save_uploaded_photo(_photo(JPEG_BYTES, "shell.php.jpg"))

        name = Path(url).name
        self.assertNotIn("php", name)
        self.assertRegex(name, r"^[0-9a-f]{16}\.jpg$")

    def test_rejects_disallowed_extension(self):
        with self.assertRaises(APIError):
            _save_uploaded_photo(_photo(PNG_BYTES, "malware.exe"))

    def test_rejects_missing_extension(self):
        with self.assertRaises(APIError):
            _save_uploaded_photo(_photo(PNG_BYTES, "noextension"))

    def test_rejects_dotfile_name_without_basename(self):
        with self.assertRaises(APIError):
            _save_uploaded_photo(_photo(JPEG_BYTES, ".jpg"))

    def test_rejects_empty_filename(self):
        with self.assertRaises(APIError):
            _save_uploaded_photo(_photo(PNG_BYTES, ""))

    def test_rejects_content_that_is_not_an_allowed_image(self):
        cases = {
            "empty file": (b"", "photo.png"),
            "executable renamed": (b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 20, "photo.jpg"),
            "plain text": (b"just some text, definitely not an image", "photo.png"),
            "svg with script": (b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', "photo.png"),
            "truncated webp": (b"RIFF\x00\x00\x00\x00WE", "photo.webp"),
            "riff but not webp": (b"RIFF\x00\x00\x00\x00AVI LIST" + b"\x00" * 10, "photo.webp"),
            "truncated png": (b"\x89PNG", "photo.png"),
            "header-only png": (FAKE_PNG_HEADER, "photo.png"),
            "header-only jpeg": (FAKE_JPEG_HEADER, "photo.jpg"),
            "header-only gif": (FAKE_GIF_HEADER, "photo.gif"),
            "header-only webp": (FAKE_WEBP_HEADER, "photo.webp"),
            "truncated real jpeg": (_noisy_bytes("JPEG")[:-400], "photo.jpg"),
            "truncated real png": (_noisy_bytes("PNG")[:-400], "photo.png"),
            "valid png header followed by garbage": (PNG_BYTES[:33] + b"\x00garbage" * 10, "photo.png"),
            "gif with truncated extra frame descriptor": (GIF_BYTES[:-1] + b",", "photo.gif"),
        }
        for label, (content, filename) in cases.items():
            with self.subTest(label):
                with self.assertRaises(APIError) as ctx:
                    _save_uploaded_photo(_photo(content, filename))

                self.assertEqual(ctx.exception.status, 400)

        upload_folder = Path(self.app.config["UPLOAD_FOLDER"])
        self.assertEqual(list(upload_folder.glob("*")) if upload_folder.exists() else [], [])

    def test_sanitizes_path_traversal_attempt_in_filename(self):
        url = _save_uploaded_photo(_photo(PNG_BYTES, "../../etc/passwd.png"))

        # secure_filename() must strip any directory components: the file can
        # only land inside UPLOAD_FOLDER, never escape it.
        saved_path = self._saved_path(url)
        self.assertTrue(saved_path.resolve().is_relative_to(Path(self.app.config["UPLOAD_FOLDER"]).resolve()))
        self.assertTrue(saved_path.exists())

    def _assert_rejected(self, content, filename):
        with self.assertRaises(APIError) as ctx:
            _save_uploaded_photo(_photo(content, filename))
        self.assertEqual(ctx.exception.status, 400)
        upload_folder = Path(self.app.config["UPLOAD_FOLDER"])
        self.assertEqual(list(upload_folder.glob("*")) if upload_folder.exists() else [], [])

    def test_trailing_payload_after_a_valid_image_is_dropped_by_reencoding(self):
        marker = b"<script>alert(1)</script>"

        url = _save_uploaded_photo(_photo(PNG_BYTES + marker, "photo.png"))

        self.assertNotIn(marker, self._saved_path(url).read_bytes())

    def test_decompression_bomb_in_warning_range_is_rejected_without_leaking_a_warning(self):
        content = _image_bytes("PNG", size=(12, 12))  # 144 pixels > 100

        with mock.patch.object(Image, "MAX_IMAGE_PIXELS", 100):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                self._assert_rejected(content, "photo.png")

        self.assertEqual([str(w.message) for w in caught], [])

    def test_decompression_bomb_in_error_range_is_rejected(self):
        content = _image_bytes("PNG", size=(20, 20))  # 400 pixels > 2 * 100

        with mock.patch.object(Image, "MAX_IMAGE_PIXELS", 100):
            self._assert_rejected(content, "photo.png")

    def test_animation_whose_total_pixels_exceed_the_limit_is_rejected(self):
        content = _animated_bytes("GIF", 10)  # 10 frames of 16 pixels each

        with mock.patch.object(Image, "MAX_IMAGE_PIXELS", 100):
            self._assert_rejected(content, "photo.gif")

    def test_exif_metadata_including_gps_is_stripped_and_orientation_applied(self):
        exif = Image.Exif()
        exif[0x010F] = "SecretCamMaker"
        exif[0x0112] = 6  # rotate 90 degrees clockwise on display
        exif.get_ifd(0x8825)[1] = "N"
        exif.get_ifd(0x8825)[2] = (48.0, 51.0, 24.0)
        content = _image_bytes("JPEG", size=(8, 4), exif=exif)
        with Image.open(BytesIO(content)) as original:
            self.assertTrue(original.getexif().get_ifd(0x8825))

        url = _save_uploaded_photo(_photo(content, "photo.jpg"))

        stored_bytes = self._saved_path(url).read_bytes()
        self.assertNotIn(b"SecretCamMaker", stored_bytes)
        with Image.open(BytesIO(stored_bytes)) as stored:
            self.assertNotIn("exif", stored.info)
            self.assertEqual(dict(stored.getexif()), {})
            self.assertEqual(stored.size, (4, 8))

    def test_png_content_named_jpg_is_stored_as_png(self):
        url = _save_uploaded_photo(_photo(PNG_BYTES, "photo.jpg"))

        self.assertTrue(url.endswith(".png"))
        with Image.open(self._saved_path(url)) as stored:
            self.assertEqual(stored.format, "PNG")

    def test_rgba_png_keeps_its_alpha_channel(self):
        content = _image_bytes("PNG", mode="RGBA", color=(255, 0, 0, 128))

        url = _save_uploaded_photo(_photo(content, "photo.png"))

        with Image.open(self._saved_path(url)) as stored:
            self.assertEqual(stored.format, "PNG")
            self.assertEqual(stored.mode, "RGBA")
            self.assertEqual(stored.getpixel((0, 0))[3], 128)

    def test_cmyk_jpeg_is_reencoded_without_error(self):
        content = _image_bytes("JPEG", mode="CMYK", color=(0, 255, 255, 0))

        url = _save_uploaded_photo(_photo(content, "photo.jpg"))

        with Image.open(self._saved_path(url)) as stored:
            self.assertEqual(stored.format, "JPEG")
            self.assertEqual(stored.mode, "RGB")

    def test_animated_gif_and_webp_keep_all_their_frames(self):
        for fmt, ext in [("GIF", "gif"), ("WEBP", "webp")]:
            with self.subTest(fmt=fmt):
                content = _animated_bytes(fmt, 3)
                with Image.open(BytesIO(content)) as original:
                    self.assertEqual(original.n_frames, 3)

                url = _save_uploaded_photo(_photo(content, f"anim.{ext}"))

                with Image.open(self._saved_path(url)) as stored:
                    self.assertEqual(stored.format, fmt)
                    self.assertEqual(stored.n_frames, 3)

    def test_animation_at_the_frame_cap_is_accepted(self):
        content = _animated_bytes("GIF", 100)
        with Image.open(BytesIO(content)) as original:
            self.assertEqual(original.n_frames, 100)

        url = _save_uploaded_photo(_photo(content, "anim.gif"))

        with Image.open(self._saved_path(url)) as stored:
            self.assertEqual(stored.n_frames, 100)

    def test_animation_above_the_frame_cap_is_rejected(self):
        content = _animated_bytes("GIF", 101)
        with Image.open(BytesIO(content)) as original:
            self.assertEqual(original.n_frames, 101)

        self._assert_rejected(content, "anim.gif")


class ReencodePhotoConcurrencyTests(unittest.TestCase):
    def test_concurrent_decoding_leaves_the_global_warnings_state_untouched(self):
        filters_before = list(warnings.filters)
        showwarnmsg_before = warnings._showwarnmsg_impl
        results, errors = [], []

        def worker():
            for _ in range(20):
                try:
                    results.append(_reencode_photo(_animated_bytes("GIF", 3)))
                except Exception as exc:  # collected and asserted below
                    errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 160)
        self.assertEqual(warnings.filters, filters_before)
        self.assertIs(warnings._showwarnmsg_impl, showwarnmsg_before)


class ProfilePhotosRouteTests(unittest.TestCase):
    """POST /profile/edit/photos through the real app (CSRF hook, error handlers)."""

    MAX_BYTES = 2048

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self._tmp_dir = tempfile.TemporaryDirectory()
        self._original_db_path = Config.DATABASE_PATH
        Config.DATABASE_PATH = self.db_path

        from app import create_app

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.app.config["UPLOAD_FOLDER"] = self._tmp_dir.name
        self.app.config["MAX_CONTENT_LENGTH"] = self.MAX_BYTES
        self.client = self.app.test_client()

        from app.db import execute

        with self.app.app_context():
            self.user_id = execute(
                """
                INSERT INTO users (email, username, first_name, last_name, password_hash, email_verified)
                VALUES ('alice@example.com', 'alice', 'Alice', 'Doe', 'x', 1)
                """
            ).lastrowid
            execute(
                "INSERT INTO profiles (user_id, sexual_preference, bio) VALUES (?, 'everyone', '')",
                (self.user_id,),
            )
            session_token = secrets.token_hex(16)
            execute(
                "INSERT INTO user_sessions (user_id, session_token) VALUES (?, ?)",
                (self.user_id, session_token),
            )

        self.csrf = generate_csrf_token(self.app.config["SECRET_KEY"])
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user_id
            sess["session_token"] = session_token
            sess["csrf_token"] = self.csrf

    def tearDown(self):
        Config.DATABASE_PATH = self._original_db_path
        os.close(self.db_fd)
        os.remove(self.db_path)
        self._tmp_dir.cleanup()

    def _upload(self, content=PNG_BYTES, filename="photo.png", with_csrf=True):
        data = {"photo": (BytesIO(content), filename)}
        if with_csrf:
            data["csrf_token"] = self.csrf
        return self.client.post(
            "/profile/edit/photos",
            data=data,
            content_type="multipart/form-data",
            headers={"Accept": "text/html"},
        )

    def _flashes(self):
        with self.client.session_transaction() as sess:
            return list(sess.get("_flashes", []))

    def _photo_count(self):
        from app.db import query_one

        with self.app.app_context():
            return query_one("SELECT COUNT(*) AS c FROM photos WHERE user_id = ?", (self.user_id,))["c"]

    def test_valid_upload_is_stored(self):
        response = self._upload()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._photo_count(), 1)

    def test_invalid_format_is_rejected_with_flash_and_redirect(self):
        response = self._upload(content=b"<svg><script>alert(1)</script></svg>", filename="photo.png")

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/profile/edit"))
        self.assertEqual(self._photo_count(), 0)
        categories = [c for c, _ in self._flashes()]
        self.assertIn("error", categories)
        self.assertTrue(any("png, jpg" in msg.lower() or "image" in msg.lower() for _, msg in self._flashes()))

    def test_missing_file_is_rejected(self):
        response = self.client.post(
            "/profile/edit/photos",
            data={"csrf_token": self.csrf},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(("error", "Please choose a photo to upload"), self._flashes())

    def test_sixth_photo_is_rejected(self):
        for _ in range(5):
            self._upload()
        with self.client.session_transaction() as sess:
            sess.pop("_flashes", None)

        response = self._upload()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._photo_count(), 5)
        self.assertIn(("error", "You can upload up to 5 photos"), self._flashes())

    def test_oversized_form_upload_redirects_with_flash_instead_of_raw_error_page(self):
        response = self._upload(content=PNG_BYTES + b"\x00" * (self.MAX_BYTES * 2))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/profile/edit"))
        self.assertEqual(self._photo_count(), 0)
        messages = [msg for cat, msg in self._flashes() if cat == "error"]
        self.assertEqual(len(messages), 1)
        self.assertIn("too large", messages[0].lower())

    def test_oversized_json_request_returns_413_json_error(self):
        response = self.client.post(
            "/profile/edit/photos",
            data=json.dumps({"padding": "x" * (self.MAX_BYTES * 2)}),
            content_type="application/json",
            headers={"X-CSRFToken": self.csrf},
        )

        self.assertEqual(response.status_code, 413)
        self.assertIn("too large", response.get_json()["error"].lower())

    def test_upload_without_csrf_token_is_still_rejected(self):
        response = self._upload(with_csrf=False)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self._photo_count(), 0)

    def test_edit_page_exposes_the_upload_size_limit_to_the_client(self):
        html = self.client.get("/profile/edit").get_data(as_text=True)

        self.assertIn(f'data-max-bytes="{self.MAX_BYTES}"', html)


if __name__ == "__main__":
    unittest.main()
