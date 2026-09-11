"""Account connection, verification, and monetization-readiness domain logic.

This module intentionally does not store platform passwords or secrets. OAuth/token
exchange is performed by platform adapters in a later integration layer.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping


class ConnectionState(StrEnum):
    DISCONNECTED = "disconnected"
    PENDING = "pending"
    CONNECTED = "connected"
    EXPIRED = "expired"
    ERROR = "error"


class VerificationState(StrEnum):
    NOT_CHECKED = "not_checked"
    VERIFIED = "verified"
    ACTION_REQUIRED = "action_required"
    FAILED = "failed"


class MonetizationState(StrEnum):
    UNKNOWN = "unknown"
    ELIGIBLE = "eligible"
    ENABLED = "enabled"
    ACTION_REQUIRED = "action_required"
    NOT_ELIGIBLE = "not_eligible"
    NOT_SUPPORTED = "not_supported"


@dataclass(frozen=True)
class AccountConnection:
    """Safe account metadata; no passwords, client secrets, or raw tokens."""

    account_id: str
    platform: str
    display_name: str
    project_id: str
    connection_state: ConnectionState = ConnectionState.DISCONNECTED
    verification_state: VerificationState = VerificationState.NOT_CHECKED
    monetization_state: MonetizationState = MonetizationState.UNKNOWN
    permissions: tuple[str, ...] = field(default_factory=tuple)
    last_error: str | None = None

    @property
    def ready_to_publish(self) -> bool:
        return (
            self.connection_state == ConnectionState.CONNECTED
            and self.verification_state == VerificationState.VERIFIED
        )

    @property
    def needs_user_action(self) -> bool:
        return (
            self.connection_state in {ConnectionState.PENDING, ConnectionState.EXPIRED}
            or self.verification_state == VerificationState.ACTION_REQUIRED
            or self.monetization_state == MonetizationState.ACTION_REQUIRED
        )


@dataclass(frozen=True)
class VerificationResult:
    state: VerificationState
    message: str
    missing_permissions: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class MonetizationResult:
    state: MonetizationState
    message: str
    actions: tuple[str, ...] = field(default_factory=tuple)


def verify_connection(
    account: AccountConnection,
    required_permissions: tuple[str, ...] = (),
) -> VerificationResult:
    """Validate connection state and required permissions without contacting a platform."""
    if account.connection_state != ConnectionState.CONNECTED:
        return VerificationResult(
            VerificationState.ACTION_REQUIRED,
            "الاتصال غير مكتمل؛ يجب إكمال OAuth من المنصة الرسمية.",
        )

    granted = set(account.permissions)
    missing = tuple(permission for permission in required_permissions if permission not in granted)
    if missing:
        return VerificationResult(
            VerificationState.ACTION_REQUIRED,
            "صلاحيات مطلوبة غير ممنوحة.",
            missing,
        )

    return VerificationResult(VerificationState.VERIFIED, "الاتصال والصلاحيات الأساسية جاهزة.")


def monetization_readiness(
    platform: str,
    status_payload: Mapping[str, object] | None,
) -> MonetizationResult:
    """Normalize official monetization information when an adapter provides it.

    The platform adapter is authoritative. If no official status is available, the
    system explicitly reports that it cannot verify monetization instead of guessing.
    """
    if not status_payload or "status" not in status_payload:
        return MonetizationResult(
            MonetizationState.UNKNOWN,
            f"لا تتوفر حالة تحقيق أرباح رسمية قابلة للتحقق آليًا لمنصة {platform}.",
            ("افتح صفحة تحقيق الأرباح الرسمية واتبع المتطلبات المعروضة هناك.",),
        )

    raw_status = str(status_payload["status"]).lower()
    mapping = {
        "eligible": MonetizationState.ELIGIBLE,
        "enabled": MonetizationState.ENABLED,
        "action_required": MonetizationState.ACTION_REQUIRED,
        "not_eligible": MonetizationState.NOT_ELIGIBLE,
        "not_supported": MonetizationState.NOT_SUPPORTED,
    }
    state = mapping.get(raw_status, MonetizationState.UNKNOWN)
    message = str(status_payload.get("message", "تم استلام حالة تحقيق الأرباح من موصل المنصة الرسمي."))
    actions = tuple(str(item) for item in status_payload.get("actions", ()) or ())
    return MonetizationResult(state, message, actions)
