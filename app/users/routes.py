from flask import Blueprint

users_bp = Blueprint("users", __name__)

@users_bp.route("/user")
def login():
    return "user page"