from fastapi.testclient import TestClient

from app.auth import InMemorySessionStore, hash_password
from app.http_app import create_http_app
from app.projects import ProjectService


def _client():
    sessions = InMemorySessionStore()
    service = ProjectService()
    client = TestClient(create_http_app(
        session_store=sessions,
        admin_password_hash=hash_password("correct horse battery staple 2026"),
        project_service=service,
    ))
    return client


def test_project_api_requires_authentication():
    client = _client()
    assert client.get("/api/projects").status_code == 401
    assert client.post("/api/projects", json={"project_id": "p1", "name": "Funny"}).status_code == 401


def test_authenticated_project_crud_and_owner_isolation():
    client = _client()
    assert client.post("/auth/login", json={"password": "correct horse battery staple 2026"}).status_code == 200

    created = client.post("/api/projects", json={
        "project_id": "funny",
        "name": "مضحك",
        "language": "ar",
        "topics": ["comedy"],
        "content_rules": ["stay on niche"],
    })
    assert created.status_code == 201
    assert created.json()["owner_id"] == "admin"

    assert client.get("/api/projects").json()[0]["project_id"] == "funny"
    assert client.get("/api/projects/funny").status_code == 200

    updated = client.put("/api/projects/funny", json={
        "project_id": "funny",
        "name": "مضحك 2",
        "language": "ar",
        "automation_enabled": True,
    })
    assert updated.status_code == 200
    assert updated.json()["automation_enabled"] is True

    assert client.delete("/api/projects/funny").status_code == 204
    assert client.get("/api/projects/funny").status_code == 404


def test_project_path_id_cannot_be_swapped():
    client = _client()
    client.post("/auth/login", json={"password": "correct horse battery staple 2026"})
    response = client.put("/api/projects/p1", json={"project_id": "p2", "name": "bad"})
    assert response.status_code == 400
