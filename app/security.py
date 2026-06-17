import json
import secrets
import string
from datetime import datetime, timedelta, timezone

from itsdangerous import URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

COMMON_ENGLISH_PASSWORDS = {
    "password", "qwerty", "hello", "welcome", "dragon", "football", "baseball",
    "letmein", "sunshine", "freedom", "superman", "mustang", "monkey", "shadow",
    "princess", "trustno1", "iloveyou", "admin", "matcha", "passw0rd", "abc123",
    "123456", "1234567", "12345678", "123456789", "1234567890", "111111", "000000",
    "asdfgh", "zxcvbn", "qwertyuiop", "starwars", "master", "login", "welcome1",
    "changeme", "secret", "unknown", "donald", "pokemon", "soccer", "hockey",
    "computer", "internet", "flower", "summer", "winter", "autumn", "spring",
    "tigger", "charlie", "michael", "jessica", "daniel", "andrew", "ashley",
    "pepper", "whatever", "baseball1", "football1", "basketball", "jordan", "maggie",
    "access", "matrix", "killer", "scooter", "ginger", "michelle", "thunder",
    "buster", "cookie", "orange", "banana", "qazwsx", "qweasd", "zaq12wsx",
    "liverpool", "arsenal", "chelsea", "manchester", "freestyle", "lovely",
    "cheese", "chocolate", "summer2024", "summer2025", "welcome123", "passion",
    "eagle", "monkey123", "hottie", "cowboy", "corvette", "mercedes", "ferrari",
    "mustang1", "silver", "golden", "diamond", "abcdef", "abcdefg", "abcdefgh",
    "hannah", "hunter", "rabbit", "ginger1", "sunshine1", "flower1", "soccer1"
}


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

    lowered = password.strip().lower()
    if lowered in COMMON_ENGLISH_PASSWORDS:
        return False, "Password cannot be a common English word"

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
