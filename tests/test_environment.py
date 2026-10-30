import importlib

import mongomock
import pytest

from app.extensions import mongo


@pytest.mark.parametrize("host_override", [False, True])
def test_backend_environment_is_independent_of_the_working_directory(
    tmp_path, monkeypatch, host_override
):
    app_module = importlib.import_module("app")
    backend = tmp_path / "backend"
    frontend = tmp_path / "frontend"
    (backend / "app").mkdir(parents=True)
    frontend.mkdir()
    (backend / ".env").write_text(
        "MONGO_URI=mongodb://localhost:27017/backend_test\n"
        "JWT_SECRET_KEY=backend-test-secret-at-least-32-characters\n"
        "JUDGE0_URL=https://backend-runner.example.test\n",
        encoding="utf-8",
    )
    (frontend / ".env").write_text(
        "MONGO_URI=mongodb://localhost:27017/wrong_database\n"
        "JWT_SECRET_KEY=wrong-test-secret\n"
        "JUDGE0_URL=https://wrong-runner.example.test\n",
        encoding="utf-8",
    )
    for key in ("MONGO_URI", "JWT_SECRET_KEY", "JUDGE0_URL"):
        monkeypatch.delenv(key, raising=False)
    if host_override:
        monkeypatch.setenv("JUDGE0_URL", "https://host-runner.example.test")
    monkeypatch.setattr(app_module, "__file__", str(backend / "app" / "__init__.py"))
    monkeypatch.chdir(frontend)
    database = mongomock.MongoClient(tz_aware=True).backend_test

    def fake_init(app):
        mongo.db = database

    monkeypatch.setattr(mongo, "init_app", fake_init)
    app = app_module.create_app({"TESTING": True})

    assert app.config["MONGO_URI"] == "mongodb://localhost:27017/backend_test"
    assert app.config["JWT_SECRET_KEY"] == "backend-test-secret-at-least-32-characters"
    expected_runner = (
        "https://host-runner.example.test"
        if host_override
        else "https://backend-runner.example.test"
    )
    assert app.config["JUDGE0_URL"] == expected_runner
