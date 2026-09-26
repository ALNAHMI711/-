from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.account_linking import AccountLinkingService
from app.account_provider import ProviderAccount, ProviderVerification
from app.auth import InMemorySessionStore, hash_password
from app.credential_vault import InMemoryCredentialVault
from app.http_app import create_http_app
from app.oauth_session import OAuthStateStore
from app.oauth_token_exchange import OAuthTokenBundle
from app.projects import InMemoryProjectRepository, Project, ProjectService


PASSWORD = "correct horse battery staple 2026"


class FakeExchanger:
    def exchange_code(self, code: str, redirect_uri: str):
        assert code == "authorization-code"
        assert redirect_uri.endswith("/oauth/callback/youtube")
        return OAuthTokenBundle(
            access_token="access-secret",
            token_type="Bearer",
            refresh_token="refresh-secret",
            expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
            scope=("https://www.googleapis.com/auth/youtube.upload",),
        )


class FakeProvider:
    def get_account(self, access_token: str):
        assert access_token == "access-secret"
        return ProviderAccount(account_id="yt-1", display_name="My Channel")

    def verify_permissions(self, access_token: str, required_permissions: tuple[str, ...]):
        assert access_token == "access-secret"
        return ProviderVerification(verified=True, permissions=("youtube.upload",))


def _client():
    projects = ProjectService(InMemoryProjectRepository())
    projects.create(Project(project_id="p1", owner_id="admin", name="Funny"))
    states = OAuthStateStore()
    client = TestClient(
        create_http_app(
            session_store=InMemorySessionStore(),
            admin_password_hash=hash_password(PASSWORD),
            project_service=projects,
            account_service=AccountLinkingService(),
            oauth_state_store=states,
            oauth_exchangers={"youtube": FakeExchanger()},
            oauth_providers={"youtube": FakeProvider()},
            credential_vault=InMemoryCredentialVault(),
        )
    )
    assert client.post("/auth/login", json={"password": PASSWORD}).status_code == 200
    return client


def test_oauth_callback_exchanges_code_verifies_and_links():
    client = _client()
    start = client.post("/api/oauth/youtube/start", params={"project_id": "p1"}, headers={})
    assert start.status_code == 503

    # Supply the public client ID only after the app has been constructed.
    import os
    os.environ["YOUTUBE_CLIENT_ID"] = "public-client-id"
    try:
        start = client.post("/api/oauth/youtube/start", params={"project_id": "p1"})
        assert start.status_code == 200
        state = start.json()["state"]

        callback = client.get(
            f"/oauth/callback/youtube?state={state}&code=authorization-code",
        )
        assert callback.status_code == 200
        body = callback.json()
        assert body["status"] == "linked"
        assert body["account_id"] == "yt-1"
        assert body["credential_id"].startswith("cred_")

        replay = client.get(
            f"/oauth/callback/youtube?state={state}&code=authorization-code",
        )
        assert replay.status_code == 400
    finally:
        os.environ.pop("YOUTUBE_CLIENT_ID", None)


def test_oauth_callback_never_accepts_wrong_platform():
    client = _client()
    import os
    os.environ["YOUTUBE_CLIENT_ID"] = "public-client-id"
    try:
        start = client.post("/api/oauth/youtube/start", params={"project_id": "p1"})
        state = start.json()["state"]
        response = client.get(f"/oauth/callback/tiktok?state={state}&code=authorization-code")
        assert response.status_code == 400
    finally:
        os.environ.pop("YOUTUBE_CLIENT_ID", None)


class MultiChannelProvider(FakeProvider):
    def list_accounts(self, access_token: str):
        assert access_token == "access-secret"
        return (
            ProviderAccount(account_id="yt-1", display_name="Channel One"),
            ProviderAccount(account_id="yt-2", display_name="Channel Two"),
        )


def test_oauth_callback_requires_channel_selection_for_multiple_channels():
    import os
    from app.pending_account_selection import PendingAccountSelectionStore

    projects = ProjectService(InMemoryProjectRepository())
    projects.create(Project(project_id="p1", owner_id="admin", name="Funny"))
    states = OAuthStateStore()
    client = TestClient(create_http_app(
        session_store=InMemorySessionStore(),
        admin_password_hash=hash_password(PASSWORD),
        project_service=projects,
        account_service=AccountLinkingService(),
        oauth_state_store=states,
        oauth_exchangers={"youtube": FakeExchanger()},
        oauth_providers={"youtube": MultiChannelProvider()},
        credential_vault=InMemoryCredentialVault(),
        pending_selection_store=PendingAccountSelectionStore(),
    ))
    assert client.post("/auth/login", json={"password": PASSWORD}).status_code == 200
    os.environ["YOUTUBE_CLIENT_ID"] = "public-client-id"
    try:
        start = client.post("/api/oauth/youtube/start", params={"project_id": "p1"})
        state = start.json()["state"]
        callback = client.get(f"/oauth/callback/youtube?state={state}&code=authorization-code")
        assert callback.status_code == 200
        body = callback.json()
        assert body["status"] == "selection_required"
        assert [a["account_id"] for a in body["accounts"]] == ["yt-1", "yt-2"]

        selected = client.post("/api/oauth/select-account", json={
            "selection_token": body["selection_token"],
            "account_id": "yt-2",
            "project_id": "p1",
        })
        assert selected.status_code == 200
        assert selected.json()["account_id"] == "yt-2"

        replay = client.post("/api/oauth/select-account", json={
            "selection_token": body["selection_token"],
            "account_id": "yt-1",
            "project_id": "p1",
        })
        assert replay.status_code == 400
    finally:
        os.environ.pop("YOUTUBE_CLIENT_ID", None)
