import os
import secrets
import sys
from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.db import execute, query_one
from app.security import hash_password

from scripts.chat_bot_responder import BOT_USERNAME_PREFIX
from scripts.generate_users import create_photos, generate_profile, reset_sequence

"""
Dev/demo tool only.

Creates a "bot" user account (see scripts/chat_bot_responder.py for the naming
convention) and matches it (mutual like) with an existing target user, so the
chat bot responder has a conversation to reply into.

Usage:
    python scripts/create_bot_user.py <match_with_user_id> [suffix]
    python scripts/create_bot_user.py cleanup START END   # delete users START id - END id
    python scripts/create_bot_user.py cleanall            # delete every bot_* user
"""


def create_bot_user(suffix=None):
    suffix = suffix or secrets.token_hex(3)
    username = f"{BOT_USERNAME_PREFIX}{suffix}"
    email = f"{username}@bot.matcha.invalid"
    password_hash = hash_password(secrets.token_urlsafe(24))
    created_at = datetime.now()

    cur = execute(
        """INSERT INTO users
           (email, username, last_name, first_name, password_hash,
            email_verified, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (email, username, "Bot", suffix, password_hash, 1, created_at.isoformat(sep=" ")),
    )
    user = {"id": cur.lastrowid, "username": username}

    generate_profile(user["id"], created_at)
    create_photos([user], photos_per_user=1)
    return user


def match_users(user_a, user_b):
    """Mutual like between the two users, i.e. a match (see app.utils.is_match)."""
    execute("INSERT OR IGNORE INTO likes (from_user_id, to_user_id) VALUES (?, ?)", (user_a, user_b))
    execute("INSERT OR IGNORE INTO likes (from_user_id, to_user_id) VALUES (?, ?)", (user_b, user_a))


def main(match_with_user_id, suffix=None):
    target = query_one("SELECT id, username FROM users WHERE id = ?", (match_with_user_id,))
    if target is None:
        print(f"Error: user {match_with_user_id} does not exist.", file=sys.stderr)
        sys.exit(1)

    bot = create_bot_user(suffix)
    match_users(bot["id"], target["id"])
    print(
        f"Created bot '{bot['username']}' (id {bot['id']}), "
        f"matched with '{target['username']}' (id {target['id']})."
    )
    return bot


def cleanup(start_id, end_id):
    execute(
        "DELETE FROM likes WHERE from_user_id BETWEEN ? AND ? OR to_user_id BETWEEN ? AND ?",
        (start_id, end_id, start_id, end_id),
    )
    execute("DELETE FROM photos WHERE user_id BETWEEN ? AND ?", (start_id, end_id))
    execute("DELETE FROM profiles WHERE user_id BETWEEN ? AND ?", (start_id, end_id))
    execute("DELETE FROM users WHERE id BETWEEN ? AND ?", (start_id, end_id))
    reset_sequence("users")
    reset_sequence("photos")
    print(f"Deleted users {start_id} to {end_id} and all related data.")


def clean_all():
    bot_pattern = (f"{BOT_USERNAME_PREFIX}%",)
    execute(
        """DELETE FROM likes
           WHERE from_user_id IN (SELECT id FROM users WHERE username LIKE ?)
              OR to_user_id IN (SELECT id FROM users WHERE username LIKE ?)""",
        bot_pattern + bot_pattern,
    )
    execute(
        "DELETE FROM photos WHERE user_id IN (SELECT id FROM users WHERE username LIKE ?)",
        bot_pattern,
    )
    execute(
        "DELETE FROM profiles WHERE user_id IN (SELECT id FROM users WHERE username LIKE ?)",
        bot_pattern,
    )
    execute("DELETE FROM users WHERE username LIKE ?", bot_pattern)
    reset_sequence("users")
    reset_sequence("photos")
    print("Deleted all bot users and related data.")


if __name__ == "__main__":
    from app import create_app

    app = create_app()
    with app.app_context():
        if len(sys.argv) > 1 and sys.argv[1] == "cleanup":
            start = int(sys.argv[2]) if len(sys.argv) > 2 else 1
            end = int(sys.argv[3]) if len(sys.argv) > 3 else 500
            cleanup(start, end)
        elif len(sys.argv) > 1 and sys.argv[1] == "cleanall":
            clean_all()
        elif len(sys.argv) > 1:
            match_with_user_id = int(sys.argv[1])
            bot_suffix = sys.argv[2] if len(sys.argv) > 2 else None
            main(match_with_user_id, bot_suffix)
        else:
            print(
                "Usage: python scripts/create_bot_user.py <match_with_user_id> [suffix]",
                file=sys.stderr,
            )
            sys.exit(1)
