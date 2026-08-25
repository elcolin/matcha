import os
import sys
import random
import sqlite3
from datetime import datetime, timedelta
from faker import Faker
import requests

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from app.db import execute

"""
Usage:
    python scripts/generate_500.py [count]           # Generate (default: 500)
    python scripts/generate_500.py cleanup START END # Delete users START-END
    python scripts/generate_500.py cleanall         # Delete all from DB
"""

app = create_app()
fake = Faker(["en_US", "fr_FR", "de_DE", "es_ES"])

GENDERS = ["female", "male", "non-binary", "other"]
SEXUAL_PREFERENCES = ["everyone", "men", "women"]
TAGS = [
    "sports",
    "movies",
    "music",
    "travel",
    "food",
    "art",
    "fitness",
    "reading",
    "gaming",
    "photography",
    "technology",
    "dancing",
    "pets",
    "outdoors",
    "cooking",
    "yoga",
    "nightlife",
    "coffee",
    "theater",
    "volunteering",
]


def random_last_seen(created_at: datetime):
    if random.random() >= 0.9:
        return None
    return min(created_at + timedelta(days=random.randint(0, 700)), datetime.now())


def generate_user(max_attempts: int = 10):
    """Generate a single user row, retrying on UNIQUE constraint failures."""
    for attempt in range(max_attempts):
        first = fake.first_name()
        last = fake.last_name()
        email = fake.unique.email()
        username = fake.unique.user_name()
        password_hash = fake.sha256()
        email_verified = random.choices([0, 1], weights=[20, 80])[0]
        created_at = fake.date_time_between(start_date="-2y", end_date="now")
        last_seen_at = random_last_seen(created_at)

        try:
            cur = execute(
                """INSERT INTO users
                   (email, username, last_name, first_name, password_hash,
                    email_verified, created_at, last_seen_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    email,
                    username,
                    last,
                    first,
                    password_hash,
                    email_verified,
                    created_at.isoformat(sep=" "),
                    last_seen_at.isoformat(sep=" ") if last_seen_at else None,
                ),
            )

            return {
                "id": cur.lastrowid,
                "email": email,
                "username": username,
                "first_name": first,
                "last_name": last,
                "created_at": created_at,
            }

        except sqlite3.IntegrityError:
            # likely a UNIQUE conflict on email or username - retry
            if attempt == max_attempts - 1:
                raise
            # reset faker unique state for safety on repeated collisions
            try:
                fake.unique.clear()
            except Exception:
                pass
            continue


def generate_profile(user_id: int, created_at: datetime):
    gender = random.choice(GENDERS)
    sexual_preference = random.choice(SEXUAL_PREFERENCES)
    bio = fake.paragraph(nb_sentences=3)
    city = fake.city()
    neighborhood = fake.street_name()
    age = random.randint(18, 70)
    popularity_score = random.randint(0, 5)
    updated_at = fake.date_time_between(start_date=created_at, end_date="now").isoformat(sep=" ")
    location_consent_gps = 1 if random.random() < 0.7 else 0
    latitude = float(fake.latitude()) if location_consent_gps else None
    longitude = float(fake.longitude()) if location_consent_gps else None

    execute(
        """INSERT INTO profiles
           (user_id, gender, sexual_preference, bio, city, neighborhood,
            latitude, longitude, location_consent_gps, popularity_score,
            age, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            user_id,
            gender,
            sexual_preference,
            bio,
            city,
            neighborhood,
            latitude,
            longitude,
            location_consent_gps,
            popularity_score,
            age,
            updated_at,
        ),
    )


def create_users(count: int):
    users = []
    for _ in range(count):
        users.append(generate_user())
    return users


def _allocate_ids(count: int):
    rows = execute("SELECT id FROM users ORDER BY id ASC").fetchall()
    existing = {r[0] for r in rows}
    ids = []
    cur = 1
    while len(ids) < count:
        if cur not in existing:
            ids.append(cur)
        cur += 1
    max_existing = max(existing) if existing else 0
    if ids and ids[-1] <= max_existing:
        needed = count - sum(1 for i in ids if i <= max_existing)
        ids = [i for i in ids if i <= max_existing]
        start = max_existing + 1
        for i in range(needed):
            ids.append(start + i)
    return ids


def generate_tags():
    tag_ids = []
    for tag in TAGS:
        cur = execute(
            "INSERT OR IGNORE INTO tags (name) VALUES (?)",
            (tag,),
        )
        if cur.lastrowid:
            tag_ids.append(cur.lastrowid)

    existing = execute("SELECT id FROM tags WHERE name IN ({})".format(
        ",".join("?" for _ in TAGS)
    ), tuple(TAGS)).fetchall()
    tag_ids.extend([row[0] for row in existing if row[0] not in tag_ids])
    return tag_ids


def create_user_tags(users, tag_ids):
    for user in users:
        user_tag_count = random.randint(1, min(5, len(tag_ids)))
        user_tags = random.sample(tag_ids, user_tag_count)
        for tag_id in user_tags:
            execute(
                "INSERT OR IGNORE INTO user_tags (user_id, tag_id) VALUES (?, ?)",
                (user["id"], tag_id),
            )


def create_profiles(users):
    for user in users:
        generate_profile(user["id"], user["created_at"])


def generate_photos(count):
    return [
        f"https://loremflickr.com/400/400/bird?lock={random.randint(1, 100000)}"
        for _ in range(count)
    ]


def create_photos(users, photos_per_user=5):
    """Create photos for each user (accepts list of user dicts)."""
    total_photos = len(users) * photos_per_user
    urls = iter(generate_photos(total_photos))

    for user in users:
        user_id = user["id"]
        for i in range(photos_per_user):
            execute(
                """
                INSERT INTO photos (user_id, url, is_profile_photo)
                VALUES (?, ?, ?)
                """,
                (
                    user_id,
                    next(urls),
                    1 if i == 0 else 0,
                ),
            )

def main(count: int = 500, reuse_ids: bool = False):
    tag_ids = generate_tags()
    if reuse_ids:
        ids = _allocate_ids(count)
        users = []
        for uid in ids:
            generated = None
            for attempt in range(10):
                try:
                    first = fake.first_name()
                    last = fake.last_name()
                    email = fake.unique.email()
                    username = fake.unique.user_name()
                    password_hash = fake.sha256()
                    email_verified = random.choices([0, 1], weights=[20, 80])[0]
                    created_at = fake.date_time_between(start_date="-2y", end_date="now")
                    last_seen_at = random_last_seen(created_at)

                    cur = execute(
                        """INSERT INTO users (id, email, username, last_name, first_name, password_hash,
                           email_verified, created_at, last_seen_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            uid,
                            email,
                            username,
                            last,
                            first,
                            password_hash,
                            email_verified,
                            created_at.isoformat(sep=" "),
                            last_seen_at.isoformat(sep=" ") if last_seen_at else None,
                        ),
                    )
                    generated = {
                        "id": uid,
                        "email": email,
                        "username": username,
                        "first_name": first,
                        "last_name": last,
                        "created_at": created_at,
                    }
                    break
                except sqlite3.IntegrityError:
                    try:
                        fake.unique.clear()
                    except Exception:
                        pass
                    continue
            if not generated:
                raise RuntimeError("Failed to insert user with explicit id")
            users.append(generated)
    else:
        users = create_users(count)

    create_profiles(users)
    create_user_tags(users, tag_ids)
    create_photos(users, 1)
    start_id = users[0]["id"] if users else None
    end_id = users[-1]["id"] if users else None
    print(f"Inserted {count} users, profiles, and user tags.")
    if start_id and end_id:
        print(f"Inserted user id range: {start_id} - {end_id}")
    return start_id, end_id


def cleanup(start_id: int, end_id: int):
    """Delete users from start_id to end_id (inclusive) and all related data."""
    execute(
        "DELETE FROM user_tags WHERE user_id BETWEEN ? AND ?",
        (start_id, end_id),
    )
    execute(
        "DELETE FROM profiles WHERE user_id BETWEEN ? AND ?",
        (start_id, end_id),
    )
    execute(
        "DELETE FROM users WHERE id BETWEEN ? AND ?",
        (start_id, end_id),
    )
    print(f"Deleted users {start_id} to {end_id} and all related data.")


def clean_all():
    """Delete all seeded data from tables created by this script."""
    # remove relations first
    execute("DELETE FROM user_tags")
    execute("DELETE FROM photos")
    execute("DELETE FROM profiles")
    execute("DELETE FROM users")
    execute("DELETE FROM tags")
    print("Deleted all seeded data (user_tags, photos, profiles, users, tags).")


if __name__ == "__main__":
    import sys

    with app.app_context():
        if len(sys.argv) > 1 and sys.argv[1] == "cleanup":
            start = int(sys.argv[2]) if len(sys.argv) > 2 else 1
            end = int(sys.argv[3]) if len(sys.argv) > 3 else 500
            cleanup(start, end)
        elif len(sys.argv) > 1 and sys.argv[1] == "temp":
            count = int(sys.argv[2]) if len(sys.argv) > 2 else 500
            start, end = main(count)
            if start and end:
                print(f"Cleaning up temporary users {start} - {end}")
                cleanup(start, end)
        elif len(sys.argv) > 1 and sys.argv[1] == "reuse":
            count = int(sys.argv[2]) if len(sys.argv) > 2 else 500
            start, end = main(count, reuse_ids=True)
            if start and end:
                print(f"Generated (reused ids) users {start} - {end}")
        elif len(sys.argv) > 1 and sys.argv[1] == "cleanall":
            clean_all()
        else:
            count = int(sys.argv[1]) if len(sys.argv) > 1 else 500
            start, end = main(count)
            if start and end:
                print(f"Generated users {start} - {end}")
