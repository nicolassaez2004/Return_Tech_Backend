from bson import ObjectId

from app.extensions import mongo
from app.services.coding import load_config


def test_create_form_saves_private_coding_configuration_and_keeps_review_and_report_flows(client, identities):
    owner = identities["owner"]["headers"]
    admin = identities["admin"]["headers"]
    talent = identities["talent"]["headers"]
    fields = {
        "title": "Análise de eventos por código", "description": "Leia os eventos e retorne a quantidade.",
        "deliverables": "Programa para avaliar os eventos.", "skills": ["Python", "SOC"],
        "level": "Júnior", "work_mode": "Remoto", "deadline": "2099-01-01",
    }
    config = {
        "languages": ["python", "javascript"], "max_points": 75,
        "example": {"stdin": "FAIL\nOK\n", "expected_output": "1\n"},
        "tests": [{"stdin": "PRIVATE-INPUT-BY-FORM", "expected_output": "PRIVATE-ANSWER-BY-FORM"}],
        "starter_code": {"python": "import sys\n"},
    }
    invalid = client.post("/api/challenges", headers=owner, json={
        **fields, "coding_config": {**config, "tests": []},
    })
    assert invalid.status_code == 400
    assert mongo.db.challenges.count_documents({}) == 0
    assert mongo.db.coding_config_versions.count_documents({}) == 0

    created = client.post("/api/challenges", headers=owner, json={**fields, "coding_config": config})
    assert created.status_code == 201
    challenge_id = created.json["challenge"]["_id"]
    saved = mongo.db.challenges.find_one({"_id": ObjectId(challenge_id)})
    assert saved["status"] == "draft"
    assert saved["revision"] == 1
    assert saved["coding_enabled"] is True
    assert saved["coding_max_points"] == 75
    assert saved["coding_config_version"]
    assert mongo.db.coding_config_versions.count_documents({}) == 1
    stored_config = load_config(saved)
    assert stored_config["tests"] == config["tests"]
    assert stored_config["example"] == config["example"]
    assert stored_config["languages"] == ["python", "javascript"]
    assert stored_config["max_points"] == 75
    route = f"/api/challenges/{challenge_id}"
    assert client.get(route, headers=talent).status_code == 404
    assert client.post(route + "/join", headers=talent).status_code == 404
    for headers in [owner, admin]:
        reviewed = client.get(route + "/coding/config", headers=headers)
        assert reviewed.status_code == 200
        assert reviewed.json["config"]["tests"] == config["tests"]

    assert client.patch(route + "/status", headers=owner, json={"action": "submit_review"}).status_code == 200
    assert client.get(route, headers=talent).status_code == 404
    approved = client.patch(route + "/status", headers=admin,
                            json={"action": "approve", "review_revision": 1})
    assert approved.status_code == 200
    assert client.post(route + "/join", headers=talent).status_code == 200
    public = client.get(route + "/coding", headers=talent)
    assert public.status_code == 200
    assert public.json["config"]["example"] == config["example"]
    assert "tests" not in public.json["config"]
    assert "PRIVATE-INPUT-BY-FORM" not in public.get_data(as_text=True)
    assert "PRIVATE-ANSWER-BY-FORM" not in public.get_data(as_text=True)

    report = client.post("/api/challenges", headers=owner,
                         json={**fields, "title": "Investigação por relatório"})
    assert report.status_code == 201
    report_challenge = mongo.db.challenges.find_one({"_id": ObjectId(report.json["challenge"]["_id"])})
    assert report_challenge["status"] == "draft"
    assert not report_challenge.get("coding_enabled")
    assert not report_challenge.get("coding_config_version")
    assert mongo.db.coding_config_versions.count_documents({}) == 1
