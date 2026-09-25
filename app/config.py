"""Application configuration loaded from environment variables."""

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Mashahid")
    app_env: str = os.getenv("APP_ENV", "development")
    admin_password_hash: str = os.getenv("ADMIN_PASSWORD_HASH", "")
    session_ttl_seconds: int = int(os.getenv("SESSION_TTL_SECONDS", "3600"))
    database_url: str = os.getenv("DATABASE_URL", "")
    redis_url: str = os.getenv("REDIS_URL", "")


settings = Settings()
