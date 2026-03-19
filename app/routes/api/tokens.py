"""
API token management routes -- /api/v1/tokens

GET    /api/v1/tokens          -- list tokens for the current member's household
POST   /api/v1/tokens          -- create a new token (admin only)
DELETE /api/v1/tokens/<id>     -- revoke a token (admin or owner)
"""
from __future__ import annotations

from quart import Blueprint, g, jsonify, request

from app.middleware.auth import login_required, admin_required
from app.models import auth as auth_model
from app.models.household import get_household
from app.services.auth import create_api_token as svc_create_token

tokens_api_bp = Blueprint("tokens_api", __name__, url_prefix="/api/v1/tokens")


def _err(message: str, code: str, status: int):
    return jsonify({"error": message, "code": code}), status


def _token_row_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "member_id": row["member_id"],
        "label": row["label"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "is_revoked": bool(row["is_revoked"]),
    }


# ---------------------------------------------------------------------------
# GET /api/v1/tokens
# ---------------------------------------------------------------------------

@tokens_api_bp.get("")
@admin_required
async def list_tokens():
    household = await get_household()
    if household is None:
        return _err("Household not found.", "NO_HOUSEHOLD", 500)

    rows = await auth_model.list_api_tokens(household["id"])
    return jsonify({"tokens": [_token_row_to_dict(r) for r in rows]}), 200


# ---------------------------------------------------------------------------
# POST /api/v1/tokens
# ---------------------------------------------------------------------------

@tokens_api_bp.post("")
@admin_required
async def create_token():
    body = await request.get_json(silent=True) or {}
    label = (body.get("label") or "").strip()
    expires_at = body.get("expires_at")  # ISO string or None

    if not label:
        return _err("label is required.", "MISSING_FIELDS", 400)

    result = await svc_create_token(
        member_id=g.current_user["id"],
        label=label,
        expires_at=expires_at,
    )
    return jsonify({
        "token_id": result["token_id"],
        "token": result["raw_token"],   # shown once
    }), 201


# ---------------------------------------------------------------------------
# DELETE /api/v1/tokens/<token_id>
# ---------------------------------------------------------------------------

@tokens_api_bp.delete("/<token_id>")
@login_required
async def revoke_token(token_id: str):
    """
    Any admin can revoke any token.
    A non-admin member can only revoke their own tokens.
    """
    # Fetch the token to verify ownership before revoking.
    from app.models.db import fetch_one
    token_row = await fetch_one(
        "SELECT * FROM api_token WHERE id = ?", (token_id,)
    )
    if token_row is None:
        return _err("Token not found.", "NOT_FOUND", 404)

    user = g.current_user
    if user["role"] != "parent" and token_row["member_id"] != user["id"]:
        return _err("You can only revoke your own tokens.", "FORBIDDEN", 403)

    await auth_model.revoke_api_token(token_id)
    return jsonify({"ok": True}), 200
