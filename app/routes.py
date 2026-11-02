from flask import Blueprint, g, render_template

from app.match.routes import candidate_profiles

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def home():
    if not g.get("current_user"):
        return render_template("index.html", profiles=[], show_profiles=False)

    profiles = candidate_profiles(g.current_user["id"])[:12]
    return render_template("index.html", profiles=profiles, show_profiles=True)