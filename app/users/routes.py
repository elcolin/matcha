from flask import Blueprint

users_bp = Blueprint("users", __name__)

@users_bp.route("/users")
def login():
    return "users page"