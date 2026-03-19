"""
Store view routes.

Blueprint: store_views
Routes:
  GET  /store          -- browseable store page for the current member
  POST /store/:id/buy  -- HTMX purchase action; returns _item_card.html or
                          _purchase_result.html partial
"""
from __future__ import annotations

from quart import Blueprint, g, render_template, request

from app.middleware.auth import login_required
from app.models import store as store_model
from app.models.household import get_household
from app.services.store import (
    InsufficientBalanceError,
    ItemNotAvailableError,
    ItemNotVisibleError,
    OutOfStockError,
    purchase_item,
)

store_views = Blueprint("store_views", __name__)


@store_views.get("/purchases")
@login_required
async def purchases_page():
    caller = g.current_user
    from app.models import purchases as purchases_model
    rows = await purchases_model.list_purchases_for_member(caller["id"])
    return await render_template(
        "purchases/index.html",
        member=caller,
        purchases=[dict(r) for r in rows],
    )


@store_views.get("/store")
@login_required
async def store_page():
    caller = g.current_user
    household = await get_household()

    if caller["role"] == "parent":
        items = await store_model.list_all_store_items(household["id"])
    else:
        items = await store_model.list_store_items_for_member(caller["id"], household["id"])

    items_dicts = [dict(i) for i in items]

    if request.headers.get("HX-Request"):
        return await render_template(
            "store/_item_grid.html",
            items=items_dicts,
            balance=caller["balance"],
        )

    return await render_template(
        "store/index.html",
        member=caller,
        items=items_dicts,
        balance=caller["balance"],
    )


@store_views.post("/store/<item_id>/buy")
@login_required
async def buy_item_htmx(item_id: str):
    caller = g.current_user
    error = None
    purchase = None

    try:
        purchase = await purchase_item(caller["id"], item_id)
    except ItemNotVisibleError:
        error = "Item not found."
    except ItemNotAvailableError:
        error = "This item is no longer available."
    except OutOfStockError:
        error = "This item is out of stock."
    except InsufficientBalanceError:
        error = "You don't have enough Lumins for this item."

    # Reload the item for the card re-render (balance may have changed).
    item = await store_model.get_store_item(item_id)

    # Refresh the caller's balance from DB so the card shows the new amount.
    from app.models import members as members_model
    fresh_member = await members_model.get_member_by_id(caller["id"])
    balance = fresh_member["balance"] if fresh_member else caller["balance"]

    return await render_template(
        "store/_purchase_result.html",
        item=dict(item) if item else None,
        purchase=dict(purchase) if purchase else None,
        error=error,
        balance=balance,
    )
