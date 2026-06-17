import secrets
from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, g, jsonify, redirect, render_template_string, request, session, url_for

from app.db import execute, query_one
from app.security import (
    hash_password,
    iso_plus_minutes,
    issue_signed_token,
    read_signed_token,
    utcnow_iso,
    validate_password_strength,
    verify_password,
)
from app.utils import APIError, login_required

auth_bp = Blueprint("auth", __name__)


def _is_locked_out(username: str):
    cfg = current_app.config
    row = query_one(
        """
        SELECT COUNT(*) AS failed_count
        FROM login_attempts
        WHERE username = ?
          AND success = 0
          AND attempted_at >= datetime('now', ?)
        """,
        (username, f"-{cfg['LOGIN_RATE_WINDOW_MINUTES']} minutes"),
    )
    return bool(row and row["failed_count"] >= cfg["LOGIN_RATE_MAX_FAILS"])


def _ensure_profile_exists(user_id: int):
    execute(
        "INSERT OR IGNORE INTO profiles (user_id, sexual_preference, bio) VALUES (?, 'bisexual', '')",
        (user_id,),
    )


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template_string(
            """
            <h1>Register</h1>
            <form method='post' action='/register'>
              <input name='email' placeholder='Email' required>
              <input name='username' placeholder='Username' required>
              <input name='last_name' placeholder='Last name' required>
              <input name='first_name' placeholder='First name' required>
              <input name='password' type='password' placeholder='Password' required>
              <button type='submit'>Register</button>
            </form>
            """
        )

    data = request.get_json(silent=True) or request.form

    required = ["email", "username", "last_name", "first_name", "password"]
    missing = [f for f in required if not str(data.get(f, "")).strip()]
    if missing:
        raise APIError(f"Missing required fields: {', '.join(missing)}", 400)

    is_ok, reason = validate_password_strength(data["password"])
    if not is_ok:
        raise APIError(reason, 400)

    try:
        cur = execute(
            """
            INSERT INTO users (email, username, last_name, first_name, password_hash)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                data["email"].strip().lower(),
                data["username"].strip(),
                data["last_name"].strip(),
                data["first_name"].strip(),
                hash_password(data["password"]),
            ),
        )
    except Exception:
        raise APIError("Email or username already exists", 409)

    user_id = cur.lastrowid
    _ensure_profile_exists(user_id)

    token = issue_signed_token(current_app.config["SECRET_KEY"], "verify_email", user_id)
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=current_app.config["EMAIL_VERIFY_TOKEN_TTL_SECONDS"])).isoformat()
    execute(
        "INSERT INTO email_verifications (user_id, token, expires_at) VALUES (?, ?, ?)",
        (user_id, token, expires_at),
    )

    verify_link = url_for("auth.verify_email", token=token, _external=True)
    return jsonify(
        {
            "message": "Registration successful. Check your email for verification link.",
            "verification_link": verify_link,
        }
    ), 201


@auth_bp.route("/verify-email/<token>", methods=["GET"])
def verify_email(token):
    try:
        user_id = read_signed_token(
            current_app.config["SECRET_KEY"],
            token,
            "verify_email",
            current_app.config["EMAIL_VERIFY_TOKEN_TTL_SECONDS"],
        )
    except Exception:
        raise APIError("Invalid or expired verification token", 400)

    row = query_one(
        "SELECT id, expires_at, used_at FROM email_verifications WHERE token = ?",
        (token,),
    )
    if not row or row["used_at"] is not None or datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
        raise APIError("Verification link is no longer valid", 400)

    execute("UPDATE users SET email_verified = 1 WHERE id = ?", (user_id,))
    execute("UPDATE email_verifications SET used_at = ? WHERE token = ?", (utcnow_iso(), token))

    return jsonify({"message": "Email verified successfully"})


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template_string(
            """
            <h1>Login</h1>
            <form method='post' action='/login'>
              <input name='username' placeholder='Username' required>
              <input name='password' type='password' placeholder='Password' required>
              <button type='submit'>Login</button>
            </form>
            """
        )

    data = request.get_json(silent=True) or request.form
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))

    if not username or not password:
        raise APIError("username and password are required", 400)

    if _is_locked_out(username):
        raise APIError("Too many failed attempts. Please retry later.", 429)

    user = query_one("SELECT * FROM users WHERE username = ?", (username,))
    if not user or not verify_password(user["password_hash"], password):
        execute("INSERT INTO login_attempts (username, success) VALUES (?, 0)", (username,))
        raise APIError("Invalid credentials", 401)

    if not user["email_verified"]:
        raise APIError("Email not verified", 403)

    execute("INSERT INTO login_attempts (username, success) VALUES (?, 1)", (username,))

    session.clear()
    session["user_id"] = user["id"]
    session_token = secrets.token_urlsafe(32)
    session["session_token"] = session_token
    session["logout_token"] = secrets.token_urlsafe(16)

    execute(
        "INSERT INTO user_sessions (user_id, session_token) VALUES (?, ?)",
        (user["id"], session_token),
    )

    return jsonify({"message": "Logged in"})


@auth_bp.route("/logout", methods=["GET", "POST"])
@login_required
def logout():
    user_id = g.current_user["id"]
    token = session.get("session_token")
    if token:
        execute("DELETE FROM user_sessions WHERE user_id = ? AND session_token = ?", (user_id, token))

    session.clear()

    if request.method == "GET":
        return redirect(url_for("main.home"))
    return jsonify({"message": "Logged out"})


@auth_bp.route("/password-reset/request", methods=["POST"])
def request_password_reset():
    data = request.get_json(silent=True) or request.form
    identifier = str(data.get("email", "")).strip().lower()

    if not identifier:
        raise APIError("email is required", 400)

    user = query_one("SELECT id FROM users WHERE email = ?", (identifier,))
    if not user:
        return jsonify({"message": "If your account exists, a reset email has been sent."})

    token = issue_signed_token(current_app.config["SECRET_KEY"], "password_reset", user["id"])
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=current_app.config["PASSWORD_RESET_TTL_SECONDS"])).isoformat()
    execute(
        "INSERT INTO password_resets (user_id, token, expires_at) VALUES (?, ?, ?)",
        (user["id"], token, expires_at),
    )

    reset_link = url_for("auth.confirm_password_reset", token=token, _external=True)
    return jsonify(
        {
            "message": "If your account exists, a reset email has been sent.",
            "reset_link": reset_link,
        }
    )


@auth_bp.route("/password-reset/confirm/<token>", methods=["POST"])
def confirm_password_reset(token):
    data = request.get_json(silent=True) or request.form
    new_password = str(data.get("password", ""))

    is_ok, reason = validate_password_strength(new_password)
    if not is_ok:
        raise APIError(reason, 400)

    try:
        user_id = read_signed_token(
            current_app.config["SECRET_KEY"],
            token,
            "password_reset",
            current_app.config["PASSWORD_RESET_TTL_SECONDS"],
        )
    except Exception:
        raise APIError("Invalid or expired reset token", 400)

    row = query_one("SELECT id, expires_at, used_at FROM password_resets WHERE token = ?", (token,))
    if not row or row["used_at"] is not None or datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
        raise APIError("Reset link is no longer valid", 400)

    execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(new_password), user_id))
    execute("UPDATE password_resets SET used_at = ? WHERE token = ?", (utcnow_iso(), token))
    execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))

    return jsonify({"message": "Password updated"})
