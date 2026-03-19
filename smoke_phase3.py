"""
Phase 3 smoke test.

Isolation guarantees
--------------------
1. A fresh temporary SQLite file is created at the start and deleted in a
   finally block, so no run ever inherits rows from a previous run,
   regardless of whether the previous run was killed mid-flight.

2. The Quart test client is created with use_cookies=False (passed directly
   to app.test_client(), NOT through TestApp.test_client() which ignores
   keyword arguments). This means the client never auto-injects cookies;
   every authenticated request must supply Cookie/Authorization explicitly.

3. bcrypt rounds are set to 4 for speed without sacrificing correctness.

Run from the project root:
    python smoke_phase3.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

import bcrypt

from app import create_app
from app.config import Config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sid(response) -> str:
    """Extract the raw session-id value from a Set-Cookie response header."""
    for cookie in response.headers.getlist("Set-Cookie"):
        if "tasklings_session=" in cookie:
            return cookie.split("tasklings_session=")[1].split(";")[0]
    raise AssertionError(
        f"No tasklings_session cookie in response. "
        f"Headers: {list(response.headers)}"
    )


def _cookie(sid: str) -> dict:
    return {"Cookie": f"tasklings_session={sid}"}


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

async def run(db_path: str) -> int:
    """Execute all checks. Returns the number of checks that passed."""
    cfg = Config(BCRYPT_ROUNDS=4, DATABASE_PATH=db_path, TESTING=True)
    app = create_app(cfg)

    # Run migrations inside test_app so before_serving fires.
    async with app.test_app():
        pass

    # use_cookies=False: cookie_jar is None, so _make_request never injects
    # cookies automatically. We pass Cookie headers manually where needed.
    client = app.test_client(use_cookies=False)
    assert client.cookie_jar is None, "cookie_jar must be None with use_cookies=False"

    ok = 0

    def check(label: str, got: int, want: int) -> None:
        nonlocal ok
        assert got == want, f"FAIL  {label}: expected HTTP {want}, got {got}"
        print(f"  [OK] {label}  =>  {want}")
        ok += 1

    # -----------------------------------------------------------------------
    print("\n── Public routes ───────────────────────────────────────────────────")
    # -----------------------------------------------------------------------

    r = await client.get("/")
    check("GET /", r.status_code, 200)

    r = await client.get("/login")
    check("GET /login (no auth)", r.status_code, 200)
    assert b"Sign In" in await r.get_data(), "login page missing 'Sign In'"

    r = await client.get("/auth/reset")
    check("GET /auth/reset", r.status_code, 200)

    r = await client.get("/auth/reset/confirm")
    check("GET /auth/reset/confirm", r.status_code, 200)

    # -----------------------------------------------------------------------
    print("\n── Credential checks ───────────────────────────────────────────────")
    # -----------------------------------------------------------------------

    r = await client.post(
        "/api/v1/auth/login",
        json={"username": "nobody", "password": "wrong"},
    )
    check("POST /api/v1/auth/login bad creds", r.status_code, 401)
    assert (await r.get_json())["code"] == "INVALID_CREDENTIALS"

    r = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "changeme"},
    )
    check("POST /api/v1/auth/login seed admin", r.status_code, 200)
    login_data = await r.get_json()
    assert login_data["member"]["username"] == "admin"
    assert login_data["member"]["role"] == "parent"
    assert "password_hash" not in login_data["member"], \
        "password_hash must never be returned to the client"
    admin_id: str = login_data["member"]["id"]
    admin_sid: str = _sid(r)

    # -----------------------------------------------------------------------
    print("\n── /me endpoint ────────────────────────────────────────────────────")
    # -----------------------------------------------------------------------

    # Critical: no Cookie header → must be 401
    r = await client.get("/api/v1/auth/me")
    check("GET /api/v1/auth/me (no auth)", r.status_code, 401)

    r = await client.get("/api/v1/auth/me", headers=_cookie(admin_sid))
    check("GET /api/v1/auth/me (session cookie)", r.status_code, 200)
    assert (await r.get_json())["member"]["username"] == "admin"

    # -----------------------------------------------------------------------
    print("\n── Redirect when already authenticated ─────────────────────────────")
    # -----------------------------------------------------------------------

    r = await client.get("/login", headers=_cookie(admin_sid))
    check("GET /login (already authed)", r.status_code, 302)

    # -----------------------------------------------------------------------
    print("\n── API token lifecycle ──────────────────────────────────────────────")
    # -----------------------------------------------------------------------

    r = await client.get("/api/v1/tokens", headers=_cookie(admin_sid))
    check("GET /api/v1/tokens (admin)", r.status_code, 200)
    assert "tokens" in await r.get_json()

    r = await client.post(
        "/api/v1/tokens",
        json={"label": "dashboard"},
        headers=_cookie(admin_sid),
    )
    check("POST /api/v1/tokens", r.status_code, 201)
    tok = await r.get_json()
    raw_token: str = tok["token"]
    token_id: str = tok["token_id"]
    assert raw_token and token_id

    r = await client.get("/api/v1/auth/me", headers=_bearer(raw_token))
    check("GET /api/v1/auth/me (Bearer token)", r.status_code, 200)
    assert (await r.get_json())["member"]["username"] == "admin"

    r = await client.delete(f"/api/v1/tokens/{token_id}", headers=_cookie(admin_sid))
    check("DELETE /api/v1/tokens/<id>", r.status_code, 200)

    r = await client.get("/api/v1/auth/me", headers=_bearer(raw_token))
    check("GET /api/v1/auth/me (revoked Bearer)", r.status_code, 401)

    # -----------------------------------------------------------------------
    print("\n── Password reset flow ──────────────────────────────────────────────")
    # -----------------------------------------------------------------------

    r = await client.post(
        "/api/v1/auth/reset-request",
        json={"username": "doesnotexist"},
    )
    check("POST /api/v1/auth/reset-request (unknown user)", r.status_code, 200)

    r = await client.post(
        "/api/v1/auth/reset-request",
        json={"username": "admin"},
    )
    check("POST /api/v1/auth/reset-request (real user)", r.status_code, 200)

    r = await client.get(
        f"/api/v1/admin/members/{admin_id}/reset-token",
        headers=_cookie(admin_sid),
    )
    check("GET /api/v1/admin/members/<id>/reset-token", r.status_code, 200)
    reset_data = await r.get_json()
    raw_reset: str = reset_data["raw_token"]
    assert raw_reset, "raw_token must be present in response"

    r = await client.post(
        "/api/v1/auth/reset-confirm",
        json={"token": raw_reset, "new_password": "newpass123"},
    )
    check("POST /api/v1/auth/reset-confirm", r.status_code, 200)

    r = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "changeme"},
    )
    check("POST /api/v1/auth/login (old password after reset)", r.status_code, 401)

    r = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "newpass123"},
    )
    check("POST /api/v1/auth/login (new password)", r.status_code, 200)
    new_sid: str = _sid(r)

    r = await client.post(
        "/api/v1/auth/reset-confirm",
        json={"token": raw_reset, "new_password": "anotherpass1"},
    )
    check("POST /api/v1/auth/reset-confirm (already used token)", r.status_code, 400)

    # -----------------------------------------------------------------------
    print("\n── change-password ──────────────────────────────────────────────────")
    # -----------------------------------------------------------------------

    r = await client.post(
        "/api/v1/auth/change-password",
        json={"old_password": "wrong", "new_password": "doesntmatter"},
        headers=_cookie(new_sid),
    )
    check("POST /api/v1/auth/change-password (wrong old pw)", r.status_code, 400)

    r = await client.post(
        "/api/v1/auth/change-password",
        json={"old_password": "newpass123", "new_password": "changedpass1"},
        headers=_cookie(new_sid),
    )
    check("POST /api/v1/auth/change-password (correct)", r.status_code, 200)

    # -----------------------------------------------------------------------
    print("\n── admin set-password ───────────────────────────────────────────────")
    # -----------------------------------------------------------------------

    r = await client.post(
        f"/api/v1/admin/members/{admin_id}/set-password",
        json={"new_password": "adminreset1"},
        headers=_cookie(new_sid),
    )
    check("POST /api/v1/admin/members/<id>/set-password", r.status_code, 200)

    r = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "adminreset1"},
    )
    check("POST /api/v1/auth/login (after admin set-password)", r.status_code, 200)
    final_sid: str = _sid(r)

    # -----------------------------------------------------------------------
    print("\n── logout ───────────────────────────────────────────────────────────")
    # -----------------------------------------------------------------------

    r = await client.post("/api/v1/auth/logout", headers=_cookie(final_sid))
    check("POST /api/v1/auth/logout", r.status_code, 200)

    r = await client.get("/api/v1/auth/me", headers=_cookie(final_sid))
    check("GET /api/v1/auth/me (after logout)", r.status_code, 401)

    # -----------------------------------------------------------------------
    print("\n── Role enforcement ─────────────────────────────────────────────────")
    # -----------------------------------------------------------------------

    # Create a child member via the model layer inside a live app context.
    async with app.test_app():
        async with app.test_request_context("/"):
            from app.models.household import get_household
            from app.models.members import create_member

            hh = await get_household()
            child_hash = bcrypt.hashpw(b"childpass1", bcrypt.gensalt(rounds=4)).decode()
            await create_member(hh["id"], "child1", child_hash, "Child One", "child")

    r = await client.post(
        "/api/v1/auth/login",
        json={"username": "child1", "password": "childpass1"},
    )
    check("POST /api/v1/auth/login (child)", r.status_code, 200)
    child_sid: str = _sid(r)

    r = await client.get("/api/v1/tokens", headers=_cookie(child_sid))
    check("GET /api/v1/tokens (child role → admin_required)", r.status_code, 403)
    assert (await r.get_json())["code"] == "FORBIDDEN"

    r = await client.post(
        f"/api/v1/admin/members/{admin_id}/set-password",
        json={"new_password": "haxorpass1"},
        headers=_cookie(child_sid),
    )
    check("POST /api/v1/admin/members/<id>/set-password (child role)", r.status_code, 403)

    r = await client.get(
        f"/api/v1/admin/members/{admin_id}/reset-token",
        headers=_cookie(child_sid),
    )
    check("GET /api/v1/admin/members/<id>/reset-token (child role)", r.status_code, 403)

    return ok


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    # Create a fresh, isolated temporary database for this run.
    # NamedTemporaryFile with delete=False so we can pass its path to SQLite,
    # then delete it ourselves in the finally block.
    tmp = tempfile.NamedTemporaryFile(
        suffix=".db",
        prefix="tasklings_smoke_",
        delete=False,
    )
    tmp.close()
    db_path = tmp.name

    try:
        ok = asyncio.run(run(db_path))
        print(f"\n{'─' * 60}")
        print(f"  {ok} checks passed.  Phase 3 smoke test PASSED.")
        print(f"{'─' * 60}\n")
    except AssertionError as exc:
        print(f"\n  FAIL: {exc}\n", file=sys.stderr)
        sys.exit(1)
    finally:
        # Always clean up, even if the test is killed after this point.
        for suffix in ("", "-wal", "-shm"):
            path = db_path + suffix
            if os.path.exists(path):
                os.unlink(path)


if __name__ == "__main__":
    main()
