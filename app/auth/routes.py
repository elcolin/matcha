import secrets
from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, g, jsonify, redirect, render_template, render_template_string, request, session, url_for

from app.db import execute, query_one
from app.email import send_email
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
    execute(
        """
        DELETE FROM login_attempts
        WHERE attempted_at < datetime('now', '-2 days')
        """,
    )
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
        return render_template("register.html")

    data = request.get_json(silent=True) or request.form

    required = ["email", "username", "last_name", "first_name", "password"]
    missing = [f for f in required if not str(data.get(f, "")).strip()]
    if missing:
        return render_template("register.html", error=f"Missing fields: {', '.join(missing)}")

    is_ok, reason = validate_password_strength(data["password"])
    if not is_ok:
        return render_template("register.html", error=reason)

    try:
        cur = execute(
            "INSERT INTO users (email, username, last_name, first_name, password_hash) VALUES (?, ?, ?, ?, ?)",
            (data["email"].strip().lower(), data["username"].strip(),
             data["last_name"].strip(), data["first_name"].strip(),
             hash_password(data["password"])),
        )
    except Exception:
        return render_template("register.html", error="Email or username already exists")

    user_id = cur.lastrowid
    _ensure_profile_exists(user_id)

    token = issue_signed_token(current_app.config["SECRET_KEY"], "verify_email", user_id)
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=current_app.config["EMAIL_VERIFY_TOKEN_TTL_SECONDS"])).isoformat()
    execute("INSERT INTO email_verifications (user_id, token, expires_at) VALUES (?, ?, ?)", (user_id, token, expires_at))

    verify_link = url_for("auth.verify_email", token=token, _external=True)

    send_email(
        data["email"].strip().lower(),
        "Verify your Matcha account",
        f"""
        <h1>Welcome to Matcha! 🐦</h1>
        <p>Thanks for signing up, {data["first_name"].strip()}!</p>
        <p><a href="{verify_link}">Verify your email</a></p>
        <p>If you did not create this account, ignore this email.</p>
        """,
    )

    return render_template(
        "register.html",
        success=f"Account created! Check {data['email'].strip().lower()} for your verification email.",
    )


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

    return redirect(url_for("auth.login", verified=1))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    data = request.get_json(silent=True) or request.form
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))

    if not username or not password:
        return render_template("login.html", error="Username and password are required")

    if _is_locked_out(username):
        return render_template("login.html", error="Too many failed attempts. Please try again later.")

    user = query_one("SELECT * FROM users WHERE username = ?", (username,))
    if not user or not verify_password(user["password_hash"], password):
        execute("INSERT INTO login_attempts (username, success) VALUES (?, 0)", (username,))
        return render_template("login.html", error="Invalid username or password")

    if not user["email_verified"]:
        return render_template("login.html", error="Please verify your email before logging in")

    execute("INSERT INTO login_attempts (username, success) VALUES (?, 1)", (username,))
    session.clear()
    session["user_id"] = user["id"]
    session_token = secrets.token_urlsafe(32)
    session["session_token"] = session_token
    session["logout_token"] = secrets.token_urlsafe(16)
    execute("INSERT INTO user_sessions (user_id, session_token) VALUES (?, ?)", (user["id"], session_token))

    return redirect("/")


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


@auth_bp.route("/password-reset/request", methods=["GET", "POST"])
def request_password_reset():
    if request.method == "GET":
        return render_template("forgot_password.html")

    identifier = str(request.form.get("email", "")).strip().lower()
    print("Password reset requested for:", identifier)

    if not identifier:
        return render_template("forgot_password.html", error="Email is required")

    user = query_one("SELECT id FROM users WHERE email = ?", (identifier,))

    if user:
        return render_template("forgot_password.html", success=f"Reset link has been sent to{identifier}")
    
    else:
        return render_template("forgot_password.html", error=f"No such user{identifier}")
    
    token = issue_signed_token(current_app.config["SECRET_KEY"], "password_reset", user["id"])
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=current_app.config["PASSWORD_RESET_TTL_SECONDS"])
    ).isoformat()
    execute(
        "INSERT INTO password_resets (user_id, token, expires_at) VALUES (?, ?, ?)",
        (user["id"], token, expires_at),
    )

    reset_link = url_for("auth.confirm_password_reset", token=token, _external=True)
    send_email(
        identifier,
        "Reset your Matcha password",
        f"""
        <h1>Password reset</h1>
        <p>You requested a password reset for your Matcha account</p>
        <p><a href="{reset_link}">Reset password</a></p>
        <p>If you did not request this, ignore this email.</p>
        """,
    )

    return render_template("forgot_password.html", success="If your account exists, a reset link has been sent.")

@auth_bp.route("/password-reset/confirm/<token>", methods=["GET", "POST"])
def confirm_password_reset(token):
    def render_form(error=None, success=None):
        return render_template_string(
            """
            {% extends "components/base.html" %}
            {% block title %}Matcha — Reset Password{% endblock %}
            {% block content %}
            <div class="d-flex justify-content-center pt-5">
              <div class="card shadow-sm" style="width:360px">
                <div class="card-body p-4">
                  <h5 class="card-title mb-1">Choose a New Password</h5>
                  <p class="text-muted mb-3" style="font-size:0.85rem">Enter a new password to complete the reset.</p>
                  {% if error %}
                    <div class="alert alert-danger">{{ error }}</div>
                  {% endif %}
                  {% if success %}
                    <div class="alert alert-success">{{ success }}</div>
                  {% endif %}
                  <form method="POST" action="{{ url_for('auth.confirm_password_reset', token=token) }}">
                    <div class="mb-3">
                      <label class="form-label">New Password</label>
                      <input name="password" class="form-control" type="password" required />
                    </div>
                    <button type="submit" class="btn btn-danger w-100 mb-3">Reset password</button>
                  </form>
                </div>
              </div>
            </div>
            {% endblock %}
            """,
            token=token,
            error=error,
            success=success,
        )

    if request.method == "GET":
        return render_form()

    new_password = str(request.form.get("password", ""))
    is_ok, reason = validate_password_strength(new_password)
    if not is_ok:
        return render_form(error=reason)

    try:
        user_id = read_signed_token(
            current_app.config["SECRET_KEY"],
            token,
            "password_reset",
            current_app.config["PASSWORD_RESET_TTL_SECONDS"],
        )
    except Exception:
        return render_form(error="Invalid or expired reset token")

    row = query_one("SELECT id, expires_at, used_at FROM password_resets WHERE token = ?", (token,))
    if not row or row["used_at"] is not None or datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
        return render_form(error="Reset link is no longer valid")

    execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(new_password), user_id))
    execute("UPDATE password_resets SET used_at = ? WHERE token = ?", (utcnow_iso(), token))
    execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))

    return render_form(success="Your password has been updated. You can now log in.")
