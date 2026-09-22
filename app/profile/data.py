from datetime import datetime, timedelta, timezone

from app.db import execute, query_all, query_one
from email_validator import validate_email, EmailNotValidError
from app.security import issue_signed_token, utcnow_iso
from app.utils import (
    APIError)

class UserUpdater():
    def request_email_change(user_id, new_email, secret_key, ttl_seconds):
        """Start an email change: the active email is left untouched until the
        confirmation link sent to `new_email` is clicked (see
        app.auth.routes.confirm_email_change). Returns the issued token, or
        None if this call was a no-op.
        """
        if new_email is None or new_email == "":
            return None

        try:
            valid = validate_email(new_email)
            new_email = valid.normalized  # cleaned-up version
        except EmailNotValidError as e:
            raise APIError(str(e))

        current = query_one("SELECT email FROM users WHERE id = ?", (user_id,))
        if current and current["email"] == new_email:
            return None

        taken = query_one(
            "SELECT 1 FROM users WHERE email = ? AND id != ?", (new_email, user_id)
        )
        if taken:
            raise APIError("Cet email est déjà utilisé par un autre compte.")

        # A new request supersedes any previous one still awaiting confirmation.
        execute(
            """
            UPDATE email_changes
            SET used_at = ?
            WHERE user_id = ? AND used_at IS NULL
            """,
            (utcnow_iso(), user_id),
        )

        token = issue_signed_token(secret_key, "change_email", user_id)
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        ).isoformat()
        execute(
            """
            INSERT INTO email_changes (user_id, new_email, token, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, new_email, token, expires_at),
        )
        return token

    def change_users_first_name(user_id, new_first_name):
        if new_first_name is None:
            return
        execute(
            """
            UPDATE users
            SET first_name = COALESCE(?, first_name)
            WHERE id = ?
            """,
            (
                new_first_name,
                user_id
            )
        )

    def change_users_lastname(user_id, new_last_name):
        if new_last_name is None:
            return
        execute(
            """
            UPDATE users
            SET last_name = COALESCE(?, last_name)
            WHERE id = ?
            """,
            (
                new_last_name,
                user_id
            )
        )
            