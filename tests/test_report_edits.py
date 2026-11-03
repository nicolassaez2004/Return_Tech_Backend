from datetime import timedelta
from io import BytesIO

import mongomock.gridfs
from bson import ObjectId

from app.extensions import mongo
from app.utils import now


def test_report_edit_preserves_file_and_history_then_locks_at_closure(client, identities):
    mongomock.gridfs.enable_gridfs_integration()
    challenge_id = mongo.db.challenges.insert_one({
        "owner_id": identities["owner"]["id"], "title": "Relatório de incidente",
        "description": "Analise as evidências.", "skills": ["SOC"], "status": "published",
        "deadline": "2099-01-01", "created_at": now(),
    }).inserted_id
    headers = identities["talent"]["headers"]
    assert client.post(f"/api/challenges/{challenge_id}/join", headers=headers).status_code == 200
    endpoint = f"/api/challenges/{challenge_id}/submissions"
    first = client.post(endpoint, headers=headers, data={
        "summary": "Análise inicial", "report_url": "https://example.test/inicial",
        "file": (BytesIO(b"Evidencias"), "relatorio.txt", "text/plain"),
    })
    assert first.status_code == 201
    original = first.json["submission"]
    mongo.db.participations.update_one({"_id": ObjectId(original["participation_id"])},
                                      {"$set": {"status": "shortlisted"}})
    edited = client.post(endpoint, headers=headers, data={
        "previous_submission_id": original["_id"], "summary": "Análise corrigida",
        "report_url": "https://example.test/final",
    })
    assert edited.status_code == 201
    saved = edited.json["submission"]
    assert saved["version"] == 2
    assert saved["file_id"] == original["file_id"]
    assert saved["file_name"] == "relatorio.txt"
    assert client.get(f"/api/submissions/{saved['_id']}/file", headers=headers).data == b"Evidencias"
    detail = client.get(f"/api/challenges/{challenge_id}", headers=headers).json["challenge"]
    assert detail["latest_submission"]["summary"] == "Análise corrigida"
    assert detail["latest_submission"]["report_url"] == "https://example.test/final"
    assert mongo.db.submissions.find_one({"_id": ObjectId(original["_id"])})["summary"] == "Análise inicial"
    assert len(client.get("/api/dashboard", headers=headers).json["submissions"]) == 2

    replacement = client.post(endpoint, headers=headers, data={
        "previous_submission_id": saved["_id"], "summary": "Análise final",
        "file": (BytesIO(b"Novas evidencias"), "final.txt", "text/plain"),
    })
    assert replacement.status_code == 201
    assert replacement.json["submission"]["file_id"] != saved["file_id"]
    mongo.db.challenges.update_one({"_id": challenge_id}, {"$set": {"status": "closed"}})
    assert client.post(endpoint, headers=headers, data={"summary": "Depois do encerramento"}).status_code == 409
    mongo.db.challenges.update_one({"_id": challenge_id}, {"$set": {
        "status": "published", "deadline": "2000-01-01", "ends_at": now() - timedelta(days=1),
    }})
    assert client.post(endpoint, headers=headers, data={"summary": "Depois do prazo"}).status_code == 409


def test_cannot_reuse_another_participants_attachment(client, identities, assessment):
    foreign = client.post(f"/api/challenges/{assessment}/submissions", headers=identities["other_talent"]["headers"],
                          data={"summary": "Entrega de outra pessoa"})
    assert foreign.status_code == 201
    response = client.post(f"/api/challenges/{assessment}/submissions", headers=identities["talent"]["headers"],
                           data={"summary": "Minha entrega", "previous_submission_id": foreign.json["submission"]["_id"]})
    assert response.status_code == 404
