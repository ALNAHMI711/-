"""Durable project repository contract and PostgreSQL adapter.

Project rows contain content configuration only; provider credentials/tokens are
stored elsewhere in the credential vault and are never persisted here.
"""

from typing import Protocol, Any

import psycopg
from psycopg.rows import dict_row

from .projects import Project, ProjectError


class DuplicateProject(ProjectError):
    """Raised when a project identifier already exists."""


class ProjectRepository(Protocol):
    def create(self, project: Project) -> Project: ...
    def get(self, owner_id: str, project_id: str) -> Project | None: ...
    def list_for_owner(self, owner_id: str) -> tuple[Project, ...]: ...
    def save(self, project: Project) -> Project: ...
    def delete(self, owner_id: str, project_id: str) -> None: ...


class PostgresProjectRepository:
    """PostgreSQL implementation with owner-scoped reads and writes."""

    def __init__(self, dsn: str) -> None:
        if not dsn.strip():
            raise ValueError("PostgreSQL DSN is required")
        self._dsn = dsn

    def _connect(self):
        return psycopg.connect(self._dsn, row_factory=dict_row)

    @staticmethod
    def _to_project(row: dict[str, Any]) -> Project:
        return Project(
            project_id=row["project_id"],
            owner_id=row["owner_id"],
            name=row["name"],
            description=row["description"],
            language=row["language"],
            topics=tuple(row["topics"] or ()),
            content_rules=tuple(row["content_rules"] or ()),
            automation_enabled=row["automation_enabled"],
        )

    def create(self, project: Project) -> Project:
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO projects
                    (project_id, owner_id, name, description, language, topics,
                     content_rules, automation_enabled)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    RETURNING project_id, owner_id, name, description, language,
                              topics, content_rules, automation_enabled
                    """ ,
                    (project.project_id, project.owner_id, project.name,
                     project.description, project.language, list(project.topics),
                     list(project.content_rules), project.automation_enabled),
                )
                return self._to_project(cur.fetchone())
        except psycopg.errors.UniqueViolation as exc:
            raise DuplicateProject(project.project_id) from exc

    def get(self, owner_id: str, project_id: str) -> Project | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT project_id, owner_id, name, description, language,
                          topics, content_rules, automation_enabled
                   FROM projects WHERE project_id=%s AND owner_id=%s""",
                (project_id, owner_id.strip()),
            )
            row = cur.fetchone()
            return None if row is None else self._to_project(row)

    def list_for_owner(self, owner_id: str) -> tuple[Project, ...]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT project_id, owner_id, name, description, language,
                          topics, content_rules, automation_enabled
                   FROM projects WHERE owner_id=%s ORDER BY project_id""",
                (owner_id.strip(),),
            )
            return tuple(self._to_project(row) for row in cur.fetchall())

    def save(self, project: Project) -> Project:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE projects SET name=%s, description=%s, language=%s,
                          topics=%s, content_rules=%s, automation_enabled=%s,
                          updated_at=NOW()
                   WHERE project_id=%s AND owner_id=%s
                   RETURNING project_id, owner_id, name, description, language,
                             topics, content_rules, automation_enabled""",
                (project.name, project.description, project.language,
                 list(project.topics), list(project.content_rules),
                 project.automation_enabled, project.project_id, project.owner_id),
            )
            row = cur.fetchone()
            if row is None:
                raise ProjectError("project does not belong to owner")
            return self._to_project(row)

    def delete(self, owner_id: str, project_id: str) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM projects WHERE project_id=%s AND owner_id=%s",
                (project_id, owner_id.strip()),
            )
            if cur.rowcount != 1:
                raise ProjectError("project does not belong to owner")
