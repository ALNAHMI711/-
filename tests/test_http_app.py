from fastapi.testclient import TestClient

from app.http_app import app


def test_health_endpoint():
    response = TestClient(app).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_endpoint():
    response = TestClient(app).get("/readyz")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
