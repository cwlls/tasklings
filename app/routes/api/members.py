"""
Member and Household API routes.

Blueprint prefix: /api/v1
"""
from __future__ import annotations

from quart import Blueprint, g, jsonify, request

from app.middleware.auth import admin_required, login_required
from app.models import members as members_model
from app.models.household import get_household, update_household
from app.services.auth import hash_password

members_api = Blueprint("members_api", __name__, url_prefix="/api/v1")

# Fields a child member may update on their own profile.
_SELF_UPDATABLE = frozenset({"name", "avatar", "color"})

# Sensitive fields never returned to non-admin callers.
_STRIP_SENSITIVE = {"password_hash"}


def _public(row: dict) -> dict:
    """Strip fields that non-admin callers should not see."""
    return {k: v for k, v in row.items() if k not in _STRIP_SENSITIVE}


# ---------------------------------------------------------------------------
# Household endpoints
# ---------------------------------------------------------------------------

@members_api.get("/household")
@login_required
async def get_household_info():
    household = await get_household()
    if household is None:
        return jsonify({"error": "No household found"}), 500
    return jsonify({"household": dict(household)})


@members_api.put("/household")
@admin_required
async def update_household_info():
    body = await request.get_json(force=True, silent=True) or {}

    name = (body.get("name") or "").strip()
    timezone = (body.get("timezone") or "").strip()

    if not name and not timezone:
        return jsonify({"error": "Provide at least one of: name, timezone"}), 400

    household = await get_household()
    if household is None:
        return jsonify({"error": "No household found"}), 500

    updated = await update_household(
        name=name or household["name"],
        timezone=timezone or household["timezone"],
    )
    return jsonify({"household": dict(updated)})


# ---------------------------------------------------------------------------
# Member list / create
# ---------------------------------------------------------------------------

@members_api.get("/members")
@login_required
async def list_members():
    household = await get_household()
    if household is None:
        return jsonify({"error": "No household found"}), 500

    caller = g.current_user
    include_inactive = (
        caller["role"] == "parent"
        and request.args.get("include_inactive", "false").lower() == "true"
    )
    rows = await members_model.list_members(household["id"], include_inactive=include_inactive)

    if caller["role"] == "parent":
        return jsonify({"members": [_public(dict(r)) for r in rows]})

    # Children only see minimal public info.
    return jsonify({
        "members": [
            {"id": r["id"], "name": r["name"], "avatar": r["avatar"], "color": r["color"]}
            for r in rows
        ]
    })


@members_api.post("/members")
@admin_required
async def create_member():
    household = await get_household()
    if household is None:
        return jsonify({"error": "No household found"}), 500

    body = await request.get_json(force=True, silent=True) or {}

    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    name = (body.get("name") or "").strip()
    role = body.get("role", "child")

    if not username:
        return jsonify({"error": "username is required"}), 400
    if len(password) < 6:
        return jsonify({"error": "password must be at least 6 characters"}), 400
    if not name:
        return jsonify({"error": "name is required"}), 400
    if role not in ("parent", "child"):
        return jsonify({"error": "role must be 'parent' or 'child'"}), 400

    pw_hash = hash_password(password)
    member = await members_model.create_member(
        household_id=household["id"],
        username=username,
        password_hash=pw_hash,
        name=name,
        role=role,
        avatar=body.get("avatar", ""),
        color=body.get("color", "#4A90D9"),
    )
    return jsonify({"member": _public(dict(member))}), 201


# ---------------------------------------------------------------------------
# Get / update / deactivate a single member
# ---------------------------------------------------------------------------

@members_api.get("/members/<member_id>")
@login_required
async def get_member(member_id: str):
    caller = g.current_user
    is_admin = caller["role"] == "parent"
    is_self = caller["id"] == member_id

    if not is_admin and not is_self:
        return jsonify({"error": "Forbidden"}), 403

    row = await members_model.get_member_by_id(member_id)
    if row is None:
        return jsonify({"error": "Member not found"}), 404

    return jsonify({"member": _public(dict(row))})


@members_api.put("/members/<member_id>")
@login_required
async def update_member(member_id: str):
    caller = g.current_user
    is_admin = caller["role"] == "parent"
    is_self = caller["id"] == member_id

    if not is_admin and not is_self:
        return jsonify({"error": "Forbidden"}), 403

    row = await members_model.get_member_by_id(member_id)
    if row is None:
        return jsonify({"error": "Member not found"}), 404

    body = await request.get_json(force=True, silent=True) or {}

    allowed = set(members_model._UPDATABLE_FIELDS) - {"password_hash", "is_active"}
    if not is_admin:
        allowed &= _SELF_UPDATABLE

    fields = {k: v for k, v in body.items() if k in allowed}
    if not fields:
        return jsonify({"member": _public(dict(row))})

    updated = await members_model.update_member(member_id, **fields)
    return jsonify({"member": _public(dict(updated))})


@members_api.delete("/members/<member_id>")
@admin_required
async def deactivate_member(member_id: str):
    row = await members_model.get_member_by_id(member_id)
    if row is None:
        return jsonify({"error": "Member not found"}), 404

    await members_model.deactivate_member(member_id)
    return jsonify({"ok": True})
