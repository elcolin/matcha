from flask import Blueprint, render_template

main_bp = Blueprint("main", __name__)

@main_bp.route("/")
def home():
    profiles = [
        {
            "id": 1,
            "name": "Satin Bowerbird",
            "age": 7,
            "city": "Paris",
            "interests": "Art, coffee, and shiny things",
            "image": "",
        },
        {
            "id": 2,
            "name": "Scarlet Macaw",
            "age": 6,
            "city": "Lyon",
            "interests": "Travel and sunsets",
            "image": "",
        },
    ]
    return render_template("index.html", name="Matcha User", profiles=profiles)
