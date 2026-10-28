"""Postgres connection pool and forward-only SQL migrations."""

import logging
from importlib import resources

from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

log = logging.getLogger("seed.db")
Pool = AsyncConnectionPool[AsyncConnection[DictRow]]
# Arbitrary constant: serialises migrations when the API and workers start together.
_MIGRATION_LOCK = 0x5EED_0001


def make_pool(url: str, *, max_size: int = 10) -> Pool:
    return AsyncConnectionPool(
        url,
        open=False,
        min_size=1,
        max_size=max_size,
        kwargs={"autocommit": True, "row_factory": dict_row},
        connection_class=AsyncConnection[DictRow],
    )


def _migrations() -> list[tuple[str, str]]:
    files = resources.files(__package__).joinpath("migrations")
    sql_files = [f for f in files.iterdir() if f.name.endswith(".sql")]
    return sorted((f.name.removesuffix(".sql"), f.read_text()) for f in sql_files)


async def migrate(pool: Pool) -> list[str]:
    """Apply pending migrations in one transaction. Returns the versions applied."""
    applied: list[str] = []
    async with pool.connection() as conn, conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock(%s)", (_MIGRATION_LOCK,))
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        cur = await conn.execute("SELECT version FROM schema_migrations")
        done = {row["version"] for row in await cur.fetchall()}
        for version, sql in _migrations():
            if version in done:
                continue
            await conn.execute(sql.encode())
            await conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
            applied.append(version)
    if applied:
        log.info("applied migrations: %s", ", ".join(applied))
    return applied
