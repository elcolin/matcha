from flask import (
    Blueprint,
    g,
    jsonify,
    redirect,
    request,
    render_template,
    url_for,
)

from app.utils import (
    login_required,
)

import json
from app.db import execute, query_all, query_one

notifications_bp = Blueprint("notifications", __name__, url_prefix="/notifications")

@notifications_bp.route("/unread-count", methods=["GET"])
@login_required
def unread_notifications_count():
    current = g.current_user["id"]
    row = query_one(
        "SELECT COUNT(*) AS c FROM notifications WHERE user_id = ? AND is_read = 0",
        (current,),
    )
    return jsonify({"unread": row["c"] if row else 0})


@notifications_bp.route("/mark-read", methods=["POST"])
@login_required
def mark_notifications_read():
    current = g.current_user["id"]
    execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (current,))
    return redirect(url_for("notifications.notifications_view"))

def _notifications_for(user_id, unread_only=False):
    if unread_only:
        rows = query_all("SELECT * FROM notifications WHERE user_id = ? AND is_read = 0 ORDER BY id DESC LIMIT 100", (user_id,))
    else:
        rows = query_all("SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT 100", (user_id,))

    payload = []
    for row in rows:
        item = dict(row)
        if item.get("payload"):
            try:
                item["payload"] = json.loads(item["payload"])
            except Exception:
                pass
        item["actor"] = None
        payload.append(item)

    actor_ids = {_actor_id(item["payload"]) for item in payload} - {None}
    if actor_ids:
        placeholders = ",".join("?" * len(actor_ids))
        actors = {
            row["id"]: dict(row)
            for row in query_all(
                f"SELECT id, username, first_name FROM users WHERE id IN ({placeholders})",
                tuple(actor_ids),
            )
        }
        for item in payload:
            item["actor"] = actors.get(_actor_id(item["payload"]))
    return payload


# Payload key holding the user who triggered the notification, depending on its type.
_ACTOR_KEYS = ("from_user_id", "viewer_id", "user_id")


def _actor_id(payload):
    if not isinstance(payload, dict):
        return None
    for key in _ACTOR_KEYS:
        value = payload.get(key)
        if isinstance(value, int):
            return value
    return None


@notifications_bp.route("/view", methods=["GET"])
@login_required
def notifications_view():
    current = g.current_user["id"]
    notifications = _notifications_for(current)
    return render_template("notifications.html", notifications=notifications)