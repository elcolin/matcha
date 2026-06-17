from flask import Blueprint, jsonify

users_bp = Blueprint("users", __name__)


@users_bp.route("/users")
def list_users_placeholder():
    return jsonify({"message": "Use /match and /profile APIs for user discovery"})
