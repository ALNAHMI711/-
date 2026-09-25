from fastapi.testclient import TestClient

from app.account_linking import AccountLinkingService
from app.auth import InMemorySessionStore, hash_password
from app.http_app import create_http_app
from app.projects import InMemoryProjectRepository, ProjectService


def _client():
    projects = ProjectService(InMemoryProjectRepository())
    projects.create(__import__("app.projects", fromlist=["Project"]).Project(
        project_id="p1", owner_id="admin", name="Funny"
    ))
    projects.create(__import__("app.projects", fromlist=["Project"]).Project(
        project_id="other", owner_id="other-user", name="Other"
    ))
    client = TestClient(create_http_app(
        session_store=InMemorySessionStore(),
        admin_password_hash=hash_password("correct horse battery staple 2026"),
        project_service=projects,
        account_service=AccountLinkingService(),
    ))
    assert client.post("/auth/login", json={"password": "correct horse battery staple 2026"}).status_code == 200
    return client


def test_accounts_are_project_scoped_and_authenticated():
    client = _client()
    assert client.get("/api/projects/p1/accounts").json() == []
    response = client.post("/api/projects/p1/accounts", json={
        "account_id": "yt-1",
        "platform": "youtube",
        "display_name": "Funny Channel",
        "permissions": ["youtube.upload"],
    })
    assert response.status_code == 201
    assert response.json()["connection_state"] == "pending"
    assert client.get("/api/projects/p1/accounts/yt-1").status_code == 200
    assert client.get("/api/projects/other/accounts").status_code == 404


def test_account_endpoints_require_authentication():
    projects = ProjectService(InMemoryProjectRepository())
    from app.projects import Project
    projects.create(Project(project_id="p1", owner_id="admin", name="Funny"))
    client = TestClient(create_http_app(project_service=projects))
    assert client.get("/api/projects/p1/accounts").status_code == 401


def test_account_disconnect():
    client = _client()
    created = client.post("/api/projects/p1/accounts", json={
        "account_id": "ig-1", "platform": "instagram", "display_name": "Page"
    })
    assert created.status_code == 201
    assert client.delete("/api/projects/p1/accounts/ig-1").status_code == 204
    assert client.get("/api/projects/p1/accounts/ig-1").status_code == 200
    assert client.get("/api/projects/p1/accounts/ig-1").json()["connection_state"] == "disconnected"


def test_account_readiness_exposes_safe_platform_and_monetization_metadata():
    client = _client()
    created = client.post("/api/projects/p1/accounts", json={
        "account_id": "yt-1",
        "platform": "youtube",
        "display_name": "Funny Channel",
        "permissions": ["https://www.googleapis.com/auth/youtube.upload"],
    })
    assert created.status_code == 201
    readiness = client.get("/api/projects/p1/accounts/yt-1/readiness")
    assert readiness.status_code == 200
    body = readiness.json()
    assert body["platform"] == "youtube"
    assert body["connection_state"] == "pending"
    assert body["ready_to_publish"] is False
    assert body["monetization_status_supported"] is False
    assert body["monetization_url"].startswith("https://")
    assert "access_token" not in readiness.text
