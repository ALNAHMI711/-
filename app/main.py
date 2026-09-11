"""HTTP application entry point."""

from .config import settings


def create_app() -> dict[str, str]:
    """Return a small framework-neutral health representation for the bootstrap stage."""
    return {"name": settings.app_name, "environment": settings.app_env, "status": "ok"}


app = create_app()
