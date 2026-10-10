"""Minimal ordered PostgreSQL migration runner for deployment and tests."""

from pathlib import Path
import psycopg


def apply_migrations(dsn: str, migrations_dir: str = "migrations") -> tuple[str, ...]:
    root = Path(migrations_dir)
    files = sorted(root.glob("*.sql"))
    if not files:
        return ()
    applied: list[str] = []
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
            )
            for path in files:
                name = path.name
                cur.execute("SELECT 1 FROM schema_migrations WHERE filename=%s", (name,))
                if cur.fetchone():
                    continue
                cur.execute(path.read_text(encoding="utf-8"))
                cur.execute("INSERT INTO schema_migrations (filename) VALUES (%s)", (name,))
                applied.append(name)
    return tuple(applied)
