"""Provider-facing account identity and permission verification primitives."""

from dataclasses import dataclass
from typing import Protocol


class ProviderAPIError(RuntimeError):
    """Raised when a provider cannot return authoritative account metadata."""


@dataclass(frozen=True)
class ProviderAccount:
    """Safe provider identity; credentials are never part of this value."""

    account_id: str
    display_name: str
    permissions: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderVerification:
    """Authoritative permission check returned by a provider adapter."""

    verified: bool
    permissions: tuple[str, ...]
    missing_permissions: tuple[str, ...] = ()
    detail: str = ""


class AccountProvider(Protocol):
    """Minimal interface implemented by each official platform adapter."""

    def get_account(self, access_token: str) -> ProviderAccount: ...

    def verify_permissions(
        self, access_token: str, required_permissions: tuple[str, ...]
    ) -> ProviderVerification: ...


def verify_required_permissions(
    granted: tuple[str, ...], required: tuple[str, ...]
) -> ProviderVerification:
    """Compare normalized permission names without exposing credentials."""
    granted_set = {value.strip() for value in granted if value.strip()}
    required_set = {value.strip() for value in required if value.strip()}
    missing = tuple(sorted(required_set - granted_set))
    return ProviderVerification(
        verified=not missing,
        permissions=tuple(sorted(granted_set)),
        missing_permissions=missing,
        detail="all required permissions granted" if not missing else "required permissions are missing",
    )
