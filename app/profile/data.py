from app.db import execute, query_all, query_one
from email_validator import validate_email, EmailNotValidError
from app.utils import (
    APIError)

class UserUpdater():
    def change_users_email(user_id, new_email):
        if new_email is None:
            return
        try:
            valid = validate_email(new_email)
            new_email = valid.normalized  # cleaned-up version
        except EmailNotValidError as e:
            raise APIError(str(e))
        execute(
            """
            UPDATE users
            SET email = COALESCE(?, email)
            WHERE id = ?
            """,
            (
                new_email,
                user_id
            )
        )
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
            