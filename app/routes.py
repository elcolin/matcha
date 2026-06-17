from flask import Blueprint, render_template
from app.profile.data import PROFILES

main_bp = Blueprint("main", __name__)

@main_bp.route("/")
def home():
    return render_template("index.html", name="Matcha User", profiles=PROFILES)
