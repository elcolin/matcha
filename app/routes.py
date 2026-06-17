from flask import Blueprint, render_template

main_bp = Blueprint("main", __name__)

@main_bp.route("/")
def home():
    profiles = [
        {"id": 1, "name": "Sofia", "age": 25, "city": "Paris", "interests": "Art & food", "image": "/static/img/p1.jpg"},
        {"id": 2, "name": "Emma", "age": 27, "city": "Lyon", "interests": "Travel", "image": "/static/img/p2.jpg"},
    ]
    return render_template("index.html", name="Matcha User", profiles=profiles)

