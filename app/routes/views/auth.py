"""
Auth view routes -- server-rendered pages for login and password reset.

Blueprint: auth_views
Routes:
  GET  /login                  -- login form
  POST /login                  -- process login (supports HTMX + standard POST)
  GET  /logout                 -- revoke session, redirect to /login
  GET  /auth/reset             -- request password reset form
  POST /auth/reset             -- process reset request
  GET  /auth/reset/confirm     -- confirm token + new password form
  POST /auth/reset/confirm     -- process confirmation
"""
from __future__ import annotations

from quart import (
    Blueprint,
    g,
    redirect,
    render_template,
    request,
    url_for,
    make_response,
)

from app.middleware.auth import COOKIE_NAME
from app.services.auth import (
    AuthError,
    login as svc_login,
    logout as svc_logout,
    request_password_reset as svc_reset_request,
    confirm_password_reset as svc_reset_confirm,
)

auth_views_bp = Blueprint("auth_views", __name__)


def _is_htmx() -> bool:
    return request.headers.get("HX-Request") == "true"


def _is_secure() -> bool:
    from quart import current_app
    return not current_app.config.get("TESTING", False) and not current_app.debug


def _set_session_cookie(response, session_id: str):
    from quart import current_app
    response.set_cookie(
        COOKIE_NAME,
        session_id,
        httponly=True,
        samesite="Lax",
        secure=_is_secure(),
        max_age=int(current_app.config.get("SESSION_LIFETIME_HOURS", 72)) * 3600,
    )
    return response


def _clear_session_cookie(response):
    response.delete_cookie(COOKIE_NAME, httponly=True, samesite="Lax")
    return response


# ---------------------------------------------------------------------------
# GET /login
# ---------------------------------------------------------------------------

@auth_views_bp.get("/login")
async def login_get():
    if g.get("current_user"):
        return redirect(url_for("index.index"))
    return await render_template("auth/login.html", error=None)


# ---------------------------------------------------------------------------
# POST /login
# ---------------------------------------------------------------------------

@auth_views_bp.post("/login")
async def login_post():
    form = await request.form
    username = (form.get("username") or "").strip()
    password = form.get("password") or ""

    if not username or not password:
        return await render_template(
            "auth/login.html", error="Username and password are required."
        )

    try:
        result = await svc_login(username, password)
    except AuthError as exc:
        return await render_template("auth/login.html", error=exc.message)

    # On success: redirect to home (full page or HTMX redirect header).
    if _is_htmx():
        response = await make_response("", 204)
        response.headers["HX-Redirect"] = url_for("runlist_views.index")
    else:
        response = await make_response(redirect(url_for("runlist_views.index")))

    _set_session_cookie(response, result["session_id"])
    return response


# ---------------------------------------------------------------------------
# GET /logout
# ---------------------------------------------------------------------------

@auth_views_bp.get("/logout")
async def logout_get():
    session_id = request.cookies.get(COOKIE_NAME)
    if session_id:
        await svc_logout(session_id)

    response = await make_response(redirect(url_for("auth_views.login_get")))
    _clear_session_cookie(response)
    return response


# ---------------------------------------------------------------------------
# GET /auth/reset
# ---------------------------------------------------------------------------

@auth_views_bp.get("/auth/reset")
async def reset_request_get():
    return await render_template("auth/reset_request.html", submitted=False, error=None)


# ---------------------------------------------------------------------------
# POST /auth/reset
# ---------------------------------------------------------------------------

@auth_views_bp.post("/auth/reset")
async def reset_request_post():
    form = await request.form
    username = (form.get("username") or "").strip()

    # Always render the confirmation view -- no info leak.
    if username:
        await svc_reset_request(username)

    return await render_template("auth/reset_request.html", submitted=True, error=None)


# ---------------------------------------------------------------------------
# GET /auth/reset/confirm
# ---------------------------------------------------------------------------

@auth_views_bp.get("/auth/reset/confirm")
async def reset_confirm_get():
    token = request.args.get("token", "")
    return await render_template("auth/reset_confirm.html", token=token, error=None)


# ---------------------------------------------------------------------------
# POST /auth/reset/confirm
# ---------------------------------------------------------------------------

@auth_views_bp.post("/auth/reset/confirm")
async def reset_confirm_post():
    form = await request.form
    raw_token = (form.get("token") or "").strip()
    new_password = form.get("new_password") or ""
    confirm_password = form.get("confirm_password") or ""

    if not raw_token or not new_password:
        return await render_template(
            "auth/reset_confirm.html",
            token=raw_token,
            error="Token and new password are required.",
        )

    if new_password != confirm_password:
        return await render_template(
            "auth/reset_confirm.html",
            token=raw_token,
            error="Passwords do not match.",
        )

    if len(new_password) < 8:
        return await render_template(
            "auth/reset_confirm.html",
            token=raw_token,
            error="Password must be at least 8 characters.",
        )

    try:
        await svc_reset_confirm(raw_token, new_password)
    except AuthError as exc:
        return await render_template(
            "auth/reset_confirm.html",
            token=raw_token,
            error=exc.message,
        )

    return redirect(url_for("auth_views.login_get") + "?reset=1")
