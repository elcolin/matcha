from flask import Blueprint, g, render_template, request

from app.search.routes import filtered_profiles

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def home():
    if not g.get("current_user"):
        return render_template("index.html", profiles=[], show_profiles=False)

    profiles = filtered_profiles(g.current_user["id"], request.args, 12, with_criteria=False)
    return render_template("index.html", profiles=profiles, show_profiles=True, args=request.args)
