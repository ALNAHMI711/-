import pytest

from app.postgres import PostgresJobRepository


def test_postgres_repository_requires_dsn():
    with pytest.raises(ValueError, match="DSN"):
        PostgresJobRepository("")


def test_postgres_repository_keeps_dsn_private():
    repo = PostgresJobRepository("postgresql://example.invalid/db")
    assert repo._dsn == "postgresql://example.invalid/db"
