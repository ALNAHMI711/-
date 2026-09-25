"""Public application HTTP surface with health, authentication, projects, accounts, and OAuth."""

import os

import redis

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel

from .account_api import create_account_router
from .account_linking import AccountLinkingService
from .auth import AuthenticationError, InMemorySessionStore, verify_password
from .config import settings
from .oauth_api import create_oauth_router
from .oauth_callback import OAuthCallbackStatus, complete_oauth_link, parse_callback_params
from .oauth_session import OAuthStateStore
from .redis_oauth_state import RedisOAuthStateStore
from .postgres_accounts import PostgresAccountRepository
from .postgres_projects import PostgresProjectRepository
from .postgres_sessions import PostgresSessionStore
from .platforms import get_platform
from .project_api import create_project_router
from .projects import ProjectService


class LoginRequest(BaseModel):
    password: str


def create_http_app(
    session_store=None,
    admin_password_hash: str | None = None,
    session_ttl_seconds: int | None = None,
    project_service: ProjectService | None = None,
    account_service: AccountLinkingService | None = None,
    oauth_state_store: OAuthStateStore | RedisOAuthStateStore | None = None,
    oauth_exchangers: dict[str, object] | None = None,
    oauth_providers: dict[str, object] | None = None,
    credential_vault=None,
) -> FastAPI:
    app = FastAPI(title=settings.app_name, docs_url=None, redoc_url=None)
    if session_store is not None:
        sessions = session_store
    elif settings.database_url:
        sessions = PostgresSessionStore(settings.database_url)
    else:
        sessions = InMemorySessionStore()

    projects = project_service or ProjectService(
        repository=PostgresProjectRepository(settings.database_url)
        if settings.database_url
        else None
    )

    accounts = account_service or AccountLinkingService(
        repository=PostgresAccountRepository(settings.database_url)
        if settings.database_url
        else None
    )

    if oauth_state_store is not None:
        oauth_states = oauth_state_store
    elif settings.redis_url:
        oauth_states = RedisOAuthStateStore(redis.from_url(settings.redis_url))
    else:
        oauth_states = OAuthStateStore()
    exchangers = oauth_exchangers or {}
    providers = oauth_providers or {}
    configured_password_hash = (
        settings.admin_password_hash if admin_password_hash is None else admin_password_hash
    )
    ttl_seconds = settings.session_ttl_seconds if session_ttl_seconds is None else session_ttl_seconds
    cookie_secure = settings.app_env.lower() not in {"development", "test"}
    cookie_name = "mashahid_session"

    @app.middleware("http")
    async def security_and_session(request: Request, call_next):
        token = request.cookies.get(cookie_name)
        if token:
            try:
                request.state.session = sessions.validate_token(token)
            except (AuthenticationError, ValueError):
                request.state.session = None
        else:
            request.state.session = None
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> dict[str, str]:
        status = "ready" if configured_password_hash else "not_configured"
        return {"status": status, "environment": settings.app_env}

    @app.post("/auth/login")
    def login(payload: LoginRequest, response: Response) -> dict[str, str]:
        if not configured_password_hash:
            raise HTTPException(status_code=503, detail="authentication is not configured")
        if not verify_password(payload.password, configured_password_hash):
            raise HTTPException(status_code=401, detail="invalid credentials")
        _, token = sessions.create_with_token("admin", ttl_seconds)
        response.set_cookie(
            cookie_name,
            token,
            httponly=True,
            secure=cookie_secure,
            samesite="strict",
            max_age=ttl_seconds,
            path="/",
        )
        return {"status": "authenticated"}

    @app.post("/auth/logout")
    def logout(request: Request, response: Response) -> dict[str, str]:
        token = request.cookies.get(cookie_name)
        if token:
            sessions.revoke_token(token)
        response.delete_cookie(cookie_name, path="/")
        return {"status": "logged_out"}

    @app.get("/auth/me")
    def me(request: Request) -> dict[str, str]:
        session = getattr(request.state, "session", None)
        if session is None:
            raise HTTPException(status_code=401, detail="authentication required")
        return {"user_id": session.user_id, "status": "authenticated"}

    @app.get("/oauth/callback/{platform}")
    def oauth_callback(platform: str, request: Request):
        state_value, code, error, error_description = parse_callback_params(request.query_params)
        expected_state = oauth_states.get(state_value)
        if expected_state is None:
            raise HTTPException(status_code=400, detail="invalid or expired OAuth state")
        exchanger = exchangers.get(expected_state.platform)
        provider = providers.get(expected_state.platform)
        if exchanger is None or provider is None or credential_vault is None:
            raise HTTPException(status_code=503, detail="OAuth provider is not configured")
        redirect_uri = (
            f"{os.getenv('APP_URL', 'http://localhost:8000').rstrip('/')}"
            f"/oauth/callback/{expected_state.platform}"
        )
        completion = complete_oauth_link(
            platform=platform,
            expected_state=expected_state,
            received_state=state_value,
            code=code,
            redirect_uri=redirect_uri,
            state_store=oauth_states,
            exchanger=exchanger,
            provider=provider,
            vault=credential_vault,
            account_service=accounts,
            required_permissions=get_platform(expected_state.platform).required_scopes,
            error=error,
            error_description=error_description,
        )
        result = completion.result
        if result.status == OAuthCallbackStatus.LINKED:
            account = result.account
            return {
                "status": result.status.value,
                "platform": result.platform,
                "project_id": expected_state.project_id,
                "account_id": account.account_id if account else "",
                "credential_id": result.credential.credential_id if result.credential else "",
            }
        status_code = 400 if result.status != OAuthCallbackStatus.PROVIDER_ERROR else 502
        raise HTTPException(status_code=status_code, detail=result.error or result.status.value)

    app.include_router(create_project_router(projects))
    app.include_router(create_account_router(accounts, projects))
    app.include_router(create_oauth_router(projects, oauth_states))
    return app


app = create_http_app()
