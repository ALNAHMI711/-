"""Public application HTTP surface with health, authentication, and projects."""

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel

from .auth import AuthenticationError, InMemorySessionStore, verify_password
from .config import settings
from .postgres_projects import PostgresProjectRepository
from .postgres_sessions import PostgresSessionStore
from .project_api import create_project_router
from .projects import ProjectService


class LoginRequest(BaseModel):
    password: str


def create_http_app(
    session_store=None,
    admin_password_hash: str | None = None,
    session_ttl_seconds: int | None = None,
    project_service: ProjectService | None = None,
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
    configured_password_hash = settings.admin_password_hash if admin_password_hash is None else admin_password_hash
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
        response.set_cookie(cookie_name, token, httponly=True, secure=cookie_secure,
                            samesite="strict", max_age=ttl_seconds, path="/")
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

    app.include_router(create_project_router(projects))
    return app


app = create_http_app()
