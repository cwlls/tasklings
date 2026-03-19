"""
Household data-access layer.

There is exactly one household row in the database. These helpers
read and update it.
"""
from __future__ import annotations

import aiosqlite

from app.models.db import fetch_one, execute


async def get_household() -> aiosqlite.Row | None:
    """Return the single household row, or None if the DB is empty."""
    return await fetch_one("SELECT * FROM household LIMIT 1")


async def update_household(name: str, timezone: str) -> aiosqlite.Row | None:
    """Update the household name and timezone. Returns the updated row."""
    await execute(
        "UPDATE household SET name = ?, timezone = ? WHERE id = (SELECT id FROM household LIMIT 1)",
        (name, timezone),
    )
    return await get_household()
