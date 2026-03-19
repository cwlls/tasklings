"""
Store and purchases API routes.

Blueprint prefix: /api/v1
"""
from __future__ import annotations

from quart import Blueprint, g, jsonify, request

from app.middleware.auth import admin_required, login_required
from app.models import purchases as purchases_model
from app.models import store as store_model
from app.models.household import get_household
from app.services.store import (
    InsufficientBalanceError,
    ItemNotAvailableError,
    ItemNotVisibleError,
    OutOfStockError,
    purchase_item,
    redeem_purchase,
)

store_api = Blueprint("store_api", __name__, url_prefix="/api/v1")


async def _item_detail(item) -> dict:
    """Augment an item row with its visibility list."""
    data = dict(item)
    vis = await store_model.get_item_visibility(item["id"])
    data["member_ids"] = [v["member_id"] for v in vis]
    data["is_global"] = len(data["member_ids"]) == 0
    return data


# ---------------------------------------------------------------------------
# Store item CRUD
# ---------------------------------------------------------------------------

@store_api.get("/store")
@login_required
async def list_store():
    household = await get_household()
    if household is None:
        return jsonify({"error": "No household found"}), 500

    caller = g.current_user
    if caller["role"] == "parent":
        rows = await store_model.list_all_store_items(household["id"])
    else:
        rows = await store_model.list_store_items_for_member(caller["id"], household["id"])

    return jsonify({"items": [dict(r) for r in rows]})


@store_api.post("/store")
@admin_required
async def create_store_item():
    household = await get_household()
    if household is None:
        return jsonify({"error": "No household found"}), 500

    body = await request.get_json(force=True, silent=True) or {}

    title = (body.get("title") or body.get("name") or "").strip()
    if not title:
        return jsonify({"error": "title is required"}), 400

    try:
        price = int(body.get("price", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "price must be an integer"}), 400
    if price < 0:
        return jsonify({"error": "price must be >= 0"}), 400

    stock_raw = body.get("stock")
    if stock_raw is None or stock_raw == -1:
        stock = None          # unlimited
    else:
        try:
            stock = int(stock_raw)
        except (TypeError, ValueError):
            return jsonify({"error": "stock must be an integer or -1 for unlimited"}), 400

    member_ids = body.get("member_ids") or []

    item = await store_model.create_store_item(
        household_id=household["id"],
        title=title,
        description=body.get("description", ""),
        icon=body.get("icon", ""),
        price=price,
        is_available=bool(body.get("is_available", True)),
        stock=stock,
        member_ids=member_ids if member_ids else None,
    )
    return jsonify({"item": await _item_detail(item)}), 201


@store_api.get("/store/<item_id>")
@login_required
async def get_store_item(item_id: str):
    household = await get_household()
    item = await store_model.get_store_item(item_id)
    if item is None:
        return jsonify({"error": "Item not found"}), 404

    caller = g.current_user
    if caller["role"] != "parent":
        # Verify the item is visible to this member.
        visible = await store_model.list_store_items_for_member(caller["id"], household["id"])
        if not any(v["id"] == item_id for v in visible):
            return jsonify({"error": "Item not found"}), 404

    return jsonify({"item": await _item_detail(item)})


@store_api.put("/store/<item_id>")
@admin_required
async def update_store_item(item_id: str):
    item = await store_model.get_store_item(item_id)
    if item is None:
        return jsonify({"error": "Item not found"}), 404

    body = await request.get_json(force=True, silent=True) or {}
    allowed = {"title", "description", "icon", "price", "is_available", "stock"}
    fields = {k: v for k, v in body.items() if k in allowed}

    if "price" in fields:
        try:
            fields["price"] = int(fields["price"])
        except (TypeError, ValueError):
            return jsonify({"error": "price must be an integer"}), 400

    if "stock" in fields:
        if fields["stock"] == -1:
            fields["stock"] = None
        elif fields["stock"] is not None:
            try:
                fields["stock"] = int(fields["stock"])
            except (TypeError, ValueError):
                return jsonify({"error": "stock must be an integer or -1"}), 400

    updated = await store_model.update_store_item(item_id, **fields)
    return jsonify({"item": await _item_detail(updated)})


@store_api.delete("/store/<item_id>")
@admin_required
async def deactivate_store_item(item_id: str):
    item = await store_model.get_store_item(item_id)
    if item is None:
        return jsonify({"error": "Item not found"}), 404

    await store_model.update_store_item(item_id, is_available=0)
    return jsonify({"ok": True})


@store_api.put("/store/<item_id>/visibility")
@admin_required
async def set_item_visibility(item_id: str):
    item = await store_model.get_store_item(item_id)
    if item is None:
        return jsonify({"error": "Item not found"}), 404

    body = await request.get_json(force=True, silent=True) or {}
    member_ids = body.get("member_ids") or []
    await store_model.set_visibility(item_id, member_ids)
    return jsonify({"item_id": item_id, "member_ids": member_ids, "is_global": len(member_ids) == 0})


# ---------------------------------------------------------------------------
# Purchase flow
# ---------------------------------------------------------------------------

@store_api.post("/store/<item_id>/purchase")
@login_required
async def buy_item(item_id: str):
    caller = g.current_user
    try:
        purchase = await purchase_item(caller["id"], item_id)
    except ItemNotVisibleError as exc:
        return jsonify({"error": str(exc)}), 404
    except ItemNotAvailableError as exc:
        return jsonify({"error": str(exc)}), 410
    except OutOfStockError as exc:
        return jsonify({"error": str(exc)}), 409
    except InsufficientBalanceError as exc:
        return jsonify({"error": str(exc)}), 402

    return jsonify({"purchase": dict(purchase)}), 201


# ---------------------------------------------------------------------------
# Purchases
# ---------------------------------------------------------------------------

@store_api.get("/purchases")
@login_required
async def list_my_purchases():
    caller = g.current_user
    rows = await purchases_model.list_purchases_for_member(caller["id"])
    return jsonify({"purchases": [dict(r) for r in rows]})


@store_api.get("/purchases/<purchase_id>")
@login_required
async def get_purchase(purchase_id: str):
    caller = g.current_user
    purchase = await purchases_model.get_purchase(purchase_id)
    if purchase is None:
        return jsonify({"error": "Purchase not found"}), 404

    is_admin = caller["role"] == "parent"
    is_owner = purchase["member_id"] == caller["id"]
    if not is_admin and not is_owner:
        return jsonify({"error": "Forbidden"}), 403

    return jsonify({"purchase": dict(purchase)})


@store_api.post("/purchases/<purchase_id>/redeem")
@admin_required
async def redeem_purchase_route(purchase_id: str):
    try:
        purchase = await redeem_purchase(purchase_id, g.current_user["id"])
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409

    return jsonify({"purchase": dict(purchase)})
