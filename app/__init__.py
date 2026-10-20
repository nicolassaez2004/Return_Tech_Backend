import os

from dotenv import load_dotenv
from flask import Flask, jsonify
from flask_cors import CORS
from pymongo import ASCENDING

from .extensions import jwt, mongo


def create_app():
    load_dotenv()
    app = Flask(__name__)
    app.config["MONGO_URI"] = os.getenv(
        "MONGO_URI", "mongodb://localhost:27017/return_tech"
    )
    app.config["JWT_SECRET_KEY"] = os.getenv(
        "JWT_SECRET_KEY", "return-tech-development-key"
    )
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = False
    app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

    CORS(
        app,
        resources={r"/api/*": {"origins": os.getenv("FRONTEND_URL", "http://localhost:5173")}},
        supports_credentials=True,
    )
    mongo.init_app(app)
    jwt.init_app(app)

    from .routes.auth import auth_bp
    from .routes.api import api_bp

    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(api_bp, url_prefix="/api")

    @app.get("/api/health")
    def health():
        mongo.db.command("ping")
        return jsonify({"status": "ok", "service": "return-tech-api"})

    with app.app_context():
        mongo.db.users.create_index("email", unique=True)
        mongo.db.participations.create_index(
            [("challenge_id", ASCENDING), ("talent_id", ASCENDING)], unique=True
        )
        mongo.db.challenges.create_index([("status", ASCENDING), ("created_at", -1)])
        mongo.db.notifications.create_index([("user_id", ASCENDING), ("created_at", -1)])

    return app

