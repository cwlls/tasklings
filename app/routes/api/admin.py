"""
Admin API routes -- /api/v1/admin/*

All endpoints require admin_required (parent role).

POST /api/v1/admin/members/<id>/set-password   -- hard-set any member's password
GET  /api/v1/admin/members/<id>/reset-token    -- retrieve active reset token (email fallback)
"""
from __future__ import annotations

from quart import Blueprint, jsonify, request

from app.middleware.auth import admin_required
from app.models import auth as auth_model
from app.models import members as members_model
from app.services.auth import (
    set_password as svc_set_password,
    request_password_reset as svc_reset_request,
)

admin_api_bp = Blueprint("admin_api", __name__, url_prefix="/api/v1/admin")


def _err(message: str, code: str, status: int):
    return jsonify({"error": message, "code": code}), status


# ---------------------------------------------------------------------------
# POST /api/v1/admin/members/<id>/set-password
# ---------------------------------------------------------------------------

@admin_api_bp.post("/members/<member_id>/set-password")
@admin_required
async def admin_set_password(member_id: str):
    """Hard-set a member's password without knowing the old one."""
    member = await members_model.get_member_by_id(member_id)
    if member is None:
        return _err("Member not found.", "NOT_FOUND", 404)

    body = await request.get_json(silent=True) or {}
    new_password = body.get("new_password") or ""

    if not new_password:
        return _err("new_password is required.", "MISSING_FIELDS", 400)
    if len(new_password) < 8:
        return _err("Password must be at least 8 characters.", "PASSWORD_TOO_SHORT", 400)

    await svc_set_password(member_id, new_password)
    return jsonify({"ok": True}), 200


# ---------------------------------------------------------------------------
# GET /api/v1/admin/members/<id>/reset-token
# ---------------------------------------------------------------------------

@admin_api_bp.get("/members/<member_id>/reset-token")
@admin_required
async def admin_get_reset_token(member_id: str):
    """
    Return the active (unexpired, unused) password reset token for a member.

    This is the admin fallback when email delivery is not configured.
    The raw token is NOT stored -- only the hash is stored. So this endpoint
    generates a fresh token each time it is called (or returns 404 if one
    was already generated and is still active, pointing the admin to use
    reset-request to generate a new one).

    Design: call POST /api/v1/auth/reset-request first, then this endpoint
    to retrieve the raw token. The token is stored in the DB as a hash;
    we cannot reverse it. So we generate a new one here on demand.
    """
    member = await members_model.get_member_by_id(member_id)
    if member is None:
        return _err("Member not found.", "NOT_FOUND", 404)

    # Generate a fresh reset token for admin delivery.
    result = await svc_reset_request(member["username"])

    if not result.get("token_id"):
        return _err("Could not generate a reset token for this member.", "TOKEN_ERROR", 500)

    return jsonify({
        "token_id": result["token_id"],
        "raw_token": result["raw_token"],
        "note": "This token expires in 1 hour. Deliver it to the member securely.",
    }), 200
