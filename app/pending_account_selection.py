"""Short-lived server-side pending OAuth account selections."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe

from .account_provider import ProviderAccount
from .credential_vault import CredentialRef


@dataclass(frozen=True)
class PendingAccountSelection:
    selection_token: str
    user_id: str
    project_id: str
    platform: str
    credential: CredentialRef
    accounts: tuple[ProviderAccount, ...]
    expires_at: datetime


class PendingAccountSelectionStore:
    """Development store; production should use Redis/PostgreSQL with TTL."""

    def __init__(self, ttl_seconds: int = 600) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self.ttl = timedelta(seconds=ttl_seconds)
        self._items: dict[str, PendingAccountSelection] = {}

    def create(self, *, user_id: str, project_id: str, platform: str,
               credential: CredentialRef, accounts: tuple[ProviderAccount, ...],
               now: datetime | None = None) -> PendingAccountSelection:
        current = now or datetime.now(timezone.utc)
        token = token_urlsafe(32)
        item = PendingAccountSelection(
            selection_token=token, user_id=user_id, project_id=project_id,
            platform=platform, credential=credential, accounts=accounts,
            expires_at=current + self.ttl,
        )
        self._items[token] = item
        return item

    def consume(self, selection_token: str, *, user_id: str, project_id: str,
                account_id: str, now: datetime | None = None) -> PendingAccountSelection:
        item = self._items.pop(selection_token, None)
        if item is None:
            raise ValueError("selection token is invalid or expired")
        current = now or datetime.now(timezone.utc)
        if item.expires_at <= current:
            raise ValueError("selection token is expired")
        if item.user_id != user_id or item.project_id != project_id:
            raise ValueError("selection token does not belong to this user/project")
        if account_id not in {account.account_id for account in item.accounts}:
            raise ValueError("selected account was not offered by the provider")
        return item
