from fastapi.testclient import TestClient
from app.main import app
from app import main
from app.db import engine
import pytest

client = TestClient(app)

def test_live():
    assert client.get("/api/health/live").json() == {"status": "ok"}

def test_ready_failure(monkeypatch):
    monkeypatch.setattr(main, "check_database", lambda *a: (_ for _ in ()).throw(RuntimeError("secret")))
    response = client.get("/api/health/ready")
    assert response.status_code == 503
    assert "secret" not in response.text

def test_ready_success(monkeypatch):
    monkeypatch.setattr(main, "check_database", lambda *a: None)
    monkeypatch.setenv("REDIS_URL", "redis://localhost/0")
    monkeypatch.setattr(main.Redis, "from_url", lambda *a, **k: type("R", (), {"ping": lambda s: True})())
    monkeypatch.setattr(main.celery.control, "ping", lambda **k: [{"worker": "pong"}])
    assert client.get("/api/health/ready").status_code == 200

def test_migration_rejects_reference(monkeypatch):
    engine.cache_clear()
    monkeypatch.setenv("APP_DATABASE_URL", "mysql+pymysql://u:p@localhost/pinfo_db")
    with pytest.raises(ValueError):
        engine()
