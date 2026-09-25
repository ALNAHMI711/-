"""Authenticated account-connection API.

Only safe account metadata is exposed here. Provider passwords and raw OAuth
credentials never enter this API; real verification belongs to provider adapters.
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .account_connections import AccountConnection, ConnectionState
from .account_linking import AccountLinkingError, AccountLinkingService, LinkRequest
from .oauth_callback import LinkedAccount
from .projects import ProjectService
from .platforms import get_platform, UnsupportedPlatform


class AccountPayload(BaseModel):
    account_id: str = Field(min_length=1, max_length=200)
    platform: str = Field(min_length=1, max_length=64)
    display_name: str = Field(default="", max_length=300)
    permissions: list[str] = Field(default_factory=list, max_length=100)


def _owner_id(request: Request) -> str:
    session = getattr(request.state, "session", None)
    if session is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return session.user_id


def _owned_project(request: Request, project_service: ProjectService, project_id: str) -> None:
    owner_id = _owner_id(request)
    if project_service.get(owner_id, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")


def create_account_router(
    service: AccountLinkingService,
    project_service: ProjectService,
) -> APIRouter:
    router = APIRouter(prefix="/api/projects/{project_id}/accounts", tags=["accounts"])

    @router.get("")
    def list_accounts(project_id: str, request: Request) -> list[AccountConnection]:
        _owned_project(request, project_service, project_id)
        return list(service.list_for_project(project_id))

    @router.get("/{account_id}")
    def get_account(project_id: str, account_id: str, request: Request) -> AccountConnection:
        _owned_project(request, project_service, project_id)
        account = service.get(project_id, account_id)
        if account is None:
            raise HTTPException(status_code=404, detail="account not found")
        return account

    @router.post("", status_code=201)
    def link_account(project_id: str, payload: AccountPayload, request: Request) -> AccountConnection:
        _owned_project(request, project_service, project_id)
        try:
            linked = LinkedAccount(
                account_id=payload.account_id,
                platform=payload.platform,
                display_name=payload.display_name,
                project_id=project_id,
                permissions=tuple(payload.permissions),
                connection_state=ConnectionState.PENDING,
            )
            return service.link(LinkRequest(project_id=project_id, account=linked))
        except (AccountLinkingError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @router.get("/{account_id}/readiness")
    def account_readiness(project_id: str, account_id: str, request: Request) -> dict[str, object]:
        _owned_project(request, project_service, project_id)
        account = service.get(project_id, account_id)
        if account is None:
            raise HTTPException(status_code=404, detail="account not found")
        try:
            platform = get_platform(account.platform)
        except UnsupportedPlatform:
            raise HTTPException(status_code=404, detail="unsupported platform") from None
        return {
            "account_id": account.account_id,
            "platform": platform.key,
            "display_name": account.display_name,
            "connection_state": account.connection_state.value,
            "verification_state": account.verification_state.value,
            "monetization_state": account.monetization_state.value,
            "ready_to_publish": account.ready_to_publish,
            "needs_user_action": account.needs_user_action,
            "required_scopes": list(platform.required_scopes),
            "monetization_status_supported": platform.monetization_status_supported,
            "monetization_url": platform.monetization_url,
            "last_error": account.last_error,
        }

    @router.delete("/{account_id}", status_code=204)
    def disconnect_account(project_id: str, account_id: str, request: Request) -> None:
        _owned_project(request, project_service, project_id)
        try:
            service.disconnect(project_id, account_id)
        except AccountLinkingError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    return router
