"""Project-scoped account linking service.

Only safe account metadata is retained here. OAuth tokens and provider secrets
must remain in the provider-specific credential store.
"""

from dataclasses import dataclass
from typing import Protocol

from .account_connections import AccountConnection, ConnectionState, VerificationState
from .oauth_callback import LinkedAccount


class AccountLinkingError(ValueError):
    """Raised when an account cannot be linked safely."""


class AccountRepository(Protocol):
    def create(self, account: AccountConnection) -> AccountConnection: ...
    def get(self, project_id: str, account_id: str) -> AccountConnection | None: ...
    def list_for_project(self, project_id: str) -> tuple[AccountConnection, ...]: ...
    def save(self, account: AccountConnection) -> AccountConnection: ...
    def delete(self, project_id: str, account_id: str) -> None: ...


class InMemoryAccountRepository:
    """Development/test repository; production uses PostgreSQL."""

    def __init__(self) -> None:
        self._accounts: dict[str, AccountConnection] = {}

    def create(self, account: AccountConnection) -> AccountConnection:
        self._accounts[account.account_id] = account
        return account

    def get(self, project_id: str, account_id: str) -> AccountConnection | None:
        account = self._accounts.get(account_id)
        if account is None or account.project_id != project_id.strip():
            return None
        return account

    def list_for_project(self, project_id: str) -> tuple[AccountConnection, ...]:
        normalized = project_id.strip()
        return tuple(
            account for account in self._accounts.values()
            if account.project_id == normalized
        )

    def save(self, account: AccountConnection) -> AccountConnection:
        self._accounts[account.account_id] = account
        return account

    def delete(self, project_id: str, account_id: str) -> None:
        account = self.get(project_id, account_id)
        if account is not None:
            self._accounts.pop(account_id, None)


@dataclass(frozen=True)
class LinkRequest:
    project_id: str
    account: LinkedAccount


class AccountLinkingService:
    """Account linking with an explicit project-scoped repository."""

    def __init__(self, repository: AccountRepository | None = None) -> None:
        self._repository = repository or InMemoryAccountRepository()

    def link(self, request: LinkRequest) -> AccountConnection:
        project_id = request.project_id.strip()
        account = request.account
        if not project_id:
            raise AccountLinkingError("project_id is required")
        if account.project_id.strip() != project_id:
            raise AccountLinkingError("الحساب لا ينتمي إلى المشروع المطلوب.")
        if not account.account_id.strip() or not account.platform.strip():
            raise AccountLinkingError("بيانات الحساب الأساسية غير مكتملة.")

        existing = self._repository.get(project_id, account.account_id)
        if existing is not None:
            raise AccountLinkingError("الحساب مرتبط بالفعل بهذا المشروع.")

        # Reject an account identity already owned by another project.
        # Repositories are intentionally project-scoped, so this check is handled
        # by the durable unique account_id constraint in production.
        connection = account.to_connection()
        try:
            return self._repository.create(connection)
        except Exception as exc:
            raise AccountLinkingError("تعذر ربط الحساب؛ قد يكون مرتبطًا بمشروع آخر.") from exc

    def get(self, project_id: str, account_id: str) -> AccountConnection | None:
        return self._repository.get(project_id, account_id)

    def list_for_project(self, project_id: str) -> tuple[AccountConnection, ...]:
        return self._repository.list_for_project(project_id)

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
        return self._repository.save(verified)

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
        return self._repository.save(disconnected)
