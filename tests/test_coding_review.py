import pytest
from bson import ObjectId
from pymongo.errors import AutoReconnect

from app.extensions import mongo


CONFIG = {"languages": ["python"], "max_points": 100,
          "tests": [{"stdin": "private-input", "expected_output": "private-answer"}]}


def create_draft(client, identities):
    response = client.post("/api/challenges", headers=identities["owner"]["headers"], json={
        "title": "Código revisado", "description": "Leia a entrada e imprima a resposta.",
        "deliverables": "Programa", "deadline": "2099-01-01", "skills": ["Python"],
    })
    assert response.status_code == 201
    return response.json["challenge"]["_id"]


def test_coding_configuration_is_part_of_the_revision_approved_by_admin(client, identities):
    challenge = create_draft(client, identities)
    owner = identities["owner"]["headers"]
    admin = identities["admin"]["headers"]
    route = f"/api/challenges/{challenge}"
    assert client.put(route + "/coding/config", headers=owner, json=CONFIG).status_code == 200
    detail = client.get(route, headers=admin).json["challenge"]
    assert detail["revision"] == 2
    review = client.get(route + "/coding/config", headers=admin)
    assert review.json["config"]["tests"] == CONFIG["tests"]
    assert client.patch(route + "/status", headers=owner, json={"action": "publish"}).json["status"] == "pending_review"
    assert client.post(route + "/join", headers=identities["talent"]["headers"]).status_code == 404
    assert client.patch(route + "/status", headers=admin,
                        json={"action": "approve", "review_revision": 1}).status_code == 409
    assert client.patch(route + "/status", headers=admin,
                        json={"action": "approve", "review_revision": detail["revision"]}).status_code == 200


@pytest.mark.parametrize("status", ["draft", "pending_review", "changes_requested"])
def test_old_participation_does_not_reveal_unreviewed_coding_content(client, identities, assessment, status):
    mongo.db.challenges.update_one({"_id": ObjectId(assessment)}, {"$set": {"status": status}})
    response = client.get(f"/api/challenges/{assessment}/coding", headers=identities["talent"]["headers"])
    assert response.status_code == 404
    assert "private" not in response.get_data(as_text=True).lower()


def test_admin_can_review_private_cases_but_cannot_change_company_configuration(client, identities):
    challenge = create_draft(client, identities)
    route = f"/api/challenges/{challenge}/coding/config"
    assert client.put(route, headers=identities["owner"]["headers"], json=CONFIG).status_code == 200
    assert client.get(route, headers=identities["admin"]["headers"]).status_code == 200
    for role in ("admin", "other_company", "talent"):
        assert client.put(route, headers=identities[role]["headers"], json=CONFIG).status_code == 403


def test_concurrent_review_keeps_the_previous_immutable_configuration(client, identities, monkeypatch):
    challenge = create_draft(client, identities)
    owner = identities["owner"]["headers"]
    route = f"/api/challenges/{challenge}"
    assert client.put(route + "/coding/config", headers=owner, json=CONFIG).status_code == 200
    previous_version = mongo.db.challenges.find_one({"_id": ObjectId(challenge)})["coding_config_version"]
    collection = mongo.db.coding_config_versions
    original_insert = collection.insert_one
    concurrent = []

    def insert_while_reviewing(*args, **kwargs):
        concurrent.append(client.patch(route + "/status", headers=owner,
                                       json={"action": "submit_review"}).status_code)
        return original_insert(*args, **kwargs)

    monkeypatch.setattr(collection, "insert_one", insert_while_reviewing)
    replacement = {**CONFIG, "tests": [{"stdin": "new-private-input", "expected_output": "new-answer"}]}
    response = client.put(route + "/coding/config", headers=owner, json=replacement)
    assert response.status_code == 409
    assert concurrent == [200]
    saved = mongo.db.challenges.find_one({"_id": ObjectId(challenge)})
    assert saved["status"] == "pending_review"
    assert saved["revision"] == 2
    assert saved["coding_config_version"] == previous_version
    assert client.get(route + "/coding/config", headers=identities["admin"]["headers"]).json["config"]["tests"] == CONFIG["tests"]


def test_stale_review_request_cannot_commit_after_configuration_changes(client, identities, monkeypatch):
    challenge = create_draft(client, identities)
    owner = identities["owner"]["headers"]
    collection = mongo.db.challenges
    original_update = collection.update_one
    configuration_responses = []

    def save_configuration_before_review(query, mutation, **kwargs):
        if mutation.get("$set", {}).get("status") == "pending_review":
            configuration_responses.append(client.put(f"/api/challenges/{challenge}/coding/config",
                                                       headers=owner, json=CONFIG).status_code)
        return original_update(query, mutation, **kwargs)

    monkeypatch.setattr(collection, "update_one", save_configuration_before_review)
    response = client.patch(f"/api/challenges/{challenge}/status", headers=owner,
                            json={"action": "submit_review"})
    assert configuration_responses == [200]
    assert response.status_code == 409
    assert mongo.db.challenges.find_one({"_id": ObjectId(challenge)})["status"] == "draft"


def test_transient_configuration_failure_does_not_lock_the_draft(client, identities, monkeypatch):
    challenge = create_draft(client, identities)
    owner = identities["owner"]["headers"]
    route = f"/api/challenges/{challenge}/coding/config"
    collection = mongo.db.coding_config_versions
    original_insert = collection.insert_one

    def unavailable(*args, **kwargs):
        raise AutoReconnect("simulated database outage")

    monkeypatch.setattr(collection, "insert_one", unavailable)
    assert client.put(route, headers=owner, json=CONFIG).status_code == 503
    assert client.get(route, headers=owner).json["editable"] is True
    monkeypatch.setattr(collection, "insert_one", original_insert)
    assert client.put(route, headers=owner, json=CONFIG).status_code == 200


def test_legacy_configuration_remains_readable_and_is_not_overwritten(client, identities):
    challenge = create_draft(client, identities)
    oid = ObjectId(challenge)
    mongo.db.coding_configs.insert_one({"challenge_id": oid, **CONFIG})
    route = f"/api/challenges/{challenge}/coding/config"
    owner = identities["owner"]["headers"]
    assert client.get(route, headers=owner).json["config"]["tests"] == CONFIG["tests"]
    assert client.put(route, headers=owner, json={**CONFIG, "max_points": 250}).status_code == 200
    assert client.get(route, headers=owner).json["config"]["max_points"] == 250
    assert mongo.db.coding_configs.find_one({"challenge_id": oid})["max_points"] == 100
