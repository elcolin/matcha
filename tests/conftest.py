import sys
from pathlib import Path

import pytest

# Make the `app` (and `scripts`) packages importable regardless of where
# pytest is invoked from.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app
from app.config import Config


@pytest.fixture
def app(tmp_path, monkeypatch):
    """A Flask app wired to a fresh, throwaway SQLite database per test."""
    monkeypatch.setattr(Config, "DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path / "uploads"))

    flask_app = create_app()
    flask_app.config.update(TESTING=True)
    yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


def register_user(client, username, password="Xk7!qzWvLp9Q", **extra):
    """Register + verify a user in one go, returning their id."""
    payload = {
        "email": f"{username}@example.com",
        "username": username,
        "last_name": "Test",
        "first_name": username.capitalize(),
        "password": password,
        **extra,
    }
    response = client.post("/register", json=payload)
    assert response.status_code == 201, response.get_data(as_text=True)

    token = response.get_json()["verification_link"].rsplit("/", 1)[-1]
    verify = client.get(f"/verify-email/{token}?format=json")
    assert verify.status_code == 200

    return response


def login_user(client, username, password="Xk7!qzWvLp9Q"):
    response = client.post("/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.get_data(as_text=True)
    return response


def give_profile_photo(app, username):
    """Likes require a profile photo; insert a placeholder one directly."""
    with app.app_context():
        from app.db import execute, query_one

        user = query_one("SELECT id FROM users WHERE username = ?", (username,))
        execute(
            "INSERT INTO photos (user_id, url, is_profile_photo) VALUES (?, 'placeholder.png', 1)",
            (user["id"],),
        )
        return user["id"]
