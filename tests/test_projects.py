import pytest

from app.projects import Project, ProjectError, ProjectService


def make_project(project_id: str, owner_id: str = "admin") -> Project:
    return Project(
        project_id=project_id,
        owner_id=owner_id,
        name=project_id,
        topics=("تعليم",),
        content_rules=("لا تخرج عن المجال",),
    )


def test_projects_are_isolated_by_owner():
    service = ProjectService()
    service.create(make_project("project-a", "owner-a"))
    service.create(make_project("project-b", "owner-b"))

    assert service.get("owner-a", "project-a") is not None
    assert service.get("owner-a", "project-b") is None
    assert service.list_for_owner("owner-a") == (service.get("owner-a", "project-a"),)


def test_update_cannot_change_owner_or_cross_project_boundary():
    service = ProjectService()
    service.create(make_project("project-a", "owner-a"))

    with pytest.raises(ProjectError):
        service.update("owner-b", make_project("project-a", "owner-b"))

    with pytest.raises(ProjectError):
        service.update("owner-a", make_project("project-a", "owner-b"))


def test_duplicate_and_delete_are_enforced():
    service = ProjectService()
    project = make_project("project-a")
    service.create(project)

    with pytest.raises(ProjectError):
        service.create(project)
    with pytest.raises(ProjectError):
        service.delete("other-user", "project-a")

    service.delete("admin", "project-a")
    assert service.get("admin", "project-a") is None
