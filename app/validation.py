"""Server-side validation of user-submitted values.

Every limit the HTML forms enforce client-side is checked again here, since
a crafted request skips the browser entirely. Each helper raises APIError
with a message safe to show to the user.
"""
import re

from app.config import UserConfig
from app.utils import APIError

_USERNAME_RE = re.compile(UserConfig.USERNAME_PATTERN)
_TAG_RE = re.compile(r"[\w -]+")


def clean_text(value, field, max_length, *, required=False):
    """Return `value` stripped (None stays None), else raise APIError."""
    if value is None and not required:
        return None
    if value is not None and not isinstance(value, str):
        raise APIError(f"{field} is invalid", 400)
    value = (value or "").strip()
    if required and not value:
        raise APIError(f"{field} is required", 400)
    if len(value) > max_length:
        raise APIError(f"{field} must be at most {max_length} characters", 400)
    return value


def parse_age(value):
    """Return the age as an int within [AGE_MIN, AGE_MAX]; blank means None."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    text = str(value).strip()
    error = f"Age must be a whole number between {UserConfig.AGE_MIN} and {UserConfig.AGE_MAX}"
    if not text.isdigit() or len(text) > 3:
        raise APIError(error, 400)
    age = int(text)
    if not UserConfig.AGE_MIN <= age <= UserConfig.AGE_MAX:
        raise APIError(error, 400)
    return age


def parse_tags(value):
    """Comma-separated string (or list) -> sorted, lowercased, unique tags."""
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, list):
        raise APIError("Tags are invalid", 400)
    tags = sorted({str(t).strip().lower() for t in value if str(t).strip()})
    if len(tags) > UserConfig.TAGS_MAX_COUNT:
        raise APIError(f"You can add at most {UserConfig.TAGS_MAX_COUNT} tags", 400)
    for tag in tags:
        if len(tag) > UserConfig.TAG_MAX_LENGTH or not _TAG_RE.fullmatch(tag):
            raise APIError(
                f"Each tag must be at most {UserConfig.TAG_MAX_LENGTH} characters "
                "(letters, digits, spaces, hyphens or underscores)",
                400,
            )
    return tags


def validate_username(value):
    """Return the stripped username, else raise APIError."""
    if not isinstance(value, str) or not _USERNAME_RE.fullmatch(value.strip()):
        raise APIError(
            "Username must be 3 to 30 characters: letters, digits, dots, hyphens or underscores",
            400,
        )
    return value.strip()
