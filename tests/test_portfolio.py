from bson import ObjectId

from app.extensions import mongo
from app.utils import now


def test_portfolio_keeps_own_code_attempts_and_reports_without_private_or_foreign_data(client, identities, assessment):
    challenge_id = ObjectId(assessment)
    talent_id = identities["talent"]["id"]
    for status, source in [("processing", "print('pending')"), ("completed", "print('saved')")]:
        mongo.db.coding_jobs.insert_one({
            "challenge_id": challenge_id, "talent_id": talent_id, "mode": "submit",
            "language": "python", "source_code": source, "status": status,
            "score": 0, "max_points": 100, "created_at": now(),
            "provider_tokens": ["private-provider-token"], "output": {"stdout": "private-output"},
        })
    mongo.db.coding_jobs.insert_one({
        "challenge_id": challenge_id, "talent_id": identities["other_talent"]["id"],
        "mode": "submit", "source_code": "OTHER_CANDIDATE_CODE", "status": "completed", "created_at": now(),
    })
    report = client.post(f"/api/challenges/{assessment}/submissions", headers=identities["talent"]["headers"], data={"summary": "Meu relatório"})
    assert report.status_code == 201
    response = client.get("/api/dashboard", headers=identities["talent"]["headers"])
    assert response.status_code == 200
    assert len(response.json["coding_submissions"]) == 2
    assert {item["source_code"] for item in response.json["coding_submissions"]} == {"print('pending')", "print('saved')"}
    assert response.json["submissions"][0]["summary"] == "Meu relatório"
    body = response.get_data(as_text=True)
    assert "private-provider-token" not in body
    assert "private-output" not in body
    assert "OTHER_CANDIDATE_CODE" not in body
    mongo.db.challenges.update_one({"_id": challenge_id}, {"$set": {"status": "pending_review", "title": "UNREVIEWED_TITLE"}})
    response = client.get("/api/dashboard", headers=identities["talent"]["headers"])
    assert "UNREVIEWED_TITLE" not in response.get_data(as_text=True)
    assert {item["challenge"]["title"] for item in response.json["coding_submissions"]} == {"Desafio em revisão"}
