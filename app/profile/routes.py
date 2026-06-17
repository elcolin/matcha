from flask import Blueprint, render_template

profile_bp = Blueprint("profile", __name__)


@profile_bp.route("/profile/<int:id>")
def detail(id):
    profiles = [
        {
            "id": 1,
            "name": "Satin Bowerbird",
            "age": 7,
            "city": "Paris",
            "interests": "Coffee • Travel • Photography • Sunsets",
            "bio": "I believe in love at first chirp. I collect shiny blue objects and build cozy nests on Sundays.",
            "image": "https://images.unsplash.com/photo-1518791841217-8f162f1e1131?auto=format&fit=crop&w=900&q=80",
        },
        {
            "id": 2,
            "name": "Scarlet Macaw",
            "age": 6,
            "city": "Lyon",
            "interests": "Music • Hiking • Espresso",
            "bio": "Always up for a spontaneous trip and deep conversations over coffee.",
            "image": "https://images.unsplash.com/photo-1463453091185-61582044d556?auto=format&fit=crop&w=900&q=80",
        },
    ]

    profile = next((p for p in profiles if p["id"] == id), None)

    if profile is None:
        return "Profile not found", 404

    return render_template("profile.html", profile=profile)