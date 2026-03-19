"""
Database connection management and migration runner.

- get_db()        -- returns request-scoped aiosqlite connection (stored on g)
- close_db()      -- teardown hook; closes connection at end of request
- init_db()       -- startup hook; runs pending SQL migrations
- execute()       -- run INSERT/UPDATE/DELETE, return lastrowid
- fetch_one()     -- SELECT returning a single dict-like Row or None
- fetch_all()     -- SELECT returning a list of dict-like Rows
"""
import os
import glob
import logging

import aiosqlite
from quart import current_app, g

logger = logging.getLogger(__name__)


async def get_db() -> aiosqlite.Connection:
    """Return the request-scoped DB connection, creating it on first access."""
    if "db" not in g:
        db_path = current_app.config["DATABASE_PATH"]
        conn = await aiosqlite.connect(db_path)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA foreign_keys=ON")
        g.db = conn
    return g.db


async def close_db(exception: BaseException | None = None) -> None:
    """Close the DB connection at the end of a request."""
    db: aiosqlite.Connection | None = g.pop("db", None)
    if db is not None:
        await db.close()


async def init_db(app) -> None:
    """
    Run pending SQL migrations on application startup.

    Opens its own short-lived connection rather than relying on request context.
    """
    db_path = app.config["DATABASE_PATH"]

    # Resolve migrations directory relative to this file's package root.
    migrations_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "migrations",
    )

    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA foreign_keys=ON")

        # Ensure the migrations tracking table exists.
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS _migrations (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT    NOT NULL UNIQUE,
                applied_at TEXT    NOT NULL
            )
            """
        )
        await conn.commit()

        # Collect already-applied migrations.
        cursor = await conn.execute("SELECT name FROM _migrations ORDER BY name")
        applied = {row["name"] for row in await cursor.fetchall()}

        # Find all *.sql files in the migrations directory, sorted by filename.
        pattern = os.path.join(migrations_dir, "*.sql")
        sql_files = sorted(glob.glob(pattern))

        for path in sql_files:
            name = os.path.basename(path)
            if name in applied:
                logger.debug("Migration already applied: %s", name)
                continue

            logger.info("Applying migration: %s", name)
            with open(path, encoding="utf-8") as f:
                sql = f.read()

            try:
                await conn.executescript(sql)
                # executescript auto-commits; re-enable foreign keys afterwards.
                await conn.execute("PRAGMA foreign_keys=ON")
                # Record as applied.
                from datetime import datetime, timezone
                now = datetime.now(timezone.utc).isoformat()
                await conn.execute(
                    "INSERT INTO _migrations (name, applied_at) VALUES (?, ?)",
                    (name, now),
                )
                await conn.commit()
                logger.info("Migration applied: %s", name)
            except Exception as exc:
                await conn.rollback()
                logger.error("Migration failed: %s -- %s", name, exc)
                raise


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

async def execute(sql: str, params: tuple | list = ()) -> int:
    """
    Execute a write statement (INSERT / UPDATE / DELETE).
    Returns the lastrowid (useful for INTEGER PRIMARY KEY tables; TEXT PKs
    are set explicitly so this value is less relevant but harmless).
    """
    db = await get_db()
    cursor = await db.execute(sql, params)
    await db.commit()
    return cursor.lastrowid


async def fetch_one(sql: str, params: tuple | list = ()) -> aiosqlite.Row | None:
    """Execute a SELECT and return the first row as a dict-like Row, or None."""
    db = await get_db()
    cursor = await db.execute(sql, params)
    return await cursor.fetchone()


async def fetch_all(sql: str, params: tuple | list = ()) -> list[aiosqlite.Row]:
    """Execute a SELECT and return all rows as a list of dict-like Rows."""
    db = await get_db()
    cursor = await db.execute(sql, params)
    return await cursor.fetchall()
