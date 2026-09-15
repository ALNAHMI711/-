"""Authenticated project API helpers.

This module keeps HTTP concerns separate from the project domain. It is wired
into the main FastAPI app with an injected ProjectService; persistence can be
swapped in later without changing the API contract.
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .projects import Project, ProjectError, ProjectService


class ProjectPayload(BaseModel):
    project_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    language: str = Field(default="ar", min_length=1, max_length=32)
    topics: list[str] = Field(default_factory=list, max_length=100)
    content_rules: list[str] = Field(default_factory=list, max_length=100)
    automation_enabled: bool = False


def _owner_id(request: Request) -> str:
    session = getattr(request.state, "session", None)
    if session is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return session.user_id


def create_project_router(service: ProjectService) -> APIRouter:
    router = APIRouter(prefix="/api/projects", tags=["projects"])

    @router.get("")
    def list_projects(request: Request) -> list[Project]:
        return list(service.list_for_owner(_owner_id(request)))

    @router.get("/{project_id}")
    def get_project(project_id: str, request: Request) -> Project:
        project = service.get(_owner_id(request), project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        return project

    @router.post("", status_code=201)
    def create_project(payload: ProjectPayload, request: Request) -> Project:
        owner_id = _owner_id(request)
        try:
            return service.create(Project(
                project_id=payload.project_id,
                owner_id=owner_id,
                name=payload.name,
                description=payload.description,
                language=payload.language,
                topics=tuple(payload.topics),
                content_rules=tuple(payload.content_rules),
                automation_enabled=payload.automation_enabled,
            ))
        except ProjectError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @router.put("/{project_id}")
    def update_project(project_id: str, payload: ProjectPayload, request: Request) -> Project:
        owner_id = _owner_id(request)
        if payload.project_id != project_id:
            raise HTTPException(status_code=400, detail="project_id does not match path")
        try:
            return service.update(owner_id, Project(
                project_id=project_id,
                owner_id=owner_id,
                name=payload.name,
                description=payload.description,
                language=payload.language,
                topics=tuple(payload.topics),
                content_rules=tuple(payload.content_rules),
                automation_enabled=payload.automation_enabled,
            ))
        except ProjectError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    @router.delete("/{project_id}", status_code=204)
    def delete_project(project_id: str, request: Request) -> None:
        try:
            service.delete(_owner_id(request), project_id)
        except ProjectError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    return router
