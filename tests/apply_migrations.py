"""Apply repository SQL migrations in CI using the same psycopg dependency as the app."""

import glob
import os

import psycopg


def main() -> None:
    dsn = os.environ["DATABASE_URL"]
    with psycopg.connect(dsn) as conn:
        for path in sorted(glob.glob("migrations/*.sql")):
            with open(path, "r", encoding="utf-8") as handle:
                conn.execute(handle.read())
    print("PostgreSQL migrations: OK")


if __name__ == "__main__":
    main()
