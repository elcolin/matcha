from functools import wraps
from flask import g, jsonify, session

from app.db import execute, query_one

POPULARITY_LIKE_WEIGHT = 10
POPULARITY_REPORT_PENALTY = 15


class APIError(Exception):
    def __init__(self, message, status=400):
        self.message = message
        self.status = status
        super().__init__(message)


def json_error(message, status=400):
    return jsonify({"error": message}), status


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not g.get("current_user"):
            raise APIError("Authentication required", 401)
        return fn(*args, **kwargs)

    return wrapper


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
