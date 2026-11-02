import unittest
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
        self.fields = {"title": "Investigação de logs", "description": "Contexto\nInstruções do desafio", "deliverables": "Relatório e evidências", "deadline": "2026-12-10", "skills": ["SOC"], "level": "Júnior", "work_mode": "Remoto"}

    def create(self):
        response = self.client.post("/api/challenges", json=self.fields, headers=self.headers["company"])
        self.assertEqual(response.status_code, 201, response.json)
        return response.json["challenge"]["_id"]

    def status(self, challenge_id, action, role="company"):
        return self.client.patch(f"/api/challenges/{challenge_id}/status", json={"action": action}, headers=self.headers[role])

    def test_company_publishes_talent_reads_joins_and_submits(self):
        challenge_id = self.create()
        self.assertEqual(self.client.get(f"/api/challenges/{challenge_id}", headers=self.headers["talent"]).status_code, 404)
        self.assertEqual(self.status(challenge_id, "publish").status_code, 200)
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
        self.assertEqual(self.status(challenge_id, "publish", "admin").status_code, 200)
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
        self.status(challenge_id, "publish")
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
