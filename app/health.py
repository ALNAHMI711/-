"""Application health contract."""

from .config import settings


def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}
