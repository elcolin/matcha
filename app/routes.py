from flask import Blueprint, render_template

main_bp = Blueprint("main", __name__)

@main_bp.route("/")
def home():
    return render_template("index.html", name="Matcha User")

@main_bp.route("/profile")
def profile():
    return render_template("profile.html")