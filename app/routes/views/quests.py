"""
Quest view routes (solo and group).

Blueprint: quests_views
Routes:
  GET /quests             -- solo quest list for current member
  GET /quests/:id         -- solo quest detail
  GET /group-quests       -- group quest list
  GET /group-quests/:id   -- group quest detail
"""
from __future__ import annotations

from datetime import datetime, timezone

from quart import Blueprint, g, render_template, request

from app.middleware.auth import login_required
from app.models import group_quests as gq_model
from app.models import quests as quests_model
from app.models.household import get_household

quests_views = Blueprint("quests_views", __name__)


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# ---------------------------------------------------------------------------
# Solo quests
# ---------------------------------------------------------------------------

@quests_views.get("/quests")
@login_required
async def quest_list():
    caller = g.current_user
    today = _today()

    if caller["role"] == "parent":
        household = await get_household()
        quests = await quests_model.list_all_quests(household["id"])
    else:
        quests = await quests_model.list_quests_for_member(caller["id"])

    # Augment each quest with today's progress.
    quests_with_progress = []
    for q in quests:
        member_id = q["member_id"] if caller["role"] == "parent" else caller["id"]
        progress = await quests_model.get_quest_progress(q["id"], member_id, today)
        total = len(progress)
        done = sum(1 for p in progress if p["completed"])
        quests_with_progress.append({
            **dict(q),
            "progress": progress,
            "total_chores": total,
            "done_chores": done,
        })

    return await render_template(
        "quests/index.html",
        member=caller,
        quests=quests_with_progress,
        today=today,
    )


@quests_views.get("/quests/<quest_id>")
@login_required
async def quest_detail(quest_id: str):
    caller = g.current_user
    today = _today()

    quest = await quests_model.get_quest(quest_id)
    if quest is None:
        return "Quest not found", 404

    if caller["role"] != "parent" and quest["member_id"] != caller["id"]:
        return "Forbidden", 403

    member_id = quest["member_id"] if caller["role"] == "parent" else caller["id"]
    progress = await quests_model.get_quest_progress(quest_id, member_id, today)
    total = len(progress)
    done = sum(1 for p in progress if p["completed"])

    return await render_template(
        "quests/detail.html",
        member=caller,
        quest=dict(quest),
        progress=progress,
        total_chores=total,
        done_chores=done,
        today=today,
    )


# ---------------------------------------------------------------------------
# Group quests
# ---------------------------------------------------------------------------

@quests_views.get("/group-quests")
@login_required
async def group_quest_list():
    caller = g.current_user

    if caller["role"] == "parent":
        household = await get_household()
        gqs = await gq_model.list_all_group_quests(household["id"])
    else:
        gqs = await gq_model.list_group_quests_for_member(caller["id"])

    gqs_with_progress = []
    for gq in gqs:
        progress = await gq_model.get_progress(gq["id"])
        total = len(progress)
        done = sum(1 for p in progress if p["is_completed"])
        contributions = await gq_model.get_contributions(gq["id"])
        gqs_with_progress.append({
            **dict(gq),
            "progress": progress,
            "total_chores": total,
            "done_chores": done,
            "contributions": contributions,
        })

    return await render_template(
        "quests/group_index.html",
        member=caller,
        group_quests=gqs_with_progress,
    )


@quests_views.get("/group-quests/<gq_id>")
@login_required
async def group_quest_detail(gq_id: str):
    caller = g.current_user

    gq = await gq_model.get_group_quest(gq_id)
    if gq is None:
        return "Group quest not found", 404

    progress = await gq_model.get_progress(gq_id)
    total = len(progress)
    done = sum(1 for p in progress if p["is_completed"])
    contributions = await gq_model.get_contributions(gq_id)
    is_done = await gq_model.is_complete(gq_id)

    return await render_template(
        "quests/group_detail.html",
        member=caller,
        gq=dict(gq),
        progress=progress,
        total_chores=total,
        done_chores=done,
        contributions=contributions,
        is_complete=is_done,
    )
