import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import mongomock
from bson import ObjectId
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token
from werkzeug.security import check_password_hash

from app.admin import create_admin
from app.extensions import mongo
from app.routes.api import api_bp
from app.routes.auth import auth_bp


class CTFTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient().return_tech_test
        self.db_patch = patch.object(mongo, "db", self.db)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, JWT_SECRET_KEY="test-only-secret-key-for-ctf-permissions", JWT_ACCESS_TOKEN_EXPIRES=False)
        JWTManager(self.app)
        self.app.register_blueprint(api_bp, url_prefix="/api")
        self.app.register_blueprint(auth_bp, url_prefix="/api/auth")
        self.app.cli.add_command(create_admin)
        self.client = self.app.test_client()
        self.users = {}
        self.headers = {}
        for key, role in (("company", "company"), ("other", "company"), ("talent", "talent"), ("outsider", "talent"), ("admin", "admin")):
            oid = self.db.users.insert_one({"name": key, "email": f"{key}@example.test", "role": role, "organization_name": key, "talent_type": "student", "skills": []}).inserted_id
            self.users[key] = oid
            with self.app.app_context():
                token = create_access_token(identity=str(oid))
            self.headers[key] = {"Authorization": f"Bearer {token}"}
        deadline = (datetime.now(timezone.utc) + timedelta(days=45)).date().isoformat()
        self.fields = {"title": "Investigação de logs", "description": "Contexto\nInstruções do desafio", "deliverables": "Relatório e evidências", "deadline": deadline, "skills": ["SOC"], "level": "Júnior", "work_mode": "Remoto"}

    def create(self):
        response = self.client.post("/api/challenges", json=self.fields, headers=self.headers["company"])
        self.assertEqual(response.status_code, 201, response.json)
        return response.json["challenge"]["_id"]

    def status(self, challenge_id, action, role="company", **extra):
        data = {"action": action, **extra}
        if action in {"approve", "request_changes"} or (action == "publish" and role == "admin"):
            challenge = self.db.challenges.find_one({"_id": ObjectId(challenge_id)})
            data.setdefault("review_revision", challenge.get("revision", 0))
        return self.client.patch(f"/api/challenges/{challenge_id}/status", json=data, headers=self.headers[role])

    def approve(self, challenge_id):
        self.assertEqual(self.status(challenge_id, "submit_review").status_code, 200)
        response = self.status(challenge_id, "approve", "admin")
        self.assertEqual(response.status_code, 200, response.json)

    def test_admin_approves_then_talent_reads_joins_and_submits(self):
        challenge_id = self.create()
        self.assertEqual(self.client.get(f"/api/challenges/{challenge_id}", headers=self.headers["talent"]).status_code, 404)
        self.approve(challenge_id)
        details = self.client.get(f"/api/challenges/{challenge_id}", headers=self.headers["talent"])
        self.assertEqual(details.json["challenge"]["description"], self.fields["description"])
        dashboard = self.client.get("/api/dashboard", headers=self.headers["talent"])
        self.assertIn(challenge_id, [row["_id"] for row in dashboard.json["challenges"]])
        self.assertEqual(self.client.post(f"/api/challenges/{challenge_id}/join", headers=self.headers["talent"]).status_code, 200)
        self.assertEqual(self.client.post(f"/api/challenges/{challenge_id}/join", headers=self.headers["talent"]).status_code, 200)
        self.assertEqual(self.db.participations.count_documents({}), 1)
        response = self.client.post(f"/api/challenges/{challenge_id}/submissions", data={"summary": "Análise realizada", "report_url": "https://example.test/report"}, headers=self.headers["talent"])
        self.assertEqual(response.status_code, 201, response.json)
        self.assertEqual(self.db.submissions.count_documents({}), 1)
        company_dashboard = self.client.get("/api/dashboard", headers=self.headers["company"])
        self.assertEqual(company_dashboard.json["submissions"][0]["summary"], "Análise realizada")

    def test_admin_is_separate_from_companies_and_talents(self):
        challenge_id = self.create()
        for role in ("company", "talent"):
            self.assertEqual(self.client.get("/api/admin/challenges", headers=self.headers[role]).status_code, 403)
        response = self.client.get("/api/admin/challenges", headers=self.headers["admin"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["challenges"][0]["_id"], challenge_id)
        self.assertNotIn("password_hash", str(response.json))
        updated = {**self.fields, "description": "Enunciado revisado pela equipe", "owner_id": str(self.users["admin"]), "status": "published"}
        response = self.client.patch(f"/api/challenges/{challenge_id}", json=updated, headers=self.headers["admin"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["challenge"]["owner_id"], str(self.users["company"]))
        self.assertEqual(response.json["challenge"]["status"], "draft")
        self.approve(challenge_id)
        self.assertEqual(self.status(challenge_id, "draft", "company").status_code, 400)
        self.assertEqual(self.status(challenge_id, "draft", "admin").status_code, 200)

    def test_other_company_and_talent_cannot_edit_or_publish(self):
        challenge_id = self.create()
        for role in ("other", "talent"):
            self.assertEqual(self.client.patch(f"/api/challenges/{challenge_id}", json=self.fields, headers=self.headers[role]).status_code, 403)
            self.assertIn(self.status(challenge_id, "publish", role).status_code, (403, 404))
        for role in ("talent", "admin"):
            self.assertEqual(self.client.post("/api/challenges", json=self.fields, headers=self.headers[role]).status_code, 403)

    def test_closed_participation_remains_visible_and_rejects_submissions(self):
        challenge_id = self.create()
        self.approve(challenge_id)
        self.client.post(f"/api/challenges/{challenge_id}/join", headers=self.headers["talent"])
        self.status(challenge_id, "close", "admin")
        self.assertEqual(self.client.get(f"/api/challenges/{challenge_id}", headers=self.headers["talent"]).status_code, 200)
        self.assertEqual(self.client.get(f"/api/challenges/{challenge_id}", headers=self.headers["outsider"]).status_code, 404)
        dashboard = self.client.get("/api/dashboard", headers=self.headers["talent"]).json
        self.assertEqual(dashboard["challenges"][0]["status"], "closed")
        response = self.client.post(f"/api/challenges/{challenge_id}/submissions", data={"summary": "Atrasada"}, headers=self.headers["talent"])
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.db.submissions.count_documents({}), 0)

    def test_public_registration_and_profile_cannot_grant_admin(self):
        response = self.client.post("/api/auth/register", json={"name": "Tentativa", "email": "new@example.test", "password": "password-test", "role": "admin"})
        self.assertEqual(response.status_code, 400)
        response = self.client.put("/api/profile", json={"role": "admin", "name": "Talento"}, headers=self.headers["talent"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["profile"]["role"], "talent")

    def test_pending_challenge_is_hidden_from_all_talent_entry_points(self):
        challenge_id = self.create()
        response = self.status(challenge_id, "submit_review")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "pending_review")
        self.assertEqual(self.client.get("/api/challenges", headers=self.headers["talent"]).json["challenges"], [])
        self.assertEqual(self.client.get("/api/dashboard", headers=self.headers["talent"]).json["challenges"], [])
        self.assertEqual(self.client.get(f"/api/challenges/{challenge_id}", headers=self.headers["talent"]).status_code, 404)
        self.assertEqual(self.client.post(f"/api/challenges/{challenge_id}/join", headers=self.headers["talent"]).status_code, 404)
        self.assertEqual(self.client.post(f"/api/challenges/{challenge_id}/submissions", data={"summary": "Tentativa"}, headers=self.headers["talent"]).status_code, 409)
        admin_list = self.client.get("/api/admin/challenges", headers=self.headers["admin"]).json
        self.assertEqual(admin_list["challenges"][0]["status"], "pending_review")

    def test_old_company_publish_action_cannot_bypass_approval(self):
        response = self.client.post("/api/challenges", json={**self.fields, "status": "published", "authorization_confirmed": True, "approved_revision": 1}, headers=self.headers["company"])
        challenge_id = response.json["challenge"]["_id"]
        self.assertEqual(response.json["challenge"]["status"], "draft")
        self.assertFalse(response.json["challenge"]["authorization_confirmed"])
        response = self.status(challenge_id, "publish")
        self.assertEqual(response.json["status"], "pending_review")
        self.assertEqual(self.status(challenge_id, "approve", "company").status_code, 403)
        self.assertEqual(self.status(challenge_id, "request_changes", "company", feedback="Tentativa").status_code, 403)
        self.assertEqual(self.status(challenge_id, "submit_review", "other").status_code, 404)
        self.assertEqual(self.status(challenge_id, "close", "company").status_code, 409)

    def test_admin_must_review_submitted_revision(self):
        challenge_id = self.create()
        self.assertEqual(self.status(challenge_id, "approve", "admin").status_code, 409)
        self.status(challenge_id, "submit_review")
        for data in ({"action": "approve"}, {"action": "approve", "review_revision": "1"}, {"action": "approve", "review_revision": True}):
            response = self.client.patch(f"/api/challenges/{challenge_id}/status", json=data, headers=self.headers["admin"])
            self.assertEqual(response.status_code, 409)
        self.assertEqual(self.status(challenge_id, "submit_review").status_code, 409)
        response = self.status(challenge_id, "approve", "admin")
        self.assertEqual(response.json["status"], "published")
        saved = self.db.challenges.find_one({"_id": ObjectId(challenge_id)})
        self.assertEqual(saved["approved_by"], self.users["admin"])
        self.assertEqual(saved["approved_revision"], saved["revision"])
        self.assertIsNotNone(saved["approved_at"])
        self.assertEqual(self.db.notifications.find_one({"user_id": self.users["company"]})["kind"], "challenge_review")

    def test_changes_require_feedback_and_can_be_resubmitted(self):
        challenge_id = self.create()
        self.status(challenge_id, "submit_review")
        self.assertEqual(self.status(challenge_id, "request_changes", "admin", feedback=" ").status_code, 400)
        response = self.status(challenge_id, "request_changes", "admin", feedback="Especifique o escopo e as evidências esperadas.")
        self.assertEqual(response.json["status"], "changes_requested")
        details = self.client.get(f"/api/challenges/{challenge_id}", headers=self.headers["company"]).json["challenge"]
        self.assertIn("Especifique", details["review_feedback"])
        update = self.client.patch(f"/api/challenges/{challenge_id}", json={**self.fields, "description": "Escopo e evidências detalhados."}, headers=self.headers["company"])
        self.assertEqual(update.json["challenge"]["status"], "draft")
        self.approve(challenge_id)
        saved = self.db.challenges.find_one({"_id": ObjectId(challenge_id)})
        self.assertEqual(saved["review_feedback"], "")

    def test_company_edits_require_new_approval_and_hide_unreviewed_content(self):
        challenge_id = self.create()
        self.approve(challenge_id)
        self.client.post(f"/api/challenges/{challenge_id}/join", headers=self.headers["talent"])
        self.client.post(f"/api/challenges/{challenge_id}/submissions", data={"summary": "Minha solução"}, headers=self.headers["talent"])
        fields = {**self.fields, "title": "NOVO ENUNCIADO AINDA NÃO APROVADO", "description": "CONTEÚDO SEM APROVAÇÃO"}
        response = self.client.patch(f"/api/challenges/{challenge_id}", json=fields, headers=self.headers["company"])
        self.assertEqual(response.json["challenge"]["status"], "draft")
        self.assertIsNone(response.json["challenge"]["approved_by"])
        self.assertFalse(response.json["challenge"]["authorization_confirmed"])
        self.assertEqual(self.client.get(f"/api/challenges/{challenge_id}", headers=self.headers["talent"]).status_code, 404)
        self.assertEqual(self.client.post(f"/api/challenges/{challenge_id}/submissions", data={"summary": "Outra solução"}, headers=self.headers["talent"]).status_code, 409)
        dashboard = self.client.get("/api/dashboard", headers=self.headers["talent"]).json
        self.assertEqual(dashboard["challenges"], [])
        self.assertEqual(dashboard["submissions"][0]["challenge"]["title"], "Desafio em revisão")
        self.assertNotIn(fields["description"], str(dashboard))
        self.approve(challenge_id)
        details = self.client.get(f"/api/challenges/{challenge_id}", headers=self.headers["talent"])
        self.assertEqual(details.json["challenge"]["title"], fields["title"])

    def test_stale_review_cannot_approve_a_resubmitted_new_version(self):
        challenge_id = self.create()
        self.status(challenge_id, "submit_review")
        old_revision = self.db.challenges.find_one({"_id": ObjectId(challenge_id)})["revision"]
        self.client.patch(f"/api/challenges/{challenge_id}", json={**self.fields, "description": "Nova versão"}, headers=self.headers["company"])
        self.status(challenge_id, "submit_review")
        for action in ("approve", "request_changes", "publish"):
            response = self.status(challenge_id, action, "admin", review_revision=old_revision, feedback="Feedback da versão anterior")
            self.assertEqual(response.status_code, 409)
        self.assertEqual(self.db.challenges.find_one({"_id": ObjectId(challenge_id)})["status"], "pending_review")
        self.assertEqual(self.status(challenge_id, "approve", "admin").status_code, 200)

    def test_concurrent_edit_prevents_approval(self):
        challenge_id = self.create()
        self.status(challenge_id, "submit_review")
        original_update = self.db.challenges.update_one
        def edit_before_approval(query, update):
            original_update({"_id": ObjectId(challenge_id)}, {"$set": {"status": "draft", "revision": 2}})
            return original_update(query, update)
        with patch.object(self.db.challenges, "update_one", side_effect=edit_before_approval):
            response = self.status(challenge_id, "approve", "admin")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.db.challenges.find_one({"_id": ObjectId(challenge_id)})["status"], "draft")
        self.assertEqual(self.db.notifications.count_documents({"kind": "challenge_review"}), 0)

    def test_saving_unchanged_content_does_not_remove_approval(self):
        challenge_id = self.create()
        self.approve(challenge_id)
        response = self.client.patch(f"/api/challenges/{challenge_id}", json=self.fields, headers=self.headers["company"])
        self.assertEqual(response.json["challenge"]["status"], "published")
        self.assertEqual(response.json["challenge"]["revision"], 1)

    def test_existing_published_challenge_is_preserved_until_company_edits(self):
        challenge_id = self.create()
        self.db.challenges.update_one({"_id": ObjectId(challenge_id)}, {"$set": {"status": "published"}, "$unset": {"revision": ""}})
        self.assertEqual(self.client.get(f"/api/challenges/{challenge_id}", headers=self.headers["talent"]).status_code, 200)
        self.client.patch(f"/api/challenges/{challenge_id}", json={**self.fields, "description": "Revisão de desafio antigo"}, headers=self.headers["company"])
        self.approve(challenge_id)
        self.assertEqual(self.db.challenges.find_one({"_id": ObjectId(challenge_id)})["status"], "published")

    def test_malformed_actions_are_rejected(self):
        challenge_id = self.create()
        for action in ([], {}, None, 7):
            response = self.client.patch(f"/api/challenges/{challenge_id}/status", json={"action": action}, headers=self.headers["company"])
            self.assertEqual(response.status_code, 400)

    def test_cli_creates_private_admin_with_hashed_password(self):
        runner = self.app.test_cli_runner()
        result = runner.invoke(args=["create-admin", "--email", "team@example.test", "--name", "Equipe"], input="password-test\npassword-test\n")
        self.assertEqual(result.exit_code, 0, result.output)
        user = self.db.users.find_one({"email": "team@example.test"})
        self.assertEqual(user["role"], "admin")
        self.assertTrue(check_password_hash(user["password_hash"], "password-test"))
        login = self.client.post("/api/auth/login", json={"email": "team@example.test", "password": "password-test"})
        self.assertEqual(login.status_code, 200)
        self.assertNotIn("password_hash", login.json["user"])
        duplicate = runner.invoke(args=["create-admin", "--email", "team@example.test", "--name", "Equipe"], input="password-test\npassword-test\n")
        self.assertNotEqual(duplicate.exit_code, 0)
        self.assertEqual(self.db.users.count_documents({"email": "team@example.test"}), 1)

    def test_validation_authentication_and_missing_challenge(self):
        self.assertEqual(self.client.get("/api/admin/challenges").status_code, 401)
        self.assertEqual(self.client.get(f"/api/challenges/{ObjectId()}").status_code, 401)
        for fields in ({**self.fields, "description": "  "}, {**self.fields, "deadline": "not-a-date"}, {**self.fields, "skills": [False]}, []):
            self.assertEqual(self.client.post("/api/challenges", json=fields, headers=self.headers["company"]).status_code, 400)
        self.assertEqual(self.client.get("/api/challenges/invalid", headers=self.headers["admin"]).status_code, 404)
        self.assertEqual(self.db.challenges.count_documents({}), 0)


if __name__ == "__main__":
    unittest.main()
