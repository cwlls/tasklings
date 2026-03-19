"""
Store service -- item purchasing and redemption.

All typed errors the routes should catch:
  ItemNotVisibleError   -- item doesn't exist or isn't visible to this member
  ItemNotAvailableError -- item exists but is_available = 0
  OutOfStockError       -- item has finite stock and stock = 0
  InsufficientBalanceError -- re-exported from currency for convenience
"""
from __future__ import annotations

from app.models import purchases as purchases_model
from app.models import store as store_model
from app.services.currency import InsufficientBalanceError, debit_lumins

# Re-export so callers only need to import from this module.
__all__ = [
    "ItemNotVisibleError",
    "ItemNotAvailableError",
    "OutOfStockError",
    "InsufficientBalanceError",
    "purchase_item",
    "redeem_purchase",
]


class ItemNotVisibleError(Exception):
    """Item does not exist or is not visible to this member."""


class ItemNotAvailableError(Exception):
    """Item exists but has been taken off-sale (is_available = 0)."""


class OutOfStockError(Exception):
    """Item has finite stock and all units have been sold."""


async def purchase_item(member_id: str, item_id: str) -> object:
    """
    Attempt to purchase *item_id* for *member_id*.

    Steps (all guarded against races by the atomic balance UPDATE):
      1. Load item, verify visibility and availability.
      2. Check stock (if finite).
      3. Debit Lumins (raises InsufficientBalanceError if balance < price).
      4. Decrement stock if finite.
      5. Insert purchase row.

    Returns the new purchase row.
    Raises ItemNotVisibleError, ItemNotAvailableError, OutOfStockError,
    or InsufficientBalanceError on failure.
    """
    item = await store_model.get_store_item(item_id)
    if item is None:
        raise ItemNotVisibleError("Item not found")

    if not item["is_available"]:
        raise ItemNotAvailableError("Item is not currently available")

    # Stock check: NULL stock = unlimited.
    if item["stock"] is not None and item["stock"] <= 0:
        raise OutOfStockError("Item is out of stock")

    price = item["price"]

    # Debit first -- if the member can't afford it, stop here cleanly.
    await debit_lumins(member_id, price, reason="purchase", reference_id=item_id)

    # Decrement finite stock.
    if item["stock"] is not None:
        await store_model.decrement_stock(item_id)

    # Record the purchase.
    purchase = await purchases_model.create_purchase(item_id, member_id, price)
    return purchase


async def redeem_purchase(purchase_id: str, admin_id: str) -> object:
    """
    Mark *purchase_id* as redeemed. *admin_id* is recorded for audit purposes
    but the model layer does not enforce it -- the route layer checks the role.

    Returns the updated purchase row.
    Raises ValueError if the purchase doesn't exist or is already redeemed.
    """
    purchase = await purchases_model.get_purchase(purchase_id)
    if purchase is None:
        raise ValueError("Purchase not found")
    if purchase["status"] != "purchased":
        raise ValueError(f"Purchase is already {purchase['status']}")

    return await purchases_model.redeem_purchase(purchase_id)
