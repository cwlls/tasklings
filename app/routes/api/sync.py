"""
Offline sync API route.

POST /api/v1/sync/completions
  Accepts a JSON array of {assignment_id, completed_at} objects.
  Bulk-completes assignments server-side with same-day grace window:
    - If the assignment is already completed -> rejected (idempotent, not an error)
    - If the assigned_date has passed (yesterday or earlier) -> rejected
    - Otherwise -> completed and Lumins awarded

Returns:
  {
    "accepted": [{"assignment_id": ..., "new_balance": ...}, ...],
    "rejected": [{"assignment_id": ..., "reason": ...}, ...]
  }
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from quart import Blueprint, g, jsonify, request

from app.middleware.auth import login_required
from app.models import chores as chores_model
from app.models import members as members_model
from app.models.household import get_household
from app.services.currency import credit_lumins

sync_api = Blueprint("sync_api", __name__, url_prefix="/api/v1")


@sync_api.post("/sync/completions")
@login_required
async def bulk_complete():
    member = g.current_user
    body = await request.get_json(force=True, silent=True) or []

    if not isinstance(body, list):
        return jsonify({"error": "Expected a JSON array"}), 400

    household = await get_household()
    tz = ZoneInfo(household["timezone"] if household else "America/Chicago")
    today_str = datetime.now(tz).date().isoformat()

    accepted = []
    rejected = []

    for item in body:
        if not isinstance(item, dict):
            continue
        assignment_id = (item.get("assignment_id") or "").strip()
        if not assignment_id:
            continue

        assignment = await chores_model.get_assignment(assignment_id)

        if assignment is None:
            rejected.append({"assignment_id": assignment_id, "reason": "not_found"})
            continue

        if assignment["member_id"] != member["id"]:
            rejected.append({"assignment_id": assignment_id, "reason": "forbidden"})
            continue

        if assignment["status"] != "pending":
            rejected.append({
                "assignment_id": assignment_id,
                "reason": "already_completed",
            })
            continue

        # Same-day grace window: only allow completions for today.
        if assignment["assigned_date"] != today_str:
            rejected.append({
                "assignment_id": assignment_id,
                "reason": "date_passed",
            })
            continue

        chore = await chores_model.get_chore_definition(assignment["chore_id"])
        lumin_value = chore["lumin_value"] if chore else 0

        now = datetime.now(timezone.utc).isoformat()
        await chores_model.update_assignment_status(
            assignment_id,
            status="completed",
            completed_at=now,
            lumins_awarded=lumin_value,
        )

        new_balance = member["balance"]
        if lumin_value > 0:
            new_balance = await credit_lumins(
                member["id"],
                lumin_value,
                reason="chore_completed",
                reference_id=assignment_id,
            )

        accepted.append({
            "assignment_id": assignment_id,
            "lumins_awarded": lumin_value,
            "new_balance": new_balance,
        })

        # Keep cached balance current for subsequent items in the same batch.
        member = await members_model.get_member_by_id(member["id"])

    return jsonify({"accepted": accepted, "rejected": rejected})
