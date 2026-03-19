"""
Runlist view routes.

Handles:
  GET /        -- redirect to /runlist (logged in) or /login (not)
  GET /runlist -- today's chore list for the current user
"""
from __future__ import annotations

from quart import Blueprint, g, redirect, render_template, request, url_for

from app.middleware.auth import login_required
from app.models import chores as chores_model
from app.models.household import get_household
from app.services import assignment_engine

runlist_views = Blueprint("runlist_views", __name__)


@runlist_views.get("/")
async def index():
    """Root redirect: logged-in users go to /runlist, others to /login."""
    if g.get("current_user"):
        return redirect(url_for("runlist_views.runlist"))
    return redirect(url_for("auth_views.login_get"))


@runlist_views.get("/runlist")
@login_required
async def runlist():
    member = g.current_user
    household = await get_household()
    household_id = household["id"]

    today = await assignment_engine.ensure_assignments_for_today(household_id)
    today_str = today.isoformat()

    assignments = await chores_model.list_assignments_for_member(member["id"], today_str)
    assignments_dicts = [dict(a) for a in assignments]

    # HTMX partial refresh: return only the chore list fragment.
    if request.headers.get("HX-Request"):
        return await render_template(
            "runlist/_chore_list.html",
            assignments=assignments_dicts,
        )

    return await render_template(
        "runlist/index.html",
        member=member,
        assignments=assignments_dicts,
        today=today_str,
        balance=member["balance"],
    )
