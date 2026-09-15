"""Public application HTTP surface with health and authentication endpoints."""

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel

from .auth import AuthenticationError, InMemorySessionStore, verify_password
from .config import settings


class LoginRequest(BaseModel):
    password: str


def create_http_app(session_store: InMemorySessionStore | None = None) -> FastAPI:
    app = FastAPI(title=settings.app_name, docs_url=None, redoc_url=None)
    sessions = session_store or InMemorySessionStore()
    cookie_secure = settings.app_env.lower() not in {"development", "test"}
    cookie_name = "mashahid_session"

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
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
        status = "ready" if settings.admin_password_hash else "not_configured"
        return {"status": status, "environment": settings.app_env}

    @app.post("/auth/login")
    def login(payload: LoginRequest, response: Response) -> dict[str, str]:
        if not settings.admin_password_hash:
            raise HTTPException(status_code=503, detail="authentication is not configured")
        if not verify_password(payload.password, settings.admin_password_hash):
            raise HTTPException(status_code=401, detail="invalid credentials")
        _, token = sessions.create_with_token("admin", settings.session_ttl_seconds)
        response.set_cookie(
            cookie_name,
            token,
            httponly=True,
            secure=cookie_secure,
            samesite="strict",
            max_age=settings.session_ttl_seconds,
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
        token = request.cookies.get(cookie_name)
        if not token:
            raise HTTPException(status_code=401, detail="authentication required")
        try:
            session = sessions.validate_token(token)
        except (AuthenticationError, ValueError):
            raise HTTPException(status_code=401, detail="authentication required") from None
        return {"user_id": session.user_id, "status": "authenticated"}

    return app


app = create_http_app()
