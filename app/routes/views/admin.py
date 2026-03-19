"""
Admin view routes.

Blueprint: admin_views
All routes require admin (parent) role.

Routes:
  GET  /admin                    -- dashboard
  GET  /admin/members            -- list all members
  GET  /admin/members/new        -- new member form
  POST /admin/members/new        -- create member
  GET  /admin/members/:id/edit   -- edit member form
  POST /admin/members/:id/edit   -- save member edits
  GET  /admin/chores             -- list chore definitions
  GET  /admin/chores/new         -- new chore form
  POST /admin/chores/new         -- create chore
  GET  /admin/chores/:id/edit    -- edit chore form
  POST /admin/chores/:id/edit    -- save chore edits
  GET  /admin/quests             -- list solo and group quests
  GET  /admin/quests/new         -- new quest form
  POST /admin/quests/new         -- create quest
  GET  /admin/store              -- list store items
  GET  /admin/store/new          -- new item form
  POST /admin/store/new          -- create item
  GET  /admin/store/:id/edit     -- edit item form
  POST /admin/store/:id/edit     -- save item edits
  GET  /admin/activity           -- recent transactions (paginated)
  GET  /admin/tokens             -- API token management
  POST /admin/tokens/new         -- create token
  POST /admin/tokens/:id/revoke  -- revoke token
"""
from __future__ import annotations

from quart import Blueprint, g, redirect, render_template, request, url_for

from app.middleware.auth import admin_required
from app.models import chores as chores_model
from app.models import members as members_model
from app.models import store as store_model
from app.models import transactions as tx_model
from app.models import auth as auth_model
from app.models.household import get_household
from app.models.quests import list_all_quests
from app.models.group_quests import list_all_group_quests
from app.models.db import fetch_all
from app.services.auth import hash_password, create_api_token
from app.services.store import purchase_item  # noqa: F401 -- imported for consistency

admin_views = Blueprint("admin_views", __name__, url_prefix="/admin")


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@admin_views.get("")
@admin_required
async def dashboard():
    household = await get_household()
    members = await members_model.list_members(household["id"])
    recent_tx = await fetch_all(
        """
        SELECT lt.*, fm.name AS member_name
        FROM lumin_transaction lt
        JOIN family_member fm ON fm.id = lt.member_id
        WHERE fm.household_id = ?
        ORDER BY lt.created_at DESC
        LIMIT 20
        """,
        (household["id"],),
    )
    # Today's assignment summary.
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from app.services import assignment_engine
    tz = ZoneInfo(household.get("timezone", "America/Chicago"))
    today = datetime.now(tz).date().isoformat()
    assignments_today = await fetch_all(
        """
        SELECT ca.status, COUNT(*) as cnt
        FROM chore_assignment ca
        JOIN family_member fm ON fm.id = ca.member_id
        WHERE fm.household_id = ? AND ca.assigned_date = ?
        GROUP BY ca.status
        """,
        (household["id"], today),
    )
    summary = {row["status"]: row["cnt"] for row in assignments_today}
    return await render_template(
        "admin/dashboard.html",
        household=dict(household),
        members=[dict(m) for m in members],
        recent_transactions=[dict(t) for t in recent_tx],
        today=today,
        assignment_summary=summary,
    )


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------

@admin_views.get("/members")
@admin_required
async def members_list():
    household = await get_household()
    include_inactive = request.args.get("inactive", "false").lower() == "true"
    members = await members_model.list_members(household["id"], include_inactive=include_inactive)
    return await render_template(
        "admin/members.html",
        members=[dict(m) for m in members],
        include_inactive=include_inactive,
    )


@admin_views.get("/members/new")
@admin_required
async def member_new_form():
    return await render_template("admin/member_form.html", member=None, errors={})


@admin_views.post("/members/new")
@admin_required
async def member_new_post():
    household = await get_household()
    form = await request.form
    errors = {}

    username = (form.get("username") or "").strip()
    password = form.get("password") or ""
    name = (form.get("name") or "").strip()
    role = form.get("role", "child")
    color = form.get("color", "#4A90D9").strip()

    if not username:
        errors["username"] = "Username is required."
    if len(password) < 4:
        errors["password"] = "Password must be at least 4 characters."
    if not name:
        errors["name"] = "Name is required."
    if role not in ("parent", "child"):
        errors["role"] = "Role must be parent or child."

    if errors:
        return await render_template("admin/member_form.html", member=None, errors=errors)

    pw_hash = hash_password(password)
    await members_model.create_member(
        household_id=household["id"],
        username=username,
        password_hash=pw_hash,
        name=name,
        role=role,
        color=color,
        avatar=form.get("avatar", ""),
    )
    return redirect(url_for("admin_views.members_list"))


@admin_views.get("/members/<member_id>/edit")
@admin_required
async def member_edit_form(member_id: str):
    member = await members_model.get_member_by_id(member_id)
    if member is None:
        return redirect(url_for("admin_views.members_list"))
    return await render_template("admin/member_form.html", member=dict(member), errors={})


@admin_views.post("/members/<member_id>/edit")
@admin_required
async def member_edit_post(member_id: str):
    member = await members_model.get_member_by_id(member_id)
    if member is None:
        return redirect(url_for("admin_views.members_list"))

    form = await request.form
    errors = {}

    name = (form.get("name") or "").strip()
    color = (form.get("color") or member["color"]).strip()
    avatar = (form.get("avatar") or "").strip()
    is_active = form.get("is_active") == "1"

    if not name:
        errors["name"] = "Name is required."

    if errors:
        return await render_template("admin/member_form.html", member=dict(member), errors=errors)

    fields = {"name": name, "color": color, "avatar": avatar, "is_active": int(is_active)}
    # Optional password reset.
    new_pw = (form.get("new_password") or "").strip()
    if new_pw:
        if len(new_pw) < 4:
            errors["new_password"] = "Password must be at least 4 characters."
            return await render_template("admin/member_form.html", member=dict(member), errors=errors)
        fields["password_hash"] = hash_password(new_pw)

    await members_model.update_member(member_id, **fields)
    return redirect(url_for("admin_views.members_list"))


# ---------------------------------------------------------------------------
# Chores
# ---------------------------------------------------------------------------

@admin_views.get("/chores")
@admin_required
async def chores_list():
    household = await get_household()
    include_inactive = request.args.get("inactive", "false").lower() == "true"
    rows = await chores_model.list_chore_definitions(
        household["id"], active_only=not include_inactive
    )
    chores = []
    for row in rows:
        d = dict(row)
        if row["chore_type"] == "constant":
            d["assignee_ids"] = await chores_model.get_assignees_for_chore(row["id"])
        chores.append(d)
    members = await members_model.list_members(household["id"])
    return await render_template(
        "admin/chores.html",
        chores=chores,
        members=[dict(m) for m in members],
        include_inactive=include_inactive,
    )


@admin_views.get("/chores/new")
@admin_required
async def chore_new_form():
    household = await get_household()
    members = await members_model.list_members(household["id"])
    return await render_template(
        "admin/chore_form.html",
        chore=None,
        members=[dict(m) for m in members],
        errors={},
    )


@admin_views.post("/chores/new")
@admin_required
async def chore_new_post():
    household = await get_household()
    form = await request.form
    errors = {}

    title = (form.get("title") or "").strip()
    chore_type = form.get("chore_type", "constant")
    rotation_frequency = form.get("rotation_frequency") or None
    try:
        lumin_value = int(form.get("lumin_value", 0))
    except ValueError:
        lumin_value = 0
        errors["lumin_value"] = "Must be a whole number."

    if not title:
        errors["title"] = "Title is required."
    if chore_type not in ("constant", "rotating"):
        errors["chore_type"] = "Invalid type."

    members = await members_model.list_members(household["id"])
    if errors:
        return await render_template(
            "admin/chore_form.html", chore=None,
            members=[dict(m) for m in members], errors=errors,
        )

    chore = await chores_model.create_chore_definition(
        household_id=household["id"],
        title=title,
        description=form.get("description", ""),
        icon=form.get("icon", ""),
        lumin_value=lumin_value,
        chore_type=chore_type,
        rotation_frequency=rotation_frequency,
    )
    # Set assignees for constant chores.
    if chore_type == "constant":
        member_ids = form.getlist("member_ids")
        if member_ids:
            await chores_model.set_assignees_for_chore(chore["id"], member_ids)

    return redirect(url_for("admin_views.chores_list"))


@admin_views.get("/chores/<chore_id>/edit")
@admin_required
async def chore_edit_form(chore_id: str):
    chore = await chores_model.get_chore_definition(chore_id)
    if chore is None:
        return redirect(url_for("admin_views.chores_list"))
    household = await get_household()
    members = await members_model.list_members(household["id"])
    d = dict(chore)
    if chore["chore_type"] == "constant":
        d["assignee_ids"] = await chores_model.get_assignees_for_chore(chore_id)
    return await render_template(
        "admin/chore_form.html",
        chore=d,
        members=[dict(m) for m in members],
        errors={},
    )


@admin_views.post("/chores/<chore_id>/edit")
@admin_required
async def chore_edit_post(chore_id: str):
    chore = await chores_model.get_chore_definition(chore_id)
    if chore is None:
        return redirect(url_for("admin_views.chores_list"))
    household = await get_household()

    form = await request.form
    errors = {}
    title = (form.get("title") or "").strip()
    if not title:
        errors["title"] = "Title is required."
    try:
        lumin_value = int(form.get("lumin_value", 0))
    except ValueError:
        lumin_value = 0
        errors["lumin_value"] = "Must be a whole number."

    members = await members_model.list_members(household["id"])
    if errors:
        return await render_template(
            "admin/chore_form.html",
            chore=dict(chore), members=[dict(m) for m in members], errors=errors,
        )

    await chores_model.update_chore_definition(chore_id, title=title, lumin_value=lumin_value,
                                               description=form.get("description", ""),
                                               icon=form.get("icon", ""))
    if chore["chore_type"] == "constant":
        member_ids = form.getlist("member_ids")
        await chores_model.set_assignees_for_chore(chore_id, member_ids)

    return redirect(url_for("admin_views.chores_list"))


# ---------------------------------------------------------------------------
# Quests
# ---------------------------------------------------------------------------

@admin_views.get("/quests")
@admin_required
async def quests_list():
    household = await get_household()
    solo_quests = await list_all_quests(household["id"])
    group_quests = await list_all_group_quests(household["id"])
    members = await members_model.list_members(household["id"])
    return await render_template(
        "admin/quests.html",
        solo_quests=[dict(q) for q in solo_quests],
        group_quests=[dict(gq) for gq in group_quests],
        members=[dict(m) for m in members],
    )


@admin_views.get("/quests/new")
@admin_required
async def quest_new_form():
    household = await get_household()
    members = await members_model.list_members(household["id"])
    chores = await chores_model.list_chore_definitions(household["id"])
    return await render_template(
        "admin/quest_form.html",
        quest=None,
        members=[dict(m) for m in members],
        chores=[dict(c) for c in chores],
        errors={},
    )


@admin_views.post("/quests/new")
@admin_required
async def quest_new_post():
    household = await get_household()
    form = await request.form
    errors = {}

    quest_type = form.get("quest_type", "solo")
    name = (form.get("name") or "").strip()
    if not name:
        errors["name"] = "Name is required."

    members = await members_model.list_members(household["id"])
    chores = await chores_model.list_chore_definitions(household["id"])
    if errors:
        return await render_template(
            "admin/quest_form.html",
            quest=None, members=[dict(m) for m in members],
            chores=[dict(c) for c in chores], errors=errors,
        )

    try:
        bonus = int(form.get("bonus_lumins", 0))
    except ValueError:
        bonus = 0

    chore_ids = form.getlist("chore_ids")
    member_ids = form.getlist("member_ids")

    if quest_type == "solo":
        member_id = form.get("member_id") or (member_ids[0] if member_ids else None)
        from app.models import quests as quests_model
        await quests_model.create_quest(
            household_id=household["id"],
            name=name,
            description=form.get("description", ""),
            member_id=member_id,
            bonus_lumins=bonus,
            chore_ids=chore_ids,
        )
    else:
        from app.models import group_quests as gq_model
        await gq_model.create_group_quest(
            household_id=household["id"],
            name=name,
            description=form.get("description", ""),
            bonus_lumins=bonus,
            reward_description=form.get("reward_description", ""),
            deadline=form.get("deadline") or None,
            chore_ids=chore_ids,
            member_ids=member_ids,
        )

    return redirect(url_for("admin_views.quests_list"))


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

@admin_views.get("/store")
@admin_required
async def store_list():
    household = await get_household()
    items = await store_model.list_all_store_items(household["id"])
    members = await members_model.list_members(household["id"])
    items_data = []
    for item in items:
        d = dict(item)
        visibility = await fetch_all(
            "SELECT member_id FROM store_item_visibility WHERE store_item_id = ?",
            (item["id"],),
        )
        d["visibility_member_ids"] = [v["member_id"] for v in visibility]
        items_data.append(d)
    return await render_template(
        "admin/store.html",
        items=items_data,
        members=[dict(m) for m in members],
    )


@admin_views.get("/store/new")
@admin_required
async def store_item_new_form():
    household = await get_household()
    members = await members_model.list_members(household["id"])
    return await render_template(
        "admin/store_form.html",
        item=None,
        members=[dict(m) for m in members],
        errors={},
    )


@admin_views.post("/store/new")
@admin_required
async def store_item_new_post():
    household = await get_household()
    form = await request.form
    errors = {}

    title = (form.get("title") or "").strip()
    if not title:
        errors["title"] = "Title is required."

    try:
        price = int(form.get("price", 0))
    except ValueError:
        price = 0
        errors["price"] = "Must be a whole number."

    try:
        stock = form.get("stock")
        stock = int(stock) if stock else None
    except ValueError:
        stock = None

    members = await members_model.list_members(household["id"])
    if errors:
        return await render_template(
            "admin/store_form.html", item=None,
            members=[dict(m) for m in members], errors=errors,
        )

    item = await store_model.create_store_item(
        household_id=household["id"],
        title=title,
        description=form.get("description", ""),
        icon=form.get("icon", ""),
        price=price,
        is_available=form.get("is_available") == "1",
        stock=stock,
    )
    # Visibility targeting.
    target_member_ids = form.getlist("member_ids")
    if target_member_ids:
        await store_model.set_visibility(item["id"], target_member_ids)

    return redirect(url_for("admin_views.store_list"))


@admin_views.get("/store/<item_id>/edit")
@admin_required
async def store_item_edit_form(item_id: str):
    item = await store_model.get_store_item(item_id)
    if item is None:
        return redirect(url_for("admin_views.store_list"))
    household = await get_household()
    members = await members_model.list_members(household["id"])
    visibility = await fetch_all(
        "SELECT member_id FROM store_item_visibility WHERE store_item_id = ?",
        (item_id,),
    )
    d = dict(item)
    d["visibility_member_ids"] = [v["member_id"] for v in visibility]
    return await render_template(
        "admin/store_form.html",
        item=d,
        members=[dict(m) for m in members],
        errors={},
    )


@admin_views.post("/store/<item_id>/edit")
@admin_required
async def store_item_edit_post(item_id: str):
    item = await store_model.get_store_item(item_id)
    if item is None:
        return redirect(url_for("admin_views.store_list"))
    household = await get_household()

    form = await request.form
    errors = {}
    title = (form.get("title") or "").strip()
    if not title:
        errors["title"] = "Title is required."

    try:
        price = int(form.get("price", item["price"]))
    except ValueError:
        price = item["price"]
        errors["price"] = "Must be a whole number."

    members = await members_model.list_members(household["id"])
    if errors:
        return await render_template(
            "admin/store_form.html", item=dict(item),
            members=[dict(m) for m in members], errors=errors,
        )

    try:
        stock_raw = form.get("stock")
        stock = int(stock_raw) if stock_raw else None
    except ValueError:
        stock = item["stock"]

    await store_model.update_store_item(
        item_id,
        title=title,
        description=form.get("description", ""),
        icon=form.get("icon", ""),
        price=price,
        is_available=form.get("is_available") == "1",
        stock=stock,
    )
    target_member_ids = form.getlist("member_ids")
    await store_model.set_visibility(item_id, target_member_ids)

    return redirect(url_for("admin_views.store_list"))


# ---------------------------------------------------------------------------
# Activity log
# ---------------------------------------------------------------------------

@admin_views.get("/activity")
@admin_required
async def activity_log():
    household = await get_household()
    try:
        limit = min(int(request.args.get("limit", 50)), 200)
        offset = max(int(request.args.get("offset", 0)), 0)
    except ValueError:
        limit, offset = 50, 0

    rows = await fetch_all(
        """
        SELECT lt.*, fm.name AS member_name, fm.color AS member_color
        FROM lumin_transaction lt
        JOIN family_member fm ON fm.id = lt.member_id
        WHERE fm.household_id = ?
        ORDER BY lt.created_at DESC
        LIMIT ? OFFSET ?
        """,
        (household["id"], limit, offset),
    )
    return await render_template(
        "admin/activity.html",
        transactions=[dict(r) for r in rows],
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# API tokens
# ---------------------------------------------------------------------------

@admin_views.get("/tokens")
@admin_required
async def tokens_list():
    household = await get_household()
    tokens = await auth_model.list_api_tokens(household["id"])
    return await render_template(
        "admin/tokens.html",
        tokens=[dict(t) for t in tokens],
        new_token=None,
    )


@admin_views.post("/tokens/new")
@admin_required
async def token_create():
    form = await request.form
    label = (form.get("label") or "").strip()
    errors = {}
    if not label:
        errors["label"] = "Label is required."

    household = await get_household()
    tokens = await auth_model.list_api_tokens(household["id"])

    if errors:
        return await render_template(
            "admin/tokens.html",
            tokens=[dict(t) for t in tokens],
            new_token=None,
            errors=errors,
        )

    result = await create_api_token(
        member_id=g.current_user["id"],
        label=label,
        expires_at=form.get("expires_at") or None,
    )
    # Reload list after creation.
    tokens = await auth_model.list_api_tokens(household["id"])
    return await render_template(
        "admin/tokens.html",
        tokens=[dict(t) for t in tokens],
        new_token=result["raw_token"],
        new_token_label=label,
    )


@admin_views.post("/tokens/<token_id>/revoke")
@admin_required
async def token_revoke(token_id: str):
    await auth_model.revoke_api_token(token_id)
    return redirect(url_for("admin_views.tokens_list"))
