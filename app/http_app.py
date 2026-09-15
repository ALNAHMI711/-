"""Public application HTTP surface with liveness and readiness checks."""

from fastapi import FastAPI

from .config import settings


def create_http_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, docs_url=None, redoc_url=None)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> dict[str, str]:
        # Database/worker dependency probes will be added when those services
        # become runtime dependencies. Keep readiness conservative and explicit.
        return {"status": "ready", "environment": settings.app_env}

    return app


app = create_http_app()
