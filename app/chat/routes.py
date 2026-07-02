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

    print(current, user_id)
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
    return jsonify({"sent": True})


@chat_bp.route("/stream", methods=["GET"])
@login_required
def stream_events():
    current = g.current_user["id"]
    since = request.args.get("since", 0, type=int)

    def generator():
        last_message_id = since
        try:
            while True:
                messages = query_all(
                    "SELECT id, sender_id, content, created_at FROM messages WHERE receiver_id = ? AND id > ? ORDER BY id ASC",
                    (current, last_message_id),
                )
                if messages:
                    for msg in messages:
                        last_message_id = msg["id"]
                        yield f"event: message\ndata: {json.dumps(dict(msg))}\n\n"
                time.sleep(POLL_INTERVAL_SECONDS)
        except GeneratorExit:
            return

    return Response(stream_with_context(generator()), mimetype="text/event-stream")