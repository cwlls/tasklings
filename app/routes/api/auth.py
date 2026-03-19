"""
Auth API routes -- /api/v1/auth/*

All endpoints return JSON.
Error envelope: {"error": "<message>", "code": "<ERROR_CODE>"}
"""
from __future__ import annotations

from quart import Blueprint, g, jsonify, request, current_app

from app.middleware.auth import login_required, COOKIE_NAME
from app.services.auth import (
    AuthError,
    login as svc_login,
    logout as svc_logout,
    change_password as svc_change_password,
    request_password_reset as svc_reset_request,
    confirm_password_reset as svc_reset_confirm,
)

auth_api_bp = Blueprint("auth_api", __name__, url_prefix="/api/v1/auth")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _err(message: str, code: str, status: int):
    return jsonify({"error": message, "code": code}), status


def _is_secure() -> bool:
    """Return True when running in production (not TESTING, not debug)."""
    return not current_app.config.get("TESTING", False) and not current_app.debug


def _set_session_cookie(response, session_id: str):
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
# POST /api/v1/auth/login
# ---------------------------------------------------------------------------

@auth_api_bp.post("/login")
async def api_login():
    body = await request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""

    if not username or not password:
        return _err("username and password are required.", "MISSING_FIELDS", 400)

    try:
        result = await svc_login(username, password)
    except AuthError as exc:
        return _err(exc.message, exc.code, 401)

    resp = jsonify({"member": result["member"]})
    _set_session_cookie(resp, result["session_id"])
    return resp, 200


# ---------------------------------------------------------------------------
# POST /api/v1/auth/logout
# ---------------------------------------------------------------------------

@auth_api_bp.post("/logout")
async def api_logout():
    session_id = request.cookies.get(COOKIE_NAME)
    if session_id:
        await svc_logout(session_id)

    resp = jsonify({"ok": True})
    _clear_session_cookie(resp)
    return resp, 200


# ---------------------------------------------------------------------------
# GET /api/v1/auth/me
# ---------------------------------------------------------------------------

@auth_api_bp.get("/me")
@login_required
async def api_me():
    return jsonify({"member": g.current_user}), 200


# ---------------------------------------------------------------------------
# POST /api/v1/auth/change-password
# ---------------------------------------------------------------------------

@auth_api_bp.post("/change-password")
@login_required
async def api_change_password():
    body = await request.get_json(silent=True) or {}
    old_password = body.get("old_password") or ""
    new_password = body.get("new_password") or ""

    if not old_password or not new_password:
        return _err("old_password and new_password are required.", "MISSING_FIELDS", 400)

    if len(new_password) < 8:
        return _err("New password must be at least 8 characters.", "PASSWORD_TOO_SHORT", 400)

    try:
        await svc_change_password(g.current_user["id"], old_password, new_password)
    except AuthError as exc:
        return _err(exc.message, exc.code, 400)

    return jsonify({"ok": True}), 200


# ---------------------------------------------------------------------------
# POST /api/v1/auth/reset-request
# ---------------------------------------------------------------------------

@auth_api_bp.post("/reset-request")
async def api_reset_request():
    """
    Always returns 200 regardless of whether the username exists (no info leak).
    When SMTP is not configured, the raw token is NOT returned here -- it is
    available to an admin via GET /api/v1/admin/members/<id>/reset-token.
    """
    body = await request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()

    if username:
        await svc_reset_request(username)

    return jsonify({"ok": True, "message": "If that username exists, a reset token has been generated."}), 200


# ---------------------------------------------------------------------------
# POST /api/v1/auth/reset-confirm
# ---------------------------------------------------------------------------

@auth_api_bp.post("/reset-confirm")
async def api_reset_confirm():
    body = await request.get_json(silent=True) or {}
    raw_token = (body.get("token") or "").strip()
    new_password = body.get("new_password") or ""

    if not raw_token or not new_password:
        return _err("token and new_password are required.", "MISSING_FIELDS", 400)

    if len(new_password) < 8:
        return _err("New password must be at least 8 characters.", "PASSWORD_TOO_SHORT", 400)

    try:
        await svc_reset_confirm(raw_token, new_password)
    except AuthError as exc:
        return _err(exc.message, exc.code, 400)

    return jsonify({"ok": True}), 200
