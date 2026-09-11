"""Minimal configuration loaded from environment variables."""

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Mashahid")
    app_env: str = os.getenv("APP_ENV", "development")


settings = Settings()
