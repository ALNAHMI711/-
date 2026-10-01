"""Apply idempotent SQL migrations before the application starts."""

from pathlib import Path

import psycopg

from .config import settings


def apply_migrations() -> tuple[str, ...]:
    if not settings.database_url:
        return ()
    directory = Path(__file__).resolve().parents[1] / "migrations"
    applied: list[str] = []
    with psycopg.connect(settings.database_url) as connection:
        for migration in sorted(directory.glob("*.sql")):
            connection.execute(migration.read_text(encoding="utf-8"))
            applied.append(migration.name)
    return tuple(applied)


if __name__ == "__main__":
    names = apply_migrations()
    print("Migrations applied: " + (", ".join(names) if names else "none (DATABASE_URL not set)"))
