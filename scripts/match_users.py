"""
Dev-only: force a match (mutual like) between two existing users.

Usage:
    python scripts/match_users.py USER_A USER_B    # each USER is an id or a username

Mirrors POST /profile/<id>/like (app/profile/routes.py) for both directions:
likes, like_received/new_match notifications, popularity update. The profile
photo requirement of the route is deliberately skipped for seeding.
"""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.db import execute, query_one
from app.security import build_notification_payload
from app.utils import add_notification, is_blocked_between, is_match, update_popularity


def resolve_user_id(user: str) -> int:
    if user.isdigit():
        row = query_one("SELECT id FROM users WHERE id = ?", (int(user),))
    else:
        row = query_one("SELECT id FROM users WHERE username = ?", (user,))
    if not row:
        raise ValueError(f"Unknown user: {user}")
    return row["id"]


def match_users(user_a: int, user_b: int) -> bool:
    """Return True if a new match was created, False if they were already matched."""
    if user_a == user_b:
        raise ValueError("Cannot match a user with themselves")
    if is_blocked_between(user_a, user_b):
        raise ValueError("Users are blocked, unblock them first")
    if is_match(user_a, user_b):
        return False

    for liker, liked in ((user_a, user_b), (user_b, user_a)):
        cur = execute(
            "INSERT OR IGNORE INTO likes (from_user_id, to_user_id) VALUES (?, ?)",
            (liker, liked),
        )
        if cur.rowcount:
            add_notification(liked, "like_received", build_notification_payload(from_user_id=liker))

    add_notification(user_b, "new_match", build_notification_payload(user_id=user_a))
    add_notification(user_a, "new_match", build_notification_payload(user_id=user_b))
    update_popularity(user_a)
    update_popularity(user_b)
    return True


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("Usage: python scripts/match_users.py USER_A USER_B")

    from app import create_app

    with create_app().app_context():
        try:
            a, b = resolve_user_id(sys.argv[1]), resolve_user_id(sys.argv[2])
            created = match_users(a, b)
        except ValueError as err:
            sys.exit(str(err))
        print(f"Matched users {a} and {b}." if created else f"Users {a} and {b} are already matched.")
