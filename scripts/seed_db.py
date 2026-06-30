"""Fill the database with fake but plausible profiles for local testing.

The subject requires at least 500 distinct profiles for evaluation. This
script inserts that many directly with SQL (bypassing the registration
email-verification flow, which would be far too slow for hundreds of
accounts) so you have something to browse/search/match against locally.

Usage:
    python scripts/seed_db.py            # adds 550 profiles
    python scripts/seed_db.py --count 800

All seeded accounts share the same password so you can log into any of
them while testing: "Seeded!Pass99x"
"""

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app
from app.db import execute, query_all, query_one
from app.security import hash_password

SEED_PASSWORD = "Seeded!Pass99x"

FIRST_NAMES = [
    "Alice", "Bob", "Chloe", "David", "Emma", "Felix", "Grace", "Hugo",
    "Ines", "Jules", "Kara", "Liam", "Mona", "Noah", "Olivia", "Paul",
    "Quinn", "Rosa", "Sami", "Tara", "Ugo", "Vera", "Will", "Xena",
    "Yara", "Zoe", "Adam", "Bella", "Caleb", "Diana", "Elio", "Fiona",
    "Gael", "Hana", "Ivo", "Jade", "Kian", "Lara", "Milo", "Nina",
]
LAST_NAMES = [
    "Martin", "Bernard", "Dubois", "Thomas", "Robert", "Petit", "Durand",
    "Leroy", "Moreau", "Simon", "Laurent", "Lefebvre", "Michel", "Garcia",
    "David", "Bertrand", "Roux", "Vincent", "Fontaine", "Chevalier",
]
# (city, neighborhood, latitude, longitude) — real-ish coordinates so the
# distance-based matching/sorting logic has something meaningful to sort.
CITIES = [
    ("Paris", "Le Marais", 48.8606, 2.3622),
    ("Paris", "Montmartre", 48.8867, 2.3431),
    ("Lyon", "Croix-Rousse", 45.7745, 4.8300),
    ("Lyon", "Presqu'ile", 45.7600, 4.8350),
    ("Marseille", "Le Panier", 43.2989, 5.3697),
    ("Toulouse", "Capitole", 43.6045, 1.4440),
    ("Bordeaux", "Chartrons", 44.8530, -0.5650),
    ("Lille", "Vieux-Lille", 50.6390, 3.0630),
    ("Nantes", "Bouffay", 47.2150, -1.5530),
    ("Strasbourg", "Petite France", 48.5810, 7.7460),
]
GENDERS = ["male", "female", "non_binary"]
PREFERENCES = ["straight", "gay", "bisexual"]
TAGS = [
    "vegan", "geek", "piercing", "travel", "music", "hiking", "coffee",
    "photography", "yoga", "gaming", "cinema", "cooking", "reading",
    "running", "art", "dancing", "climbing", "surfing", "wine", "cats",
]
BIO_TEMPLATES = [
    "Always up for a spontaneous trip and a good coffee.",
    "Looking for someone to share long conversations with.",
    "Big fan of {tag} and quiet Sunday mornings.",
    "New in town, exploring everything {city} has to offer.",
    "Passionate about {tag}, terrible at small talk.",
]


def build_profile(index, app_password_hash):
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    city, neighborhood, lat, lon = random.choice(CITIES)
    gender = random.choice(GENDERS)
    preference = random.choice(PREFERENCES)
    age = random.randint(18, 65)
    tags = random.sample(TAGS, k=random.randint(2, 5))
    bio = random.choice(BIO_TEMPLATES).format(tag=tags[0], city=city)

    username = f"{first.lower()}{last.lower()}{index}"
    email = f"{username}@seed.matcha"

    return {
        "email": email,
        "username": username,
        "first_name": first,
        "last_name": last,
        "password_hash": app_password_hash,
        "gender": gender,
        "sexual_preference": preference,
        "bio": bio,
        "city": city,
        "neighborhood": neighborhood,
        "latitude": lat + random.uniform(-0.01, 0.01),
        "longitude": lon + random.uniform(-0.01, 0.01),
        "age": age,
        "tags": tags,
    }


def insert_profile(profile):
    cur = execute(
        """
        INSERT INTO users (email, username, last_name, first_name, password_hash, email_verified)
        VALUES (?, ?, ?, ?, ?, 1)
        """,
        (
            profile["email"],
            profile["username"],
            profile["last_name"],
            profile["first_name"],
            profile["password_hash"],
        ),
    )
    user_id = cur.lastrowid

    execute(
        """
        INSERT INTO profiles (
            user_id, gender, sexual_preference, bio, city, neighborhood,
            latitude, longitude, location_consent_gps, age
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        """,
        (
            user_id,
            profile["gender"],
            profile["sexual_preference"],
            profile["bio"],
            profile["city"],
            profile["neighborhood"],
            profile["latitude"],
            profile["longitude"],
            profile["age"],
        ),
    )

    for tag_name in profile["tags"]:
        execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag_name,))
        tag_row = query_one("SELECT id FROM tags WHERE name = ?", (tag_name,))
        execute("INSERT OR IGNORE INTO user_tags (user_id, tag_id) VALUES (?, ?)", (user_id, tag_row["id"]))

    # Placeholder avatar so the "needs a profile photo to like" rule doesn't
    # block seeded accounts from being liked/matched during testing.
    avatar_url = f"https://i.pravatar.cc/300?img={(user_id % 70) + 1}"
    execute(
        "INSERT INTO photos (user_id, url, is_profile_photo) VALUES (?, ?, 1)",
        (user_id, avatar_url),
    )


def seed(count):
    app = create_app()
    with app.app_context():
        existing = query_one("SELECT COUNT(*) AS c FROM users WHERE email LIKE '%@seed.matcha'")
        already = existing["c"] if existing else 0

        password_hash = hash_password(SEED_PASSWORD)
        created = 0
        attempts = 0
        # usernames are derived from random name pairs, so a handful of
        # collisions are expected and simply skipped/retried.
        while created < count and attempts < count * 3:
            attempts += 1
            profile = build_profile(already + created + attempts, password_hash)
            if query_one("SELECT 1 FROM users WHERE username = ? OR email = ?", (profile["username"], profile["email"])):
                continue
            insert_profile(profile)
            created += 1

        total = query_all("SELECT COUNT(*) AS c FROM users")[0]["c"]
        print(f"Inserted {created} new profiles (total in DB: {total}).")
        print(f"All seeded accounts share the password: {SEED_PASSWORD}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=550, help="number of profiles to create")
    args = parser.parse_args()
    seed(args.count)
