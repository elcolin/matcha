import os
from pathlib import Path


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    BASE_DIR = Path(__file__).resolve().parent.parent
    DATABASE_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "instance" / "matcha.db"))

    UPLOAD_FOLDER = "app/static/uploads"
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024

    EMAIL_VERIFY_TOKEN_TTL_SECONDS = int(os.getenv("EMAIL_VERIFY_TOKEN_TTL_SECONDS", "86400"))
    PASSWORD_RESET_TTL_SECONDS = int(os.getenv("PASSWORD_RESET_TTL_SECONDS", "3600"))
    LOGIN_RATE_WINDOW_MINUTES = int(os.getenv("LOGIN_RATE_WINDOW_MINUTES", "15"))
    LOGIN_RATE_MAX_FAILS = int(os.getenv("LOGIN_RATE_MAX_FAILS", "6"))
