from flask import Flask
from dotenv import load_dotenv
from app.auth.routes import auth_bp
from app.users.routes import users_bp
from app.match.routes import match_bp
from app.chat.routes import chat_bp

load_dotenv()

def create_app():
    app = Flask(__name__)

    app.config.from_object("app.config.Config")

    app.register_blueprint(auth_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(match_bp)
    app.register_blueprint(chat_bp)

    return app