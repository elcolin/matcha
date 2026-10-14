import argparse
import os
import secrets
import string
import sys
from datetime import datetime, timedelta, timezone
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from flask import current_app
from app.db import execute, query_one
from app.security import hash_password, issue_signed_token, validate_password_strength

"""
Dev-only: create a user you can log in as, and print its credentials.

Usage:
    python scripts/create_user.py                         # random user, email verified
    python scripts/create_user.py --unverified            # email not verified (prints a verification link)
    python scripts/create_user.py --username alice --password 'S0me-Str0ng!Pass'
    python scripts/create_user.py --unverified --base-url http://127.0.0.1:8000   # host used in the verify link
"""

PASSWORD_ALPHABET = string.ascii_letters + string.digits + "!#$%&*+-=?@^_"


def generate_password(length: int = 16, max_attempts: int = 100):
    for _ in range(max_attempts):
        password = "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(length))
        if validate_password_strength(password)[0]:
            return password
    raise RuntimeError("Could not generate a password passing validate_password_strength")


def create_user(username=None, email=None, password=None,
                first_name="Test", last_name="User", verified=True):
    suffix = secrets.token_hex(3)
    username = username or f"test_{suffix}"
    email = email or f"{username}@example.com"
    if password is None:
        password = generate_password()
    else:
        is_ok, reason = validate_password_strength(password)
        if not is_ok:
            raise ValueError(f"Password rejected: {reason}")

    if query_one("SELECT id FROM users WHERE username = ? OR email = ?", (username, email)):
        raise ValueError("Username or email already exists")

    cur = execute(
        """INSERT INTO users (email, username, last_name, first_name, password_hash, email_verified)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (email, username, last_name, first_name, hash_password(password), 1 if verified else 0),
    )
    user_id = cur.lastrowid
    # Same minimal profile row as registration (app/auth/routes.py, _ensure_profile_exists).
    execute(
        "INSERT OR IGNORE INTO profiles (user_id, sexual_preference, bio) VALUES (?, 'everyone', '')",
        (user_id,),
    )
    return {"id": user_id, "username": username, "email": email, "password": password, "verified": verified}


def issue_verification_token(user_id: int):
    """Store a verification token exactly like send_verification_email, without sending an email."""
    token = issue_signed_token(current_app.config["SECRET_KEY"], "verify_email", user_id)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=current_app.config["EMAIL_VERIFY_TOKEN_TTL_SECONDS"])
    ).isoformat()
    execute("INSERT INTO email_verifications (user_id, token, expires_at) VALUES (?, ?, ?)", (user_id, token, expires_at))
    return token


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Create a Matcha user and print its login credentials.")
    parser.add_argument("--username")
    parser.add_argument("--email")
    parser.add_argument("--password", help="must pass the app's password policy (random strong one if omitted)")
    parser.add_argument("--first-name", default="Test")
    parser.add_argument("--last-name", default="User")
    verified = parser.add_mutually_exclusive_group()
    verified.add_argument("--verified", dest="verified", action="store_true", default=True,
                          help="mark the email as verified (default)")
    verified.add_argument("--unverified", dest="verified", action="store_false",
                          help="leave the email unverified (login will be refused until verified)")
    parser.add_argument("--base-url", default="http://localhost:8000", help="used to build the verification link")
    return parser.parse_args(argv)


def main(argv=None):
    from app import create_app
    from flask import url_for

    args = parse_args(argv)
    app = create_app()
    with app.app_context():
        try:
            user = create_user(args.username, args.email, args.password,
                               args.first_name, args.last_name, args.verified)
        except ValueError as exc:
            sys.exit(f"Error: {exc}")

        print(f"Created user #{user['id']}")
        print(f"  username: {user['username']}")
        print(f"  password: {user['password']}")
        print(f"  email:    {user['email']}")
        print(f"  verified: {'yes' if user['verified'] else 'no'}")
        if not user["verified"]:
            token = issue_verification_token(user["id"])
            with app.test_request_context(base_url=args.base_url):
                print(f"  verify:   {url_for('auth.verify_email', token=token, _external=True)}")


if __name__ == "__main__":
    main()
