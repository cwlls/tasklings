"""
Chore definition API routes.

Blueprint prefix: /api/v1
"""
from __future__ import annotations

from quart import Blueprint, g, jsonify, request

from app.middleware.auth import admin_required, login_required
from app.models import chores as chores_model
from app.models import rotation as rotation_model
from app.models.household import get_household

chores_api = Blueprint("chores_api", __name__, url_prefix="/api/v1")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _chore_detail(chore_row) -> dict:
    """Augment a chore row with its assignees and rotation schedule."""
    data = dict(chore_row)
    if chore_row["chore_type"] == "constant":
        data["assignee_ids"] = await chores_model.get_assignees_for_chore(chore_row["id"])
    else:
        schedule = await rotation_model.get_rotation_schedule(chore_row["id"])
        data["rotation_schedule"] = [dict(e) for e in schedule]
    return data


# ---------------------------------------------------------------------------
# List / create
# ---------------------------------------------------------------------------

@chores_api.get("/chores")
@login_required
async def list_chores():
    household = await get_household()
    if household is None:
        return jsonify({"error": "No household found"}), 500

    include_inactive = request.args.get("include_inactive", "false").lower() == "true"
    rows = await chores_model.list_chore_definitions(
        household["id"], active_only=not include_inactive
    )
    return jsonify({"chores": [dict(r) for r in rows]})


@chores_api.post("/chores")
@admin_required
async def create_chore():
    household = await get_household()
    if household is None:
        return jsonify({"error": "No household found"}), 500

    body = await request.get_json(force=True, silent=True) or {}

    title = (body.get("title") or "").strip()
    if not title:
        return jsonify({"error": "title is required"}), 400

    chore_type = body.get("chore_type", "constant")
    if chore_type not in ("constant", "rotating"):
        return jsonify({"error": "chore_type must be 'constant' or 'rotating'"}), 400

    rotation_frequency = body.get("rotation_frequency")
    if chore_type == "rotating" and rotation_frequency not in ("daily", "weekly", "monthly"):
        return jsonify({
            "error": "rotation_frequency must be 'daily', 'weekly', or 'monthly' for rotating chores"
        }), 400

    try:
        lumin_value = int(body.get("lumin_value", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "lumin_value must be an integer"}), 400

    chore = await chores_model.create_chore_definition(
        household_id=household["id"],
        title=title,
        description=body.get("description", ""),
        icon=body.get("icon", ""),
        lumin_value=lumin_value,
        chore_type=chore_type,
        rotation_frequency=rotation_frequency if chore_type == "rotating" else None,
    )

    # Wire up assignees / rotation on creation.
    if chore_type == "constant":
        assignee_ids = body.get("assignee_ids") or []
        if assignee_ids:
            await chores_model.set_assignees_for_chore(chore["id"], assignee_ids)

    elif chore_type == "rotating":
        rotation_members = body.get("rotation_members") or []
        if rotation_members:
            entries = [
                {"member_id": mid, "order_index": i}
                for i, mid in enumerate(rotation_members)
            ]
            await rotation_model.set_rotation_schedule(chore["id"], entries)

    detail = await _chore_detail(chore)
    return jsonify({"chore": detail}), 201


# ---------------------------------------------------------------------------
# Get / update / delete single chore
# ---------------------------------------------------------------------------

@chores_api.get("/chores/<chore_id>")
@login_required
async def get_chore(chore_id: str):
    chore = await chores_model.get_chore_definition(chore_id)
    if chore is None:
        return jsonify({"error": "Chore not found"}), 404
    return jsonify({"chore": await _chore_detail(chore)})


@chores_api.put("/chores/<chore_id>")
@admin_required
async def update_chore(chore_id: str):
    chore = await chores_model.get_chore_definition(chore_id)
    if chore is None:
        return jsonify({"error": "Chore not found"}), 404

    body = await request.get_json(force=True, silent=True) or {}

    allowed = {"title", "description", "icon", "lumin_value", "rotation_frequency"}
    fields = {k: v for k, v in body.items() if k in allowed}

    if "lumin_value" in fields:
        try:
            fields["lumin_value"] = int(fields["lumin_value"])
        except (TypeError, ValueError):
            return jsonify({"error": "lumin_value must be an integer"}), 400

    updated = await chores_model.update_chore_definition(chore_id, **fields)
    return jsonify({"chore": await _chore_detail(updated)})


@chores_api.delete("/chores/<chore_id>")
@admin_required
async def delete_chore(chore_id: str):
    chore = await chores_model.get_chore_definition(chore_id)
    if chore is None:
        return jsonify({"error": "Chore not found"}), 404

    await chores_model.deactivate_chore_definition(chore_id)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Assignees (constant chores)
# ---------------------------------------------------------------------------

@chores_api.put("/chores/<chore_id>/assignees")
@admin_required
async def set_assignees(chore_id: str):
    chore = await chores_model.get_chore_definition(chore_id)
    if chore is None:
        return jsonify({"error": "Chore not found"}), 404

    if chore["chore_type"] != "constant":
        return jsonify({"error": "Only constant chores have assignees"}), 400

    body = await request.get_json(force=True, silent=True) or {}
    member_ids = body.get("member_ids") or []
    await chores_model.set_assignees_for_chore(chore_id, member_ids)
    return jsonify({"assignee_ids": member_ids})


# ---------------------------------------------------------------------------
# Rotation schedule (rotating chores)
# ---------------------------------------------------------------------------

@chores_api.get("/chores/<chore_id>/rotation")
@login_required
async def get_rotation(chore_id: str):
    chore = await chores_model.get_chore_definition(chore_id)
    if chore is None:
        return jsonify({"error": "Chore not found"}), 404

    schedule = await rotation_model.get_rotation_schedule(chore_id)
    return jsonify({"rotation": [dict(e) for e in schedule]})


@chores_api.put("/chores/<chore_id>/rotation")
@admin_required
async def set_rotation(chore_id: str):
    chore = await chores_model.get_chore_definition(chore_id)
    if chore is None:
        return jsonify({"error": "Chore not found"}), 404

    if chore["chore_type"] != "rotating":
        return jsonify({"error": "Only rotating chores have a rotation schedule"}), 400

    body = await request.get_json(force=True, silent=True) or {}
    members = body.get("member_ids") or []
    entries = [{"member_id": mid, "order_index": i} for i, mid in enumerate(members)]
    await rotation_model.set_rotation_schedule(chore_id, entries)
    schedule = await rotation_model.get_rotation_schedule(chore_id)
    return jsonify({"rotation": [dict(e) for e in schedule]})


@chores_api.post("/chores/<chore_id>/rotation/advance")
@admin_required
async def advance_rotation(chore_id: str):
    chore = await chores_model.get_chore_definition(chore_id)
    if chore is None:
        return jsonify({"error": "Chore not found"}), 404

    next_member_id = await rotation_model.advance_rotation(chore_id)
    return jsonify({"next_member_id": next_member_id})
