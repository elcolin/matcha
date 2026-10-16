"""
Tests HTTP de la suppression de photo (issue #89) : DELETE /profile/edit/photos
(JSON) et POST /profile/edit/photos/delete (formulaire HTML).

Verifie que la ligne en base ET le fichier sur disque sont supprimes, que la
photo de profil est reassignee, et que l'ownership / CSRF / auth sont respectes.
UPLOAD_FOLDER pointe vers un dossier temporaire : rien n'est ecrit dans le repo.
"""

import os
import tempfile
import unittest

from app import create_app
from app.config import Config
from app.db import execute, query_one
from app.security import hash_password

PASSWORD = "StrongPass123!"


def _make_verified_user(email, username):
    cur = execute(
        "INSERT INTO users (email, username, last_name, first_name, password_hash, email_verified) "
        "VALUES (?, ?, ?, ?, ?, 1)",
        (email, username, "Test", "User", hash_password(PASSWORD)),
    )
    user_id = cur.lastrowid
    execute(
        "INSERT OR IGNORE INTO profiles (user_id, sexual_preference, bio) VALUES (?, 'everyone', '')",
        (user_id,),
    )
    return user_id


class PhotoDeleteTests(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.upload_dir = os.path.join(self._tmp_dir.name, "uploads")
        os.makedirs(self.upload_dir)

        self._orig_db_path = Config.DATABASE_PATH
        Config.DATABASE_PATH = os.path.join(self._tmp_dir.name, "test.db")

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.app.config["UPLOAD_FOLDER"] = self.upload_dir
        self.client = self.app.test_client()

        with self.app.app_context():
            self.user_a = _make_verified_user("alice@example.com", "alice")
            self.user_b = _make_verified_user("bob@example.com", "bob")

    def tearDown(self):
        Config.DATABASE_PATH = self._orig_db_path
        self._tmp_dir.cleanup()

    # -- helpers ------------------------------------------------------

    def csrf_token(self):
        self.client.get("/login")
        with self.client.session_transaction() as sess:
            return sess["csrf_token"]

    def login(self, username):
        response = self.client.post(
            "/login",
            data={"username": username, "password": PASSWORD},
            headers={"X-CSRFToken": self.csrf_token()},
        )
        self.assertIn(response.status_code, (200, 302))

    def add_photo(self, user_id, name, is_primary=False, create_file=True, url=None):
        url = url or f"/static/uploads/{name}"
        if create_file:
            with open(os.path.join(self.upload_dir, name), "wb") as f:
                f.write(b"fake-image-bytes")
        with self.app.app_context():
            cur = execute(
                "INSERT INTO photos (user_id, url, is_profile_photo) VALUES (?, ?, ?)",
                (user_id, url, int(is_primary)),
            )
            return cur.lastrowid

    def photo_row(self, photo_id):
        with self.app.app_context():
            row = query_one("SELECT * FROM photos WHERE id = ?", (photo_id,))
            return dict(row) if row else None

    def file_exists(self, name):
        return os.path.exists(os.path.join(self.upload_dir, name))

    def json_delete(self, photo_id=None, token=None):
        body = {} if photo_id is None else {"photo_id": photo_id}
        headers = {"X-CSRFToken": token if token is not None else self.csrf_token()}
        return self.client.delete("/profile/edit/photos", json=body, headers=headers)

    def form_delete(self, photo_id=None, token=None):
        data = {"csrf_token": token if token is not None else self.csrf_token()}
        if photo_id is not None:
            data["photo_id"] = str(photo_id)
        return self.client.post("/profile/edit/photos/delete", data=data)

    # -- a / b : nominal ------------------------------------------------

    def test_json_delete_removes_row_file_and_reassigns_primary(self):
        self.login("alice")
        primary = self.add_photo(self.user_a, "a1.jpg", is_primary=True)
        secondary = self.add_photo(self.user_a, "a2.jpg")

        response = self.json_delete(primary)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.photo_row(primary))
        self.assertFalse(self.file_exists("a1.jpg"))
        self.assertEqual(self.photo_row(secondary)["is_profile_photo"], 1)
        photos = response.get_json()
        self.assertEqual([p["id"] for p in photos], [secondary])

    def test_form_delete_removes_row_file_and_reassigns_primary(self):
        self.login("alice")
        primary = self.add_photo(self.user_a, "a1.jpg", is_primary=True)
        secondary = self.add_photo(self.user_a, "a2.jpg")

        response = self.form_delete(primary)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/profile/edit"))
        self.assertIsNone(self.photo_row(primary))
        self.assertFalse(self.file_exists("a1.jpg"))
        self.assertTrue(self.file_exists("a2.jpg"))
        self.assertEqual(self.photo_row(secondary)["is_profile_photo"], 1)

    # -- c : ownership --------------------------------------------------

    def test_cannot_delete_another_users_photo(self):
        self.login("alice")
        own = self.add_photo(self.user_a, "a1.jpg", is_primary=True)
        foreign = self.add_photo(self.user_b, "b1.jpg", is_primary=True)

        json_response = self.json_delete(foreign)
        form_response = self.form_delete(foreign)

        self.assertEqual(json_response.status_code, 200)
        self.assertEqual([p["id"] for p in json_response.get_json()], [own])
        self.assertEqual(form_response.status_code, 302)
        self.assertIsNotNone(self.photo_row(foreign))
        self.assertTrue(self.file_exists("b1.jpg"))

    # -- d / e : url externe, fichier deja absent -------------------------

    def clear_photos(self, user_id):
        with self.app.app_context():
            execute("DELETE FROM photos WHERE user_id = ?", (user_id,))

    def test_external_url_deletes_row_without_touching_files(self):
        self.login("alice")
        for delete in (self.json_delete, self.form_delete):
            with self.subTest(route=delete.__name__):
                self.clear_photos(self.user_a)
                # Fichier local homonyme : ne doit pas etre supprime.
                local = self.add_photo(self.user_a, "x.jpg")
                external = self.add_photo(
                    self.user_a, "x.jpg", is_primary=True, create_file=False,
                    url="https://example.com/x.jpg",
                )

                response = delete(external)

                self.assertIn(response.status_code, (200, 302))
                self.assertIsNone(self.photo_row(external))
                self.assertTrue(self.file_exists("x.jpg"))
                self.assertEqual(self.photo_row(local)["is_profile_photo"], 1)

    def test_missing_file_on_disk_still_deletes_row_and_reassigns_primary(self):
        self.login("alice")
        for delete in (self.json_delete, self.form_delete):
            with self.subTest(route=delete.__name__):
                self.clear_photos(self.user_a)
                primary = self.add_photo(self.user_a, "gone.jpg", is_primary=True, create_file=False)
                secondary = self.add_photo(self.user_a, "keep.jpg")

                response = delete(primary)

                self.assertIn(response.status_code, (200, 302))
                self.assertIsNone(self.photo_row(primary))
                self.assertEqual(self.photo_row(secondary)["is_profile_photo"], 1)

    # -- f : photo_id manquant ------------------------------------------

    def test_missing_photo_id(self):
        self.login("alice")
        photo = self.add_photo(self.user_a, "a1.jpg", is_primary=True)

        json_response = self.json_delete()
        self.assertEqual(json_response.status_code, 400)
        self.assertEqual(json_response.get_json(), {"error": "photo_id is required"})

        form_response = self.form_delete()
        self.assertEqual(form_response.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertIn(("error", "photo_id is required"), sess.get("_flashes", []))

        self.assertIsNotNone(self.photo_row(photo))

    # -- g : CSRF -------------------------------------------------------

    def test_invalid_csrf_is_rejected(self):
        self.login("alice")
        photo = self.add_photo(self.user_a, "a1.jpg", is_primary=True)

        for token in ("", "wrong-token"):
            with self.subTest(token=token):
                self.assertEqual(self.json_delete(photo, token=token).status_code, 403)
                self.assertEqual(self.form_delete(photo, token=token).status_code, 403)

        self.assertIsNotNone(self.photo_row(photo))
        self.assertTrue(self.file_exists("a1.jpg"))

    # -- h : non authentifie ----------------------------------------------

    def test_unauthenticated_is_rejected(self):
        photo = self.add_photo(self.user_a, "a1.jpg", is_primary=True)

        self.assertEqual(self.json_delete(photo).status_code, 401)
        self.assertEqual(self.form_delete(photo).status_code, 401)

        self.assertIsNotNone(self.photo_row(photo))
        self.assertTrue(self.file_exists("a1.jpg"))


if __name__ == "__main__":
    unittest.main()
