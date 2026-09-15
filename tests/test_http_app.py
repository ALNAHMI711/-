from fastapi.testclient import TestClient

from app.auth import InMemorySessionStore, hash_password
from app.http_app import create_http_app


def test_health_and_readiness():
    client = TestClient(create_http_app())
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json()["status"] == "not_configured"


def test_login_me_and_logout():
    password_hash = hash_password("correct horse battery staple 2026")
    client = TestClient(
        create_http_app(
            session_store=InMemorySessionStore(),
            admin_password_hash=password_hash,
            session_ttl_seconds=60,
        )
    )

    assert client.get("/auth/me").status_code == 401
    assert client.post("/auth/login", json={"password": "wrong password"}).status_code == 401

    login = client.post("/auth/login", json={"password": "correct horse battery staple 2026"})
    assert login.status_code == 200
    assert "mashahid_session=" in login.headers["set-cookie"]
    assert "HttpOnly" in login.headers["set-cookie"]
    assert "SameSite=strict" in login.headers["set-cookie"]

    assert client.get("/auth/me").json() == {"user_id": "admin", "status": "authenticated"}
    assert client.post("/auth/logout").json() == {"status": "logged_out"}
    assert client.get("/auth/me").status_code == 401


def test_login_is_unavailable_until_password_is_configured():
    client = TestClient(create_http_app())
    response = client.post("/auth/login", json={"password": "anything"})
    assert response.status_code == 503
