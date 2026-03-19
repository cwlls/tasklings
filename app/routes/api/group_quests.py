"""
Group Quest API routes.

Blueprint prefix: /api/v1
"""
from __future__ import annotations

from quart import Blueprint, g, jsonify, request

from app.middleware.auth import admin_required, login_required
from app.models import group_quests as gq_model
from app.models.household import get_household
from app.services.group_quests import (
    AlreadyMemberError,
    ChoreAlreadyCompleteError,
    NotMemberError,
    QuestAlreadyCompleteError,
    claim_chore,
    complete_chore,
    join_group_quest,
    leave_group_quest,
    release_claim,
)

group_quests_api = Blueprint("group_quests_api", __name__, url_prefix="/api/v1")


async def _gq_detail(gq) -> dict:
    data = dict(gq)
    progress = await gq_model.get_progress(gq["id"])
    data["chores"] = progress
    contributions = await gq_model.get_contributions(gq["id"])
    data["contributions"] = contributions
    return data


# ---------------------------------------------------------------------------
# List / create
# ---------------------------------------------------------------------------

@group_quests_api.get("/group-quests")
@login_required
async def list_group_quests():
    caller = g.current_user
    if caller["role"] == "parent":
        household = await get_household()
        rows = await gq_model.list_all_group_quests(household["id"])
    else:
        rows = await gq_model.list_group_quests_for_member(caller["id"])
    return jsonify({"group_quests": [dict(r) for r in rows]})


@group_quests_api.post("/group-quests")
@admin_required
async def create_group_quest():
    household = await get_household()
    if household is None:
        return jsonify({"error": "No household found"}), 500

    body = await request.get_json(force=True, silent=True) or {}

    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    try:
        bonus_lumins = int(body.get("bonus_lumins", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "bonus_lumins must be an integer"}), 400

    gq = await gq_model.create_group_quest(
        household_id=household["id"],
        name=name,
        description=body.get("description", ""),
        bonus_lumins=bonus_lumins,
        reward_description=body.get("reward_description"),
        deadline=body.get("deadline"),
        chore_ids=body.get("chore_ids") or [],
        member_ids=body.get("member_ids") or [],
    )
    return jsonify({"group_quest": await _gq_detail(gq)}), 201


# ---------------------------------------------------------------------------
# Get / update / delete
# ---------------------------------------------------------------------------

@group_quests_api.get("/group-quests/<gq_id>")
@login_required
async def get_group_quest(gq_id: str):
    gq = await gq_model.get_group_quest(gq_id)
    if gq is None:
        return jsonify({"error": "Group quest not found"}), 404
    return jsonify({"group_quest": await _gq_detail(gq)})


@group_quests_api.put("/group-quests/<gq_id>")
@admin_required
async def update_group_quest(gq_id: str):
    gq = await gq_model.get_group_quest(gq_id)
    if gq is None:
        return jsonify({"error": "Group quest not found"}), 404

    body = await request.get_json(force=True, silent=True) or {}
    allowed = {"name", "description", "bonus_lumins", "reward_description", "deadline"}
    fields = {k: v for k, v in body.items() if k in allowed}

    if "bonus_lumins" in fields:
        try:
            fields["bonus_lumins"] = int(fields["bonus_lumins"])
        except (TypeError, ValueError):
            return jsonify({"error": "bonus_lumins must be an integer"}), 400

    updated = await gq_model.update_group_quest(gq_id, **fields)
    return jsonify({"group_quest": await _gq_detail(updated)})


@group_quests_api.delete("/group-quests/<gq_id>")
@admin_required
async def delete_group_quest(gq_id: str):
    gq = await gq_model.get_group_quest(gq_id)
    if gq is None:
        return jsonify({"error": "Group quest not found"}), 404
    await gq_model.deactivate_group_quest(gq_id)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Membership
# ---------------------------------------------------------------------------

@group_quests_api.post("/group-quests/<gq_id>/join")
@login_required
async def join_gq(gq_id: str):
    gq = await gq_model.get_group_quest(gq_id)
    if gq is None:
        return jsonify({"error": "Group quest not found"}), 404

    try:
        await join_group_quest(g.current_user["id"], gq_id)
    except AlreadyMemberError as exc:
        return jsonify({"error": str(exc)}), 409

    return jsonify({"ok": True, "group_quest_id": gq_id})


@group_quests_api.delete("/group-quests/<gq_id>/leave")
@login_required
async def leave_gq(gq_id: str):
    gq = await gq_model.get_group_quest(gq_id)
    if gq is None:
        return jsonify({"error": "Group quest not found"}), 404

    try:
        await leave_group_quest(g.current_user["id"], gq_id)
    except NotMemberError as exc:
        return jsonify({"error": str(exc)}), 409
    except QuestAlreadyCompleteError as exc:
        return jsonify({"error": str(exc)}), 409

    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Progress & contributions
# ---------------------------------------------------------------------------

@group_quests_api.get("/group-quests/<gq_id>/progress")
@login_required
async def gq_progress(gq_id: str):
    gq = await gq_model.get_group_quest(gq_id)
    if gq is None:
        return jsonify({"error": "Group quest not found"}), 404

    progress = await gq_model.get_progress(gq_id)
    is_done = await gq_model.is_complete(gq_id)
    return jsonify({"group_quest_id": gq_id, "is_complete": is_done, "chores": progress})


@group_quests_api.get("/group-quests/<gq_id>/contributions")
@login_required
async def gq_contributions(gq_id: str):
    gq = await gq_model.get_group_quest(gq_id)
    if gq is None:
        return jsonify({"error": "Group quest not found"}), 404

    contributions = await gq_model.get_contributions(gq_id)
    return jsonify({"group_quest_id": gq_id, "contributions": contributions})


# ---------------------------------------------------------------------------
# Claim / release
# ---------------------------------------------------------------------------

@group_quests_api.post("/group-quests/<gq_id>/chores/<chore_id>/claim")
@login_required
async def claim_gq_chore(gq_id: str, chore_id: str):
    gq = await gq_model.get_group_quest(gq_id)
    if gq is None:
        return jsonify({"error": "Group quest not found"}), 404

    state = await claim_chore(g.current_user["id"], gq_id, chore_id)
    return jsonify({"claim": state})


@group_quests_api.delete("/group-quests/<gq_id>/chores/<chore_id>/claim")
@login_required
async def release_gq_claim(gq_id: str, chore_id: str):
    gq = await gq_model.get_group_quest(gq_id)
    if gq is None:
        return jsonify({"error": "Group quest not found"}), 404

    await release_claim(g.current_user["id"], gq_id, chore_id)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Complete a chore from the shared pool
# ---------------------------------------------------------------------------

@group_quests_api.post("/group-quests/<gq_id>/chores/<chore_id>/complete")
@login_required
async def complete_gq_chore(gq_id: str, chore_id: str):
    gq = await gq_model.get_group_quest(gq_id)
    if gq is None:
        return jsonify({"error": "Group quest not found"}), 404

    try:
        result = await complete_chore(g.current_user["id"], gq_id, chore_id)
    except NotMemberError as exc:
        return jsonify({"error": str(exc)}), 403
    except ChoreAlreadyCompleteError as exc:
        return jsonify({"error": str(exc)}), 409

    return jsonify(result)
