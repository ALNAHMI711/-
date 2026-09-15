"""Authenticated account connection API.

This API exposes safe connection metadata only. Provider passwords and raw OAuth
credentials never enter the HTTP/domain model; token exchange belongs to a
provider adapter and credential vault integration.
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .account_connections import (
    AccountConnection,
    ConnectionState,
    MonetizationState,
    VerificationState,
)
from .account_linking import AccountLinkingError, AccountLinkingService, LinkRequest
from .oauth_callback import LinkedAccount


class AccountPayload(BaseModel):
    account_id: str = Field(min_length=1, max_length=200)
    platform: str = Field(min_length=1, max_length=64)
    display_name: str = Field(default="", max_length=300)
    connection_state: ConnectionState = ConnectionState.PENDING
    verification_state: VerificationState = VerificationState.NOT_CHECKED
    monetization_state: MonetizationState = MonetizationState.UNKNOWN
    permissions: list[str] = Field(default_factory=list, max_length=100)


def _owner_id(request: Request) -> str:
    session = getattr(request.state, "session", None)
    if session is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return session.user_id


def create_account_router(service: AccountLinkingService) -> APIRouter:
    router = APIRouter(prefix="/api/projects/{project_id}/accounts", tags=["accounts"])

    @router.get("")
    def list_accounts(project_id: str, request: Request) -> list[AccountConnection]:
        # The owner check is intentionally explicit; account service is project-scoped.
        _owner_id(request)
        return list(service.list_for_project(project_id))

    @router.get("/{account_id}")
    def get_account(project_id: str, account_id: str, request: Request) -> AccountConnection:
        _owner_id(request)
        account = service.get(project_id, account_id)
        if account is None:
            raise HTTPException(status_code=404, detail="account not found")
        return account

    @router.post("", status_code=201)
    def link_account(project_id: str, payload: AccountPayload, request: Request) -> AccountConnection:
        _owner_id(request)
        try:
            linked = LinkedAccount(
                account_id=payload.account_id,
                platform=payload.platform,
                display_name=payload.display_name,
                project_id=project_id,
                permissions=tuple(payload.permissions),
                connection_state=payload.connection_state,
                verification_state=payload.verification_state,
                monetization_state=payload.monetization_state,
            )
            return service.link(LinkRequest(project_id=project_id, account=linked))
        except (AccountLinkingError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @router.post("/{account_id}/verify")
    def verify_account(project_id: str, account_id: str, request: Request) -> AccountConnection:
        _owner_id(request)
        try:
            return service.mark_verified(project_id, account_id)
        except AccountLinkingError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    @router.delete("/{account_id}", status_code=204)
    def disconnect_account(project_id: str, account_id: str, request: Request) -> None:
        _owner_id(request)
        try:
            service.disconnect(project_id, account_id)
        except AccountLinkingError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    return router
