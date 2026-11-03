"""Coding endpoints are separate from report submissions and human evaluation."""
from datetime import timedelta
from uuid import uuid4

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import jwt_required
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError

from ..extensions import mongo
from ..services.coding import (
    deadline_passed, load_config, public_config, public_job, refresh_job, validated_config,
)
from ..services.judge0 import Judge0Error, LANGUAGES
from ..utils import api_error, current_user, now, object_id, serialize

coding_bp = Blueprint("coding", __name__)


@coding_bp.errorhandler(Judge0Error)
def provider_error(error):
    return api_error(str(error), error.status)


def access(challenge_id, owner=False, allow_unpublished=False):
    user = current_user()
    if not user:
        return None, None, api_error("Usuário não encontrado.", 404)
    challenge = mongo.db.challenges.find_one({"_id": object_id(challenge_id)})
    if not challenge:
        return user, None, api_error("Desafio não encontrado.", 404)
    is_owner = user["role"] == "company" and challenge["owner_id"] == user["_id"]
    is_admin = user["role"] == "admin"
    if owner and not (is_owner or is_admin):
        return user, None, api_error("Acesso negado.", 403)
    if not (is_owner or is_admin) and (user["role"] != "talent" or not mongo.db.participations.find_one({
        "challenge_id": challenge["_id"], "talent_id": user["_id"],
    })):
        return user, None, api_error("Inscreva-se no desafio para acessar o editor.", 403)
    if not (is_owner or is_admin or allow_unpublished) and challenge["status"] not in {"published", "closed"}:
        return user, None, api_error("Desafio não encontrado.", 404)
    return user, challenge, None


@coding_bp.get("/challenges/<challenge_id>/coding")
@jwt_required()
def coding_detail(challenge_id):
    user, challenge, error = access(challenge_id)
    if error:
        return error
    config = load_config(challenge)
    if not config or not challenge.get("coding_enabled"):
        return api_error("Este desafio não tem avaliação por código.", 404)
    job = mongo.db.coding_jobs.find_one({"challenge_id": challenge["_id"], "talent_id": user["_id"], "mode": "submit"}, sort=[("created_at", -1)])
    warning = ""
    if job:
        try:
            job = refresh_job(job)
        except Judge0Error as exc:
            warning = str(exc)
    score = mongo.db.coding_scores.find_one({"challenge_id": challenge["_id"], "talent_id": user["_id"]})
    return jsonify(serialize({
        "config": public_config(config), "warning": warning,
        "language_options": [{"key": key, "name": LANGUAGES[key][0], "editor": LANGUAGES[key][1]} for key in config["languages"]],
        "runner_configured": current_app.extensions["judge0_client"].configured,
        "can_submit": user["role"] == "talent" and challenge["status"] == "published" and not deadline_passed(challenge),
        "best_score": score.get("score", 0) if score else 0,
        "latest_job": public_job(job) if job else None,
    }))


@coding_bp.route("/challenges/<challenge_id>/coding/config", methods=["GET", "PUT"])
@jwt_required()
def coding_config(challenge_id):
    user, challenge, error = access(challenge_id, owner=True)
    if error:
        return error
    if request.method == "GET":
        config = load_config(challenge)
        is_owner = user["role"] == "company" and challenge["owner_id"] == user["_id"]
        has_attempts = mongo.db.coding_jobs.find_one({"challenge_id": challenge["_id"]}) is not None
        editable = is_owner and challenge["status"] == "draft" and not has_attempts
        reason = "" if editable else (
            "Apenas a empresa responsável pode configurar a avaliação." if not is_owner else
            "A configuração só pode mudar em um rascunho sem tentativas."
        )
        return jsonify(serialize({
            "config": {k: v for k, v in config.items() if k not in {"_id", "challenge_id", "created_at", "updated_at"}} if config else None,
            "editable": editable, "lock_reason": reason,
        }))
    if user["role"] != "company" or challenge["owner_id"] != user["_id"]:
        return api_error("Apenas a empresa responsável pode configurar a avaliação.", 403)
    if challenge["status"] != "draft" or mongo.db.coding_jobs.find_one({"challenge_id": challenge["_id"]}):
        return api_error("A configuração só pode mudar em um rascunho sem tentativas.", 409)
    try:
        config = validated_config(request.get_json(silent=True))
    except ValueError as exc:
        return api_error(str(exc))
    # Write a private immutable snapshot first. Only an atomic change to the
    # draft's pointer/revision makes it active; concurrent review keeps using the
    # previous snapshot even if this request fails or loses its acknowledgement.
    version = uuid4().hex
    try:
        mongo.db.coding_config_versions.insert_one({
            "_id": version, "challenge_id": challenge["_id"], **config, "created_at": now(),
        })
        result = mongo.db.challenges.update_one({
            "_id": challenge["_id"], "status": "draft", "updated_at": challenge.get("updated_at"),
            "revision": challenge["revision"] if "revision" in challenge else {"$exists": False},
        }, {
            "$set": {"coding_enabled": True, "coding_max_points": config["max_points"], "coding_config_version": version,
                     "updated_at": now(), "revision": challenge.get("revision", 0) + 1,
                     "authorization_confirmed": False, "approved_by": None,
                     "approved_at": None, "approved_revision": None,
                     "submitted_at": None, "review_feedback": ""},
        })
    except PyMongoError as exc:
        current_app.logger.error("Falha ao salvar avaliação de código: %s", type(exc).__name__)
        return api_error("Não foi possível confirmar a configuração da avaliação. Recarregue a página e tente novamente.", 503)
    if not result.matched_count:
        return api_error("O desafio mudou de estado. Recarregue a página.", 409)
    return jsonify({"ok": True})


@coding_bp.post("/challenges/<challenge_id>/code-jobs")
@jwt_required()
def create_code_job(challenge_id):
    user, challenge, error = access(challenge_id, allow_unpublished=True)
    if error:
        return error
    if user["role"] != "talent":
        return api_error("Apenas candidatos podem enviar código.", 403)
    if challenge["status"] != "published" or deadline_passed(challenge):
        return api_error("O período de envio deste desafio terminou.", 409)
    config = load_config(challenge)
    if not challenge.get("coding_enabled") or not config:
        return api_error("Este desafio não tem avaliação por código.", 404)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return api_error("Envie o código em JSON.")
    mode, language, source = data.get("mode", "submit"), data.get("language"), data.get("source_code")
    if mode != "submit":
        return api_error("Envie a solução para correção.")
    if "stdin" in data:
        return api_error("As entradas da avaliação são definidas pela empresa.")
    if not isinstance(language, str) or language not in config["languages"]:
        return api_error("Linguagem não permitida neste desafio.")
    if not isinstance(source, str) or not source.strip() or len(source.encode("utf-8")) > 64000:
        return api_error("Envie um código não vazio de até 64 KB.")
    client = current_app.extensions["judge0_client"]
    if not client.configured:
        raise Judge0Error("Execução indisponível. A equipe precisa configurar o Judge0 no backend.", 503)
    active = mongo.db.coding_jobs.find_one({"challenge_id": challenge["_id"], "talent_id": user["_id"], "active": True})
    if active:
        active = refresh_job(active)
        if active.get("active"):
            return jsonify(serialize({"error": "Já existe uma execução em andamento.", "job": public_job(active)})), 409
    participation = mongo.db.participations.find_one_and_update({
        "challenge_id": challenge["_id"], "talent_id": user["_id"],
        "$or": [{"coding_next_submit_at": {"$exists": False}}, {"coding_next_submit_at": {"$lte": now()}}],
    }, {"$set": {"coding_next_submit_at": now() + timedelta(seconds=3)}}, return_document=ReturnDocument.AFTER)
    if not participation:
        return api_error("Aguarde alguns segundos antes de enviar novamente.", 429)
    tests = config["tests"]
    job = {
        "challenge_id": challenge["_id"], "talent_id": user["_id"], "participation_id": participation["_id"],
        "mode": mode, "language": language, "source_code": source, "max_points": config["max_points"],
        "total": len(tests), "status": "creating", "active": True, "created_at": now(),
    }
    try:
        job["_id"] = mongo.db.coding_jobs.insert_one(job).inserted_id
    except DuplicateKeyError:
        return api_error("Já existe uma execução em andamento.", 409)
    mongo.db.participations.update_one({
        "_id": participation["_id"], "status": {"$in": ["joined", "submitted"]},
    }, {"$set": {"status": "submitted", "updated_at": now()}})
    try:
        tokens = client.create_batch(language, source, tests, config)
    except Judge0Error as exc:
        mongo.db.coding_jobs.update_one({"_id": job["_id"]}, {"$set": {
            "status": "service_error", "active": False, "error": str(exc), "finished_at": now(),
        }})
        raise
    mongo.db.coding_jobs.update_one({"_id": job["_id"]}, {"$set": {"provider_tokens": tokens, "status": "processing"}})
    job["status"] = "processing"
    return jsonify(serialize({"job": public_job(job)})), 202, {"Location": f'/api/code-jobs/{job["_id"]}'}


@coding_bp.get("/code-jobs/<job_id>")
@jwt_required()
def code_job(job_id):
    user = current_user()
    if not user:
        return api_error("Usuário não encontrado.", 404)
    job = mongo.db.coding_jobs.find_one({"_id": object_id(job_id)})
    if not job:
        return api_error("Execução não encontrada.", 404)
    challenge = mongo.db.challenges.find_one({"_id": job["challenge_id"]})
    if user["role"] != "admin" and user["_id"] != job["talent_id"] and (not challenge or user["_id"] != challenge["owner_id"]):
        return api_error("Acesso negado.", 403)
    job = refresh_job(job)
    score = mongo.db.coding_scores.find_one({"challenge_id": job["challenge_id"], "talent_id": job["talent_id"]})
    return jsonify(serialize({"job": public_job(job), "best_score": score.get("score", 0) if score else 0}))


@coding_bp.get("/challenges/<challenge_id>/coding/results")
@jwt_required()
def coding_results(challenge_id):
    user, challenge, error = access(challenge_id, owner=True)
    if error:
        return error
    rows = []
    warning = ""
    for participation in mongo.db.participations.find({"challenge_id": challenge["_id"]}):
        talent = mongo.db.users.find_one({"_id": participation["talent_id"]}, {"name": 1, "headline": 1})
        jobs = list(mongo.db.coding_jobs.find({"challenge_id": challenge["_id"], "talent_id": participation["talent_id"], "mode": "submit"}).sort("created_at", -1))
        latest = jobs[0] if jobs else None
        if latest:
            try:
                latest = refresh_job(latest)
            except Judge0Error as exc:
                warning = str(exc)
        # Refresh may have just persisted the first score.
        score = mongo.db.coding_scores.find_one({"challenge_id": challenge["_id"], "talent_id": participation["talent_id"]})
        rows.append({
            "talent_id": participation["talent_id"], "name": talent.get("name", "Candidato") if talent else "Candidato",
            "score": score.get("score", 0) if score else 0,
            "solved_at": score.get("solved_at") if score else None,
            "attempts": len(jobs), "latest_job": public_job(latest) if latest else None,
            "source_code": latest.get("source_code", "") if latest else "",
        })
    rows.sort(key=lambda r: (-r["score"], str(r.get("solved_at") or "9999"), r["name"]))
    return jsonify(serialize({"results": rows, "warning": warning}))

