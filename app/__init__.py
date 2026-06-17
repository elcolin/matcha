import secrets
from datetime import datetime, timedelta, timezone

from flask import Flask, g, session
from dotenv import load_dotenv

from app.routes import main_bp
from app.auth.routes import auth_bp
from app.users.routes import users_bp
from app.match.routes import match_bp
from app.chat.routes import chat_bp
from app.profile.routes import profile_bp
from app.db import close_db, init_db, query_one, execute

load_dotenv()


def create_app():
    app = Flask(__name__)
    app.config.from_object("app.config.Config")

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(match_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(profile_bp)

    app.teardown_appcontext(close_db)

    with app.app_context():
        init_db()

    @app.errorhandler(400)
    def bad_request(_):
        return {"error": "Bad request"}, 400

    from app.utils import APIError

    @app.errorhandler(APIError)
    def api_error_handler(err):
        return {"error": err.message}, err.status

    @app.before_request
    def load_current_user():
        g.current_user = None
        user_id = session.get("user_id")
        session_token = session.get("session_token")

        if not user_id or not session_token:
            return

        active = query_one(
            "SELECT id FROM user_sessions WHERE user_id = ? AND session_token = ?",
            (user_id, session_token),
        )
        if not active:
            session.clear()
            return

        user = query_one(
            """
            SELECT u.id, u.username, u.email, u.first_name, u.last_name, u.email_verified,
                   p.popularity_score
            FROM users u
            LEFT JOIN profiles p ON p.user_id = u.id
            WHERE u.id = ?
            """,
            (user_id,),
        )

        if user:
            g.current_user = dict(user)
            now = datetime.now(timezone.utc)
            online_until = (now + timedelta(seconds=30)).isoformat()
            execute(
                "UPDATE users SET last_seen_at = ?, online_until = ? WHERE id = ?",
                (now.isoformat(), online_until, user_id),
            )
            execute(
                "UPDATE user_sessions SET last_seen_at = CURRENT_TIMESTAMP WHERE user_id = ? AND session_token = ?",
                (user_id, session_token),
            )

    @app.context_processor
    def inject_auth():
        unread_count = 0
        if g.get("current_user"):
            row = query_one(
                "SELECT COUNT(*) AS c FROM notifications WHERE user_id = ? AND is_read = 0",
                (g.current_user["id"],),
            )
            unread_count = row["c"] if row else 0
        return {
            "current_user": g.get("current_user"),
            "unread_notifications": unread_count,
            "logout_token": session.get("logout_token") or session.setdefault("logout_token", secrets.token_urlsafe(16)),
        }

    return app
