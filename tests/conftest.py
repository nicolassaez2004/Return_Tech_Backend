import base64
import uuid
from datetime import timedelta

import mongomock
import pytest
from flask_jwt_extended import create_access_token

from app import create_app
from app.extensions import mongo
from app.utils import now


class FakeJudge0:
    """Deterministic provider double. It never executes candidate programs."""
    configured = True

    def __init__(self):
        self.statuses = None
        self.pending = False
        self.fail_create = False
        self.fail_read = False
        self.created = []
        self.rows = {}

    def create_batch(self, language, source, tests, limits):
        from app.services.judge0 import Judge0Error
        if self.fail_create:
            raise Judge0Error("Executor indisponível.", 503)
        self.created.append({"language": language, "source": source, "tests": tests, "limits": limits})
        statuses = self.statuses or [3] * len(tests)
        tokens = []
        for index, case in enumerate(tests):
            token = str(uuid.uuid4())
            tokens.append(token)
            self.rows[token] = {"token": token, "status": {"id": statuses[index]},
                "stdout": base64.b64encode(b"PRIVATE-OUTPUT").decode(),
                "stderr": base64.b64encode(b"PRIVATE-STDERR").decode(), "compile_output": None}
        return tokens

    def get_batch(self, tokens, include_output=False):
        from app.services.judge0 import Judge0Error
        if self.fail_read:
            raise Judge0Error("Executor temporariamente indisponível.", 503)
        if self.pending:
            return [{"token": token, "status": {"id": 2}} for token in tokens]
        return [self.rows[token] for token in tokens]


@pytest.fixture
def app(monkeypatch):
    db = mongomock.MongoClient(tz_aware=True).return_tech_test
    def fake_init(instance):
        mongo.db = db
    monkeypatch.setattr(mongo, "init_app", fake_init)
    instance = create_app({"TESTING": True, "JWT_SECRET_KEY": "test-key-with-at-least-thirty-two-characters", "JUDGE0_URL": ""})
    instance.extensions["judge0_client"] = FakeJudge0()
    return instance


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def identities(app):
    output = {}
    for key, role in [("owner", "company"), ("other_company", "company"), ("talent", "talent"), ("other_talent", "talent")]:
        oid = mongo.db.users.insert_one({"name": key, "email": f"{key}@example.test", "role": role, "organization_name": key}).inserted_id
        with app.app_context():
            token = create_access_token(identity=str(oid))
        output[key] = {"id": oid, "headers": {"Authorization": f"Bearer {token}"}}
    return output


@pytest.fixture
def assessment(client, identities):
    result = client.post("/api/coding/demo", headers=identities["owner"]["headers"])
    assert result.status_code == 201
    challenge_id = result.json["challenge"]["_id"]
    from bson import ObjectId
    mongo.db.challenges.update_one({"_id": ObjectId(challenge_id)}, {"$set": {"status": "published"}})
    for key in ["talent", "other_talent"]:
        mongo.db.participations.insert_one({"challenge_id": ObjectId(challenge_id), "talent_id": identities[key]["id"], "status": "joined", "created_at": now()})
    return challenge_id


def unlock():
    mongo.db.participations.update_many({}, {"$set": {"coding_next_submit_at": now() - timedelta(seconds=5)}})
    mongo.db.coding_jobs.update_many({}, {"$set": {"refresh_after": now() - timedelta(seconds=5)}})
