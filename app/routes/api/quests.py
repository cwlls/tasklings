"""
Solo Quest API routes.

Blueprint prefix: /api/v1
"""
from __future__ import annotations

from datetime import datetime, timezone

from quart import Blueprint, g, jsonify, request

from app.middleware.auth import admin_required, login_required
from app.models import quests as quests_model
from app.models.household import get_household
from app.services.quests import check_quest_completion, complete_quest_chore

quests_api = Blueprint("quests_api", __name__, url_prefix="/api/v1")


def _now_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()


async def _quest_detail(quest) -> dict:
    data = dict(quest)
    chores = await quests_model.get_quest_chores(quest["id"])
    data["chores"] = [dict(c) for c in chores]
    return data


# ---------------------------------------------------------------------------
# List / create
# ---------------------------------------------------------------------------

@quests_api.get("/quests")
@login_required
async def list_quests():
    caller = g.current_user
    if caller["role"] == "parent":
        household = await get_household()
        rows = await quests_model.list_all_quests(household["id"])
    else:
        rows = await quests_model.list_quests_for_member(caller["id"])
    return jsonify({"quests": [dict(r) for r in rows]})


@quests_api.post("/quests")
@admin_required
async def create_quest():
    household = await get_household()
    if household is None:
        return jsonify({"error": "No household found"}), 500

    body = await request.get_json(force=True, silent=True) or {}

    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    member_id = body.get("member_id", "")
    if not member_id:
        return jsonify({"error": "member_id is required"}), 400

    try:
        bonus_lumins = int(body.get("bonus_lumins", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "bonus_lumins must be an integer"}), 400

    chore_ids = body.get("chore_ids") or []

    quest = await quests_model.create_quest(
        household_id=household["id"],
        name=name,
        description=body.get("description", ""),
        member_id=member_id,
        bonus_lumins=bonus_lumins,
        chore_ids=chore_ids,
    )
    return jsonify({"quest": await _quest_detail(quest)}), 201


# ---------------------------------------------------------------------------
# Get / update / delete
# ---------------------------------------------------------------------------

@quests_api.get("/quests/<quest_id>")
@login_required
async def get_quest(quest_id: str):
    quest = await quests_model.get_quest(quest_id)
    if quest is None:
        return jsonify({"error": "Quest not found"}), 404

    caller = g.current_user
    if caller["role"] != "parent" and quest["member_id"] != caller["id"]:
        return jsonify({"error": "Forbidden"}), 403

    return jsonify({"quest": await _quest_detail(quest)})


@quests_api.put("/quests/<quest_id>")
@admin_required
async def update_quest(quest_id: str):
    quest = await quests_model.get_quest(quest_id)
    if quest is None:
        return jsonify({"error": "Quest not found"}), 404

    body = await request.get_json(force=True, silent=True) or {}
    allowed = {"name", "description", "member_id", "bonus_lumins"}
    fields = {k: v for k, v in body.items() if k in allowed}

    if "bonus_lumins" in fields:
        try:
            fields["bonus_lumins"] = int(fields["bonus_lumins"])
        except (TypeError, ValueError):
            return jsonify({"error": "bonus_lumins must be an integer"}), 400

    updated = await quests_model.update_quest(quest_id, **fields)
    return jsonify({"quest": await _quest_detail(updated)})


@quests_api.delete("/quests/<quest_id>")
@admin_required
async def delete_quest(quest_id: str):
    quest = await quests_model.get_quest(quest_id)
    if quest is None:
        return jsonify({"error": "Quest not found"}), 404

    await quests_model.deactivate_quest(quest_id)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------

@quests_api.get("/quests/<quest_id>/progress")
@login_required
async def quest_progress(quest_id: str):
    quest = await quests_model.get_quest(quest_id)
    if quest is None:
        return jsonify({"error": "Quest not found"}), 404

    caller = g.current_user
    member_id = caller["id"]

    if caller["role"] == "parent":
        # Admin can query any member; default to the quest's assigned member.
        member_id = request.args.get("member_id") or quest["member_id"]

    date = request.args.get("date") or _now_date()
    progress = await quests_model.get_quest_progress(quest_id, member_id, date)
    return jsonify({"quest_id": quest_id, "date": date, "progress": progress})


# ---------------------------------------------------------------------------
# Complete a chore within a quest
# ---------------------------------------------------------------------------

@quests_api.post("/quests/<quest_id>/chores/<chore_id>/complete")
@login_required
async def complete_quest_chore_route(quest_id: str, chore_id: str):
    caller = g.current_user

    quest = await quests_model.get_quest(quest_id)
    if quest is None:
        return jsonify({"error": "Quest not found"}), 404

    if caller["role"] != "parent" and quest["member_id"] != caller["id"]:
        return jsonify({"error": "This quest is not assigned to you"}), 403

    date = request.args.get("date") or _now_date()
    result = await complete_quest_chore(caller["id"], quest_id, chore_id, date)
    return jsonify(result)
