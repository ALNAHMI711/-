"""Framework-neutral OAuth callback validation and account-linking primitives."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping, Protocol, TYPE_CHECKING

from .account_connections import AccountConnection, ConnectionState, VerificationState
from .account_provider import AccountProvider, ProviderAPIError, ProviderAccount
from .credential_vault import CredentialRef, CredentialVault
from .oauth_session import OAuthState, OAuthStateStore

if TYPE_CHECKING:
    from .account_linking import AccountLinkingService


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
    account: AccountConnection | None = None
    credential: CredentialRef | None = None

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
    now: float | None = None,
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
    if not session_store.consume(expected_state, received_state, now=now):
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


class OAuthCodeExchanger(Protocol):
    """Provider-specific server-side authorization-code exchange."""

    def exchange_code(self, code: str, redirect_uri: str): ...


@dataclass(frozen=True)
class OAuthCompletion:
    result: OAuthCallbackResult
    provider_account: ProviderAccount | None = None


def complete_oauth_link(
    *,
    platform: str,
    expected_state: OAuthState,
    received_state: str,
    code: str,
    redirect_uri: str,
    state_store: OAuthStateStore,
    exchanger: OAuthCodeExchanger,
    provider: AccountProvider,
    vault: CredentialVault,
    account_service: "AccountLinkingService",
    required_permissions: tuple[str, ...] = (),
    error: str | None = None,
    error_description: str | None = None,
    now: float | None = None,
) -> OAuthCompletion:
    """Run the complete server-side callback pipeline without exposing tokens."""
    from .account_linking import AccountLinkingError, LinkRequest

    validation = handle_oauth_callback(
        platform=platform,
        expected_state=expected_state,
        received_state=received_state,
        session_store=state_store,
        error=error,
        error_description=error_description,
        now=now,
    )
    if not validation.success:
        return OAuthCompletion(validation)
    if not code.strip() or not redirect_uri.strip():
        return OAuthCompletion(OAuthCallbackResult(
            OAuthCallbackStatus.INVALID_REQUEST,
            validation.platform,
            expected_state,
            error="authorization code and redirect_uri are required",
        ))
    try:
        token_set = exchanger.exchange_code(code.strip(), redirect_uri.strip())
        access_token = str(token_set.access_token)
        provider_account = provider.get_account(access_token)
        verification = provider.verify_permissions(access_token, required_permissions)
        granted_scopes = tuple(sorted(set(token_set.scope)))
        if granted_scopes and not set(required_permissions).issubset(granted_scopes):
            missing = tuple(sorted(set(required_permissions) - set(granted_scopes)))
            return OAuthCompletion(OAuthCallbackResult(
                OAuthCallbackStatus.PROVIDER_ERROR,
                validation.platform,
                expected_state,
                error="required permissions are missing: " + ", ".join(missing),
            ), provider_account)
        if not verification.verified:
            return OAuthCompletion(OAuthCallbackResult(
                OAuthCallbackStatus.PROVIDER_ERROR,
                validation.platform,
                expected_state,
                error="required permissions are missing",
            ), provider_account)
        credential = vault.put(
            platform=validation.platform,
            account_id=provider_account.account_id,
            access_token=access_token,
            refresh_token=token_set.refresh_token,
            scopes=granted_scopes or verification.permissions,
            expires_at=token_set.expires_at,
        )
        linked = LinkedAccount(
            account_id=provider_account.account_id,
            platform=validation.platform,
            project_id=expected_state.project_id,
            display_name=provider_account.display_name,
            permissions=granted_scopes or verification.permissions,
            connection_state=ConnectionState.CONNECTED,
            verification_state=VerificationState.VERIFIED,
        )
        account = account_service.link(LinkRequest(project_id=expected_state.project_id, account=linked))
        return OAuthCompletion(OAuthCallbackResult(
            OAuthCallbackStatus.LINKED,
            validation.platform,
            expected_state,
            account=account,
            credential=credential,
        ), provider_account)
    except (ProviderAPIError, AccountLinkingError, ValueError, RuntimeError) as exc:
        return OAuthCompletion(OAuthCallbackResult(
            OAuthCallbackStatus.PROVIDER_ERROR,
            validation.platform,
            expected_state,
            error=str(exc) or "provider integration failed",
        ))
