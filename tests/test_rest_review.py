import json

import mongomock.gridfs
from bson import ObjectId

from app.extensions import mongo


def test_partial_profile_and_created_resources_use_http_semantics(client, identities, assessment):
    owner = identities["owner"]
    mongo.db.users.update_one({"_id": owner["id"]}, {"$set": {"city": "São Paulo", "bio": "Perfil preservado"}})
    response = client.patch("/api/profile", headers=owner["headers"], json={"headline": "Analista"})
    assert response.status_code == 200
    assert response.json["profile"]["headline"] == "Analista"
    assert response.json["profile"]["city"] == "São Paulo"
    assert response.json["profile"]["bio"] == "Perfil preservado"
    assert client.put("/api/profile", headers=owner["headers"], json={"headline": "Especialista"}).status_code == 200
    created = client.post("/api/challenges", headers=owner["headers"], json={
        "title": "Revisão de logs", "description": "Analise os registros.", "deliverables": "Um relatório.",
        "deadline": "2099-01-01", "skills": ["SOC"],
    })
    assert created.status_code == 201
    assert created.headers["Location"] == f'/api/challenges/{created.json["challenge"]["_id"]}'
    assert client.get(created.headers["Location"], headers=owner["headers"]).status_code == 200

    for identity, original_status in [("talent", "joined"), ("other_talent", "shortlisted")]:
        talent = identities[identity]
        participation = mongo.db.participations.find_one({"challenge_id": ObjectId(assessment), "talent_id": talent["id"]})
        mongo.db.participations.update_one({"_id": participation["_id"]}, {"$set": {"status": original_status}})
        submitted = client.post(f"/api/challenges/{assessment}/code-jobs", headers=talent["headers"],
                                json={"mode": "submit", "language": "python", "source_code": "print(1)"})
        assert submitted.status_code == 202
        assert submitted.headers["Location"] == f'/api/code-jobs/{submitted.json["job"]["_id"]}'
        assert client.get(submitted.headers["Location"], headers=talent["headers"]).status_code == 200
        expected_status = "submitted" if original_status == "joined" else original_status
        assert mongo.db.participations.find_one({"_id": participation["_id"]})["status"] == expected_status


def test_invalid_json_and_scores_are_client_errors_without_writes(client, identities, assessment):
    report = client.post(f"/api/challenges/{assessment}/submissions", headers=identities["talent"]["headers"],
                         data={"summary": "Relatório de análise"})
    assert report.status_code == 201
    endpoint = f'/api/submissions/{report.json["submission"]["_id"]}/evaluate'
    owner_headers = identities["owner"]["headers"]
    user_before = mongo.db.users.find_one({"_id": identities["owner"]["id"]})
    counts_before = {name: mongo.db[name].count_documents({}) for name in ("users", "evaluations", "notifications", "company_shortlist")}
    for body in (json.dumps(["invalid"]), "null", '{"invalid":'):
        for method, path in [("POST", "/api/auth/register"), ("POST", "/api/auth/login"),
                             ("PATCH", "/api/profile"), ("POST", endpoint)]:
            response = client.open(path, method=method, headers=owner_headers, data=body, content_type="application/json")
            assert response.status_code == 400, (path, body)
    for score in (None, "80", "abc", True, False, float("nan"), float("inf"), -1, 101, 55.5):
        response = client.post(endpoint, headers=owner_headers,
                               json={"decision": "shortlisted", "feedback": "Análise concluída", "score": score})
        assert response.status_code == 400, score
    for skills in ([{"invalid": "object"}], [None], [1], {"invalid": "object"}):
        assert client.patch("/api/profile", headers=owner_headers, json={"skills": skills}).status_code == 400
        assert client.post("/api/auth/register", json={
            "email": "invalid-skills@example.test", "password": "test-password-only", "name": "Talento",
            "role": "talent", "talent_type": "student", "skills": skills,
        }).status_code == 400
    assert mongo.db.users.find_one({"_id": identities["owner"]["id"]}) == user_before
    assert {name: mongo.db[name].count_documents({}) for name in counts_before} == counts_before
    for score in (0, 100):
        response = client.post(endpoint, headers=owner_headers,
                               json={"decision": "rejected", "feedback": "Análise concluída", "score": score})
        assert response.status_code == 201
        assert response.json["evaluation"]["score"] == score


def test_missing_submission_relations_or_file_return_not_found(client, identities, assessment):
    mongomock.gridfs.enable_gridfs_integration()
    talent = identities["talent"]
    participation = mongo.db.participations.find_one({"challenge_id": ObjectId(assessment), "talent_id": talent["id"]})
    report_id = mongo.db.submissions.insert_one({"participation_id": participation["_id"], "file_id": ObjectId()}).inserted_id
    endpoint = f"/api/submissions/{report_id}/file"
    assert client.get(endpoint, headers=identities["other_talent"]["headers"]).status_code == 403
    assert client.get(endpoint, headers=talent["headers"]).status_code == 404
    challenge = mongo.db.challenges.find_one_and_delete({"_id": ObjectId(assessment)})
    assert client.get(endpoint, headers=talent["headers"]).status_code == 404
    mongo.db.challenges.insert_one(challenge)
    mongo.db.participations.delete_one({"_id": participation["_id"]})
    assert client.get(endpoint, headers=talent["headers"]).status_code == 404
