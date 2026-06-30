import json
import time

from flask import Blueprint, Response, g, jsonify, render_template, request, stream_with_context

from app.db import execute, query_all, query_one
from app.security import build_notification_payload
from app.utils import APIError, add_notification, is_blocked_between, is_match, login_required

chat_bp = Blueprint("chat", __name__, url_prefix="/chat")
POLL_INTERVAL_SECONDS = 1
HEARTBEAT_EVERY_N_POLLS = 10  # send the unread-count heartbeat every ~10s
PRESENCE_STALE_SECONDS = 15  # how long a "viewing this chat" ping stays valid


def _is_viewing_chat(viewer_id, partner_id):
    """True if `viewer_id` pinged the chat page with `partner_id` open recently."""
    row = query_one(
        """
        SELECT 1 FROM chat_presence
        WHERE user_id = ? AND partner_id = ?
          AND updated_at >= datetime('now', ?)
        """,
        (viewer_id, partner_id, f"-{PRESENCE_STALE_SECONDS} seconds"),
    )
    return bool(row)


@chat_bp.route("", methods=["GET"])
@login_required
def chat_home():
    return "Chat API is ready"


def _matches_for(user_id):
    """Users with a mutual like (i.e. a match) with the given user."""
    rows = query_all(
        """
        SELECT u.id, u.username, u.first_name, u.last_name
        FROM likes a
        JOIN likes b ON a.from_user_id = b.to_user_id AND a.to_user_id = b.from_user_id
        JOIN users u ON u.id = a.to_user_id
        WHERE a.from_user_id = ?
        ORDER BY u.first_name ASC
        """,
        (user_id,),
    )
    return [dict(r) for r in rows]


@chat_bp.route("/view", methods=["GET"], defaults={"user_id": None})
@chat_bp.route("/view/<int:user_id>", methods=["GET"])
@login_required
def chat_view(user_id):
    current = g.current_user["id"]
    matches = _matches_for(current)

    active = None
    if user_id is not None:
        active = next((m for m in matches if m["id"] == user_id), None)
        if active is None:
            raise APIError("Chat is available only for connected users", 403)

    return render_template("chat.html", matches=matches, active=active)


@chat_bp.route("/<int:user_id>", methods=["GET"])
@login_required
def conversation(user_id):
    current = g.current_user["id"]
    if not is_match(current, user_id):
        raise APIError("Chat is available only for connected users", 403)
    if is_blocked_between(current, user_id):
        raise APIError("Chat unavailable", 403)

    rows = query_all(
        """
        SELECT id, sender_id, receiver_id, content, created_at, read_at
        FROM messages
        WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?)
        ORDER BY id ASC
        LIMIT 500
        """,
        (current, user_id, user_id, current),
    )

    execute(
        "UPDATE messages SET read_at = CURRENT_TIMESTAMP WHERE sender_id = ? AND receiver_id = ? AND read_at IS NULL",
        (user_id, current),
    )

    return jsonify([dict(r) for r in rows])


@chat_bp.route("/<int:user_id>/send", methods=["POST"])
@login_required
def send_message(user_id):
    current = g.current_user["id"]
    if not is_match(current, user_id):
        raise APIError("Chat is available only for connected users", 403)
    if is_blocked_between(current, user_id):
        raise APIError("Chat unavailable", 403)

    data = request.get_json(silent=True) or request.form
    content = str(data.get("content", "")).strip()
    if not content:
        raise APIError("content is required", 400)

    execute(
        "INSERT INTO messages (sender_id, receiver_id, content) VALUES (?, ?, ?)",
        (current, user_id, content),
    )

    # Skip the notification if the recipient already has this conversation
    # open — they'll see the message live via the SSE "message" event anyway.
    if not _is_viewing_chat(user_id, current):
        add_notification(user_id, "new_message", build_notification_payload(from_user_id=current, preview=content[:100]))

    return jsonify({"sent": True})


@chat_bp.route("/<int:user_id>/presence", methods=["POST"])
@login_required
def ping_presence(user_id):
    """Called periodically by the chat page while a conversation is open."""
    current = g.current_user["id"]
    if not is_match(current, user_id):
        raise APIError("Chat is available only for connected users", 403)

    execute(
        """
        INSERT INTO chat_presence (user_id, partner_id, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET partner_id = excluded.partner_id, updated_at = excluded.updated_at
        """,
        (current, user_id),
    )
    return jsonify({"ok": True})


@chat_bp.route("/stream", methods=["GET"])
@login_required
def stream_events():
    current = g.current_user["id"]

    def generator():
        last_notif_id = 0
        last_message_id = 0
        polls = 0

        try:
            while True:
                notifications = query_all(
                    "SELECT id, type, payload, created_at FROM notifications WHERE user_id = ? AND id > ? ORDER BY id ASC",
                    (current, last_notif_id),
                )
                if notifications:
                    for notif in notifications:
                        last_notif_id = notif["id"]
                        yield f"event: notification\ndata: {json.dumps(dict(notif))}\n\n"

                messages = query_all(
                    "SELECT id, sender_id, content, created_at FROM messages WHERE receiver_id = ? AND id > ? ORDER BY id ASC",
                    (current, last_message_id),
                )
                if messages:
                    for msg in messages:
                        last_message_id = msg["id"]
                        yield f"event: message\ndata: {json.dumps(dict(msg))}\n\n"

                # Only recompute/emit the unread-count heartbeat periodically,
                # so messages/notifications are picked up almost instantly
                # (every POLL_INTERVAL_SECONDS) without hammering the DB.
                if polls % HEARTBEAT_EVERY_N_POLLS == 0:
                    unread = query_one("SELECT COUNT(*) AS c FROM notifications WHERE user_id = ? AND is_read = 0", (current,))
                    yield f"event: heartbeat\ndata: {json.dumps({'unread_notifications': unread['c'] if unread else 0})}\n\n"

                polls += 1
                time.sleep(POLL_INTERVAL_SECONDS)
        except GeneratorExit:
            return

    return Response(stream_with_context(generator()), mimetype="text/event-stream")
