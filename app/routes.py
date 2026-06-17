from flask import Blueprint, render_template

from app.db import query_all

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def home():
    rows = query_all(
        """
        SELECT u.id, u.username AS name, COALESCE(p.age, 0) AS age,
               COALESCE(p.city, 'Unknown') AS city,
               COALESCE(p.bio, '') AS bio,
               COALESCE(ph.url, '') AS image
        FROM users u
        LEFT JOIN profiles p ON p.user_id = u.id
        LEFT JOIN photos ph ON ph.user_id = u.id AND ph.is_profile_photo = 1
        ORDER BY u.id DESC
        LIMIT 12
        """
    )

    profiles = []
    for r in rows:
        profiles.append({
            "id": r["id"],
            "name": r["name"],
            "age": r["age"],
            "city": r["city"],
            "interests": [],
            "bio": r["bio"],
            "image": r["image"] or "https://placehold.co/600x400?text=Matcha",
        })

    return render_template("index.html", name="Matcha User", profiles=profiles)
