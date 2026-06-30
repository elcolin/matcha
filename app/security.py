import json
import re
import secrets
import string
from datetime import datetime, timedelta, timezone
from pathlib import Path

from itsdangerous import URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

# Real English dictionary (~210k common/lowercase words), bundled as a plain
# text file so the check doesn't depend on the OS having /usr/share/dict/words
# installed. Loaded once and cached, since it's read-only for the app's lifetime.
DICTIONARY_PATH = Path(__file__).resolve().parent / "data" / "english_words.txt"
_NON_LETTERS_AT_EDGES = re.compile(r"^[^a-z]+|[^a-z]+$")

_dictionary_cache = None


def _load_dictionary():
    global _dictionary_cache
    if _dictionary_cache is None:
        _dictionary_cache = frozenset(DICTIONARY_PATH.read_text().split())
    return _dictionary_cache


def is_dictionary_word(password: str) -> bool:
    """True if the password, once leading/trailing digits and symbols are
    stripped (e.g. "Summer2025!" -> "summer"), is a common English word."""
    lowered = password.strip().lower()
    core = _NON_LETTERS_AT_EDGES.sub("", lowered)
    dictionary = _load_dictionary()
    return lowered in dictionary or core in dictionary


def utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


def iso_plus_minutes(minutes: int):
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


def is_future_iso(value: str):
    return datetime.fromisoformat(value) > datetime.now(timezone.utc)


def hash_password(password: str):
    return generate_password_hash(password)


def verify_password(password_hash: str, password: str):
    return check_password_hash(password_hash, password)


def validate_password_strength(password: str):
    if len(password) < 10:
        return False, "Password must be at least 10 characters long"
    if not any(c.isupper() for c in password):
        return False, "Password must contain an uppercase letter"
    if not any(c.islower() for c in password):
        return False, "Password must contain a lowercase letter"
    if not any(c.isdigit() for c in password):
        return False, "Password must contain a digit"
    if not any(c in string.punctuation for c in password):
        return False, "Password must contain a special character"

    if is_dictionary_word(password):
        return False, "Password cannot be a common dictionary word"

    return True, None


def make_serializer(secret_key: str):
    return URLSafeTimedSerializer(secret_key=secret_key, salt="matcha-auth")


def issue_signed_token(secret_key: str, purpose: str, user_id: int):
    serializer = make_serializer(secret_key)
    return serializer.dumps({"purpose": purpose, "user_id": user_id, "nonce": secrets.token_urlsafe(8)})


def read_signed_token(secret_key: str, token: str, purpose: str, max_age_seconds: int):
    serializer = make_serializer(secret_key)
    payload = serializer.loads(token, max_age=max_age_seconds)
    if payload.get("purpose") != purpose:
        raise ValueError("Invalid token purpose")
    return int(payload["user_id"])


def build_notification_payload(**kwargs):
    return json.dumps(kwargs)
