"""
Solo Quest data-access layer.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from app.models.db import fetch_one, fetch_all, execute, get_db


_UPDATABLE_FIELDS = frozenset(
    {"name", "description", "member_id", "bonus_lumins", "is_active"}
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def list_quests_for_member(member_id: str) -> list[aiosqlite.Row]:
    """Return active quests assigned to a specific member."""
    return await fetch_all(
        "SELECT * FROM quest WHERE member_id = ? AND is_active = 1 ORDER BY name",
        (member_id,),
    )


async def list_all_quests(household_id: str) -> list[aiosqlite.Row]:
    """Return all quests for a household (admin view)."""
    return await fetch_all(
        "SELECT * FROM quest WHERE household_id = ? ORDER BY name",
        (household_id,),
    )


async def get_quest(quest_id: str) -> aiosqlite.Row | None:
    """Return a quest row or None."""
    return await fetch_one("SELECT * FROM quest WHERE id = ?", (quest_id,))


async def get_quest_chores(quest_id: str) -> list[aiosqlite.Row]:
    """Return chores linked to a quest, with definition details, ordered."""
    return await fetch_all(
        """
        SELECT qc."order", cd.*
        FROM quest_chore qc
        JOIN chore_definition cd ON cd.id = qc.chore_id
        WHERE qc.quest_id = ?
        ORDER BY qc."order"
        """,
        (quest_id,),
    )


async def create_quest(
    household_id: str,
    name: str,
    description: str,
    member_id: str,
    bonus_lumins: int,
    chore_ids: list[str],
) -> aiosqlite.Row:
    """Insert a quest and its linked chore rows. Returns the new quest row."""
    quest_id = str(uuid.uuid4())
    now = _now_iso()
    db = await get_db()
    await db.execute(
        """
        INSERT INTO quest (id, household_id, name, description, member_id, bonus_lumins, is_active, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 1, ?)
        """,
        (quest_id, household_id, name, description, member_id, bonus_lumins, now),
    )
    for order_idx, chore_id in enumerate(chore_ids):
        await db.execute(
            'INSERT INTO quest_chore (quest_id, chore_id, "order") VALUES (?, ?, ?)',
            (quest_id, chore_id, order_idx),
        )
    await db.commit()
    row = await get_quest(quest_id)
    assert row is not None
    return row


async def update_quest(quest_id: str, **fields: Any) -> aiosqlite.Row | None:
    """Update quest fields. Raises ValueError for unknown fields."""
    invalid = set(fields) - _UPDATABLE_FIELDS
    if invalid:
        raise ValueError(f"Unknown field(s) for quest: {invalid}")
    if not fields:
        return await get_quest(quest_id)

    set_clause = ", ".join(f"{col} = ?" for col in fields)
    values = list(fields.values()) + [quest_id]
    await execute(f"UPDATE quest SET {set_clause} WHERE id = ?", values)
    return await get_quest(quest_id)


async def deactivate_quest(quest_id: str) -> None:
    """Soft-delete a quest."""
    await execute("UPDATE quest SET is_active = 0 WHERE id = ?", (quest_id,))


async def get_quest_progress(
    quest_id: str, member_id: str, date: str
) -> list[dict]:
    """
    Return quest chores with their completion status for the given member on the
    given date. Each item is a dict with chore definition fields plus
    `completed` (bool) and `assignment_status` (str | None).
    """
    chores = await get_quest_chores(quest_id)
    results = []
    for chore in chores:
        assignment = await fetch_one(
            """
            SELECT status FROM chore_assignment
            WHERE chore_id = ? AND member_id = ? AND assigned_date = ?
            LIMIT 1
            """,
            (chore["id"], member_id, date),
        )
        status = assignment["status"] if assignment else None
        results.append(
            {
                **dict(chore),
                "completed": status in ("completed", "verified"),
                "assignment_status": status,
            }
        )
    return results
