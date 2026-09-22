import secrets
from functools import wraps
from flask import current_app, g, request, session

from app.db import execute, query_one
from app.security import csrf_token_signature_valid, generate_csrf_token

POPULARITY_LIKE_WEIGHT = 10
POPULARITY_REPORT_PENALTY = 15

CSRF_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class APIError(Exception):
    def __init__(self, message, status=400):
        self.message = message
        self.status = status
        super().__init__(message)


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not g.get("current_user"):
            raise APIError("Authentication required", 401)
        return fn(*args, **kwargs)

    return wrapper


def get_csrf_token():
    """Return the CSRF token bound to the current session, creating one if missing.

    Exposed to templates as `{{ csrf_token() }}` (see the `inject_auth` context
    processor in app/__init__.py) so every `<form method="post">` can carry it as a
    hidden field, and to any inline script via the `<meta name="csrf-token">` tag in
    components/base.html.
    """
    token = session.get("csrf_token")
    if not token:
        token = generate_csrf_token(current_app.config["SECRET_KEY"])
        session["csrf_token"] = token
    return token


def _submitted_csrf_token():
    token = request.form.get("csrf_token")
    if token:
        return token

    token = request.headers.get("X-CSRFToken")
    if token:
        return token

    json_body = request.get_json(silent=True)
    if isinstance(json_body, dict):
        return json_body.get("csrf_token")

    return None


def csrf_protect():
    """Reject state-changing requests (POST/PUT/DELETE/PATCH) without a valid CSRF token.

    Wired as a global `before_request` hook (see app/__init__.py) so every mutating
    route is covered, rather than relying on a per-view decorator that could be
    forgotten on a new form. Safe methods (GET/HEAD/OPTIONS) are never checked.
    """
    if request.method in CSRF_SAFE_METHODS:
        return

    session_token = session.get("csrf_token")
    submitted_token = _submitted_csrf_token()

    valid = (
        bool(session_token)
        and bool(submitted_token)
        and secrets.compare_digest(session_token, submitted_token)
        and csrf_token_signature_valid(current_app.config["SECRET_KEY"], session_token)
    )
    if not valid:
        raise APIError("Invalid or missing CSRF token", 403)


def update_popularity(user_id: int):
    row = query_one(
        "SELECT COUNT(*) AS views FROM profile_views WHERE viewed_id = ?",
        (user_id,),
    )
    views = row["views"] if row else 0

    likes = query_one("SELECT COUNT(*) AS likes FROM likes WHERE to_user_id = ?", (user_id,))
    like_count = likes["likes"] if likes else 0

    reports = query_one("SELECT COUNT(*) AS reports FROM reports WHERE reported_id = ?", (user_id,))
    report_count = reports["reports"] if reports else 0

    score = max(0, (like_count * POPULARITY_LIKE_WEIGHT) + views - (report_count * POPULARITY_REPORT_PENALTY))
    execute("UPDATE profiles SET popularity_score = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?", (score, user_id))
    return score


def add_notification(user_id: int, notif_type: str, payload: str | None = None):
    execute(
        "INSERT INTO notifications (user_id, type, payload) VALUES (?, ?, ?)",
        (user_id, notif_type, payload),
    )


def is_blocked_between(user_a: int, user_b: int):
    row = query_one(
        """
        SELECT 1
        FROM blocks
        WHERE (blocker_id = ? AND blocked_id = ?) OR (blocker_id = ? AND blocked_id = ?)
        """,
        (user_a, user_b, user_b, user_a),
    )
    return bool(row)


def is_match(user_a: int, user_b: int):
    first = query_one("SELECT 1 FROM likes WHERE from_user_id = ? AND to_user_id = ?", (user_a, user_b))
    second = query_one("SELECT 1 FROM likes WHERE from_user_id = ? AND to_user_id = ?", (user_b, user_a))
    return bool(first and second)
