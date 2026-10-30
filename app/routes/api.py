import gridfs
from bson import ObjectId
from flask import Blueprint, Response, jsonify, request
from flask_jwt_extended import jwt_required
from pymongo import DESCENDING
from werkzeug.utils import secure_filename

from ..extensions import mongo
from ..utils import api_error, current_user, now, object_id, serialize

api_bp = Blueprint("api", __name__)


def require_role(role):
    user = current_user()
    if not user:
        return None, api_error("Usuário não encontrado.", 404)
    if user.get("role") != role:
        return None, api_error("Acesso não autorizado para este perfil.", 403)
    return user, None


def add_notification(user_id, title, body, kind):
    mongo.db.notifications.insert_one(
        {
            "user_id": user_id,
            "title": title,
            "body": body,
            "kind": kind,
            "read": False,
            "created_at": now(),
        }
    )


def company_name(owner_id):
    company = mongo.db.users.find_one({"_id": owner_id})
    if not company:
        return "Empresa"
    return company.get("organization_name") or company.get("name") or "Empresa"


@api_bp.route("/profile", methods=["GET", "PUT"])
@jwt_required()
def profile():
    user = current_user()
    if not user:
        return api_error("Usuário não encontrado.", 404)
    if request.method == "GET":
        user.pop("password_hash", None)
        return jsonify({"profile": serialize(user)})

    data = request.get_json(silent=True) or {}
    fields = ["name", "headline", "city", "bio"]
    updates = {field: str(data.get(field, user.get(field, ""))).strip() for field in fields}
    skills = data.get("skills", user.get("skills", []))
    if isinstance(skills, str):
        skills = [item.strip() for item in skills.split(",") if item.strip()]
    updates["skills"] = skills if isinstance(skills, list) else []
    if user["role"] == "company":
        updates["organization_name"] = str(
            data.get("organization_name", user.get("organization_name", ""))
        ).strip()
        if not updates["organization_name"]:
            return api_error("Informe o nome da empresa.")
    else:
        talent_type = str(data.get("talent_type", user.get("talent_type", "")))
        if talent_type not in {"student", "professional"}:
            return api_error("Tipo de talento inválido.")
        updates["talent_type"] = talent_type
    updates["updated_at"] = now()
    mongo.db.users.update_one({"_id": user["_id"]}, {"$set": updates})
    updated = mongo.db.users.find_one({"_id": user["_id"]})
    updated.pop("password_hash", None)
    return jsonify({"profile": serialize(updated)})


@api_bp.route("/challenges", methods=["GET", "POST"])
@jwt_required()
def challenges():
    user = current_user()
    if not user:
        return api_error("Usuário não encontrado.", 404)
    if request.method == "GET":
        query = {"status": "published"}
        if user["role"] == "company" and request.args.get("mine") == "1":
            query = {"owner_id": user["_id"]}
        rows = []
        for challenge in mongo.db.challenges.find(query).sort("created_at", DESCENDING):
            challenge["company_name"] = company_name(challenge["owner_id"])
            participation = mongo.db.participations.find_one(
                {"challenge_id": challenge["_id"], "talent_id": user["_id"]}
            ) if user["role"] == "talent" else None
            challenge["participation"] = participation
            rows.append(challenge)
        return jsonify({"challenges": serialize(rows)})

    if user["role"] != "company":
        return api_error("Apenas empresas podem publicar.", 403)
    data = request.get_json(silent=True) or {}
    required = ["title", "description", "deliverables", "deadline"]
    missing = [field for field in required if not str(data.get(field, "")).strip()]
    if missing:
        return api_error("Preencha todos os campos obrigatórios.")
    skills = data.get("skills", [])
    if isinstance(skills, str):
        skills = [item.strip() for item in skills.split(",") if item.strip()]
    document = {
        "owner_id": user["_id"],
        "title": str(data["title"]).strip(),
        "description": str(data["description"]).strip(),
        "deliverables": str(data["deliverables"]).strip(),
        "skills": skills if isinstance(skills, list) else [],
        "level": str(data.get("level", "Intermediário")).strip(),
        "work_mode": str(data.get("work_mode", "Remoto")).strip(),
        "deadline": str(data["deadline"]),
        "status": "draft",
        "is_recruitment": True,
        "authorization_confirmed": False,
        "created_at": now(),
        "updated_at": now(),
    }
    result = mongo.db.challenges.insert_one(document)
    document["_id"] = result.inserted_id
    document["company_name"] = user.get("organization_name") or user["name"]
    return jsonify({"challenge": serialize(document)}), 201


@api_bp.patch("/challenges/<challenge_id>/status")
@jwt_required()
def challenge_status(challenge_id):
    user, error = require_role("company")
    if error:
        return error
    oid = object_id(challenge_id)
    challenge = mongo.db.challenges.find_one({"_id": oid, "owner_id": user["_id"]})
    if not challenge:
        return api_error("Desafio não encontrado.", 404)
    action = (request.get_json(silent=True) or {}).get("action")
    if action == "publish":
        update = {"status": "published", "authorization_confirmed": True}
    elif action == "close":
        update = {"status": "closed"}
    else:
        return api_error("Ação inválida.")
    update["updated_at"] = now()
    mongo.db.challenges.update_one({"_id": oid}, {"$set": update})
    return jsonify({"ok": True})


@api_bp.post("/challenges/<challenge_id>/join")
@jwt_required()
def join_challenge(challenge_id):
    user, error = require_role("talent")
    if error:
        return error
    oid = object_id(challenge_id)
    challenge = mongo.db.challenges.find_one({"_id": oid, "status": "published"})
    if not challenge:
        return api_error("Desafio indisponível.", 404)
    existing = mongo.db.participations.find_one(
        {"challenge_id": oid, "talent_id": user["_id"]}
    )
    if not existing:
        mongo.db.participations.insert_one(
            {
                "challenge_id": oid,
                "talent_id": user["_id"],
                "status": "joined",
                "created_at": now(),
                "updated_at": now(),
            }
        )
        add_notification(
            challenge["owner_id"],
            "Novo talento no desafio",
            f'{user["name"]} entrou em “{challenge["title"]}”.',
            "participation",
        )
    return jsonify({"ok": True})


@api_bp.post("/challenges/<challenge_id>/submissions")
@jwt_required()
def submit_work(challenge_id):
    user, error = require_role("talent")
    if error:
        return error
    oid = object_id(challenge_id)
    participation = mongo.db.participations.find_one(
        {"challenge_id": oid, "talent_id": user["_id"]}
    )
    if not participation:
        return api_error("Entre no desafio antes de enviar.", 409)
    challenge = mongo.db.challenges.find_one({"_id": oid, "status": "published"})
    if not challenge:
        return api_error("Este desafio não está mais recebendo entregas.", 409)
    summary = str(request.form.get("summary", "")).strip()
    if not summary:
        return api_error("Informe o resumo da solução.")
    file = request.files.get("file")
    file_id = None
    file_name = ""
    if file and file.filename:
        allowed = {"application/pdf", "text/plain", "application/zip", "application/x-zip-compressed"}
        if file.mimetype not in allowed:
            return api_error("Envie PDF, TXT ou ZIP.")
        fs = gridfs.GridFS(mongo.db)
        file_name = secure_filename(file.filename) or "entrega"
        file_id = fs.put(
            file.stream,
            filename=file_name,
            content_type=file.mimetype,
            owner_id=str(user["_id"]),
        )
    version = mongo.db.submissions.count_documents(
        {"participation_id": participation["_id"]}
    ) + 1
    submission = {
        "participation_id": participation["_id"],
        "version": version,
        "summary": summary,
        "report_url": str(request.form.get("report_url", "")).strip(),
        "file_id": file_id,
        "file_name": file_name,
        "created_at": now(),
    }
    result = mongo.db.submissions.insert_one(submission)
    mongo.db.participations.update_one(
        {"_id": participation["_id"]},
        {"$set": {"status": "submitted", "updated_at": now()}},
    )
    add_notification(
        challenge["owner_id"],
        "Nova entrega recebida",
        f'{user["name"]} enviou a versão {version} de “{challenge["title"]}”.',
        "submission",
    )
    submission["_id"] = result.inserted_id
    return jsonify({"submission": serialize(submission)}), 201


@api_bp.get("/submissions/<submission_id>/file")
@jwt_required()
def submission_file(submission_id):
    user = current_user()
    submission = mongo.db.submissions.find_one({"_id": object_id(submission_id)})
    if not user or not submission or not submission.get("file_id"):
        return api_error("Arquivo não encontrado.", 404)
    participation = mongo.db.participations.find_one({"_id": submission["participation_id"]})
    challenge = mongo.db.challenges.find_one({"_id": participation["challenge_id"]})
    if user["_id"] not in {participation["talent_id"], challenge["owner_id"]}:
        return api_error("Acesso negado.", 403)
    stored = gridfs.GridFS(mongo.db).get(submission["file_id"])
    return Response(
        stored.read(),
        mimetype=stored.content_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{stored.filename}"'},
    )


@api_bp.post("/submissions/<submission_id>/evaluate")
@jwt_required()
def evaluate_submission(submission_id):
    user, error = require_role("company")
    if error:
        return error
    submission = mongo.db.submissions.find_one({"_id": object_id(submission_id)})
    if not submission:
        return api_error("Entrega não encontrada.", 404)
    participation = mongo.db.participations.find_one({"_id": submission["participation_id"]})
    challenge = mongo.db.challenges.find_one(
        {"_id": participation["challenge_id"], "owner_id": user["_id"]}
    )
    if not challenge:
        return api_error("Entrega não pertence à empresa.", 403)
    data = request.get_json(silent=True) or {}
    decision = str(data.get("decision", ""))
    if decision not in {"shortlisted", "rejected"}:
        return api_error("Decisão inválida.")
    feedback = str(data.get("feedback", "")).strip()
    if not feedback:
        return api_error("Informe o feedback.")
    shortlisted = decision == "shortlisted"
    evaluation = {
        "submission_id": submission["_id"],
        "evaluator_id": user["_id"],
        "decision": decision,
        "score": max(0, min(100, int(data.get("score") or 0))),
        "feedback": feedback,
        "recognized": shortlisted,
        "shortlisted": shortlisted,
        "reward_note": str(data.get("reward_note", "")).strip(),
        "created_at": now(),
    }
    mongo.db.evaluations.insert_one(evaluation)
    status = decision
    mongo.db.participations.update_one(
        {"_id": participation["_id"]},
        {"$set": {"status": status, "updated_at": now()}},
    )
    add_notification(
        participation["talent_id"],
        "Entrega avaliada",
        f'A empresa avaliou sua entrega em “{challenge["title"]}”.',
        "evaluation",
    )
    return jsonify({"evaluation": serialize(evaluation)}), 201


@api_bp.get("/dashboard")
@jwt_required()
def dashboard():
    user = current_user()
    if not user:
        return api_error("Usuário não encontrado.", 404)
    if user["role"] == "talent":
        challenges = []
        joined_ids = mongo.db.participations.distinct("challenge_id", {"talent_id": user["_id"]})
        visible = {"$or": [{"status": "published"}, {"_id": {"$in": joined_ids}}]}
        for challenge in mongo.db.challenges.find(visible).sort("created_at", -1):
            challenge["company_name"] = company_name(challenge["owner_id"])
            challenge["participation"] = mongo.db.participations.find_one(
                {"challenge_id": challenge["_id"], "talent_id": user["_id"]}
            )
            challenges.append(challenge)
        participations = list(mongo.db.participations.find({"talent_id": user["_id"]}))
        submissions = []
        for participation in participations:
            challenge = mongo.db.challenges.find_one({"_id": participation["challenge_id"]})
            for submission in mongo.db.submissions.find(
                {"participation_id": participation["_id"]}
            ).sort("created_at", -1):
                submission["challenge"] = challenge
                submission["participation"] = participation
                submission["evaluation"] = mongo.db.evaluations.find_one(
                    {"submission_id": submission["_id"]}, sort=[("created_at", -1)]
                )
                submissions.append(submission)
        payload = {"challenges": challenges, "submissions": submissions}
    else:
        challenges = list(
            mongo.db.challenges.find({"owner_id": user["_id"]}).sort("created_at", -1)
        )
        submissions = []
        for challenge in challenges:
            parts = list(mongo.db.participations.find({"challenge_id": challenge["_id"]}))
            challenge["participant_count"] = len(parts)
            challenge["pending_count"] = sum(p["status"] == "submitted" for p in parts)
            challenge["approved_count"] = sum(
                p["status"] in {"approved", "shortlisted"} for p in parts
            )
            for participation in parts:
                talent = mongo.db.users.find_one({"_id": participation["talent_id"]})
                if talent:
                    talent.pop("password_hash", None)
                for submission in mongo.db.submissions.find(
                    {"participation_id": participation["_id"]}
                ).sort("created_at", -1):
                    submission["challenge"] = challenge
                    submission["participation"] = participation
                    submission["talent"] = talent
                    submission["evaluation"] = mongo.db.evaluations.find_one(
                        {"submission_id": submission["_id"]}, sort=[("created_at", -1)]
                    )
                    submissions.append(submission)
        payload = {"challenges": challenges, "submissions": submissions}
    notifications = list(
        mongo.db.notifications.find({"user_id": user["_id"]})
        .sort("created_at", -1)
        .limit(20)
    )
    user.pop("password_hash", None)
    return jsonify(
        serialize({"profile": user, "notifications": notifications, **payload})
    )


@api_bp.post("/notifications/read")
@jwt_required()
def read_notifications():
    user = current_user()
    mongo.db.notifications.update_many(
        {"user_id": user["_id"], "read": False}, {"$set": {"read": True}}
    )
    return jsonify({"ok": True})

