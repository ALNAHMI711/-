"""Apply ordered idempotent SQL migrations before application startup."""

from pathlib import Path

from .config import settings
from .migration_runner import apply_migrations as run_migrations


def apply_migrations() -> tuple[str, ...]:
    if not settings.database_url:
        return ()
    directory = Path(__file__).resolve().parents[1] / "migrations"
    return run_migrations(settings.database_url, str(directory))


if __name__ == "__main__":
    names = apply_migrations()
    print("Migrations applied: " + (", ".join(names) if names else "none (DATABASE_URL not set)"))
