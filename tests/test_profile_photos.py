import os
import unittest
from io import BytesIO
from pathlib import Path

from werkzeug.datastructures import FileStorage

from app.profile.routes import _save_uploaded_photo
from app.utils import APIError
from tests.helpers import DBTestCase


class SaveUploadedPhotoTests(DBTestCase):
    def test_accepts_each_allowed_extension_and_saves_under_upload_folder(self):
        for ext in ("png", "jpg", "jpeg", "gif", "webp"):
            with self.subTest(ext=ext):
                photo = FileStorage(stream=BytesIO(b"fake-image-bytes"), filename=f"photo.{ext}")

                url = _save_uploaded_photo(photo)

                self.assertTrue(url.startswith("/static/uploads/"))
                self.assertTrue(url.endswith(f".{ext}"))
                saved_path = Path(self.app.config["UPLOAD_FOLDER"]) / Path(url).name
                self.assertTrue(saved_path.exists())

    def test_generates_a_unique_filename_for_repeated_uploads(self):
        first = _save_uploaded_photo(FileStorage(stream=BytesIO(b"a"), filename="photo.png"))
        second = _save_uploaded_photo(FileStorage(stream=BytesIO(b"b"), filename="photo.png"))

        self.assertNotEqual(first, second)

    def test_rejects_disallowed_extension(self):
        photo = FileStorage(stream=BytesIO(b"not-an-image"), filename="malware.exe")

        with self.assertRaises(APIError):
            _save_uploaded_photo(photo)

    def test_rejects_missing_extension(self):
        photo = FileStorage(stream=BytesIO(b"data"), filename="noextension")

        with self.assertRaises(APIError):
            _save_uploaded_photo(photo)

    def test_rejects_empty_filename(self):
        photo = FileStorage(stream=BytesIO(b"data"), filename="")

        with self.assertRaises(APIError):
            _save_uploaded_photo(photo)

    def test_sanitizes_path_traversal_attempt_in_filename(self):
        photo = FileStorage(stream=BytesIO(b"data"), filename="../../etc/passwd.png")

        url = _save_uploaded_photo(photo)

        # secure_filename() must strip any directory components: the file can
        # only land inside UPLOAD_FOLDER, never escape it.
        saved_path = Path(self.app.config["UPLOAD_FOLDER"]) / Path(url).name
        self.assertTrue(saved_path.resolve().is_relative_to(Path(self.app.config["UPLOAD_FOLDER"]).resolve()))
        self.assertTrue(saved_path.exists())


if __name__ == "__main__":
    unittest.main()
