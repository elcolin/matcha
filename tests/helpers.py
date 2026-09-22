"""Shared test utilities.

Not a `test_*.py` module: `unittest discover` will not collect it directly,
but the test modules in this package import `DBTestCase` from here.
"""
import tempfile
import unittest
from pathlib import Path

from flask import Flask

from app.db import close_db, execute, get_db

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "app" / "schema.sql"


class DBTestCase(unittest.TestCase):
    """Pushes a Flask app context backed by a throwaway SQLite file.

    Business logic under app/utils.py, app/match/routes.py, app/profile/*
    reads and writes through app.db.get_db(), which resolves the connection
    against whichever Flask app context is currently active. This harness
    provides that context with a real (temporary, disposable) database file
    loaded from the project's actual app/schema.sql, so tests never touch the
    real instance/matcha.db and never rely on network access.
    """

    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self._tmp_dir.name) / "test.db"

        self.app = Flask(__name__)
        self.app.config["SECRET_KEY"] = "test-secret"
        self.app.config["DATABASE_PATH"] = str(db_path)
        self.app.config["UPLOAD_FOLDER"] = str(Path(self._tmp_dir.name) / "uploads")
        # Mirror app.config.Config defaults so functions reading these keys
        # (e.g. auth's login lockout) behave the same as in production.
        self.app.config["LOGIN_RATE_WINDOW_MINUTES"] = 15
        self.app.config["LOGIN_RATE_MAX_FAILS"] = 6

        self._ctx = self.app.app_context()
        self._ctx.push()

        db = get_db()
        db.executescript(SCHEMA_PATH.read_text())
        db.commit()

    def tearDown(self):
        close_db()
        self._ctx.pop()
        self._tmp_dir.cleanup()

    def create_user(self, *, email, username, first_name="First", last_name="Last",
                     password_hash="x", email_verified=1):
        cur = execute(
            """
            INSERT INTO users (email, username, first_name, last_name, password_hash, email_verified)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (email, username, first_name, last_name, password_hash, email_verified),
        )
        user_id = cur.lastrowid
        execute(
            "INSERT INTO profiles (user_id, sexual_preference, bio) VALUES (?, 'everyone', '')",
            (user_id,),
        )
        return user_id
