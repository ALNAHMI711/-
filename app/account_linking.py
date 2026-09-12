"""Project-scoped account linking service.

Only safe account metadata is retained here. OAuth tokens and provider secrets
must remain in the provider-specific credential store.
"""

from dataclasses import dataclass

from .account_connections import AccountConnection, ConnectionState, VerificationState
from .oauth_callback import LinkedAccount


class AccountLinkingError(ValueError):
    """Raised when an account cannot be linked safely."""


@dataclass(frozen=True)
class LinkRequest:
    project_id: str
    account: LinkedAccount


class AccountLinkingService:
    """In-memory domain service enforcing project ownership boundaries."""

    def __init__(self) -> None:
        self._accounts: dict[str, AccountConnection] = {}

    def link(self, request: LinkRequest) -> AccountConnection:
        project_id = request.project_id.strip()
        account = request.account
        if not project_id:
            raise AccountLinkingError("project_id is required")
        if account.project_id.strip() != project_id:
            raise AccountLinkingError("الحساب لا ينتمي إلى المشروع المطلوب.")
        if not account.account_id.strip() or not account.platform.strip():
            raise AccountLinkingError("بيانات الحساب الأساسية غير مكتملة.")
        if account.account_id in self._accounts:
            existing = self._accounts[account.account_id]
            if existing.project_id != project_id:
                raise AccountLinkingError("الحساب مرتبط بمشروع آخر ولا يمكن نقله ضمن هذه العملية.")
            raise AccountLinkingError("الحساب مرتبط بالفعل بهذا المشروع.")

        connection = account.to_connection()
        self._accounts[connection.account_id] = connection
        return connection

    def get(self, project_id: str, account_id: str) -> AccountConnection | None:
        account = self._accounts.get(account_id)
        if account is None or account.project_id != project_id.strip():
            return None
        return account

    def list_for_project(self, project_id: str) -> tuple[AccountConnection, ...]:
        normalized = project_id.strip()
        return tuple(account for account in self._accounts.values() if account.project_id == normalized)

    def mark_verified(self, project_id: str, account_id: str) -> AccountConnection:
        account = self.get(project_id, account_id)
        if account is None:
            raise AccountLinkingError("الحساب غير موجود في هذا المشروع.")
        verified = AccountConnection(
            account_id=account.account_id,
            platform=account.platform,
            display_name=account.display_name,
            project_id=account.project_id,
            connection_state=account.connection_state,
            verification_state=VerificationState.VERIFIED,
            monetization_state=account.monetization_state,
            permissions=account.permissions,
            last_error=account.last_error,
        )
        self._accounts[account_id] = verified
        return verified

    def disconnect(self, project_id: str, account_id: str) -> AccountConnection:
        account = self.get(project_id, account_id)
        if account is None:
            raise AccountLinkingError("الحساب غير موجود في هذا المشروع.")
        disconnected = AccountConnection(
            account_id=account.account_id,
            platform=account.platform,
            display_name=account.display_name,
            project_id=account.project_id,
            connection_state=ConnectionState.DISCONNECTED,
            verification_state=VerificationState.NOT_CHECKED,
            monetization_state=account.monetization_state,
            permissions=account.permissions,
        )
        self._accounts[account_id] = disconnected
        return disconnected
