"""
Store item data-access layer.

StoreItemVisibility rule:
  - No rows for an item  => visible to all members (global).
  - Rows present          => visible only to the listed members.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from app.models.db import fetch_one, fetch_all, execute, get_db


_UPDATABLE_FIELDS = frozenset(
    {"title", "description", "icon", "price", "is_available", "stock"}
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def list_store_items_for_member(
    member_id: str, household_id: str
) -> list[aiosqlite.Row]:
    """
    Return store items visible to the given member:
      - All available global items (no visibility rows), plus
      - Available items explicitly targeted to this member.
    """
    return await fetch_all(
        """
        SELECT si.*
        FROM store_item si
        WHERE si.household_id = ?
          AND si.is_available = 1
          AND (
              -- global: no visibility rows at all
              NOT EXISTS (
                  SELECT 1 FROM store_item_visibility siv WHERE siv.store_item_id = si.id
              )
              OR
              -- targeted: this member is in the visibility list
              EXISTS (
                  SELECT 1 FROM store_item_visibility siv
                  WHERE siv.store_item_id = si.id AND siv.member_id = ?
              )
          )
        ORDER BY si.title
        """,
        (household_id, member_id),
    )


async def list_all_store_items(household_id: str) -> list[aiosqlite.Row]:
    """Return all store items for a household (admin view, includes unavailable)."""
    return await fetch_all(
        "SELECT * FROM store_item WHERE household_id = ? ORDER BY title",
        (household_id,),
    )


async def get_store_item(item_id: str) -> aiosqlite.Row | None:
    """Return a single store item row or None."""
    return await fetch_one("SELECT * FROM store_item WHERE id = ?", (item_id,))


async def get_item_visibility(item_id: str) -> list[aiosqlite.Row]:
    """Return the visibility list (member rows) for an item."""
    return await fetch_all(
        """
        SELECT siv.member_id, fm.name AS member_name
        FROM store_item_visibility siv
        JOIN family_member fm ON fm.id = siv.member_id
        WHERE siv.store_item_id = ?
        """,
        (item_id,),
    )


async def create_store_item(
    household_id: str,
    title: str,
    description: str,
    icon: str,
    price: int,
    is_available: bool,
    stock: int | None,
    member_ids: list[str] | None = None,
) -> aiosqlite.Row:
    """
    Insert a store item. If member_ids is provided and non-empty,
    creates visibility rows to restrict who can see it.
    Returns the new item row.
    """
    item_id = str(uuid.uuid4())
    now = _now_iso()
    db = await get_db()

    await db.execute(
        """
        INSERT INTO store_item
            (id, household_id, title, description, icon, price, is_available, stock, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (item_id, household_id, title, description, icon, price, int(is_available), stock, now),
    )

    if member_ids:
        for member_id in member_ids:
            await db.execute(
                "INSERT OR IGNORE INTO store_item_visibility (store_item_id, member_id) VALUES (?, ?)",
                (item_id, member_id),
            )

    await db.commit()
    row = await get_store_item(item_id)
    assert row is not None
    return row


async def update_store_item(item_id: str, **fields: Any) -> aiosqlite.Row | None:
    """Update store item fields."""
    invalid = set(fields) - _UPDATABLE_FIELDS
    if invalid:
        raise ValueError(f"Unknown field(s) for store_item: {invalid}")
    if not fields:
        return await get_store_item(item_id)

    set_clause = ", ".join(f"{col} = ?" for col in fields)
    values = list(fields.values()) + [item_id]
    await execute(f"UPDATE store_item SET {set_clause} WHERE id = ?", values)
    return await get_store_item(item_id)


async def set_visibility(item_id: str, member_ids: list[str]) -> None:
    """
    Replace the visibility list for an item.
    Empty list = global (no rows = visible to all).
    """
    db = await get_db()
    await db.execute(
        "DELETE FROM store_item_visibility WHERE store_item_id = ?",
        (item_id,),
    )
    for member_id in member_ids:
        await db.execute(
            "INSERT OR IGNORE INTO store_item_visibility (store_item_id, member_id) VALUES (?, ?)",
            (item_id, member_id),
        )
    await db.commit()


async def delete_store_item(item_id: str) -> None:
    """Hard-delete a store item (visibility rows cascade)."""
    await execute("DELETE FROM store_item WHERE id = ?", (item_id,))


async def decrement_stock(item_id: str) -> bool:
    """
    Decrement stock by 1 if stock is not NULL and > 0.
    Returns True on success, False if out of stock or stock is not tracked.
    """
    db = await get_db()
    cursor = await db.execute(
        """
        UPDATE store_item
        SET stock = stock - 1
        WHERE id = ?
          AND stock IS NOT NULL
          AND stock > 0
        """,
        (item_id,),
    )
    await db.commit()
    return cursor.rowcount > 0
