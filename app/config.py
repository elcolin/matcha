import os
from pathlib import Path


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    BASE_DIR = Path(__file__).resolve().parent.parent
    DATABASE_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "instance" / "matcha.db"))

    # Defense in depth against CSRF (on top of the signed-token check in app.utils):
    # cookies are not sent on cross-site requests initiated by other sites. Only set
    # SECURE from an env flag so local HTTP dev keeps working.
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"

    UPLOAD_FOLDER = "app/static/uploads"
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024

    EMAIL_VERIFY_TOKEN_TTL_SECONDS = int(os.getenv("EMAIL_VERIFY_TOKEN_TTL_SECONDS", "86400"))
    EMAIL_CHANGE_TOKEN_TTL_SECONDS = int(os.getenv("EMAIL_CHANGE_TOKEN_TTL_SECONDS", "86400"))
    PASSWORD_RESET_TTL_SECONDS = int(os.getenv("PASSWORD_RESET_TTL_SECONDS", "3600"))
    LOGIN_RATE_WINDOW_MINUTES = int(os.getenv("LOGIN_RATE_WINDOW_MINUTES", "15"))
    LOGIN_RATE_MAX_FAILS = int(os.getenv("LOGIN_RATE_MAX_FAILS", "6"))

class UserConfig(Config):
    GENDERS = ["female", "male", "non-binary", "other"]
    SEXUAL_PREFERENCES = ["everyone", "men", "women"]

    # Server-side limits, mirrored by the form attributes (min/max/maxlength/
    # pattern) in the templates: the client checks are only a convenience.
    AGE_MIN = 18
    AGE_MAX = 120
    NAME_MAX_LENGTH = 50
    USERNAME_PATTERN = r"[A-Za-z0-9_.-]{3,30}"
    BIO_MAX_LENGTH = 1000
    PLACE_MAX_LENGTH = 100
    TAG_MAX_LENGTH = 30
    TAGS_MAX_COUNT = 10
    MESSAGE_MAX_LENGTH = 1000
    PASSWORD_MAX_LENGTH = 128
    TAGS = {
        "early-bird": 1,
        "night-owl": 2,
        "nesting": 3,
        "sky-lover": 4,
        "long-flights": 5,
        "seed-snacks": 6,
        "city-percher": 7,
        "forest-walker": 8,
        "songbird": 9,
        "shiny-things": 10,
        "migration": 11,
        "birdwatching": 12,
        "cozy-nest": 13,
        "coffee": 14,
        "sunsets": 15,
        "dancing": 16,
        "travel": 17,
        "photography": 18,
        "music": 19,
        "outdoors": 20,
    }
