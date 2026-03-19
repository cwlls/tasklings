"""
Authentication middleware.

Registers a before_request handler that resolves the current user from either:
  1. The ``tasklings_session`` httpOnly cookie (PWA / browser clients), or
  2. An ``Authorization: Bearer <token>`` header (external API consumers).

Resolved user is stored on ``g.current_user`` as a dict (or None).
A Jinja2 context processor makes ``current_user`` available in all templates.

Decorators
----------
@login_required   -- 401 JSON or redirect to /login
@admin_required   -- 403 JSON or redirect to /login (after login_required check)
"""
from __future__ import annotations

import functools
import logging
from typing import Callable

from quart import g, request, redirect, url_for, jsonify

logger = logging.getLogger(__name__)

COOKIE_NAME = "tasklings_session"


# ---------------------------------------------------------------------------
# before_request handler
# ---------------------------------------------------------------------------

async def resolve_user() -> None:
    """
    Populate ``g.current_user`` on every request.

    Precedence: session cookie > Bearer token > None.
    """
    # Import here to avoid circular imports at module load time.
    from app.services.auth import validate_session, validate_api_token

    g.current_user = None

    # 1. Session cookie (browser / PWA)
    session_id = request.cookies.get(COOKIE_NAME)
    if session_id:
        g.current_user = await validate_session(session_id)
        if g.current_user:
            return

    # 2. Bearer token (external API consumers)
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        raw_token = auth_header[len("Bearer "):]
        g.current_user = await validate_api_token(raw_token)


# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------

def _is_api_request() -> bool:
    return request.path.startswith("/api/")


def login_required(f: Callable) -> Callable:
    """
    Require an authenticated user.

    - API routes (/api/...): returns 401 JSON on failure.
    - View routes:           redirects to /login on failure.
    """
    @functools.wraps(f)
    async def wrapper(*args, **kwargs):
        if not g.get("current_user"):
            if _is_api_request():
                return jsonify({"error": "Authentication required.", "code": "UNAUTHENTICATED"}), 401
            return redirect(url_for("auth_views.login_get"))
        return await f(*args, **kwargs)
    return wrapper


def admin_required(f: Callable) -> Callable:
    """
    Require an authenticated *parent* (admin) user.

    Applies login_required logic first, then checks role.
    - API routes: 401 if unauthenticated, 403 if wrong role.
    - View routes: redirects to /login if unauthenticated, 403 JSON if wrong role.
    """
    @functools.wraps(f)
    async def wrapper(*args, **kwargs):
        user = g.get("current_user")
        if not user:
            if _is_api_request():
                return jsonify({"error": "Authentication required.", "code": "UNAUTHENTICATED"}), 401
            return redirect(url_for("auth_views.login_get"))

        if user.get("role") != "parent":
            return jsonify({"error": "Admin access required.", "code": "FORBIDDEN"}), 403

        return await f(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Jinja2 context processor
# ---------------------------------------------------------------------------

def inject_current_user() -> dict:
    """Make ``current_user`` available in every template automatically."""
    return {"current_user": g.get("current_user")}
