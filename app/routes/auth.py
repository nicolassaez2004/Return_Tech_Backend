from flask import Blueprint, jsonify, request
from flask_jwt_extended import create_access_token, get_jwt_identity, jwt_required
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import mongo
from ..utils import api_error, now, object_id, serialize

auth_bp = Blueprint("auth", __name__)


@auth_bp.post("/register")
def register():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    role = str(data.get("role", ""))
    name = str(data.get("name", "")).strip()
    organization = str(data.get("organization_name", "")).strip()
    talent_type = str(data.get("talent_type", "")).strip()

    if not email or "@" not in email:
        return api_error("Informe um e-mail válido.")
    if len(password) < 8:
        return api_error("A senha deve ter pelo menos 8 caracteres.")
    if role not in {"talent", "company"}:
        return api_error("Escolha um perfil válido.")
    if not name:
        return api_error("Informe seu nome.")
    if role == "company" and not organization:
        return api_error("Informe o nome da empresa.")
    if role == "talent" and talent_type not in {"student", "professional"}:
        return api_error("Informe se você é estudante ou profissional.")
    if mongo.db.users.find_one({"email": email}):
        return api_error("Este e-mail já está cadastrado.", 409)

    timestamp = now()
    skills = data.get("skills", [])
    if isinstance(skills, str):
        skills = [item.strip() for item in skills.split(",") if item.strip()]
    elif not isinstance(skills, list):
        skills = []

    user = {
        "email": email,
        "password_hash": generate_password_hash(password),
        "role": role,
        "name": name,
        "organization_name": organization if role == "company" else "",
        "talent_type": talent_type if role == "talent" else "",
        "headline": str(data.get("headline", "")).strip(),
        "city": str(data.get("city", "")).strip(),
        "skills": skills,
        "bio": str(data.get("bio", "")).strip(),
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    result = mongo.db.users.insert_one(user)
    user["_id"] = result.inserted_id
    token = create_access_token(identity=str(result.inserted_id))
    user.pop("password_hash", None)
    return jsonify({"access_token": token, "user": serialize(user)}), 201


@auth_bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    user = mongo.db.users.find_one({"email": email})
    if not user or not check_password_hash(user["password_hash"], password):
        return api_error("E-mail ou senha incorretos.", 401)
    token = create_access_token(identity=str(user["_id"]))
    user.pop("password_hash", None)
    return jsonify({"access_token": token, "user": serialize(user)})


@auth_bp.get("/me")
@jwt_required()
def me():
    user = mongo.db.users.find_one({"_id": object_id(get_jwt_identity())})
    if not user:
        return api_error("Usuário não encontrado.", 404)
    user.pop("password_hash", None)
    return jsonify({"user": serialize(user)})

