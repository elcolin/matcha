from app.config import Config


def test_seed_script_creates_requested_number_of_profiles(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "DATABASE_PATH", str(tmp_path / "seed.db"))

    from scripts import seed_db

    seed_db.seed(5)

    from app import create_app

    app = create_app()
    with app.app_context():
        from app.db import query_one

        row = query_one("SELECT COUNT(*) AS c FROM users")

    assert row["c"] >= 5
