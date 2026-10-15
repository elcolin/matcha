import os
import sys
import time

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.db import execute, query_all, query_one
from app.utils import is_blocked_between

from scripts.generate_chat import (
    MAX_GENERATION_ATTEMPTS,
    MODEL,
    OllamaUnavailableError,
    build_prompt,
    call_ollama,
    check_ollama_available,
    clean_generated_text,
    is_valid_message,
)

"""
Dev/demo tool only.

Polls the database for matched, non-blocked conversations involving one or more
"bot" users and makes the bot reply, in real time, to the last message it received
(never to initiate a conversation). Messages are inserted directly into the
`messages` table exactly like `app.chat.routes.send_message`, so the existing
SSE stream (`/chat/stream`) and polling deliver them without any change.

This script is never imported nor started by `app/__init__.py`, and no Flask
route triggers it. It must be launched manually, e.g.:

    python scripts/chat_bot_responder.py             # reply as every bot_* user
    python scripts/chat_bot_responder.py bot_ana      # reply only as user "bot_ana"

Requires a local Ollama server, see scripts/generate_chat.py for setup instructions.
"""

# Convention used to identify a "bot" account: a regular `users` row whose
# username starts with this prefix. Imported (never duplicated) by
# scripts/create_bot_user.py.
BOT_USERNAME_PREFIX = "bot_"

# Labels fed to scripts.generate_chat.build_prompt: the bot never starts a
# conversation, so its label only ever appears as a reply to PARTNER_LABEL.
BOT_LABEL = "B"
PARTNER_LABEL = "A"

# Keep this comfortably under the mandatory 10s real-time budget once the
# Ollama generation latency is added on top of it.
DEFAULT_POLL_INTERVAL_SECONDS = 2


def is_bot_username(username):
    """True if `username` follows the bot naming convention."""
    if not username:
        return False
    return username.startswith(BOT_USERNAME_PREFIX)


def needs_bot_reply(last_message, bot_id):
    """True if the bot identified by `bot_id` should reply to `last_message`.

    `last_message` is a mapping with at least a `sender_id` key (or None if the
    conversation has no message yet). The bot only replies, it never starts a
    conversation, and it never replies to its own last message.
    """
    if last_message is None:
        return False
    return last_message["sender_id"] != bot_id


def build_bot_history(rows, bot_id):
    """Convert `messages` rows into (label, text) tuples for `build_prompt`.

    Does not mutate `rows`.
    """
    history = []
    for row in rows:
        label = BOT_LABEL if row["sender_id"] == bot_id else PARTNER_LABEL
        history.append((label, row["content"]))
    return history


def find_bot_pairs(bot_id):
    """Matched (mutually liked), non-blocked partners of the given bot."""
    rows = query_all(
        """
        SELECT u.id, u.username
        FROM likes a
        JOIN likes b ON a.from_user_id = b.to_user_id AND a.to_user_id = b.from_user_id
        JOIN users u ON u.id = a.to_user_id
        WHERE a.from_user_id = ?
        """,
        (bot_id,),
    )
    partners = []
    for row in rows:
        if is_blocked_between(bot_id, row["id"]):
            continue
        partners.append({"id": row["id"], "username": row["username"]})
    return partners


def last_message_between(user_a, user_b):
    """Most recent message between the two users, including the sender's username."""
    return query_one(
        """
        SELECT m.sender_id, m.receiver_id, m.content, u.username AS sender_username
        FROM messages m
        JOIN users u ON u.id = m.sender_id
        WHERE (m.sender_id = ? AND m.receiver_id = ?) OR (m.sender_id = ? AND m.receiver_id = ?)
        ORDER BY m.id DESC
        LIMIT 1
        """,
        (user_a, user_b, user_b, user_a),
    )


def conversation_history(bot_id, partner_id):
    """All messages between the bot and its partner, oldest first."""
    return query_all(
        """
        SELECT sender_id, content
        FROM messages
        WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?)
        ORDER BY id ASC
        """,
        (bot_id, partner_id, partner_id, bot_id),
    )


def build_reply_prompt(history, bot_label=BOT_LABEL, partner_label=PARTNER_LABEL):
    """Prompt for a single bot reply, built on top of the shared `build_prompt`.

    `build_prompt` alone (a plain alternating transcript) is not directive enough
    for small instruct models: they can drift and complete the partner's turn
    instead of the bot's own -- i.e. answer prefixed with `partner_label:` instead
    of `bot_label:`. Making both "who replies" and "to what" explicit greatly
    reduces that drift. This lives here rather than in `build_prompt` because that
    function is shared with `generate_chat.py`, which generates both sides of a
    conversation and has no single "partner to react to".
    """
    prompt = build_prompt(history, bot_label)

    partner_last = next(
        (text for label, text in reversed(history) if label == partner_label),
        None,
    )
    if partner_last is None:
        return prompt

    instruction = (
        f'Respond directly to what {partner_label} just said above ("{partner_last}"). '
        f"You are {bot_label}; write only your own reply, never {partner_label}'s line."
    )
    head, next_label_line = prompt.rsplit("\n", 1)
    return f"{head}\n{instruction}\n{next_label_line}"


def _is_mislabeled_as_partner(candidate):
    """True if `candidate` still carries the partner's speaker prefix.

    Happens when the model drifts and completes the partner's turn instead of
    the bot's own: `clean_generated_text` only strips the *expected*
    (`BOT_LABEL`) prefix, so a `PARTNER_LABEL:` prefix would otherwise leak
    verbatim into the message actually sent.
    """
    return candidate.lower().startswith(f"{PARTNER_LABEL.lower()}:")


def _is_echo_of_partner(candidate, partner_last):
    """True if `candidate` just parrots back the partner's last message.

    Small instruct models occasionally reply by repeating the received
    message verbatim (case/whitespace aside) instead of generating an actual
    reply -- e.g. answering "What's up?" with "What's up?". `partner_last` is
    None when the bot has nothing to react to yet, in which case there is
    nothing to echo.
    """
    if partner_last is None:
        return False
    return candidate.strip().lower() == partner_last.strip().lower()


def generate_bot_reply(bot_id, partner_id, model=MODEL):
    """Generate a single reply from the bot to its partner, or None if it fails."""
    history = build_bot_history(conversation_history(bot_id, partner_id), bot_id)
    prompt = build_reply_prompt(history, BOT_LABEL, PARTNER_LABEL)
    partner_last = next(
        (text for label, text in reversed(history) if label == PARTNER_LABEL),
        None,
    )

    for _attempt in range(MAX_GENERATION_ATTEMPTS):
        raw = call_ollama(prompt, model=model)
        candidate = clean_generated_text(raw, label=BOT_LABEL)
        if (
            is_valid_message(candidate)
            and not _is_mislabeled_as_partner(candidate)
            and not _is_echo_of_partner(candidate, partner_last)
        ):
            return candidate
    return None


def insert_bot_message(bot_id, partner_id, content):
    execute(
        "INSERT INTO messages (sender_id, receiver_id, content) VALUES (?, ?, ?)",
        (bot_id, partner_id, content),
    )


def resolve_bots(bot_selector=None):
    """Bot user(s) targeted by the CLI: a single username, or every bot_* user."""
    if bot_selector:
        row = query_one("SELECT id, username FROM users WHERE username = ?", (bot_selector,))
        return [dict(row)] if row else []

    rows = query_all(
        "SELECT id, username FROM users WHERE username LIKE ?",
        (f"{BOT_USERNAME_PREFIX}%",),
    )
    return [dict(row) for row in rows]


def run(bot_selector=None, poll_interval=DEFAULT_POLL_INTERVAL_SECONDS, model=MODEL):
    # Fail fast: refuse to start if Ollama (or the configured model) is unreachable.
    check_ollama_available(model=model)

    bots = resolve_bots(bot_selector)
    if not bots:
        print("No bot user found (looked for username(s) matching "
              f"'{BOT_USERNAME_PREFIX}*').", file=sys.stderr)
        return

    print("Bot responder started for: " + ", ".join(bot["username"] for bot in bots))

    while True:
        for bot in bots:
            # Recomputed every cycle so an unlike/block cuts the auto-reply
            # off starting the very next poll, with no stale cache involved.
            for partner in find_bot_pairs(bot["id"]):
                last = last_message_between(bot["id"], partner["id"])
                if not needs_bot_reply(last, bot["id"]):
                    continue
                # Anti infinite-loop guard: never reply to another bot's message.
                if is_bot_username(last["sender_username"]):
                    continue

                try:
                    reply = generate_bot_reply(bot["id"], partner["id"], model=model)
                except OllamaUnavailableError as exc:
                    print(f"Error: Ollama became unavailable: {exc}", file=sys.stderr)
                    sys.exit(1)

                if reply is None:
                    print(
                        f"Skipped reply from '{bot['username']}' to '{partner['username']}': "
                        "no valid message could be generated.",
                        file=sys.stderr,
                    )
                    continue

                insert_bot_message(bot["id"], partner["id"], reply)
                print(f"[{bot['username']}] -> [{partner['username']}]: {reply}")

        time.sleep(poll_interval)


if __name__ == "__main__":
    from app import create_app

    app = create_app()
    with app.app_context():
        selector = sys.argv[1] if len(sys.argv) > 1 else None
        try:
            run(bot_selector=selector)
        except OllamaUnavailableError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
