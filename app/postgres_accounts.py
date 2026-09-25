"""PostgreSQL-backed account connection repository.

Only non-secret account metadata is persisted. OAuth access/refresh tokens and
provider credentials are intentionally excluded.
"""

from collections.abc import Sequence

import psycopg
from psycopg.rows import dict_row

from .account_connections import (
    AccountConnection,
    ConnectionState,
    MonetizationState,
    VerificationState,
)


class PostgresAccountRepository:
    """Durable repository enforcing globally unique provider account identities."""

    def __init__(self, dsn: str) -> None:
        if not dsn.strip():
            raise ValueError("database DSN is required")
        self._dsn = dsn

    def _connect(self):
        return psycopg.connect(self._dsn, row_factory=dict_row)

    @staticmethod
    def _from_row(row: dict) -> AccountConnection:
        return AccountConnection(
            account_id=row["account_id"],
            platform=row["platform"],
            display_name=row["display_name"],
            project_id=row["project_id"],
            connection_state=ConnectionState(row["connection_state"]),
            verification_state=VerificationState(row["verification_state"]),
            monetization_state=MonetizationState(row["monetization_state"]),
            permissions=tuple(row["permissions"] or ()),
            last_error=row["last_error"],
        )

    def create(self, account: AccountConnection) -> AccountConnection:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO account_connections
                        (account_id, platform, display_name, project_id,
                         connection_state, verification_state, monetization_state,
                         permissions, last_error)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING account_id, platform, display_name, project_id,
                              connection_state, verification_state,
                              monetization_state, permissions, last_error
                    """,
                    (
                        account.account_id,
                        account.platform,
                        account.display_name,
                        account.project_id,
                        account.connection_state.value,
                        account.verification_state.value,
                        account.monetization_state.value,
                        list(account.permissions),
                        account.last_error,
                    ),
                )
                return self._from_row(cur.fetchone())

    def get(self, project_id: str, account_id: str) -> AccountConnection | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT account_id, platform, display_name, project_id,
                           connection_state, verification_state,
                           monetization_state, permissions, last_error
                    FROM account_connections
                    WHERE project_id = %s AND account_id = %s
                    """,
                    (project_id, account_id),
                )
                row = cur.fetchone()
                return None if row is None else self._from_row(row)

    def find_by_account_id(self, account_id: str) -> AccountConnection | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT account_id, platform, display_name, project_id,
                           connection_state, verification_state,
                           monetization_state, permissions, last_error
                    FROM account_connections
                    WHERE account_id = %s
                    """,
                    (account_id,),
                )
                row = cur.fetchone()
                return None if row is None else self._from_row(row)

    def list_for_project(self, project_id: str) -> tuple[AccountConnection, ...]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT account_id, platform, display_name, project_id,
                           connection_state, verification_state,
                           monetization_state, permissions, last_error
                    FROM account_connections
                    WHERE project_id = %s
                    ORDER BY platform, account_id
                    """,
                    (project_id,),
                )
                rows: Sequence[dict] = cur.fetchall()
                return tuple(self._from_row(row) for row in rows)

    def save(self, account: AccountConnection) -> AccountConnection:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE account_connections
                    SET display_name = %s,
                        connection_state = %s,
                        verification_state = %s,
                        monetization_state = %s,
                        permissions = %s,
                        last_error = %s,
                        updated_at = NOW()
                    WHERE project_id = %s AND account_id = %s
                    RETURNING account_id, platform, display_name, project_id,
                              connection_state, verification_state,
                              monetization_state, permissions, last_error
                    """,
                    (
                        account.display_name,
                        account.connection_state.value,
                        account.verification_state.value,
                        account.monetization_state.value,
                        list(account.permissions),
                        account.last_error,
                        account.project_id,
                        account.account_id,
                    ),
                )
                row = cur.fetchone()
                if row is None:
                    raise KeyError("account not found")
                return self._from_row(row)

    def delete(self, project_id: str, account_id: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM account_connections WHERE project_id = %s AND account_id = %s",
                    (project_id, account_id),
                )
