"""Authenticated OAuth authorization-start API.

The endpoint creates a short-lived, single-use state bound to the authenticated
user and project. It returns only a provider authorization URL; client secrets
and provider tokens never cross the browser API.
"""

import os
from dataclasses import dataclass

from fastapi import APIRouter, HTTPException, Request

from .oauth_adapter import OAuthAdapterConfig, create_oauth_adapter
from .oauth_session import OAuthStateStore
from .platforms import get_platform, supported_platforms
from .projects import ProjectService


@dataclass(frozen=True)
class OAuthRuntimeConfig:
    client_id: str
    authorization_endpoint: str
    redirect_uri: str


_ENDPOINTS = {
    "youtube": "https://accounts.google.com/o/oauth2/v2/auth",
    "tiktok": "https://www.tiktok.com/v2/auth/authorize/",
    "linkedin": "https://www.linkedin.com/oauth/v2/authorization",
}
_ENV_CLIENT_IDS = {
    "youtube": "YOUTUBE_CLIENT_ID",
    "tiktok": "TIKTOK_CLIENT_KEY",
    "linkedin": "LINKEDIN_CLIENT_ID",
}


def create_oauth_router(project_service: ProjectService, state_store: OAuthStateStore | None = None) -> APIRouter:
    router = APIRouter(prefix="/api/oauth", tags=["oauth"])
    states = state_store or OAuthStateStore()

    def owner_id(request: Request) -> str:
        session = getattr(request.state, "session", None)
        if session is None:
            raise HTTPException(status_code=401, detail="authentication required")
        return session.user_id

    def owned_project(request: Request, project_id: str) -> str:
        user_id = owner_id(request)
        if project_service.get(user_id, project_id) is None:
            raise HTTPException(status_code=404, detail="project not found")
        return user_id

    @router.get("/platforms")
    def platforms(request: Request) -> list[dict[str, object]]:
        owner_id(request)
        return [
            {
                "key": platform.key,
                "display_name": platform.display_name,
                "oauth_supported": platform.oauth_supported,
                "required_scopes": list(platform.required_scopes),
            }
            for platform in supported_platforms()
        ]

    @router.post("/{platform}/start")
    def start(platform: str, project_id: str, request: Request) -> dict[str, str]:
        user_id = owned_project(request, project_id)
        try:
            definition = get_platform(platform)
            client_env = _ENV_CLIENT_IDS.get(definition.key)
            client_id = os.getenv(client_env, "") if client_env else ""
            if not client_id:
                raise HTTPException(status_code=503, detail="OAuth client is not configured")
            endpoint = _ENDPOINTS.get(definition.key, "")
            redirect_uri = f"{os.getenv('APP_URL', 'http://localhost:8000').rstrip('/')}/oauth/callback/{definition.key}"
            adapter = create_oauth_adapter(
                definition.key,
                OAuthAdapterConfig(
                    client_id=client_id,
                    authorization_endpoint=endpoint,
                    redirect_uri=redirect_uri,
                ),
            )
            state = states.create(definition.key, user_id=user_id, project_id=project_id)
            oauth = adapter.start()
            # Replace the adapter-generated state with our server-side state.
            separator = "&" if "?" in oauth.authorization_url else "?"
            authorization_url = f"{oauth.authorization_url}{separator}state={state.value}"
            return {"platform": definition.key, "project_id": project_id, "state": state.value, "authorization_url": authorization_url}
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    return router
