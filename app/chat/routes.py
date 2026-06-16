from flask import Blueprint

chat_bp = Blueprint("chat", __name__)

@chat_bp.route("/chat")
def login():
    return "Chat page"