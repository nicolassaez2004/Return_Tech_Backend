from datetime import date
from hashlib import sha256
from uuid import uuid4

import gridfs
from gridfs.errors import NoFile
from bson import ObjectId
from flask import Blueprint, Response, jsonify, request
from flask_jwt_extended import jwt_required
from pymongo import DESCENDING
from pymongo.errors import PyMongoError
from werkzeug.utils import secure_filename

from ..extensions import mongo
from ..challenge_lifecycle import close_if_expired, deadline_end, deadline_passed
from ..mail_notifications import mail_event
from ..services.coding import validated_config
from ..utils import api_error, current_user, now, object_id, serialize

api_bp = Blueprint("api", __name__)
LEGACY_CHALLENGE_IDS = {
    "demo-sentinel-fintech", "demo-aurora-cloud", "demo-horizonte-saude",
    "demo-vertice-logistica", "demo-solaris-energia", "demo-nexo-varejo",
}


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


@api_bp.route("/profile", methods=["GET", "PATCH", "PUT"])
@jwt_required()
def profile():
    user = current_user()
    if not user:
        return api_error("Usuário não encontrado.", 404)
    if request.method == "GET":
        user.pop("password_hash", None)
        return jsonify({"profile": serialize(user)})

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return api_error("Envie os dados do perfil como um objeto.")
    fields = ["name", "headline", "city", "bio"]
    updates = {field: str(data.get(field, user.get(field, ""))).strip() for field in fields}
    skills = data.get("skills", user.get("skills", []))
    if isinstance(skills, str):
        skills = [item.strip() for item in skills.split(",") if item.strip()]
    if not isinstance(skills, list) or any(not isinstance(item, str) for item in skills):
        return api_error("Informe competências como uma lista de textos.")
    updates["skills"] = [item.strip() for item in skills if item.strip()]
    if user["role"] == "company":
        updates["organization_name"] = str(
            data.get("organization_name", user.get("organization_name", ""))
        ).strip()
        if not updates["organization_name"]:
            return api_error("Informe o nome da empresa.")
    elif user["role"] == "talent":
        talent_type = str(data.get("talent_type", user.get("talent_type", "")))
        if talent_type not in {"student", "professional"}:
            return api_error("Tipo de talento inválido.")
        updates["talent_type"] = talent_type
    updates["updated_at"] = now()
    mongo.db.users.update_one({"_id": user["_id"]}, {"$set": updates})
    updated = mongo.db.users.find_one({"_id": user["_id"]})
    updated.pop("password_hash", None)
    return jsonify({"profile": serialize(updated)})


def challenge_fields(data):
    """Validate editable fields without allowing changes to ownership or status."""
    if not isinstance(data, dict):
        return None, api_error("Envie os dados do desafio como um objeto.")
    fields = {}
    for field in ("title", "description", "deliverables", "deadline"):
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            return None, api_error("Preencha todos os campos obrigatórios.")
        fields[field] = value.strip()
    try:
        date.fromisoformat(fields["deadline"])
        deadline_end(fields["deadline"])
    except (ValueError, OverflowError):
        return None, api_error("Informe um prazo válido.")
    skills = data.get("skills", [])
    if isinstance(skills, str):
        skills = skills.split(",")
    if not isinstance(skills, list) or any(not isinstance(item, str) for item in skills):
        return None, api_error("Informe uma lista de competências válida.")
    fields["skills"] = [item.strip() for item in skills if item.strip()]
    for field, default in (("level", "Intermediário"), ("work_mode", "Remoto")):
        value = data.get(field, default)
        if not isinstance(value, str) or not value.strip():
            return None, api_error("Informe o nível e o modelo do desafio.")
        fields[field] = value.strip()
    return fields, None


def challenge_details(challenge, user):
    challenge["company_name"] = company_name(challenge["owner_id"])
    challenge["participant_count"] = mongo.db.participations.count_documents(
        {"challenge_id": challenge["_id"]}
    )
    if user["role"] == "talent":
        challenge["participation"] = mongo.db.participations.find_one(
            {"challenge_id": challenge["_id"], "talent_id": user["_id"]}
        )
        if challenge["participation"] and not challenge.get("coding_enabled"):
            challenge["latest_submission"] = mongo.db.submissions.find_one(
                {"participation_id": challenge["participation"]["_id"]},
                {"summary": 1, "report_url": 1, "file_name": 1, "version": 1, "created_at": 1},
                sort=[("version", -1), ("created_at", -1)],
            )
    challenge["coding_editable"] = (
        user["role"] == "company" and challenge["owner_id"] == user["_id"]
        and challenge["status"] == "draft"
        and mongo.db.coding_jobs.find_one({"challenge_id": challenge["_id"]}) is None
    )
    return challenge


@api_bp.route("/challenges/<challenge_id>", methods=["GET", "PATCH"])
@jwt_required()
def challenge_detail(challenge_id):
    user = current_user()
    if not user:
        return api_error("Usuário não encontrado.", 404)
    oid = object_id(challenge_id)
    query = {"_id": oid} if oid else {"legacy_id": challenge_id} if challenge_id in LEGACY_CHALLENGE_IDS else None
    challenge = mongo.db.challenges.find_one(query) if query else None
    if not challenge:
        return api_error("Desafio não encontrado.", 404)
    oid = challenge["_id"]
    can_manage = user["role"] == "admin" or (
        user["role"] == "company" and challenge["owner_id"] == user["_id"]
    )
    participation = mongo.db.participations.find_one(
        {"challenge_id": oid, "talent_id": user["_id"]}
    ) if user["role"] == "talent" else None
    if request.method == "GET":
        if not can_manage and challenge["status"] != "published":
            if not (participation and challenge["status"] == "closed"):
                return api_error("Desafio não encontrado.", 404)
    else:
        if not can_manage:
            return api_error("Você não pode editar este desafio.", 403)
        fields, error = challenge_fields(request.get_json(silent=True))
        if error:
            return error
        changed = any(challenge.get(field) != value for field, value in fields.items())
        if not changed:
            return jsonify({"challenge": serialize(challenge_details(challenge, user))})
        fields["updated_at"] = now()
        fields["revision"] = challenge.get("revision", 0) + 1
        fields["ends_at"] = deadline_end(fields["deadline"])
        if user["role"] == "company":
            fields.update({
                "status": "draft", "authorization_confirmed": False,
                "approved_by": None, "approved_at": None, "approved_revision": None,
                "submitted_at": None,
            })
        elif challenge["status"] == "published":
            fields.update({"approved_by": user["_id"], "approved_at": now(),
                           "approved_revision": fields["revision"]})
        result = mongo.db.challenges.update_one(
            {"_id": oid, "status": challenge["status"], "updated_at": challenge.get("updated_at"),
             "revision": challenge["revision"] if "revision" in challenge else {"$exists": False}},
            {"$set": fields},
        )
        if result.matched_count != 1:
            return api_error("O desafio foi alterado. Atualize a página antes de salvar.", 409)
        challenge.update(fields)
    return jsonify({"challenge": serialize(challenge_details(challenge, user))})


@api_bp.post("/legacy-participations/import")
@jwt_required()
def import_legacy_participations():
    user, error = require_role("talent")
    if error:
        return error
    data = request.get_json(silent=True)
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list) or len(items) > len(LEGACY_CHALLENGE_IDS):
        return api_error("Informe até seis inscrições para sincronizar.")
    validated = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            return api_error("Inscrição inválida.")
        legacy_id = item.get("legacy_id")
        summary = item.get("summary", "")
        report_url = item.get("report_url", "")
        if (not isinstance(legacy_id, str) or legacy_id not in LEGACY_CHALLENGE_IDS or legacy_id in seen
                or not isinstance(summary, str) or not isinstance(report_url, str)):
            return api_error("Inscrição inválida.")
        challenge = mongo.db.challenges.find_one({"legacy_id": legacy_id})
        if not challenge:
            return api_error("O desafio ainda não está disponível para sincronização.", 409)
        seen.add(legacy_id)
        validated.append((challenge, legacy_id, summary.strip(), report_url.strip()))

    imported_participations = 0
    imported_submissions = 0
    for challenge, legacy_id, summary, report_url in validated:
        timestamp = now()
        participation_query = {"challenge_id": challenge["_id"], "talent_id": user["_id"]}
        result = mongo.db.participations.update_one(participation_query, {"$setOnInsert": {
            **participation_query, "status": "submitted" if summary else "joined",
            "created_at": timestamp, "updated_at": timestamp,
        }}, upsert=True)
        imported_participations += result.upserted_id is not None
        participation = mongo.db.participations.find_one(participation_query)
        if not summary:
            continue
        digest = sha256(f"legacy-import\0{user['_id']}\0{legacy_id}".encode("utf-8")).hexdigest()[:24]
        submission_id = ObjectId(digest)
        version = mongo.db.submissions.count_documents({"participation_id": participation["_id"]}) + 1
        result = mongo.db.submissions.update_one({"_id": submission_id}, {"$setOnInsert": {
            "participation_id": participation["_id"], "version": version,
            "summary": summary, "report_url": report_url, "file_id": None, "file_name": "",
            "created_at": timestamp, "legacy_id": legacy_id,
        }}, upsert=True)
        if result.upserted_id is not None:
            imported_submissions += 1
            mongo.db.participations.update_one({"_id": participation["_id"], "status": {"$nin": ["shortlisted", "approved"]}},
                                              {"$set": {"status": "submitted", "updated_at": timestamp}})
    return jsonify({"ok": True, "imported_participations": imported_participations,
                    "imported_submissions": imported_submissions})


@api_bp.get("/admin/challenges")
@jwt_required()
def admin_challenges():
    user, error = require_role("admin")
    if error:
        return error
    rows = [challenge_details(challenge, user) for challenge in
            mongo.db.challenges.find().sort("created_at", DESCENDING)]
    return jsonify({"challenges": serialize(rows)})


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
    data = request.get_json(silent=True)
    fields, error = challenge_fields(data)
    if error:
        return error
    coding_config = None
    if "coding_config" in data:
        try:
            coding_config = validated_config(data["coding_config"])
        except ValueError as exc:
            return api_error(str(exc))
    document = {
        **fields,
        "owner_id": user["_id"],
        "status": "draft",
        "revision": 1,
        "review_feedback": "",
        "ends_at": deadline_end(fields["deadline"]),
        "is_recruitment": True,
        "authorization_confirmed": False,
        "created_at": now(),
        "updated_at": now(),
    }
    if coding_config is not None:
        document.update({
            "_id": ObjectId(), "coding_enabled": True,
            "coding_max_points": coding_config["max_points"], "coding_config_version": uuid4().hex,
        })
    try:
        if coding_config is not None:
            mongo.db.coding_config_versions.insert_one({
                "_id": document["coding_config_version"], "challenge_id": document["_id"],
                **coding_config, "created_at": document["created_at"],
            })
        result = mongo.db.challenges.insert_one(document)
    except PyMongoError:
        return api_error("Não foi possível confirmar o cadastro do desafio. Confira seus rascunhos antes de tentar novamente.", 503)
    document["_id"] = result.inserted_id
    document["company_name"] = user.get("organization_name") or user["name"]
    return jsonify({"challenge": serialize(document)}), 201, {"Location": f'/api/challenges/{document["_id"]}'}


@api_bp.patch("/challenges/<challenge_id>/status")
@jwt_required()
def challenge_status(challenge_id):
    user = current_user()
    if not user:
        return api_error("Usuário não encontrado.", 404)
    if user["role"] not in {"company", "admin"}:
        return api_error("Acesso não autorizado para este perfil.", 403)
    oid = object_id(challenge_id)
    query = {"_id": oid}
    if user["role"] != "admin":
        query["owner_id"] = user["_id"]
    challenge = mongo.db.challenges.find_one(query) if oid else None
    if not challenge:
        return api_error("Desafio não encontrado.", 404)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return api_error("Informe a ação desejada.")
    action = data.get("action")
    if not isinstance(action, str):
        return api_error("Informe uma ação válida.")
    current_status = challenge["status"]
    revision = challenge.get("revision", 0)
    is_admin = user["role"] == "admin"
    if action in {"approve", "request_changes"} or (action == "publish" and is_admin):
        if not is_admin:
            return api_error("Apenas administradores podem aprovar ou solicitar ajustes.", 403)
        if current_status != "pending_review":
            return api_error("Este desafio não está aguardando aprovação.", 409)
        if type(data.get("review_revision")) is not int or data["review_revision"] != revision:
            return api_error("O enunciado foi alterado. Atualize a página e revise a versão atual.", 409)
        if action == "request_changes":
            feedback = data.get("feedback", "")
            if not isinstance(feedback, str) or not feedback.strip() or len(feedback.strip()) > 2000:
                return api_error("Descreva os ajustes necessários em até 2000 caracteres.")
            update = {"status": "changes_requested", "authorization_confirmed": False,
                      "review_feedback": feedback.strip(), "reviewed_by": user["_id"],
                      "reviewed_at": now(), "approved_by": None, "approved_at": None,
                      "approved_revision": None}
        else:
            if deadline_passed(challenge):
                return api_error("O prazo do desafio já terminou. Atualize o prazo antes de aprovar a publicação.", 409)
            update = {"status": "published", "authorization_confirmed": True,
                      "approved_by": user["_id"], "approved_at": now(), "approved_revision": revision,
                      "reviewed_by": user["_id"], "reviewed_at": now(), "review_feedback": ""}
    elif action == "submit_review" or (action == "publish" and not is_admin):
        if is_admin:
            return api_error("O envio para aprovação deve ser feito pela empresa responsável.", 403)
        if current_status not in {"draft", "changes_requested", "closed"}:
            return api_error("Este desafio já está publicado ou aguardando aprovação.", 409)
        update = {"status": "pending_review", "authorization_confirmed": False,
                  "submitted_at": now(), "review_feedback": "", "reviewed_by": None,
                  "reviewed_at": None, "approved_by": None, "approved_at": None,
                  "approved_revision": None}
    elif action == "close":
        if current_status != "published":
            return api_error("Apenas desafios publicados podem ser encerrados.", 409)
        update = {"status": "closed", "closed_at": now(), "closed_reason": "manual"}
    elif action == "draft" and is_admin:
        update = {"status": "draft", "authorization_confirmed": False,
                  "approved_by": None, "approved_at": None, "approved_revision": None,
                  "submitted_at": None, "review_feedback": ""}
    else:
        return api_error("Ação inválida.")
    update["updated_at"] = now()
    mutation = {"$set": update}
    event_kind = {"pending_review": "review_requested", "published": "challenge_published", "closed": "challenge_closed"}.get(update["status"])
    if event_kind:
        mutation["$push"] = {"mail_events": mail_event(event_kind, challenge)}
    result = mongo.db.challenges.update_one(
        {"_id": oid, "status": current_status, "updated_at": challenge.get("updated_at"),
         "revision": challenge["revision"] if "revision" in challenge else {"$exists": False}},
        mutation,
    )
    if result.matched_count != 1:
        return api_error("O desafio foi alterado. Atualize a página e tente novamente.", 409)
    if is_admin and action in {"approve", "publish", "request_changes"}:
        add_notification(
            challenge["owner_id"],
            "Desafio aprovado" if update["status"] == "published" else "Ajustes solicitados no desafio",
            f'O desafio “{challenge["title"]}” foi aprovado e publicado.' if update["status"] == "published"
            else f'Foram solicitados ajustes em “{challenge["title"]}”: {update["review_feedback"]}',
            "challenge_review",
        )
    return jsonify({"ok": True, "status": update["status"]})


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
    if deadline_passed(challenge):
        close_if_expired(challenge)
        return api_error("O prazo de inscrição neste desafio já terminou.", 409)
    result = mongo.db.participations.update_one(
        {"challenge_id": oid, "talent_id": user["_id"]}, {"$setOnInsert": {
            "challenge_id": oid, "talent_id": user["_id"], "status": "joined",
            "created_at": now(), "updated_at": now(),
            "mail_events": [mail_event("challenge_joined", challenge, user["_id"])],
        }}, upsert=True,
    )
    if result.upserted_id is not None:
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
    if deadline_passed(challenge):
        close_if_expired(challenge)
        return api_error("O prazo de envio deste desafio já terminou.", 409)
    summary = str(request.form.get("summary", "")).strip()
    if not summary:
        return api_error("Informe o resumo da solução.")
    file = request.files.get("file")
    file_id = None
    file_name = ""
    previous_id = request.form.get("previous_submission_id")
    if previous_id:
        previous = mongo.db.submissions.find_one({
            "_id": object_id(previous_id), "participation_id": participation["_id"],
        })
        if not previous:
            return api_error("A entrega anterior não foi encontrada.", 404)
        file_id = previous.get("file_id")
        file_name = previous.get("file_name", "")
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
    if not participation:
        return api_error("Arquivo não encontrado.", 404)
    challenge = mongo.db.challenges.find_one({"_id": participation["challenge_id"]})
    if not challenge:
        return api_error("Arquivo não encontrado.", 404)
    if user["_id"] not in {participation["talent_id"], challenge["owner_id"]}:
        return api_error("Acesso negado.", 403)
    try:
        stored = gridfs.GridFS(mongo.db).get(submission["file_id"])
    except NoFile:
        return api_error("Arquivo não encontrado.", 404)
    return Response(
        stored.read(),
        mimetype=stored.content_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{stored.filename}"'},
    )


def talent_profile(talent_id):
    return mongo.db.users.find_one({"_id": talent_id}, {
        "name": 1, "email": 1, "headline": 1, "city": 1,
        "bio": 1, "skills": 1, "talent_type": 1,
    })


def save_shortlist(company_id, participation):
    timestamp = now()
    mongo.db.company_shortlist.update_one(
        {"_id": f'{company_id}_{participation["talent_id"]}'},
        {"$setOnInsert": {"company_id": company_id, "talent_id": participation["talent_id"], "created_at": timestamp},
         "$set": {"updated_at": timestamp},
         "$addToSet": {"participation_ids": participation["_id"]}},
        upsert=True,
    )


@api_bp.post("/participations/<participation_id>/shortlist")
@jwt_required()
def shortlist_participant(participation_id):
    user, error = require_role("company")
    if error:
        return error
    participation = mongo.db.participations.find_one({"_id": object_id(participation_id)})
    if not participation:
        return api_error("Participação não encontrada.", 404)
    challenge = mongo.db.challenges.find_one({"_id": participation["challenge_id"], "owner_id": user["_id"]})
    if not challenge:
        return api_error("Participação não pertence à empresa.", 403)
    has_report = mongo.db.submissions.find_one({"participation_id": participation["_id"]}, {"_id": 1})
    has_code = mongo.db.coding_jobs.find_one({
        "challenge_id": challenge["_id"], "talent_id": participation["talent_id"], "mode": "submit",
    }, {"_id": 1})
    if not has_report and not has_code:
        return api_error("Este participante ainda não enviou uma resolução.", 409)
    save_shortlist(user["_id"], participation)
    mongo.db.participations.update_one({"_id": participation["_id"]},
                                      {"$set": {"status": "shortlisted", "updated_at": now()}})
    return jsonify({"ok": True})


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
    if not participation:
        return api_error("Participação não encontrada.", 404)
    challenge = mongo.db.challenges.find_one(
        {"_id": participation["challenge_id"], "owner_id": user["_id"]}
    )
    if not challenge:
        return api_error("Entrega não pertence à empresa.", 403)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return api_error("Envie os dados da avaliação como um objeto.")
    decision = str(data.get("decision", ""))
    if decision not in {"shortlisted", "rejected"}:
        return api_error("Decisão inválida.")
    feedback = str(data.get("feedback", "")).strip()
    if not feedback:
        return api_error("Informe o feedback.")
    score = data.get("score")
    if (isinstance(score, bool) or not isinstance(score, (int, float))
            or not 0 <= score <= 100 or not float(score).is_integer()):
        return api_error("Informe uma nota inteira de 0 a 100.")
    shortlisted = decision == "shortlisted"
    evaluation = {
        "submission_id": submission["_id"],
        "evaluator_id": user["_id"],
        "decision": decision,
        "score": int(score),
        "feedback": feedback,
        "recognized": shortlisted,
        "shortlisted": shortlisted,
        "reward_note": str(data.get("reward_note", "")).strip(),
        "created_at": now(),
    }
    mongo.db.evaluations.insert_one(evaluation)
    if shortlisted:
        save_shortlist(user["_id"], participation)
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
        participations = list(mongo.db.participations.find({"talent_id": user["_id"]}))
        participating_ids = [item["challenge_id"] for item in participations]
        visible = {"$or": [
            {"status": "published"},
            {"_id": {"$in": participating_ids}, "status": "closed"},
        ]}
        for challenge in mongo.db.challenges.find(visible).sort("created_at", -1):
            challenges.append(challenge_details(challenge, user))
        submissions = []
        for participation in participations:
            challenge = mongo.db.challenges.find_one({"_id": participation["challenge_id"]})
            if challenge and challenge["status"] not in {"published", "closed"}:
                challenge = {"_id": challenge["_id"], "title": "Desafio em revisão", "skills": []}
            for submission in mongo.db.submissions.find(
                {"participation_id": participation["_id"]}
            ).sort("created_at", -1):
                submission["challenge"] = challenge
                submission["participation"] = participation
                submission["evaluation"] = mongo.db.evaluations.find_one(
                    {"submission_id": submission["_id"]}, sort=[("created_at", -1)]
                )
                submissions.append(submission)
        coding_submissions = []
        portfolio_challenges = {item["_id"]: item for item in challenges}
        participation_by_challenge = {item["challenge_id"]: item for item in participations}
        for job in mongo.db.coding_jobs.find({"talent_id": user["_id"], "mode": "submit"}).sort("created_at", -1):
            code_challenge = portfolio_challenges.get(job["challenge_id"])
            if code_challenge is None:
                stored = mongo.db.challenges.find_one({"_id": job["challenge_id"]}, {"_id": 1, "status": 1})
                code_challenge = {"_id": job["challenge_id"], "title": "Desafio em revisão" if stored else "Desafio indisponível", "skills": []}
                portfolio_challenges[job["challenge_id"]] = code_challenge
            item = {key: job[key] for key in ("_id", "challenge_id", "mode", "language", "status", "created_at", "finished_at", "passed", "total", "score", "max_points", "error") if key in job}
            item.update({
                "kind": "code", "source_code": job.get("source_code", ""),
                "challenge": {key: code_challenge[key] for key in ("_id", "title", "skills", "status", "coding_enabled") if key in code_challenge},
                "participation": participation_by_challenge.get(job["challenge_id"]),
            })
            coding_submissions.append(item)
        payload = {"challenges": challenges, "submissions": submissions, "coding_submissions": coding_submissions}
    elif user["role"] == "company":
        challenges = list(
            mongo.db.challenges.find({"owner_id": user["_id"]}).sort("created_at", -1)
        )
        submissions = []
        coding_submissions = []
        shortlisted_talents = {row["talent_id"] for row in mongo.db.company_shortlist.find({"company_id": user["_id"]})}
        for challenge in challenges:
            challenge["coding_editable"] = (challenge["status"] == "draft" and
                                            mongo.db.coding_jobs.find_one({"challenge_id": challenge["_id"]}) is None)
            parts = list(mongo.db.participations.find({"challenge_id": challenge["_id"]}))
            challenge["participant_count"] = len(parts)
            challenge["pending_count"] = sum(p["status"] == "submitted" for p in parts)
            challenge["approved_count"] = sum(
                p["status"] in {"approved", "shortlisted"} for p in parts
            )
            for participation in parts:
                talent = talent_profile(participation["talent_id"])
                for submission in mongo.db.submissions.find(
                    {"participation_id": participation["_id"]}
                ).sort("created_at", -1):
                    submission["challenge"] = challenge
                    submission["participation"] = participation
                    submission["talent"] = talent
                    submission["evaluation"] = mongo.db.evaluations.find_one(
                        {"submission_id": submission["_id"]}, sort=[("created_at", -1)]
                    )
                    if submission["evaluation"] and submission["evaluation"].get("decision") == "shortlisted":
                        shortlisted_talents.add(participation["talent_id"])
                    submissions.append(submission)
                for job in mongo.db.coding_jobs.find({
                    "challenge_id": challenge["_id"], "talent_id": participation["talent_id"], "mode": "submit",
                }).sort("created_at", -1):
                    item = {key: job[key] for key in (
                        "_id", "language", "source_code", "status", "score", "max_points", "passed", "total", "created_at", "error",
                    ) if key in job}
                    item.update({"kind": "code", "challenge": challenge, "participation": participation, "talent": talent})
                    coding_submissions.append(item)
        shortlist = {}
        for item in submissions + coding_submissions:
            talent = item.get("talent")
            item["shortlisted"] = bool(talent and talent["_id"] in shortlisted_talents)
            if item["shortlisted"]:
                entry = shortlist.setdefault(talent["_id"], {"talent": talent, "challenges": {}})
                challenge = item["challenge"]
                entry["challenges"][challenge["_id"]] = {"_id": challenge["_id"], "title": challenge["title"]}
        for talent_id in shortlisted_talents - shortlist.keys():
            talent = talent_profile(talent_id)
            if talent:
                shortlist[talent_id] = {"talent": talent, "challenges": {}}
        shortlist_profiles = [{"talent": entry["talent"], "challenges": list(entry["challenges"].values())}
                              for entry in shortlist.values()]
        shortlist_profiles.sort(key=lambda entry: entry["talent"].get("name", "").casefold())
        payload = {"challenges": challenges, "submissions": submissions,
                   "coding_submissions": coding_submissions, "shortlist": shortlist_profiles}
    else:
        return api_error("Use o painel de administração.", 403)
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

