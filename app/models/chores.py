"""
Chore definition and assignment data-access layer.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from app.models.db import fetch_one, fetch_all, execute


_UPDATABLE_DEF_FIELDS = frozenset(
    {"title", "description", "icon", "lumin_value", "chore_type", "rotation_frequency", "is_active"}
)

_UPDATABLE_ASSIGN_FIELDS = frozenset(
    {"status", "completed_at", "verified_by", "lumins_awarded"}
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Chore Definitions
# ---------------------------------------------------------------------------

async def list_chore_definitions(
    household_id: str, active_only: bool = True
) -> list[aiosqlite.Row]:
    """Return chore definitions for a household."""
    if active_only:
        return await fetch_all(
            "SELECT * FROM chore_definition WHERE household_id = ? AND is_active = 1 ORDER BY title",
            (household_id,),
        )
    return await fetch_all(
        "SELECT * FROM chore_definition WHERE household_id = ? ORDER BY title",
        (household_id,),
    )


async def get_chore_definition(chore_id: str) -> aiosqlite.Row | None:
    """Return a single chore definition row or None."""
    return await fetch_one(
        "SELECT * FROM chore_definition WHERE id = ?",
        (chore_id,),
    )


async def create_chore_definition(
    household_id: str,
    title: str,
    description: str,
    icon: str,
    lumin_value: int,
    chore_type: str,
    rotation_frequency: str | None = None,
) -> aiosqlite.Row:
    """Create a chore definition and return the new row."""
    chore_id = str(uuid.uuid4())
    now = _now_iso()
    await execute(
        """
        INSERT INTO chore_definition
            (id, household_id, title, description, icon, lumin_value, chore_type, rotation_frequency, is_active, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        """,
        (chore_id, household_id, title, description, icon, lumin_value, chore_type, rotation_frequency, now),
    )
    row = await get_chore_definition(chore_id)
    assert row is not None
    return row


async def update_chore_definition(chore_id: str, **fields: Any) -> aiosqlite.Row | None:
    """Update only the provided fields on a chore definition."""
    invalid = set(fields) - _UPDATABLE_DEF_FIELDS
    if invalid:
        raise ValueError(f"Unknown field(s) for chore_definition: {invalid}")
    if not fields:
        return await get_chore_definition(chore_id)

    set_clause = ", ".join(f"{col} = ?" for col in fields)
    values = list(fields.values()) + [chore_id]
    await execute(
        f"UPDATE chore_definition SET {set_clause} WHERE id = ?",
        values,
    )
    return await get_chore_definition(chore_id)


async def deactivate_chore_definition(chore_id: str) -> None:
    """Soft-delete a chore definition."""
    await execute(
        "UPDATE chore_definition SET is_active = 0 WHERE id = ?",
        (chore_id,),
    )


# ---------------------------------------------------------------------------
# Chore Assignments
# ---------------------------------------------------------------------------

async def list_assignments_for_member(
    member_id: str, date: str
) -> list[aiosqlite.Row]:
    """
    Return chore assignments for a member on a given date, joined with the
    chore definition to include title, icon, and lumin_value.
    """
    return await fetch_all(
        """
        SELECT
            ca.*,
            cd.title,
            cd.icon,
            cd.lumin_value,
            cd.description AS chore_description
        FROM chore_assignment ca
        JOIN chore_definition cd ON cd.id = ca.chore_id
        WHERE ca.member_id = ?
          AND ca.assigned_date = ?
        ORDER BY cd.title
        """,
        (member_id, date),
    )


async def get_assignment(assignment_id: str) -> aiosqlite.Row | None:
    """Return a single assignment row or None."""
    return await fetch_one(
        "SELECT * FROM chore_assignment WHERE id = ?",
        (assignment_id,),
    )


async def create_assignment(
    chore_id: str, member_id: str, assigned_date: str
) -> aiosqlite.Row:
    """Generate a daily chore assignment record."""
    assignment_id = str(uuid.uuid4())
    now = _now_iso()
    await execute(
        """
        INSERT INTO chore_assignment
            (id, chore_id, member_id, assigned_date, status, completed_at, verified_by, lumins_awarded, created_at)
        VALUES (?, ?, ?, ?, 'pending', NULL, NULL, 0, ?)
        """,
        (assignment_id, chore_id, member_id, assigned_date, now),
    )
    row = await get_assignment(assignment_id)
    assert row is not None
    return row


async def update_assignment_status(
    assignment_id: str,
    status: str,
    completed_at: str | None = None,
    verified_by: str | None = None,
    lumins_awarded: int | None = None,
) -> aiosqlite.Row | None:
    """Update mutable fields on an assignment."""
    fields: dict[str, Any] = {"status": status}
    if completed_at is not None:
        fields["completed_at"] = completed_at
    if verified_by is not None:
        fields["verified_by"] = verified_by
    if lumins_awarded is not None:
        fields["lumins_awarded"] = lumins_awarded

    invalid = set(fields) - _UPDATABLE_ASSIGN_FIELDS
    if invalid:
        raise ValueError(f"Unknown field(s) for chore_assignment: {invalid}")

    set_clause = ", ".join(f"{col} = ?" for col in fields)
    values = list(fields.values()) + [assignment_id]
    await execute(
        f"UPDATE chore_assignment SET {set_clause} WHERE id = ?",
        values,
    )
    return await get_assignment(assignment_id)


async def assignments_exist_for_date(household_id: str, date: str) -> bool:
    """
    Return True if any chore assignments exist for this household on the given date.
    Used by the lazy generation logic to avoid duplicate generation.
    """
    row = await fetch_one(
        """
        SELECT 1
        FROM chore_assignment ca
        JOIN chore_definition cd ON cd.id = ca.chore_id
        WHERE cd.household_id = ?
          AND ca.assigned_date = ?
        LIMIT 1
        """,
        (household_id, date),
    )
    return row is not None
