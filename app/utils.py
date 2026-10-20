from datetime import datetime, timezone

from bson import ObjectId
from flask import jsonify
from flask_jwt_extended import get_jwt_identity

from .extensions import mongo


def now():
    return datetime.now(timezone.utc)


def object_id(value):
    try:
        return ObjectId(str(value))
    except Exception:
        return None


def serialize(value):
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: serialize(item) for key, item in value.items()}
    return value


def current_user():
    user_id = object_id(get_jwt_identity())
    if not user_id:
        return None
    return mongo.db.users.find_one({"_id": user_id})


def api_error(message, status=400):
    return jsonify({"error": message}), status

