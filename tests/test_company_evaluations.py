from bson import ObjectId

from app.extensions import mongo
from app.utils import now


def insert_code(challenge_id, talent_id, participation_id, source, score):
    return mongo.db.coding_jobs.insert_one({
        "challenge_id": challenge_id, "talent_id": talent_id,
        "participation_id": participation_id, "mode": "submit", "language": "python",
        "source_code": source, "status": "completed", "active": False,
        "score": score, "max_points": 100, "passed": 2 if score else 0, "total": 2,
        "created_at": now(), "provider_tokens": ["PRIVATE-PROVIDER-TOKEN"],
        "output": {"stdout": "PRIVATE-EXECUTOR-OUTPUT"},
    }).inserted_id


def test_company_receives_every_report_and_code_attempt_with_author_but_no_foreign_or_private_data(client, identities, assessment):
    challenge_id = ObjectId(assessment)
    talent_id = identities["talent"]["id"]
    participation = mongo.db.participations.find_one({"challenge_id": challenge_id, "talent_id": talent_id})
    mongo.db.users.update_one({"_id": talent_id}, {"$set": {
        "name": "Ana Silva", "headline": "Analista SOC", "city": "São Paulo",
        "bio": "Investigo incidentes.", "skills": ["SOC", "Python"],
        "password_hash": "PRIVATE-PASSWORD-HASH", "reset_token": "PRIVATE-RESET-TOKEN",
    }})
    for score in [0, 100]:
        insert_code(challenge_id, talent_id, participation["_id"], f"print({score})", score)
    report = client.post(f"/api/challenges/{assessment}/submissions", headers=identities["talent"]["headers"],
                         data={"summary": "Relatório da investigação"})
    assert report.status_code == 201
    foreign_id = mongo.db.challenges.insert_one({
        "owner_id": identities["other_company"]["id"], "title": "Desafio de outra empresa",
        "status": "published", "deadline": "2099-01-01", "created_at": now(),
    }).inserted_id
    foreign_part = mongo.db.participations.insert_one({
        "challenge_id": foreign_id, "talent_id": talent_id, "status": "submitted",
    }).inserted_id
    insert_code(foreign_id, talent_id, foreign_part, "FOREIGN-COMPANY-SOURCE", 100)

    response = client.get("/api/dashboard", headers=identities["owner"]["headers"])
    assert response.status_code == 200
    payload = response.json
    assert len(payload["submissions"]) == 1
    assert payload["submissions"][0]["summary"] == "Relatório da investigação"
    assert len(payload["coding_submissions"]) == 2
    assert {item["source_code"] for item in payload["coding_submissions"]} == {"print(0)", "print(100)"}
    assert {item["score"] for item in payload["coding_submissions"]} == {0, 100}
    for item in payload["submissions"] + payload["coding_submissions"]:
        assert item["talent"]["_id"] == str(talent_id)
        assert item["talent"]["email"] == "talent@example.test"
        assert item["talent"]["headline"] == "Analista SOC"
        assert item["participation"]["_id"] == str(participation["_id"])
        assert item["challenge"]["_id"] == assessment
        assert item["shortlisted"] is False
    body = response.get_data(as_text=True)
    for secret in ["FOREIGN-COMPANY-SOURCE", "PRIVATE-PROVIDER-TOKEN", "PRIVATE-EXECUTOR-OUTPUT",
                   "PRIVATE-PASSWORD-HASH", "PRIVATE-RESET-TOKEN"]:
        assert secret not in body


def test_shortlist_is_owner_only_idempotent_and_keeps_current_profile_after_new_delivery(client, identities, assessment):
    challenge_id = ObjectId(assessment)
    talent_id = identities["talent"]["id"]
    participation = mongo.db.participations.find_one({"challenge_id": challenge_id, "talent_id": talent_id})
    insert_code(challenge_id, talent_id, participation["_id"], "print(1)", 100)
    endpoint = f"/api/participations/{participation['_id']}/shortlist"
    assert client.post(endpoint, headers=identities["other_company"]["headers"]).status_code == 403
    assert client.post(endpoint, headers=identities["talent"]["headers"]).status_code == 403
    for _ in range(2):
        assert client.post(endpoint, headers=identities["owner"]["headers"]).status_code == 200
    assert mongo.db.company_shortlist.count_documents({"company_id": identities["owner"]["id"], "talent_id": talent_id}) == 1
    mongo.db.users.update_one({"_id": talent_id}, {"$set": {
        "name": "Ana Atualizada", "headline": "Especialista SOC", "bio": "Meu perfil atualizado.",
        "city": "Campinas", "skills": ["SIEM"],
    }})
    sent = client.post(f"/api/challenges/{assessment}/submissions", headers=identities["talent"]["headers"],
                       data={"summary": "Nova entrega após a seleção"})
    assert sent.status_code == 201
    assert mongo.db.participations.find_one({"_id": participation["_id"]})["status"] == "submitted"
    dashboard = client.get("/api/dashboard", headers=identities["owner"]["headers"]).json
    selected, = dashboard["shortlist"]
    assert selected["talent"]["_id"] == str(talent_id)
    assert selected["talent"]["name"] == "Ana Atualizada"
    assert selected["talent"]["bio"] == "Meu perfil atualizado."
    assert selected["talent"]["skills"] == ["SIEM"]
    assert selected["challenges"][0]["_id"] == assessment
    assert all(item["shortlisted"] for item in dashboard["submissions"] + dashboard["coding_submissions"])

    # Existing selections made through a report evaluation remain visible.
    legacy = client.post(f"/api/challenges/{assessment}/submissions", headers=identities["other_talent"]["headers"],
                         data={"summary": "Entrega já selecionada no fluxo antigo"})
    assert legacy.status_code == 201
    mongo.db.evaluations.insert_one({
        "submission_id": ObjectId(legacy.json["submission"]["_id"]),
        "evaluator_id": identities["owner"]["id"], "decision": "shortlisted",
        "score": 80, "feedback": "Bom trabalho.", "created_at": now(),
    })
    before = mongo.db.company_shortlist.count_documents({})
    dashboard = client.get("/api/dashboard", headers=identities["owner"]["headers"]).json
    assert {row["talent"]["_id"] for row in dashboard["shortlist"]} == {
        str(talent_id), str(identities["other_talent"]["id"]),
    }
    assert mongo.db.company_shortlist.count_documents({}) == before


def test_legacy_import_is_validated_idempotent_private_and_preserves_old_links(client, identities):
    owner_id = identities["owner"]["id"]
    for legacy_id, status in [("demo-sentinel-fintech", "closed"), ("demo-aurora-cloud", "published")]:
        mongo.db.challenges.insert_one({
            "legacy_id": legacy_id, "owner_id": owner_id, "title": legacy_id,
            "status": status, "deadline": "2099-01-01", "created_at": now(), "skills": ["SOC"],
        })
    headers = identities["talent"]["headers"]
    endpoint = "/api/legacy-participations/import"
    report = {"legacy_id": "demo-sentinel-fintech", "summary": "Minha análise anterior",
              "report_url": "https://example.test/evidencias", "talent_id": str(identities["other_talent"]["id"])}
    invalid = client.post(endpoint, headers=headers, json={"items": [report, {"legacy_id": "demo-inventado"}]})
    assert invalid.status_code == 400
    assert mongo.db.participations.count_documents({}) == 0
    assert mongo.db.submissions.count_documents({}) == 0
    payload = {"items": [report, {"legacy_id": "demo-aurora-cloud", "summary": "", "report_url": ""}]}
    assert client.post(endpoint, headers=identities["owner"]["headers"], json=payload).status_code == 403
    for _ in range(2):
        response = client.post(endpoint, headers=headers, json=payload)
        assert response.status_code == 200
        assert response.json["ok"] is True
    assert mongo.db.participations.count_documents({"talent_id": identities["talent"]["id"]}) == 2
    assert mongo.db.participations.count_documents({"talent_id": identities["other_talent"]["id"]}) == 0
    assert mongo.db.submissions.count_documents({}) == 1
    assert mongo.db.notifications.count_documents({}) == 0
    assert mongo.db.email_outbox.count_documents({}) == 0
    assert all("mail_events" not in item for item in mongo.db.participations.find())
    imported = mongo.db.submissions.find_one()
    assert imported["summary"] == "Minha análise anterior"
    assert imported["version"] == 1
    assert imported["file_id"] is None
    altered_payload = {"items": [{**report, "summary": "Alteração após o encerramento",
                                  "report_url": "https://example.test/alterado"}]}
    assert client.post(endpoint, headers=headers, json=altered_payload).status_code == 200
    assert mongo.db.submissions.count_documents({}) == 1
    unchanged = mongo.db.submissions.find_one({"_id": imported["_id"]})
    assert unchanged["summary"] == "Minha análise anterior"
    assert unchanged["report_url"] == "https://example.test/evidencias"
    mongo.db.participations.update_one({"_id": imported["participation_id"]}, {"$set": {"status": "shortlisted"}})
    assert client.post(endpoint, headers=headers, json=payload).status_code == 200
    assert mongo.db.participations.find_one({"_id": imported["participation_id"]})["status"] == "shortlisted"
    detail = client.get("/api/challenges/demo-sentinel-fintech", headers=headers)
    assert detail.status_code == 200
    assert detail.json["challenge"]["_id"] != "demo-sentinel-fintech"
    assert detail.json["challenge"]["latest_submission"]["_id"] == str(imported["_id"])
    assert detail.json["challenge"]["participation"]["status"] == "shortlisted"
    owner_dashboard = client.get("/api/dashboard", headers=identities["owner"]["headers"])
    assert owner_dashboard.status_code == 200
    assert len(owner_dashboard.json["submissions"]) == 1
    assert owner_dashboard.json["submissions"][0]["talent"]["_id"] == str(identities["talent"]["id"])
    other_dashboard = client.get("/api/dashboard", headers=identities["other_company"]["headers"])
    assert other_dashboard.status_code == 200
    assert other_dashboard.json["submissions"] == []
