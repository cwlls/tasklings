"""
Profile view routes.

Blueprint: profile_views
Routes:
  GET  /profile               -- member's own profile page
  POST /profile               -- update name, avatar URL, color
  POST /profile/change-password -- change own password
"""
from __future__ import annotations

import re

from quart import Blueprint, g, redirect, render_template, request, url_for

from app.middleware.auth import login_required
from app.models import members as members_model
from app.models import transactions as tx_model
from app.models import purchases as purchases_model
from app.services.auth import hash_password, verify_password

profile_views = Blueprint("profile_views", __name__)

_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_MAX_URL_LEN = 512


@profile_views.get("/profile")
@login_required
async def profile_page():
    caller = g.current_user
    member = await members_model.get_member_by_id(caller["id"])
    recent_tx = await tx_model.list_transactions_for_member(caller["id"], limit=10)
    recent_purchases = await purchases_model.list_purchases_for_member(caller["id"])
    return await render_template(
        "profile/index.html",
        member=dict(member),
        recent_transactions=[dict(t) for t in recent_tx],
        recent_purchases=[dict(p) for p in recent_purchases[:5]],
    )


@profile_views.post("/profile")
@login_required
async def update_profile():
    caller = g.current_user
    body = await request.form
    errors = {}

    name = (body.get("name") or "").strip()
    avatar = (body.get("avatar") or "").strip()
    color = (body.get("color") or "").strip()

    if name and len(name) > 80:
        errors["name"] = "Name must be 80 characters or fewer."
    if avatar and len(avatar) > _MAX_URL_LEN:
        errors["avatar"] = "Avatar URL is too long."
    if color and not _HEX_COLOR.match(color):
        errors["color"] = "Color must be a hex code like #4A90D9."

    member = await members_model.get_member_by_id(caller["id"])

    if errors:
        recent_tx = await tx_model.list_transactions_for_member(caller["id"], limit=10)
        recent_purchases = await purchases_model.list_purchases_for_member(caller["id"])
        return await render_template(
            "profile/index.html",
            member=dict(member),
            errors=errors,
            recent_transactions=[dict(t) for t in recent_tx],
            recent_purchases=[dict(p) for p in recent_purchases[:5]],
        )

    fields = {}
    if name:
        fields["name"] = name
    if avatar:
        fields["avatar"] = avatar
    if color:
        fields["color"] = color

    if fields:
        await members_model.update_member(caller["id"], **fields)

    return redirect(url_for("profile_views.profile_page"))


@profile_views.post("/profile/change-password")
@login_required
async def change_password():
    caller = g.current_user
    body = await request.form

    old_pw = body.get("old_password") or ""
    new_pw = body.get("new_password") or ""

    member = await members_model.get_member_by_id(caller["id"])
    recent_tx = await tx_model.list_transactions_for_member(caller["id"], limit=10)
    recent_purchases = await purchases_model.list_purchases_for_member(caller["id"])

    ctx = {
        "member": dict(member),
        "recent_transactions": [dict(t) for t in recent_tx],
        "recent_purchases": [dict(p) for p in recent_purchases[:5]],
    }

    if not verify_password(old_pw, member["password_hash"]):
        return await render_template(
            "profile/index.html",
            **ctx,
            pw_error="Current password is incorrect.",
        )

    min_len = 8 if member["role"] == "parent" else 4
    if len(new_pw) < min_len:
        return await render_template(
            "profile/index.html",
            **ctx,
            pw_error=f"Password must be at least {min_len} characters.",
        )

    await members_model.update_member(caller["id"], password_hash=hash_password(new_pw))

    return await render_template(
        "profile/index.html",
        **ctx,
        pw_success="Password changed successfully.",
    )
