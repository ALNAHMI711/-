"""Contract-level tests for the durable project repository boundary."""

from datetime import datetime

import pytest

from app.project_persistence import ProjectRepository
from app.projects import Project, ProjectError


class FakeProjectRepository:
    """Small repository double used to verify service-compatible semantics."""

    def __init__(self) -> None:
        self.rows: dict[str, Project] = {}

    def create(self, project: Project) -> Project:
        if project.project_id in self.rows:
            raise ValueError("duplicate")
        self.rows[project.project_id] = project
        return project

    def get(self, owner_id: str, project_id: str) -> Project | None:
        row = self.rows.get(project_id)
        return row if row and row.owner_id == owner_id else None

    def list_for_owner(self, owner_id: str) -> tuple[Project, ...]:
        return tuple(row for row in self.rows.values() if row.owner_id == owner_id)

    def save(self, project: Project) -> Project:
        if self.get(project.owner_id, project.project_id) is None:
            raise ProjectError("project does not belong to owner")
        self.rows[project.project_id] = project
        return project

    def delete(self, owner_id: str, project_id: str) -> None:
        if self.get(owner_id, project_id) is None:
            raise ProjectError("project does not belong to owner")
        del self.rows[project_id]


def test_repository_protocol_is_runtime_documentation_boundary() -> None:
    repo: ProjectRepository = FakeProjectRepository()
    project = Project("p1", "owner-a", "تعليم")
    assert repo.create(project) == project
    assert repo.get("owner-a", "p1") == project
    assert repo.get("owner-b", "p1") is None


def test_project_configuration_round_trip_without_credentials() -> None:
    repo = FakeProjectRepository()
    project = Project(
        "p2", "owner-a", "صيانة", language="ar",
        topics=("سيارات",), content_rules=("لا محتوى خارج الصيانة",),
        automation_enabled=True,
    )
    saved = repo.create(project)
    assert saved.topics == ("سيارات",)
    assert saved.content_rules == ("لا محتوى خارج الصيانة",)
    assert saved.automation_enabled is True


def test_cross_owner_update_and_delete_are_blocked() -> None:
    repo = FakeProjectRepository()
    repo.create(Project("p3", "owner-a", "مضحك"))
    with pytest.raises(ProjectError):
        repo.save(Project("p3", "owner-b", "محاولة"))
    with pytest.raises(ProjectError):
        repo.delete("owner-b", "p3")
