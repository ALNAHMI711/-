"""Framework-neutral OAuth callback validation and account-linking primitives."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping

from .account_connections import AccountConnection, ConnectionState, VerificationState
from .oauth_session import OAuthState, OAuthStateStore


class OAuthCallbackStatus(StrEnum):
    LINKED = "linked"
    AUTHORIZATION_DENIED = "authorization_denied"
    INVALID_REQUEST = "invalid_request"
    INVALID_STATE = "invalid_state"
    PROVIDER_ERROR = "provider_error"


@dataclass(frozen=True)
class OAuthCallbackResult:
    status: OAuthCallbackStatus
    platform: str
    state: OAuthState | None = None
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.status == OAuthCallbackStatus.LINKED


@dataclass(frozen=True)
class LinkedAccount:
    """Safe result of an OAuth callback; token material is intentionally absent."""

    account_id: str
    platform: str
    project_id: str
    display_name: str
    permissions: tuple[str, ...]
    connection_state: ConnectionState = ConnectionState.CONNECTED
    verification_state: VerificationState = VerificationState.NOT_CHECKED

    def to_connection(self) -> AccountConnection:
        return AccountConnection(
            account_id=self.account_id,
            platform=self.platform,
            display_name=self.display_name,
            project_id=self.project_id,
            connection_state=self.connection_state,
            verification_state=self.verification_state,
            permissions=self.permissions,
        )


def handle_oauth_callback(
    *,
    platform: str,
    expected_state: OAuthState,
    received_state: str,
    session_store: OAuthStateStore,
    error: str | None = None,
    error_description: str | None = None,
) -> OAuthCallbackResult:
    """Validate a provider callback before any token exchange or account mutation."""
    normalized_platform = platform.strip().lower()
    if not normalized_platform or expected_state.platform != normalized_platform:
        return OAuthCallbackResult(
            OAuthCallbackStatus.INVALID_REQUEST,
            normalized_platform,
            error="منصة OAuth غير صالحة أو لا تطابق جلسة الربط.",
        )

    if not received_state.strip():
        return OAuthCallbackResult(
            OAuthCallbackStatus.INVALID_STATE,
            normalized_platform,
            error="حالة OAuth مفقودة؛ تم رفض الطلب.",
        )

    if not session_store.consume(expected_state, received_state):
        return OAuthCallbackResult(
            OAuthCallbackStatus.INVALID_STATE,
            normalized_platform,
            error="حالة OAuth غير صالحة أو منتهية أو مستخدمة مسبقًا.",
        )

    if error:
        detail = error_description.strip() if error_description else error.strip()
        return OAuthCallbackResult(
            OAuthCallbackStatus.AUTHORIZATION_DENIED,
            normalized_platform,
            expected_state,
            error=detail or "تم رفض التفويض من المنصة.",
        )

    return OAuthCallbackResult(OAuthCallbackStatus.LINKED, normalized_platform, expected_state)


def parse_callback_params(params: Mapping[str, str]) -> tuple[str, str, str | None, str | None]:
    """Extract callback fields without retaining arbitrary provider parameters."""
    return (
        str(params.get("state", "")),
        str(params.get("code", "")),
        str(params.get("error", "")) or None,
        str(params.get("error_description", "")) or None,
    )
