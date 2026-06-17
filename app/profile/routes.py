from flask import Blueprint, render_template

profile_bp = Blueprint("profile", __name__)


@profile_bp.route("/profile/<int:id>")
def detail(id):
    profiles = [
        {
            "id": 1,
            "name": "Sofia",
            "age": 25,
            "city": "Paris",
            "interests": "Art & food",
            "image": "/static/img/profile3.jpg"
        },
        {
            "id": 2,
            "name": "Emma",
            "age": 27,
            "city": "Lyon",
            "interests": "Travel & coffee",
            "image": "/static/img/profile2.jpg"
        }
    ]

    profile = next((p for p in profiles if p["id"] == id), None)

    if profile is None:
        return "Profile not found", 404

    return render_template("profile.html", profile=profile)