"""
Phase 4 smoke test -- Core Runlist.

Covers:
  - Household + Members API
  - Chore CRUD (constant + rotating)
  - Assignment generation (lazy, idempotent)
  - Complete assignment + Lumin award
  - Uncomplete (self, same-day)
  - Balance endpoint
  - Runlist view (HTML + HTMX partial)
  - Root redirect behaviour
  - Admin-only enforcement on chore creation
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

# ---------------------------------------------------------------------------
# Bootstrap path
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from app.config import Config


SEED_ADMIN_USERNAME = "admin"
SEED_ADMIN_PASSWORD = "changeme"

_CHECKS = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global _CHECKS
    if not condition:
        msg = f"FAIL: {label}"
        if detail:
            msg += f" -- {detail}"
        raise AssertionError(msg)
    _CHECKS += 1
    print(f"  [OK] {label}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def login(client, username: str, password: str) -> str | None:
    """Return the raw session cookie value, or None on failure."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    if resp.status_code != 200:
        return None
    # Extract the session cookie from the response headers.
    for header_value in resp.headers.getlist("Set-Cookie"):
        if "tasklings_session=" in header_value:
            cookie_part = header_value.split(";")[0]
            return cookie_part.split("=", 1)[1]
    return None


def auth_headers(session: str) -> dict:
    return {"Cookie": f"tasklings_session={session}"}


def bearer_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Main test runner
# ---------------------------------------------------------------------------

async def run(db_path: str) -> int:
    cfg = Config(BCRYPT_ROUNDS=4, DATABASE_PATH=db_path, TESTING=True)
    app = create_app(cfg)

    async with app.test_app():
        pass  # fires before_serving / init_db

    client = app.test_client(use_cookies=False)
    assert client.cookie_jar is None

    # ── Admin login ──────────────────────────────────────────────────────────
    print("\n── Admin session ───────────────────────────────────────────────────")
    admin_session = await login(client, SEED_ADMIN_USERNAME, SEED_ADMIN_PASSWORD)
    check("Admin login", admin_session is not None)
    adm = auth_headers(admin_session)

    # ── Household API ────────────────────────────────────────────────────────
    print("\n── Household API ───────────────────────────────────────────────────")
    resp = await client.get("/api/v1/household", headers=adm)
    check("GET /api/v1/household", resp.status_code == 200)
    data = await resp.get_json()
    household_id = data["household"]["id"]
    check("Household has id", bool(household_id))

    resp = await client.put(
        "/api/v1/household",
        json={"name": "Smoke Test Family"},
        headers=adm,
    )
    check("PUT /api/v1/household", resp.status_code == 200)
    data = await resp.get_json()
    check("Household name updated", data["household"]["name"] == "Smoke Test Family")

    # ── Members API ──────────────────────────────────────────────────────────
    print("\n── Members API ─────────────────────────────────────────────────────")
    resp = await client.get("/api/v1/members", headers=adm)
    check("GET /api/v1/members (admin)", resp.status_code == 200)

    resp = await client.post(
        "/api/v1/members",
        json={
            "username": "child1",
            "password": "kidpass1",
            "name": "Alice",
            "role": "child",
            "color": "#ff6b6b",
        },
        headers=adm,
    )
    check("POST /api/v1/members (create child)", resp.status_code == 201)
    child_data = await resp.get_json()
    child_id = child_data["member"]["id"]
    check("Child created", bool(child_id))

    # Child can log in
    child_session = await login(client, "child1", "kidpass1")
    check("Child login", child_session is not None)
    kid = auth_headers(child_session)

    # Child sees limited member list
    resp = await client.get("/api/v1/members", headers=kid)
    check("GET /api/v1/members (child sees limited)", resp.status_code == 200)
    kid_members = (await resp.get_json())["members"]
    check("Child member list has no password_hash", all("password_hash" not in m for m in kid_members))

    # GET /members/:id (self)
    resp = await client.get(f"/api/v1/members/{child_id}", headers=kid)
    check("GET /api/v1/members/:id (self)", resp.status_code == 200)

    # PUT /members/:id (self, limited fields)
    resp = await client.put(
        f"/api/v1/members/{child_id}",
        json={"name": "Alice Updated", "color": "#aabbcc"},
        headers=kid,
    )
    check("PUT /api/v1/members/:id (self)", resp.status_code == 200)
    check("Name updated", (await resp.get_json())["member"]["name"] == "Alice Updated")

    # ── Constant chore ───────────────────────────────────────────────────────
    print("\n── Constant chore ──────────────────────────────────────────────────")
    resp = await client.post(
        "/api/v1/chores",
        json={
            "title": "Make Bed",
            "description": "Every morning",
            "lumin_value": 10,
            "chore_type": "constant",
            "assignee_ids": [child_id],
        },
        headers=adm,
    )
    check("POST /api/v1/chores (constant)", resp.status_code == 201)
    constant_chore = (await resp.get_json())["chore"]
    constant_chore_id = constant_chore["id"]
    check("Constant chore created", bool(constant_chore_id))
    check("Assignee stored", child_id in constant_chore.get("assignee_ids", []))

    # Get chore detail
    resp = await client.get(f"/api/v1/chores/{constant_chore_id}", headers=adm)
    check("GET /api/v1/chores/:id", resp.status_code == 200)

    # Update assignees
    resp = await client.put(
        f"/api/v1/chores/{constant_chore_id}/assignees",
        json={"member_ids": [child_id]},
        headers=adm,
    )
    check("PUT /api/v1/chores/:id/assignees", resp.status_code == 200)

    # ── Rotating chore ───────────────────────────────────────────────────────
    print("\n── Rotating chore ──────────────────────────────────────────────────")
    admin_member_resp = await client.get("/api/v1/members", headers=adm)
    admin_members = (await admin_member_resp.get_json())["members"]
    admin_id = next(m["id"] for m in admin_members if m.get("username") == "admin" or m["name"] == "Admin")

    resp = await client.post(
        "/api/v1/chores",
        json={
            "title": "Wash Dishes",
            "lumin_value": 15,
            "chore_type": "rotating",
            "rotation_frequency": "daily",
            "rotation_members": [child_id, admin_id],
        },
        headers=adm,
    )
    check("POST /api/v1/chores (rotating)", resp.status_code == 201)
    rotating_chore_id = (await resp.get_json())["chore"]["id"]

    # GET rotation
    resp = await client.get(f"/api/v1/chores/{rotating_chore_id}/rotation", headers=adm)
    check("GET /api/v1/chores/:id/rotation", resp.status_code == 200)
    rotation = (await resp.get_json())["rotation"]
    check("Rotation has 2 members", len(rotation) == 2)

    # Advance rotation
    resp = await client.post(f"/api/v1/chores/{rotating_chore_id}/rotation/advance", headers=adm)
    check("POST rotation/advance", resp.status_code == 200)

    # List chores
    resp = await client.get("/api/v1/chores", headers=adm)
    check("GET /api/v1/chores", resp.status_code == 200)
    all_chores = (await resp.get_json())["chores"]
    check("Two chores exist", len(all_chores) >= 2)

    # ── Assignment generation (lazy) ─────────────────────────────────────────
    print("\n── Assignment generation ───────────────────────────────────────────")
    resp = await client.get("/api/v1/my/assignments", headers=kid)
    check("GET /api/v1/my/assignments (child)", resp.status_code == 200)
    assign_data = await resp.get_json()
    assignments = assign_data["assignments"]
    check("Assignments generated", len(assignments) >= 1)
    check("Idempotent: second call same count", True)  # second call below

    resp2 = await client.get("/api/v1/my/assignments", headers=kid)
    assign_data2 = await resp2.get_json()
    check("Second call same count", len(assign_data2["assignments"]) == len(assignments))

    # Find the "Make Bed" assignment for the child
    bed_assignment = next(
        (a for a in assign_data2["assignments"] if a["title"] == "Make Bed"),
        None,
    )
    check("Make Bed assignment exists for child", bed_assignment is not None)

    # ── Complete assignment ──────────────────────────────────────────────────
    print("\n── Complete / balance ──────────────────────────────────────────────")
    resp = await client.post(
        f"/api/v1/my/assignments/{bed_assignment['id']}/complete",
        headers=kid,
    )
    check("POST complete assignment", resp.status_code == 200)
    complete_data = await resp.get_json()
    check("Status = completed", complete_data["assignment"]["status"] == "completed")
    check("Lumins awarded = 10", complete_data["assignment"]["lumins_awarded"] == 10)
    check("New balance = 10", complete_data["new_balance"] == 10)

    # Double-complete should 409
    resp = await client.post(
        f"/api/v1/my/assignments/{bed_assignment['id']}/complete",
        headers=kid,
    )
    check("Double-complete returns 409", resp.status_code == 409)

    # Balance endpoint
    resp = await client.get("/api/v1/my/balance", headers=kid)
    check("GET /api/v1/my/balance", resp.status_code == 200)
    bal_data = await resp.get_json()
    check("Balance is 10", bal_data["balance"] == 10)

    # Transactions
    resp = await client.get("/api/v1/my/transactions", headers=kid)
    check("GET /api/v1/my/transactions", resp.status_code == 200)
    txns = (await resp.get_json())["transactions"]
    check("One transaction exists", len(txns) >= 1)

    # ── Uncomplete ───────────────────────────────────────────────────────────
    print("\n── Uncomplete ──────────────────────────────────────────────────────")
    resp = await client.post(
        f"/api/v1/my/assignments/{bed_assignment['id']}/uncomplete",
        headers=kid,
    )
    check("POST uncomplete (self, same-day)", resp.status_code == 200)
    check("Status back to pending", (await resp.get_json())["assignment"]["status"] == "pending")

    # Balance should be 0 again
    resp = await client.get("/api/v1/my/balance", headers=kid)
    bal_after = (await resp.get_json())["balance"]
    check("Balance after uncomplete = 0", bal_after == 0)

    # ── Admin verify / skip ──────────────────────────────────────────────────
    print("\n── Admin verify / skip ─────────────────────────────────────────────")
    # Re-complete so we can verify
    await client.post(f"/api/v1/my/assignments/{bed_assignment['id']}/complete", headers=kid)

    resp = await client.post(
        f"/api/v1/assignments/{bed_assignment['id']}/verify",
        headers=adm,
    )
    check("POST /assignments/:id/verify", resp.status_code == 200)
    check("Status = verified", (await resp.get_json())["assignment"]["status"] == "verified")

    resp = await client.get(f"/api/v1/members/{child_id}/assignments", headers=adm)
    check("GET /members/:id/assignments (admin)", resp.status_code == 200)

    # ── Runlist view ─────────────────────────────────────────────────────────
    print("\n── Runlist view ────────────────────────────────────────────────────")
    resp = await client.get("/runlist", headers=kid)
    check("GET /runlist (HTML)", resp.status_code == 200)
    body_text = (await resp.get_data(as_text=True))
    check("Runlist page has chore list", "chore-list" in body_text)
    check("Runlist page shows balance", "lumin-display" in body_text)

    # HTMX partial
    resp = await client.get(
        "/runlist",
        headers={**kid, "HX-Request": "true"},
    )
    check("GET /runlist HTMX partial", resp.status_code == 200)
    partial_text = (await resp.get_data(as_text=True))
    check("Partial contains chore-list", "chore-list" in partial_text)
    check("Partial does NOT contain full page html tag", "<html" not in partial_text)

    # HTMX complete -- returns rendered partial (not JSON)
    # First re-find a pending assignment
    resp = await client.get("/api/v1/my/assignments", headers=kid)
    pending_assignments = [
        a for a in (await resp.get_json())["assignments"] if a["status"] == "pending"
    ]
    if pending_assignments:
        pa = pending_assignments[0]
        resp = await client.post(
            f"/api/v1/my/assignments/{pa['id']}/complete",
            headers={**kid, "HX-Request": "true"},
        )
        check("HTMX complete returns HTML partial", resp.status_code == 200)
        htmx_body = await resp.get_data(as_text=True)
        check("Partial contains chore-item", "chore-item" in htmx_body)
    else:
        check("(no pending assignment to HTMX-complete -- skipped)", True)

    # ── Root redirect ────────────────────────────────────────────────────────
    print("\n── Root redirect ───────────────────────────────────────────────────")
    resp = await client.get("/")
    check("GET / (no auth) redirects to /login", resp.status_code == 302)
    check("Redirect location = /login", "/login" in resp.headers.get("Location", ""))

    resp = await client.get("/", headers=kid)
    check("GET / (authed) redirects to /runlist", resp.status_code == 302)
    check("Redirect location = /runlist", "/runlist" in resp.headers.get("Location", ""))

    # ── Delete chore (soft) ──────────────────────────────────────────────────
    print("\n── Chore deactivation ──────────────────────────────────────────────")
    resp = await client.delete(f"/api/v1/chores/{constant_chore_id}", headers=adm)
    check("DELETE /api/v1/chores/:id", resp.status_code == 200)

    resp = await client.get("/api/v1/chores", headers=adm)
    active_ids = [c["id"] for c in (await resp.get_json())["chores"]]
    check("Deactivated chore not in active list", constant_chore_id not in active_ids)

    # Still accessible with include_inactive
    resp = await client.get("/api/v1/chores?include_inactive=true", headers=adm)
    all_ids = [c["id"] for c in (await resp.get_json())["chores"]]
    check("Deactivated chore visible with include_inactive", constant_chore_id in all_ids)

    # ── Role enforcement ─────────────────────────────────────────────────────
    print("\n── Role enforcement ────────────────────────────────────────────────")
    resp = await client.post(
        "/api/v1/chores",
        json={"title": "Forbidden", "chore_type": "constant"},
        headers=kid,
    )
    check("POST /api/v1/chores (child) => 403", resp.status_code == 403)

    resp = await client.put("/api/v1/household", json={"name": "Hacked"}, headers=kid)
    check("PUT /api/v1/household (child) => 403", resp.status_code == 403)

    resp = await client.delete(f"/api/v1/members/{child_id}", headers=kid)
    check("DELETE /api/v1/members/:id (child) => 403", resp.status_code == 403)

    return _CHECKS


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    tmp = tempfile.NamedTemporaryFile(
        suffix=".db",
        prefix="tasklings_smoke4_",
        delete=False,
    )
    tmp.close()
    db_path = tmp.name
    try:
        ok = asyncio.run(run(db_path))
        print(f"\n{'─' * 60}")
        print(f"  {ok} checks passed.  Phase 4 smoke test PASSED.")
        print(f"{'─' * 60}\n")
    except AssertionError as exc:
        print(f"\n  FAIL: {exc}\n", file=sys.stderr)
        sys.exit(1)
    finally:
        for suffix in ("", "-wal", "-shm"):
            path = db_path + suffix
            if os.path.exists(path):
                os.unlink(path)


if __name__ == "__main__":
    main()
