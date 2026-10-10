"""Application configuration loaded from environment variables."""

from dataclasses import dataclass
import base64
import os

from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Mashahid")
    app_env: str = os.getenv("APP_ENV", "development")
    admin_password_hash: str = os.getenv("ADMIN_PASSWORD_HASH", "")
    session_ttl_seconds: int = int(os.getenv("SESSION_TTL_SECONDS", "3600"))
    database_url: str = os.getenv("DATABASE_URL", "")
    redis_url: str = os.getenv("REDIS_URL", "")
    credential_vault_master_key: str = os.getenv("CREDENTIAL_VAULT_MASTER_KEY", "")

    def youtube_upload_session_key(self) -> bytes | None:
        """Derive a separate 32-byte key for resumable upload session URLs."""
        raw = self.credential_vault_master_key.strip()
        if not raw:
            return None
        try:
            material = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        except Exception:
            material = raw.encode()
        if len(material) < 32:
            raise ValueError("CREDENTIAL_VAULT_MASTER_KEY must provide at least 32 bytes")
        return HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=b"mashahid/youtube-upload-session/v1",
        ).derive(material)


settings = Settings()
