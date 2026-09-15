from fastapi.testclient import TestClient

from app.auth import InMemorySessionStore, hash_password
from app.http_app import create_http_app
from app.oauth_session import OAuthStateStore
from app.projects import InMemoryProjectRepository, Project, ProjectService


PASSWORD = "correct horse battery staple 2026"


def _client():
    projects = ProjectService(InMemoryProjectRepository())
    projects.create(Project(project_id="p1", owner_id="admin", name="Funny"))
    client = TestClient(
        create_http_app(
            session_store=InMemorySessionStore(),
            admin_password_hash=hash_password(PASSWORD),
            project_service=projects,
            oauth_state_store=OAuthStateStore(),
        )
    )
    assert client.post("/auth/login", json={"password": PASSWORD}).status_code == 200
    return client


def test_platform_catalog_requires_authentication():
    client = TestClient(create_http_app())
    assert client.get("/api/oauth/platforms").status_code == 401


def test_oauth_start_requires_configured_client(monkeypatch):
    monkeypatch.delenv("YOUTUBE_CLIENT_ID", raising=False)
    client = _client()
    response = client.post("/api/oauth/youtube/start", params={"project_id": "p1"})
    assert response.status_code == 503


def test_oauth_start_binds_state_to_project(monkeypatch):
    monkeypatch.setenv("YOUTUBE_CLIENT_ID", "public-client-id")
    client = _client()
    response = client.post("/api/oauth/youtube/start", params={"project_id": "p1"})
    assert response.status_code == 200
    body = response.json()
    assert body["platform"] == "youtube"
    assert body["project_id"] == "p1"
    assert body["state"] in body["authorization_url"]
    assert "client_id=public-client-id" in body["authorization_url"]


def test_oauth_start_rejects_unowned_project(monkeypatch):
    monkeypatch.setenv("YOUTUBE_CLIENT_ID", "public-client-id")
    client = _client()
    assert client.post("/api/oauth/youtube/start", params={"project_id": "missing"}).status_code == 404
