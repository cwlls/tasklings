"""
LuminTransaction data-access layer.

This is an append-only ledger. Records are never mutated after insertion.
The FamilyMember.balance column is a denormalized fast-read cache that is
kept in sync by the currency service (Phase 5).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import aiosqlite

from app.models.db import fetch_one, fetch_all, execute


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def create_transaction(
    member_id: str,
    amount: int,
    reason: str,
    reference_id: str | None = None,
) -> aiosqlite.Row:
    """
    Append a Lumin transaction to the ledger. Returns the new row.

    `amount` is positive for earnings, negative for deductions.
    `reason` must be one of the CHECK constraint values in the schema.
    `reference_id` is the UUID of the related entity (assignment, quest, purchase, etc.)
    """
    tx_id = str(uuid.uuid4())
    now = _now_iso()
    await execute(
        """
        INSERT INTO lumin_transaction (id, member_id, amount, reason, reference_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (tx_id, member_id, amount, reason, reference_id, now),
    )
    row = await fetch_one(
        "SELECT * FROM lumin_transaction WHERE id = ?",
        (tx_id,),
    )
    assert row is not None
    return row


async def list_transactions_for_member(
    member_id: str, limit: int = 50, offset: int = 0
) -> list[aiosqlite.Row]:
    """Return paginated Lumin transactions for a member, newest first."""
    return await fetch_all(
        """
        SELECT * FROM lumin_transaction
        WHERE member_id = ?
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """,
        (member_id, limit, offset),
    )
