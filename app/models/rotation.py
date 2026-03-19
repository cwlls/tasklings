"""
Rotation schedule data-access layer.

Manages the ordered list of members for rotating chores and advances
the "current" pointer when a rotation boundary is hit.
"""
from __future__ import annotations

import uuid

import aiosqlite

from app.models.db import fetch_one, fetch_all, execute, get_db


async def get_rotation_schedule(chore_id: str) -> list[aiosqlite.Row]:
    """Return all rotation schedule entries for a chore, ordered by order_index."""
    return await fetch_all(
        """
        SELECT rs.*, fm.name AS member_name, fm.is_active
        FROM rotation_schedule rs
        JOIN family_member fm ON fm.id = rs.member_id
        WHERE rs.chore_id = ?
        ORDER BY rs.order_index
        """,
        (chore_id,),
    )


async def set_rotation_schedule(
    chore_id: str, entries: list[dict]
) -> None:
    """
    Replace the entire rotation schedule for a chore.

    `entries` is a list of dicts with keys: member_id, order_index.
    The first entry in the list gets current=1; all others get current=0.
    """
    db = await get_db()
    await db.execute(
        "DELETE FROM rotation_schedule WHERE chore_id = ?",
        (chore_id,),
    )
    for i, entry in enumerate(entries):
        schedule_id = str(uuid.uuid4())
        current = 1 if i == 0 else 0
        await db.execute(
            """
            INSERT INTO rotation_schedule (id, chore_id, member_id, order_index, current)
            VALUES (?, ?, ?, ?, ?)
            """,
            (schedule_id, chore_id, entry["member_id"], entry["order_index"], current),
        )
    await db.commit()


async def get_current_rotation_member(chore_id: str) -> str | None:
    """Return the member_id of the member currently 'up' in the rotation."""
    row = await fetch_one(
        "SELECT member_id FROM rotation_schedule WHERE chore_id = ? AND current = 1",
        (chore_id,),
    )
    return row["member_id"] if row else None


async def advance_rotation(chore_id: str) -> str | None:
    """
    Move the current=1 pointer to the next active member in order,
    wrapping around. Inactive members are skipped.

    Returns the member_id of the new current member, or None if the
    schedule is empty or has no active members.
    """
    entries = await get_rotation_schedule(chore_id)
    if not entries:
        return None

    # Filter to active members only, preserving order.
    active = [e for e in entries if e["is_active"]]
    if not active:
        return None

    # Find the index of the current active member.
    current_idx = next(
        (i for i, e in enumerate(active) if e["current"] == 1),
        None,
    )
    if current_idx is None:
        # No current marker on an active member -- reset to first active.
        next_member_id = active[0]["member_id"]
    else:
        next_idx = (current_idx + 1) % len(active)
        next_member_id = active[next_idx]["member_id"]

    db = await get_db()
    # Clear all current flags for this chore.
    await db.execute(
        "UPDATE rotation_schedule SET current = 0 WHERE chore_id = ?",
        (chore_id,),
    )
    # Set the new current member.
    await db.execute(
        "UPDATE rotation_schedule SET current = 1 WHERE chore_id = ? AND member_id = ?",
        (chore_id, next_member_id),
    )
    await db.commit()
    return next_member_id
