"""
Group Quest data-access layer.

Group Quests have a shared chore pool. Any enrolled member can complete any
chore. Members can claim chores as a soft social signal (not a lock).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from app.models.db import fetch_one, fetch_all, execute, get_db


_UPDATABLE_FIELDS = frozenset(
    {"name", "description", "bonus_lumins", "reward_description", "deadline", "is_active"}
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

async def list_group_quests_for_member(member_id: str) -> list[aiosqlite.Row]:
    """Return active group quests the member is enrolled in."""
    return await fetch_all(
        """
        SELECT gq.*
        FROM group_quest gq
        JOIN group_quest_member gqm ON gqm.group_quest_id = gq.id
        WHERE gqm.member_id = ?
          AND gq.is_active = 1
        ORDER BY gq.name
        """,
        (member_id,),
    )


async def list_all_group_quests(household_id: str) -> list[aiosqlite.Row]:
    """Return all group quests for a household (admin view)."""
    return await fetch_all(
        "SELECT * FROM group_quest WHERE household_id = ? ORDER BY name",
        (household_id,),
    )


async def get_group_quest(group_quest_id: str) -> aiosqlite.Row | None:
    """Return the group quest row or None."""
    return await fetch_one(
        "SELECT * FROM group_quest WHERE id = ?",
        (group_quest_id,),
    )


async def create_group_quest(
    household_id: str,
    name: str,
    description: str,
    bonus_lumins: int,
    reward_description: str | None,
    deadline: str | None,
    chore_ids: list[str],
    member_ids: list[str],
) -> aiosqlite.Row:
    """
    Create a group quest with its shared chore pool and initial member roster.
    Returns the new group quest row.
    """
    gq_id = str(uuid.uuid4())
    now = _now_iso()
    db = await get_db()

    await db.execute(
        """
        INSERT INTO group_quest
            (id, household_id, name, description, bonus_lumins, reward_description, deadline, is_active, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
        """,
        (gq_id, household_id, name, description, bonus_lumins, reward_description, deadline, now),
    )

    for order_idx, chore_id in enumerate(chore_ids):
        await db.execute(
            'INSERT INTO group_quest_chore (group_quest_id, chore_id, "order", claimed_by, claimed_at) VALUES (?, ?, ?, NULL, NULL)',
            (gq_id, chore_id, order_idx),
        )

    for member_id in member_ids:
        await db.execute(
            """
            INSERT INTO group_quest_member (group_quest_id, member_id, joined_at, joined_by)
            VALUES (?, ?, ?, 'admin')
            """,
            (gq_id, member_id, now),
        )

    await db.commit()
    row = await get_group_quest(gq_id)
    assert row is not None
    return row


async def update_group_quest(group_quest_id: str, **fields: Any) -> aiosqlite.Row | None:
    """Update group quest fields."""
    invalid = set(fields) - _UPDATABLE_FIELDS
    if invalid:
        raise ValueError(f"Unknown field(s) for group_quest: {invalid}")
    if not fields:
        return await get_group_quest(group_quest_id)

    set_clause = ", ".join(f"{col} = ?" for col in fields)
    values = list(fields.values()) + [group_quest_id]
    await execute(f"UPDATE group_quest SET {set_clause} WHERE id = ?", values)
    return await get_group_quest(group_quest_id)


async def deactivate_group_quest(group_quest_id: str) -> None:
    """Soft-delete a group quest."""
    await execute(
        "UPDATE group_quest SET is_active = 0 WHERE id = ?",
        (group_quest_id,),
    )


# ---------------------------------------------------------------------------
# Membership
# ---------------------------------------------------------------------------

async def add_member(
    group_quest_id: str, member_id: str, joined_by: str
) -> None:
    """Enroll a member in a group quest. joined_by is 'self' or 'admin'."""
    now = _now_iso()
    await execute(
        """
        INSERT OR IGNORE INTO group_quest_member (group_quest_id, member_id, joined_at, joined_by)
        VALUES (?, ?, ?, ?)
        """,
        (group_quest_id, member_id, now, joined_by),
    )


async def remove_member(group_quest_id: str, member_id: str) -> None:
    """Remove a member from a group quest."""
    await execute(
        "DELETE FROM group_quest_member WHERE group_quest_id = ? AND member_id = ?",
        (group_quest_id, member_id),
    )


# ---------------------------------------------------------------------------
# Claim / Dibs mechanic
# ---------------------------------------------------------------------------

async def claim_chore(
    group_quest_id: str, chore_id: str, member_id: str
) -> None:
    """
    Claim a chore (soft signal -- not a lock). Overwrites any existing claim.
    """
    now = _now_iso()
    await execute(
        """
        UPDATE group_quest_chore
        SET claimed_by = ?, claimed_at = ?
        WHERE group_quest_id = ? AND chore_id = ?
        """,
        (member_id, now, group_quest_id, chore_id),
    )


async def release_claim(
    group_quest_id: str, chore_id: str, member_id: str
) -> None:
    """
    Release a claim only if it belongs to the requesting member.
    Other members' claims are not affected.
    """
    await execute(
        """
        UPDATE group_quest_chore
        SET claimed_by = NULL, claimed_at = NULL
        WHERE group_quest_id = ? AND chore_id = ? AND claimed_by = ?
        """,
        (group_quest_id, chore_id, member_id),
    )


# ---------------------------------------------------------------------------
# Completion
# ---------------------------------------------------------------------------

async def complete_chore(
    group_quest_id: str, chore_id: str, member_id: str
) -> bool:
    """
    Record a chore completion in the shared pool. Clears any claim on the chore.
    Returns False if the chore was already completed (UNIQUE constraint), True on success.
    """
    db = await get_db()
    completion_id = str(uuid.uuid4())
    now = _now_iso()

    # Check if already completed.
    existing = await fetch_one(
        "SELECT id FROM group_quest_completion WHERE group_quest_id = ? AND chore_id = ?",
        (group_quest_id, chore_id),
    )
    if existing:
        return False

    await db.execute(
        """
        INSERT INTO group_quest_completion (id, group_quest_id, chore_id, completed_by, completed_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (completion_id, group_quest_id, chore_id, member_id, now),
    )
    # Clear the claim now that the chore is done.
    await db.execute(
        "UPDATE group_quest_chore SET claimed_by = NULL, claimed_at = NULL WHERE group_quest_id = ? AND chore_id = ?",
        (group_quest_id, chore_id),
    )
    await db.commit()
    return True


# ---------------------------------------------------------------------------
# Progress & Contributions
# ---------------------------------------------------------------------------

async def get_progress(group_quest_id: str) -> list[dict]:
    """
    Return per-chore progress for a group quest.
    Each item includes chore definition fields, claim info, and completion info.
    """
    chores = await fetch_all(
        """
        SELECT gqc.*, cd.title, cd.icon, cd.description AS chore_description,
               gqc."order",
               fm_claim.name AS claimed_by_name
        FROM group_quest_chore gqc
        JOIN chore_definition cd ON cd.id = gqc.chore_id
        LEFT JOIN family_member fm_claim ON fm_claim.id = gqc.claimed_by
        WHERE gqc.group_quest_id = ?
        ORDER BY gqc."order"
        """,
        (group_quest_id,),
    )

    completions = await fetch_all(
        """
        SELECT gqc2.chore_id, fm.name AS completed_by_name, gqc2.completed_at
        FROM group_quest_completion gqc2
        JOIN family_member fm ON fm.id = gqc2.completed_by
        WHERE gqc2.group_quest_id = ?
        """,
        (group_quest_id,),
    )
    completion_map = {c["chore_id"]: c for c in completions}

    results = []
    for chore in chores:
        completion = completion_map.get(chore["chore_id"])
        results.append(
            {
                **dict(chore),
                "is_completed": completion is not None,
                "completed_by_name": completion["completed_by_name"] if completion else None,
                "completed_at": completion["completed_at"] if completion else None,
            }
        )
    return results


async def get_contributions(group_quest_id: str) -> list[dict]:
    """
    Return per-member contribution counts for a group quest.
    Each item: member_id, member_name, color, completed_count, total_chores.
    """
    total_row = await fetch_one(
        "SELECT COUNT(*) AS total FROM group_quest_chore WHERE group_quest_id = ?",
        (group_quest_id,),
    )
    total = total_row["total"] if total_row else 0

    rows = await fetch_all(
        """
        SELECT fm.id AS member_id, fm.name AS member_name, fm.color,
               COUNT(gqc2.id) AS completed_count
        FROM group_quest_member gqm
        JOIN family_member fm ON fm.id = gqm.member_id
        LEFT JOIN group_quest_completion gqc2
            ON gqc2.group_quest_id = gqm.group_quest_id
            AND gqc2.completed_by = gqm.member_id
        WHERE gqm.group_quest_id = ?
        GROUP BY fm.id
        ORDER BY completed_count DESC
        """,
        (group_quest_id,),
    )
    return [
        {**dict(r), "total_chores": total}
        for r in rows
    ]


async def is_complete(group_quest_id: str) -> bool:
    """Return True if every chore in the pool has a completion record."""
    row = await fetch_one(
        """
        SELECT
            (SELECT COUNT(*) FROM group_quest_chore WHERE group_quest_id = ?) AS total,
            (SELECT COUNT(*) FROM group_quest_completion WHERE group_quest_id = ?) AS done
        """,
        (group_quest_id, group_quest_id),
    )
    if row is None:
        return False
    return row["total"] > 0 and row["done"] >= row["total"]
