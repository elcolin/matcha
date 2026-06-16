from flask import Blueprint

match_bp = Blueprint("match", __name__)

@match_bp.route("/match")
def login():
    return "Match page"