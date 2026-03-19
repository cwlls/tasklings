"""
Runlist / Assignment API routes.

Blueprint prefix: /api/v1
"""
from __future__ import annotations

from datetime import datetime, timezone

from quart import Blueprint, g, jsonify, render_template, request

from app.middleware.auth import admin_required, login_required
from app.models import chores as chores_model
from app.models import members as members_model
from app.models import purchases as purchases_model
from app.models import transactions as tx_model
from app.models.household import get_household
from app.services import assignment_engine
from app.services.currency import credit_lumins

assignments_api = Blueprint("assignments_api", __name__, url_prefix="/api/v1")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row) -> dict:
    return dict(row) if row is not None else None


# ---------------------------------------------------------------------------
# My assignments (today or a specific date)
# ---------------------------------------------------------------------------

@assignments_api.get("/my/assignments")
@login_required
async def my_assignments():
    member = g.current_user
    household = await get_household()
    household_id = household["id"]

    date_param = request.args.get("date")
    if date_param:
        # Validate format
        try:
            from datetime import date as _Date
            _Date.fromisoformat(date_param)
        except ValueError:
            return jsonify({"error": "Invalid date format, expected YYYY-MM-DD"}), 400
        target_date_str = date_param
    else:
        today = await assignment_engine.ensure_assignments_for_today(household_id)
        target_date_str = today.isoformat()

    assignments = await chores_model.list_assignments_for_member(
        member["id"], target_date_str
    )
    return jsonify({
        "date": target_date_str,
        "assignments": [dict(a) for a in assignments],
    })


# ---------------------------------------------------------------------------
# Complete an assignment
# ---------------------------------------------------------------------------

@assignments_api.post("/my/assignments/<assignment_id>/complete")
@login_required
async def complete_assignment(assignment_id: str):
    member = g.current_user

    assignment = await chores_model.get_assignment(assignment_id)
    if assignment is None:
        return jsonify({"error": "Assignment not found"}), 404

    if assignment["member_id"] != member["id"]:
        return jsonify({"error": "This assignment does not belong to you"}), 403

    if assignment["status"] not in ("pending",):
        return jsonify({"error": f"Assignment is already {assignment['status']}"}), 409

    chore = await chores_model.get_chore_definition(assignment["chore_id"])
    lumin_value = chore["lumin_value"] if chore else 0

    now = _now_iso()
    updated = await chores_model.update_assignment_status(
        assignment_id,
        status="completed",
        completed_at=now,
        lumins_awarded=lumin_value,
    )

    if lumin_value > 0:
        await credit_lumins(
            member["id"],
            lumin_value,
            reason="chore_completed",
            reference_id=assignment_id,
        )

    member_row = await members_model.get_member_by_id(member["id"])
    new_balance = member_row["balance"] if member_row else 0

    # HTMX request: return a rendered chore-item partial so the caller can
    # swap the completed row in-place without a full page reload.
    if request.headers.get("HX-Request"):
        # Re-fetch with joined chore definition fields for the template.
        joined = await chores_model.list_assignments_for_member(
            member["id"], updated["assigned_date"]
        )
        assignment_dict = next(
            (dict(a) for a in joined if a["id"] == assignment_id),
            dict(updated),
        )
        return await render_template(
            "runlist/_chore_item.html",
            assignment=assignment_dict,
        )

    return jsonify({
        "assignment": dict(updated),
        "new_balance": new_balance,
    })


# ---------------------------------------------------------------------------
# Uncomplete an assignment (admin, or same-day self-correction)
# ---------------------------------------------------------------------------

@assignments_api.post("/my/assignments/<assignment_id>/uncomplete")
@login_required
async def uncomplete_assignment(assignment_id: str):
    member = g.current_user

    assignment = await chores_model.get_assignment(assignment_id)
    if assignment is None:
        return jsonify({"error": "Assignment not found"}), 404

    is_admin = member["role"] == "parent"
    is_owner = assignment["member_id"] == member["id"]

    if not is_admin and not is_owner:
        return jsonify({"error": "Forbidden"}), 403

    if assignment["status"] not in ("completed", "verified"):
        return jsonify({"error": f"Assignment is not completed (status={assignment['status']})"}), 409

    # Non-admins may only undo on the same calendar date.
    if not is_admin:
        from zoneinfo import ZoneInfo
        household = await get_household()
        tz = ZoneInfo(household["timezone"] if household else "America/Chicago")
        today_str = datetime.now(tz).date().isoformat()
        if assignment["assigned_date"] != today_str:
            return jsonify({"error": "You may only undo a completion on the same day"}), 403

    lumins_to_reverse = assignment["lumins_awarded"] or 0

    updated = await chores_model.update_assignment_status(
        assignment_id,
        status="pending",
        completed_at=None,
        lumins_awarded=0,
    )

    if lumins_to_reverse > 0:
        from app.services.currency import InsufficientBalanceError, debit_lumins
        try:
            await debit_lumins(
                assignment["member_id"],
                lumins_to_reverse,
                reason="adjustment",
                reference_id=assignment_id,
            )
        except InsufficientBalanceError:
            # Best-effort: don't block the undo if the member has already spent
            # those Lumins.
            pass

    member_row = await members_model.get_member_by_id(assignment["member_id"])
    return jsonify({
        "assignment": dict(updated),
        "new_balance": member_row["balance"] if member_row else 0,
    })


# ---------------------------------------------------------------------------
# Balance + transactions
# ---------------------------------------------------------------------------

@assignments_api.get("/my/balance")
@login_required
async def my_balance():
    member = g.current_user
    transactions = await tx_model.list_transactions_for_member(member["id"], limit=10)
    return jsonify({
        "balance": member["balance"],
        "recent_transactions": [dict(t) for t in transactions],
    })


@assignments_api.get("/my/transactions")
@login_required
async def my_transactions():
    member = g.current_user
    try:
        limit = min(int(request.args.get("limit", 50)), 200)
        offset = max(int(request.args.get("offset", 0)), 0)
    except ValueError:
        return jsonify({"error": "limit and offset must be integers"}), 400

    transactions = await tx_model.list_transactions_for_member(
        member["id"], limit=limit, offset=offset
    )
    return jsonify({
        "transactions": [dict(t) for t in transactions],
        "limit": limit,
        "offset": offset,
    })


@assignments_api.get("/my/purchases")
@login_required
async def my_purchases():
    member = g.current_user
    rows = await purchases_model.list_purchases_for_member(member["id"])
    return jsonify({"purchases": [dict(r) for r in rows]})


# ---------------------------------------------------------------------------
# Admin: view any member's assignments
# ---------------------------------------------------------------------------

@assignments_api.get("/members/<member_id>/assignments")
@admin_required
async def member_assignments(member_id: str):
    target = await members_model.get_member_by_id(member_id)
    if target is None:
        return jsonify({"error": "Member not found"}), 404

    date_param = request.args.get("date")
    if date_param:
        try:
            from datetime import date as _Date
            _Date.fromisoformat(date_param)
        except ValueError:
            return jsonify({"error": "Invalid date format, expected YYYY-MM-DD"}), 400
        target_date_str = date_param
    else:
        household = await get_household()
        today = await assignment_engine.ensure_assignments_for_today(household["id"])
        target_date_str = today.isoformat()

    assignments = await chores_model.list_assignments_for_member(member_id, target_date_str)
    return jsonify({
        "member_id": member_id,
        "date": target_date_str,
        "assignments": [dict(a) for a in assignments],
    })


# ---------------------------------------------------------------------------
# Admin: verify / skip / force-generate
# ---------------------------------------------------------------------------

@assignments_api.post("/assignments/<assignment_id>/verify")
@admin_required
async def verify_assignment(assignment_id: str):
    assignment = await chores_model.get_assignment(assignment_id)
    if assignment is None:
        return jsonify({"error": "Assignment not found"}), 404

    updated = await chores_model.update_assignment_status(
        assignment_id,
        status="verified",
        verified_by=g.current_user["id"],
    )
    return jsonify({"assignment": dict(updated)})


@assignments_api.post("/assignments/<assignment_id>/skip")
@admin_required
async def skip_assignment(assignment_id: str):
    assignment = await chores_model.get_assignment(assignment_id)
    if assignment is None:
        return jsonify({"error": "Assignment not found"}), 404

    updated = await chores_model.update_assignment_status(assignment_id, status="skipped")
    return jsonify({"assignment": dict(updated)})


@assignments_api.post("/assignments/generate")
@admin_required
async def force_generate():
    household = await get_household()
    if household is None:
        return jsonify({"error": "No household found"}), 500

    today = await assignment_engine.ensure_assignments_for_today(household["id"])
    return jsonify({"generated_for": today.isoformat()})
