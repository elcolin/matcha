from flask import (
    Blueprint,
    g,
    jsonify,
    request,
    render_template
)

from app.utils import (
    login_required,
)

import json
from app.db import execute, query_all, query_one

notifications_bp = Blueprint("notifications", __name__)

@notifications_bp.route("/notifications", methods=["GET"])
@login_required
def list_notifications():
    current = g.current_user["id"]
    unread_only = request.args.get("unread") == "1"
    if unread_only:
        rows = query_all(
            "SELECT * FROM notifications WHERE user_id = ? AND is_read = 0 ORDER BY id DESC LIMIT 100",
            (current,),
        )
    else:
        rows = query_all(
            "SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT 100",
            (current,),
        )

    payload = []
    for row in rows:
        item = dict(row)
        if item.get("payload"):
            try:
                item["payload"] = json.loads(item["payload"])
            except Exception:
                pass
        payload.append(item)

    return jsonify(payload)


@notifications_bp.route("/notifications/unread-count", methods=["GET"])
@login_required
def unread_notifications_count():
    current = g.current_user["id"]
    row = query_one(
        "SELECT COUNT(*) AS c FROM notifications WHERE user_id = ? AND is_read = 0",
        (current,),
    )
    return jsonify({"unread": row["c"] if row else 0})


@notifications_bp.route("/notifications/mark-read", methods=["POST"])
@login_required
def mark_notifications_read():
    current = g.current_user["id"]
    execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (current,))
    return jsonify({"ok": True})

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
        payload.append(item)
    return payload


@notifications_bp.route("/notifications/view", methods=["GET"])
@login_required
def notifications_view():
    current = g.current_user["id"]
    notifications = _notifications_for(current)
    return render_template("notifications.html", notifications=notifications)