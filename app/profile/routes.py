from flask import Blueprint, render_template
from app.profile.data import get_profile_by_id

profile_bp = Blueprint("profile", __name__)


@profile_bp.route("/profile/<int:id>")
def detail(id):
    profile = get_profile_by_id(id)

    if profile is None:
        return "Profile not found", 404

    return render_template("profile.html", profile=profile)