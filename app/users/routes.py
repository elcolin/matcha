from flask import Blueprint, g, jsonify

from app.db import query_one
from app.profile.routes import _compute_online
from app.utils import APIError, is_blocked_between, is_match, login_required

users_bp = Blueprint("users", __name__)


@users_bp.route("/users")
def list_users_placeholder():
    return jsonify({"message": "Use /match and /profile APIs for user discovery"})


@users_bp.route("/users/<int:id>/online-status", methods=["GET"])
@login_required
def online_status(id):
    row = query_one(
        "SELECT last_seen_at, online_until FROM users WHERE id = ?", (id,)
    )
    if row is None:
        raise APIError("User not found", 404)

    current = g.current_user["id"]
    if not is_match(current, id):
        raise APIError("Online status is available only for connected users", 403)
    if is_blocked_between(current, id):
        raise APIError("Online status unavailable", 403)

    return jsonify(
        {
            "online": _compute_online(row["online_until"]),
            "last_seen_at": row["last_seen_at"],
        }
    )
