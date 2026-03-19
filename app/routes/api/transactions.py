"""
Transaction / Lumin ledger API routes.

Blueprint prefix: /api/v1
"""
from __future__ import annotations

from quart import Blueprint, g, jsonify, request

from app.middleware.auth import admin_required, login_required
from app.models import members as members_model
from app.models import transactions as tx_model
from app.models.household import get_household
from app.models.db import fetch_all
from app.services.currency import adjust_lumins, get_balance, InsufficientBalanceError

transactions_api = Blueprint("transactions_api", __name__, url_prefix="/api/v1")

_VALID_ADJUSTMENT_REASONS = frozenset({"bonus", "penalty", "adjustment"})


def _pagination_params() -> tuple[int, int]:
    """Parse and clamp ?limit= and ?offset= from the current request args."""
    try:
        limit = min(int(request.args.get("limit", 50)), 200)
        offset = max(int(request.args.get("offset", 0)), 0)
    except ValueError:
        limit, offset = 50, 0
    return limit, offset


# ---------------------------------------------------------------------------
# GET /api/v1/transactions  -- household-wide ledger (admin)
# ---------------------------------------------------------------------------

@transactions_api.get("/transactions")
@admin_required
async def list_all_transactions():
    household = await get_household()
    if household is None:
        return jsonify({"error": "No household found"}), 500

    limit, offset = _pagination_params()

    rows = await fetch_all(
        """
        SELECT lt.*, fm.name AS member_name, fm.username
        FROM lumin_transaction lt
        JOIN family_member fm ON fm.id = lt.member_id
        WHERE fm.household_id = ?
        ORDER BY lt.created_at DESC
        LIMIT ? OFFSET ?
        """,
        (household["id"], limit, offset),
    )
    return jsonify({
        "transactions": [dict(r) for r in rows],
        "limit": limit,
        "offset": offset,
    })


# ---------------------------------------------------------------------------
# GET /api/v1/members/:id/transactions  -- per-member ledger (admin or self)
# ---------------------------------------------------------------------------

@transactions_api.get("/members/<member_id>/transactions")
@login_required
async def member_transactions(member_id: str):
    caller = g.current_user
    is_admin = caller["role"] == "parent"
    is_self  = caller["id"] == member_id

    if not is_admin and not is_self:
        return jsonify({"error": "Forbidden"}), 403

    target = await members_model.get_member_by_id(member_id)
    if target is None:
        return jsonify({"error": "Member not found"}), 404

    limit, offset = _pagination_params()
    rows = await tx_model.list_transactions_for_member(member_id, limit=limit, offset=offset)
    return jsonify({
        "member_id": member_id,
        "transactions": [dict(r) for r in rows],
        "limit": limit,
        "offset": offset,
    })


# ---------------------------------------------------------------------------
# GET /api/v1/members/:id/balance  -- balance (admin or self)
# ---------------------------------------------------------------------------

@transactions_api.get("/members/<member_id>/balance")
@login_required
async def member_balance(member_id: str):
    caller = g.current_user
    is_admin = caller["role"] == "parent"
    is_self  = caller["id"] == member_id

    if not is_admin and not is_self:
        return jsonify({"error": "Forbidden"}), 403

    target = await members_model.get_member_by_id(member_id)
    if target is None:
        return jsonify({"error": "Member not found"}), 404

    balance = await get_balance(member_id)
    return jsonify({"member_id": member_id, "balance": balance})


# ---------------------------------------------------------------------------
# POST /api/v1/members/:id/lumins/adjust  -- manual adjustment (admin)
# ---------------------------------------------------------------------------

@transactions_api.post("/members/<member_id>/lumins/adjust")
@admin_required
async def adjust_member_lumins(member_id: str):
    target = await members_model.get_member_by_id(member_id)
    if target is None:
        return jsonify({"error": "Member not found"}), 404

    body = await request.get_json(force=True, silent=True) or {}

    try:
        amount = int(body.get("amount", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be an integer"}), 400

    if amount == 0:
        return jsonify({"error": "amount must be non-zero"}), 400

    reason = (body.get("reason") or "").strip()
    if reason not in _VALID_ADJUSTMENT_REASONS:
        return jsonify({
            "error": f"reason must be one of: {sorted(_VALID_ADJUSTMENT_REASONS)}"
        }), 400

    try:
        new_balance = await adjust_lumins(member_id, amount, reason)
    except InsufficientBalanceError as exc:
        return jsonify({"error": str(exc)}), 409

    return jsonify({"member_id": member_id, "new_balance": new_balance, "amount": amount})
