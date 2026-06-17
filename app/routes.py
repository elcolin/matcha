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
            "image": "https://images.unsplash.com/photo-1518791841217-8f162f1e1131?auto=format&fit=crop&w=900&q=80",
        },
        {
            "id": 2,
            "name": "Scarlet Macaw",
            "age": 6,
            "city": "Lyon",
            "interests": "Travel and sunsets",
            "image": "https://images.unsplash.com/photo-1463453091185-61582044d556?auto=format&fit=crop&w=900&q=80",
        },
    ]
    return render_template("index.html", name="Matcha User", profiles=profiles)
