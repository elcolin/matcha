from flask import Blueprint, g, render_template

from app.db import query_all
from app.match.routes import candidate_profiles

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def home():
    if g.get("current_user"):
        rows = candidate_profiles(g.current_user["id"])[:12]
        profiles = []
        for item in rows:
            photos = item.get("photos") or []
            image = ""
            for photo in photos:
                if photo.get("is_profile_photo"):
                    image = photo.get("url") or ""
                    break
            if not image and photos:
                image = photos[0].get("url") or ""

            profiles.append({
                "id": item["id"],
                "name": item.get("first_name") or item.get("username") or "Matcha User",
                "age": item.get("age", 0),
                "city": item.get("city") or "Unknown",
                "neighborhood": item.get("neighborhood") or "Unknown area",
                "interests": item.get("tags", [])[:5],
                "bio": item.get("bio") or "",
                "image": image or "https://placehold.co/600x400?text=Matcha",
            })
        return render_template("index.html", name="Matcha User", profiles=profiles, show_profiles=True)

    return render_template("index.html", name="Matcha User", profiles=[], show_profiles=False)
