"""
Purchase data-access layer.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import aiosqlite

from app.models.db import fetch_one, fetch_all, execute


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def create_purchase(
    item_id: str, member_id: str, price_paid: int
) -> aiosqlite.Row:
    """Insert a purchase record and return the new row."""
    purchase_id = str(uuid.uuid4())
    now = _now_iso()
    await execute(
        """
        INSERT INTO purchase (id, item_id, member_id, price_paid, status, purchased_at, redeemed_at)
        VALUES (?, ?, ?, ?, 'purchased', ?, NULL)
        """,
        (purchase_id, item_id, member_id, price_paid, now),
    )
    row = await get_purchase(purchase_id)
    assert row is not None
    return row


async def list_purchases_for_member(member_id: str) -> list[aiosqlite.Row]:
    """Return all purchases for a member, joined with store_item for display fields."""
    return await fetch_all(
        """
        SELECT p.*, si.title AS item_title, si.icon AS item_icon
        FROM purchase p
        JOIN store_item si ON si.id = p.item_id
        WHERE p.member_id = ?
        ORDER BY p.purchased_at DESC
        """,
        (member_id,),
    )


async def get_purchase(purchase_id: str) -> aiosqlite.Row | None:
    """Return a single purchase row or None."""
    return await fetch_one("SELECT * FROM purchase WHERE id = ?", (purchase_id,))


async def redeem_purchase(purchase_id: str) -> aiosqlite.Row | None:
    """Mark a purchase as redeemed. Returns the updated row."""
    now = _now_iso()
    await execute(
        "UPDATE purchase SET status = 'redeemed', redeemed_at = ? WHERE id = ?",
        (now, purchase_id),
    )
    return await get_purchase(purchase_id)
