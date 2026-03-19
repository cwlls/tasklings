"""
FamilyMember data-access layer.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from app.models.db import fetch_one, fetch_all, execute, get_db


_UPDATABLE_FIELDS = frozenset(
    {"username", "password_hash", "name", "avatar", "role", "color", "is_active"}
)


async def get_member_by_id(member_id: str) -> aiosqlite.Row | None:
    """Return a full member row by primary key, or None."""
    return await fetch_one(
        "SELECT * FROM family_member WHERE id = ?",
        (member_id,),
    )


async def get_member_by_username(
    household_id: str, username: str
) -> aiosqlite.Row | None:
    """Look up a member by username within a household (used for login)."""
    return await fetch_one(
        "SELECT * FROM family_member WHERE household_id = ? AND username = ?",
        (household_id, username),
    )


async def list_members(
    household_id: str, include_inactive: bool = False
) -> list[aiosqlite.Row]:
    """Return household members, optionally including deactivated ones."""
    if include_inactive:
        return await fetch_all(
            "SELECT * FROM family_member WHERE household_id = ? ORDER BY name",
            (household_id,),
        )
    return await fetch_all(
        "SELECT * FROM family_member WHERE household_id = ? AND is_active = 1 ORDER BY name",
        (household_id,),
    )


async def create_member(
    household_id: str,
    username: str,
    password_hash: str,
    name: str,
    role: str,
    avatar: str = "",
    color: str = "#4A90D9",
) -> aiosqlite.Row:
    """Insert a new family member and return the created row."""
    member_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    await execute(
        """
        INSERT INTO family_member
            (id, household_id, username, password_hash, name, avatar, role, color, balance, is_active, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 1, ?)
        """,
        (member_id, household_id, username, password_hash, name, avatar, role, color, now),
    )
    row = await get_member_by_id(member_id)
    assert row is not None
    return row


async def update_member(member_id: str, **fields: Any) -> aiosqlite.Row | None:
    """
    Update only the provided fields on a member.
    Raises ValueError for unknown field names to prevent injection.
    """
    invalid = set(fields) - _UPDATABLE_FIELDS
    if invalid:
        raise ValueError(f"Unknown field(s) for family_member: {invalid}")
    if not fields:
        return await get_member_by_id(member_id)

    set_clause = ", ".join(f"{col} = ?" for col in fields)
    values = list(fields.values()) + [member_id]
    await execute(
        f"UPDATE family_member SET {set_clause} WHERE id = ?",
        values,
    )
    return await get_member_by_id(member_id)


async def deactivate_member(member_id: str) -> None:
    """Soft-delete a member by setting is_active = 0."""
    await execute(
        "UPDATE family_member SET is_active = 0 WHERE id = ?",
        (member_id,),
    )


async def update_balance(member_id: str, amount: int) -> int:
    """
    Atomically add `amount` (positive or negative) to the member's Lumin balance.

    Raises ValueError if the resulting balance would go below zero.
    Returns the new balance.
    """
    db = await get_db()
    # Use a single atomic UPDATE with a check so no negative balances can slip through.
    cursor = await db.execute(
        """
        UPDATE family_member
        SET balance = balance + ?
        WHERE id = ?
          AND (balance + ?) >= 0
        """,
        (amount, member_id, amount),
    )
    await db.commit()

    if cursor.rowcount == 0:
        # Either member doesn't exist or balance would go negative.
        row = await get_member_by_id(member_id)
        if row is None:
            raise ValueError(f"Member {member_id!r} not found")
        raise ValueError(
            f"Insufficient Lumin balance: current={row['balance']}, requested={amount}"
        )

    row = await get_member_by_id(member_id)
    assert row is not None
    return row["balance"]
