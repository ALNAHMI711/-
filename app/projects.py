"""Project and channel-constitution domain primitives.

Projects are the isolation boundary for content rules, connected accounts, and
automation. The domain layer contains no provider credentials and no HTTP code.
"""

from dataclasses import dataclass, field


class ProjectError(ValueError):
    """Raised when a project operation violates domain rules."""


@dataclass(frozen=True)
class Project:
    project_id: str
    owner_id: str
    name: str
    description: str = ""
    language: str = "ar"
    topics: tuple[str, ...] = field(default_factory=tuple)
    content_rules: tuple[str, ...] = field(default_factory=tuple)
    automation_enabled: bool = False

    def __post_init__(self) -> None:
        if not self.project_id.strip() or not self.owner_id.strip() or not self.name.strip():
            raise ProjectError("project_id, owner_id and name are required")
        if not self.language.strip():
            raise ProjectError("language is required")


class ProjectService:
    """In-memory project service used until the durable project repository is added."""

    def __init__(self) -> None:
        self._projects: dict[str, Project] = {}

    def create(self, project: Project) -> Project:
        if project.project_id in self._projects:
            raise ProjectError("project already exists")
        self._projects[project.project_id] = project
        return project

    def get(self, owner_id: str, project_id: str) -> Project | None:
        project = self._projects.get(project_id)
        if project is None or project.owner_id != owner_id.strip():
            return None
        return project

    def list_for_owner(self, owner_id: str) -> tuple[Project, ...]:
        owner = owner_id.strip()
        return tuple(project for project in self._projects.values() if project.owner_id == owner)

    def update(self, owner_id: str, project: Project) -> Project:
        existing = self.get(owner_id, project.project_id)
        if existing is None:
            raise ProjectError("project does not belong to owner")
        if project.owner_id != owner_id.strip():
            raise ProjectError("project owner cannot be changed")
        self._projects[project.project_id] = project
        return project

    def delete(self, owner_id: str, project_id: str) -> None:
        if self.get(owner_id, project_id) is None:
            raise ProjectError("project does not belong to owner")
        del self._projects[project_id]
