"""PostgreSQL-backed project repository."""

from collections.abc import Sequence

import psycopg
from psycopg.rows import dict_row

from .projects import Project


class PostgresProjectRepository:
    """Durable repository for project configuration.

    Provider credentials and OAuth tokens are intentionally not part of this table.
    """

    def __init__(self, dsn: str) -> None:
        if not dsn.strip():
            raise ValueError("database DSN is required")
        self._dsn = dsn

    def _connect(self):
        return psycopg.connect(self._dsn, row_factory=dict_row)

    @staticmethod
    def _from_row(row: dict) -> Project:
        return Project(
            project_id=row["project_id"],
            owner_id=row["owner_id"],
            name=row["name"],
            description=row["description"],
            language=row["language"],
            topics=tuple(row["topics"] or ()),
            content_rules=tuple(row["content_rules"] or ()),
            automation_enabled=bool(row["automation_enabled"]),
        )

    def create(self, project: Project) -> Project:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO projects
                        (project_id, owner_id, name, description, language,
                         topics, content_rules, automation_enabled)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING project_id, owner_id, name, description, language,
                              topics, content_rules, automation_enabled
                    """,
                    (
                        project.project_id,
                        project.owner_id,
                        project.name,
                        project.description,
                        project.language,
                        list(project.topics),
                        list(project.content_rules),
                        project.automation_enabled,
                    ),
                )
                return self._from_row(cur.fetchone())

    def get(self, owner_id: str, project_id: str) -> Project | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT project_id, owner_id, name, description, language,
                           topics, content_rules, automation_enabled
                    FROM projects
                    WHERE owner_id = %s AND project_id = %s
                    """,
                    (owner_id, project_id),
                )
                row = cur.fetchone()
                return None if row is None else self._from_row(row)

    def list_for_owner(self, owner_id: str) -> tuple[Project, ...]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT project_id, owner_id, name, description, language,
                           topics, content_rules, automation_enabled
                    FROM projects
                    WHERE owner_id = %s
                    ORDER BY project_id
                    """,
                    (owner_id,),
                )
                rows: Sequence[dict] = cur.fetchall()
                return tuple(self._from_row(row) for row in rows)

    def save(self, project: Project) -> Project:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE projects
                    SET name = %s,
                        description = %s,
                        language = %s,
                        topics = %s,
                        content_rules = %s,
                        automation_enabled = %s,
                        updated_at = NOW()
                    WHERE owner_id = %s AND project_id = %s
                    RETURNING project_id, owner_id, name, description, language,
                              topics, content_rules, automation_enabled
                    """,
                    (
                        project.name,
                        project.description,
                        project.language,
                        list(project.topics),
                        list(project.content_rules),
                        project.automation_enabled,
                        project.owner_id,
                        project.project_id,
                    ),
                )
                row = cur.fetchone()
                if row is None:
                    raise KeyError("project not found")
                return self._from_row(row)

    def delete(self, owner_id: str, project_id: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM projects WHERE owner_id = %s AND project_id = %s",
                    (owner_id, project_id),
                )
