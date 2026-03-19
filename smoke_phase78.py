"""
Phase 7 + 8 smoke test -- Solo Quests and Group Quests.

Phase 7 -- Solo Quests:
  - Create quest (admin), assigned to a member, with chore_ids
  - GET /api/v1/quests (member sees own, admin sees all)
  - GET /api/v1/quests/:id (member, forbidden for other member)
  - GET /api/v1/quests/:id/progress (tracks completion status)
  - POST /api/v1/quests/:id/chores/:chore_id/complete
      - awards chore lumin_value
      - awards quest bonus_lumins when last chore done
      - bonus awarded only once (idempotent re-complete)
  - PUT /api/v1/quests/:id (update)
  - DELETE /api/v1/quests/:id (deactivate)
  - Quest view pages render (GET /quests, GET /quests/:id)

Phase 8 -- Group Quests:
  - Create group quest (admin) with chore pool and initial member roster
  - GET /api/v1/group-quests (member sees enrolled, admin sees all)
  - GET /api/v1/group-quests/:id
  - POST /api/v1/group-quests/:id/join (self-enroll, 409 if already in)
  - DELETE /api/v1/group-quests/:id/leave (not-member 409, completed-quest 409)
  - POST /api/v1/group-quests/:id/chores/:chore_id/claim (soft, non-blocking)
  - DELETE /api/v1/group-quests/:id/chores/:chore_id/claim (own claim only)
  - POST /api/v1/group-quests/:id/chores/:chore_id/complete
      - awards chore lumin_value to completer
      - 409 on double-complete
      - awards bonus to ALL members when last chore done
  - GET /api/v1/group-quests/:id/progress
  - GET /api/v1/group-quests/:id/contributions
  - PUT /api/v1/group-quests/:id (update)
  - DELETE /api/v1/group-quests/:id (deactivate)
  - Role enforcement: child cannot create/update/delete
  - Group quest view pages render (GET /group-quests, GET /group-quests/:id)
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from app.config import Config

SEED_ADMIN = ("admin", "changeme")
_CHECKS = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global _CHECKS
    if not condition:
        msg = f"FAIL: {label}"
        if detail:
            msg += f"  ({detail})"
        raise AssertionError(msg)
    _CHECKS += 1
    print(f"  [OK] {label}")


async def login(client, username: str, password: str) -> str | None:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    if resp.status_code != 200:
        return None
    for hv in resp.headers.getlist("Set-Cookie"):
        if "tasklings_session=" in hv:
            return hv.split(";")[0].split("=", 1)[1]
    return None


def ah(session: str) -> dict:
    return {"Cookie": f"tasklings_session={session}"}


async def create_child(client, adm: dict, username: str, name: str) -> tuple[str, str]:
    r = await client.post(
        "/api/v1/members",
        json={"username": username, "password": "kidpass1", "name": name, "role": "child"},
        headers=adm,
    )
    assert r.status_code == 201
    mid = (await r.get_json())["member"]["id"]
    sess = await login(client, username, "kidpass1")
    assert sess
    return mid, sess


async def create_chore(client, adm: dict, title: str, lumin_value: int = 10) -> str:
    r = await client.post(
        "/api/v1/chores",
        json={"title": title, "chore_type": "constant", "lumin_value": lumin_value},
        headers=adm,
    )
    assert r.status_code == 201
    return (await r.get_json())["chore"]["id"]


async def run(db_path: str) -> int:
    cfg = Config(BCRYPT_ROUNDS=4, DATABASE_PATH=db_path, TESTING=True)
    app = create_app(cfg)
    async with app.test_app():
        pass

    client = app.test_client(use_cookies=False)
    assert client.cookie_jar is None

    # ── Auth ──────────────────────────────────────────────────────────────────
    admin_sess = await login(client, *SEED_ADMIN)
    check("Admin login", admin_sess is not None)
    adm = ah(admin_sess)

    alice_id, a_sess = await create_child(client, adm, "alice", "Alice")
    bob_id, b_sess   = await create_child(client, adm, "bob",   "Bob")
    a = ah(a_sess)
    b = ah(b_sess)

    # Give alice some Lumins to verify balance changes.
    await client.post(f"/api/v1/members/{alice_id}/lumins/adjust",
                      json={"amount": 50, "reason": "bonus"}, headers=adm)
    await client.post(f"/api/v1/members/{bob_id}/lumins/adjust",
                      json={"amount": 50, "reason": "bonus"}, headers=adm)

    # Create chores for use in quests.
    chore1_id = await create_chore(client, adm, "Sweep Floor", lumin_value=5)
    chore2_id = await create_chore(client, adm, "Take Trash",  lumin_value=8)
    chore3_id = await create_chore(client, adm, "Water Plants", lumin_value=6)

    # Assign chores to alice so daily generation can create assignments.
    await client.put(f"/api/v1/chores/{chore1_id}/assignees",
                     json={"member_ids": [alice_id]}, headers=adm)
    await client.put(f"/api/v1/chores/{chore2_id}/assignees",
                     json={"member_ids": [alice_id]}, headers=adm)
    await client.put(f"/api/v1/chores/{chore3_id}/assignees",
                     json={"member_ids": [bob_id]},   headers=adm)

    # Trigger assignment generation so chore_assignment rows exist.
    await client.get("/api/v1/my/assignments", headers=a)  # alice's today
    await client.get("/api/v1/my/assignments", headers=b)  # bob's today

    # ── Phase 7: Solo Quests ─────────────────────────────────────────────────
    print("\n── Phase 7: Solo Quests ────────────────────────────────────────────")

    # Create quest for alice: both chores, 20 bonus
    r = await client.post("/api/v1/quests", json={
        "name": "Alice's Morning Quest",
        "description": "Start the day right",
        "member_id": alice_id,
        "bonus_lumins": 20,
        "chore_ids": [chore1_id, chore2_id],
    }, headers=adm)
    check("POST /api/v1/quests (create)", r.status_code == 201)
    quest_data = await r.get_json()
    quest_id = quest_data["quest"]["id"]
    check("Quest has chores", len(quest_data["quest"]["chores"]) == 2)

    # Alice sees it; Bob does not.
    r = await client.get("/api/v1/quests", headers=a)
    check("GET /api/v1/quests (alice)", r.status_code == 200)
    alice_quests = (await r.get_json())["quests"]
    check("Alice sees her quest", any(q["id"] == quest_id for q in alice_quests))

    r = await client.get("/api/v1/quests", headers=b)
    bob_quests = (await r.get_json())["quests"]
    check("Bob does not see alice's quest", not any(q["id"] == quest_id for q in bob_quests))

    # Admin sees all.
    r = await client.get("/api/v1/quests", headers=adm)
    check("GET /api/v1/quests (admin sees all)", r.status_code == 200)

    # GET quest detail -- alice can, bob cannot.
    r = await client.get(f"/api/v1/quests/{quest_id}", headers=a)
    check("GET /api/v1/quests/:id (alice)", r.status_code == 200)
    r = await client.get(f"/api/v1/quests/{quest_id}", headers=b)
    check("GET /api/v1/quests/:id (bob forbidden)", r.status_code == 403)

    # Progress -- nothing done yet.
    r = await client.get(f"/api/v1/quests/{quest_id}/progress", headers=a)
    check("GET /api/v1/quests/:id/progress", r.status_code == 200)
    progress = (await r.get_json())["progress"]
    check("Progress: 2 chores, none done", len(progress) == 2 and not any(p["completed"] for p in progress))

    # Complete first chore -- check balance increments.
    r = await client.get("/api/v1/my/assignments", headers=a)
    assignments = (await r.get_json())["assignments"]
    assign1 = next((a2 for a2 in assignments if a2["chore_id"] == chore1_id), None)
    check("Alice has assignment for chore1", assign1 is not None)

    r = await client.post(f"/api/v1/quests/{quest_id}/chores/{chore1_id}/complete", headers=a)
    check("POST quest chore complete (chore1)", r.status_code == 200)
    result = await r.get_json()
    check("Chore was completed", result["chore_completed"] is True)
    check("Quest not yet complete", result["quest_completed"] is False)
    check("No bonus yet", result["bonus_awarded"] == 0)

    # Balance = 50 + 5 (chore1) = 55.
    r = await client.get(f"/api/v1/members/{alice_id}/balance", headers=a)
    check("Balance after chore1: 55", (await r.get_json())["balance"] == 55)

    # Complete second chore -- quest should complete.
    r = await client.post(f"/api/v1/quests/{quest_id}/chores/{chore2_id}/complete", headers=a)
    check("POST quest chore complete (chore2 = last)", r.status_code == 200)
    result = await r.get_json()
    check("Quest completed", result["quest_completed"] is True)
    check("Bonus awarded = 20", result["bonus_awarded"] == 20)

    # Balance = 55 + 8 (chore2) + 20 (bonus) = 83.
    r = await client.get(f"/api/v1/members/{alice_id}/balance", headers=a)
    check("Balance after quest completion: 83", (await r.get_json())["balance"] == 83)

    # Re-completing does not award bonus again (idempotent).
    r = await client.post(f"/api/v1/quests/{quest_id}/chores/{chore1_id}/complete", headers=a)
    result2 = await r.get_json()
    check("Re-complete: chore not re-done (already completed)", result2["chore_completed"] is False)
    check("Re-complete: no extra bonus", result2["bonus_awarded"] == 0)

    # Balance unchanged.
    r = await client.get(f"/api/v1/members/{alice_id}/balance", headers=a)
    check("Balance unchanged after re-complete: 83", (await r.get_json())["balance"] == 83)

    # Update quest.
    r = await client.put(f"/api/v1/quests/{quest_id}", json={"name": "Alice's Quest (updated)"}, headers=adm)
    check("PUT /api/v1/quests/:id", r.status_code == 200)
    check("Name updated", (await r.get_json())["quest"]["name"] == "Alice's Quest (updated)")

    # Deactivate quest.
    r = await client.delete(f"/api/v1/quests/{quest_id}", headers=adm)
    check("DELETE /api/v1/quests/:id", r.status_code == 200)
    r = await client.get("/api/v1/quests", headers=a)
    remaining = (await r.get_json())["quests"]
    check("Deactivated quest gone from alice's list", not any(q["id"] == quest_id for q in remaining))

    # Role enforcement.
    r = await client.post("/api/v1/quests", json={"name": "Nope", "member_id": alice_id, "chore_ids": []}, headers=a)
    check("POST /api/v1/quests (child) => 403", r.status_code == 403)

    # Views.
    r = await client.get("/quests", headers=a)
    check("GET /quests (HTML)", r.status_code == 200)
    check("Quests page has quest-list", "quests" in (await r.get_data(as_text=True)).lower())

    # Create a second quest for detail page test.
    r = await client.post("/api/v1/quests", json={
        "name": "Detail Test Quest",
        "member_id": alice_id,
        "bonus_lumins": 0,
        "chore_ids": [chore1_id],
    }, headers=adm)
    detail_quest_id = (await r.get_json())["quest"]["id"]
    r = await client.get(f"/quests/{detail_quest_id}", headers=a)
    check("GET /quests/:id (HTML)", r.status_code == 200)

    # ── Phase 8: Group Quests ─────────────────────────────────────────────────
    print("\n── Phase 8: Group Quests ───────────────────────────────────────────")

    # Create group quest with alice pre-enrolled, 2 chores in pool.
    r = await client.post("/api/v1/group-quests", json={
        "name": "Family Clean-Up",
        "description": "Get it all done together",
        "bonus_lumins": 15,
        "reward_description": "Movie night!",
        "deadline": "2026-12-31",
        "chore_ids": [chore1_id, chore2_id],
        "member_ids": [alice_id],
    }, headers=adm)
    check("POST /api/v1/group-quests (create)", r.status_code == 201)
    gq = (await r.get_json())["group_quest"]
    gq_id = gq["id"]
    check("GQ has 2 chores", len(gq["chores"]) == 2)
    check("GQ has alice in contributions", any(c["member_id"] == alice_id for c in gq["contributions"]))

    # Alice sees it; Bob (not enrolled) does not via member list.
    r = await client.get("/api/v1/group-quests", headers=a)
    check("GET /api/v1/group-quests (alice enrolled)", r.status_code == 200)
    alice_gqs = (await r.get_json())["group_quests"]
    check("Alice sees GQ", any(g["id"] == gq_id for g in alice_gqs))

    r = await client.get("/api/v1/group-quests", headers=b)
    bob_gqs = (await r.get_json())["group_quests"]
    check("Bob not enrolled, doesn't see GQ", not any(g["id"] == gq_id for g in bob_gqs))

    # GET detail.
    r = await client.get(f"/api/v1/group-quests/{gq_id}", headers=a)
    check("GET /api/v1/group-quests/:id", r.status_code == 200)
    gq_detail = (await r.get_json())["group_quest"]
    check("GQ detail has reward_description", gq_detail["reward_description"] == "Movie night!")
    check("GQ detail has deadline", gq_detail["deadline"] == "2026-12-31")

    # Bob joins.
    r = await client.post(f"/api/v1/group-quests/{gq_id}/join", headers=b)
    check("POST /api/v1/group-quests/:id/join (bob)", r.status_code == 200)

    # Double-join => 409.
    r = await client.post(f"/api/v1/group-quests/{gq_id}/join", headers=b)
    check("Double join => 409", r.status_code == 409)

    # Bob now sees it.
    r = await client.get("/api/v1/group-quests", headers=b)
    bob_gqs2 = (await r.get_json())["group_quests"]
    check("Bob sees GQ after joining", any(g["id"] == gq_id for g in bob_gqs2))

    # Contributions.
    r = await client.get(f"/api/v1/group-quests/{gq_id}/contributions", headers=a)
    check("GET contributions", r.status_code == 200)
    contribs = (await r.get_json())["contributions"]
    check("Contributions has 2 members", len(contribs) == 2)
    check("Both start at 0", all(c["completed_count"] == 0 for c in contribs))

    # Alice claims chore1.
    r = await client.post(f"/api/v1/group-quests/{gq_id}/chores/{chore1_id}/claim", headers=a)
    check("POST claim chore1 (alice)", r.status_code == 200)
    claim = (await r.get_json())["claim"]
    check("Claim recorded for alice", claim["claimed_by"] == alice_id)

    # Bob also claims it -- overwrites alice's claim (non-blocking per spec).
    r = await client.post(f"/api/v1/group-quests/{gq_id}/chores/{chore1_id}/claim", headers=b)
    check("POST claim chore1 (bob, overwrites alice)", r.status_code == 200)
    claim2 = (await r.get_json())["claim"]
    check("Bob's claim recorded", claim2["claimed_by"] == bob_id)

    # Alice tries to release -- not her claim, so it's a no-op (silent).
    r = await client.delete(f"/api/v1/group-quests/{gq_id}/chores/{chore1_id}/claim", headers=a)
    check("DELETE claim (alice releases non-own, silent ok)", r.status_code == 200)

    # Verify claim is still bob's.
    r = await client.get(f"/api/v1/group-quests/{gq_id}/progress", headers=a)
    prog = (await r.get_json())["chores"]
    c1_prog = next(c for c in prog if c["chore_id"] == chore1_id)
    check("Claim still bob's after alice's failed release", c1_prog["claimed_by"] == bob_id)

    # Alice completes chore1 (she's enrolled, so she can complete any chore).
    alice_balance_before = (await (await client.get(f"/api/v1/members/{alice_id}/balance", headers=a)).get_json())["balance"]
    r = await client.post(f"/api/v1/group-quests/{gq_id}/chores/{chore1_id}/complete", headers=a)
    check("POST complete chore1 (alice)", r.status_code == 200)
    comp = await r.get_json()
    check("Completed = True", comp["completed"] is True)
    check("Quest not yet complete", comp["quest_complete"] is False)

    # Alice earned chore1's lumin_value (5) ... but wait: chore1 was originally
    # assigned to alice in daily assignments; its lumin_value is 5.
    alice_balance_after = (await (await client.get(f"/api/v1/members/{alice_id}/balance", headers=a)).get_json())["balance"]
    check("Alice balance +5 after completing chore1", alice_balance_after == alice_balance_before + 5)

    # Double-complete => 409.
    r = await client.post(f"/api/v1/group-quests/{gq_id}/chores/{chore1_id}/complete", headers=b)
    check("Double complete chore1 => 409", r.status_code == 409)

    # Non-member cannot complete.
    # Create a third child not in the quest.
    carol_id, c_sess = await create_child(client, adm, "carol", "Carol")
    c = ah(c_sess)
    r = await client.post(f"/api/v1/group-quests/{gq_id}/chores/{chore2_id}/complete", headers=c)
    check("Non-member complete => 403", r.status_code == 403)

    # Bob completes chore2 -- that's the last one, quest completes.
    bob_balance_before = (await (await client.get(f"/api/v1/members/{bob_id}/balance", headers=b)).get_json())["balance"]
    alice_balance_pre2  = (await (await client.get(f"/api/v1/members/{alice_id}/balance", headers=a)).get_json())["balance"]
    r = await client.post(f"/api/v1/group-quests/{gq_id}/chores/{chore2_id}/complete", headers=b)
    check("POST complete chore2 (bob, last chore)", r.status_code == 200)
    comp2 = await r.get_json()
    check("Quest complete", comp2["quest_complete"] is True)
    check("Bonus awarded = 15", comp2["bonus_awarded"] == 15)
    check("Reward description returned", comp2["reward_description"] == "Movie night!")

    # Both alice and bob should have received the 15 Lumin bonus.
    alice_balance_post2 = (await (await client.get(f"/api/v1/members/{alice_id}/balance", headers=a)).get_json())["balance"]
    bob_balance_after   = (await (await client.get(f"/api/v1/members/{bob_id}/balance", headers=b)).get_json())["balance"]
    # Bob earned: chore2 lumin_value(8) + bonus(15) = +23
    check("Bob balance +23 (chore2 + bonus)", bob_balance_after == bob_balance_before + 8 + 15)
    # Alice earned: bonus(15) only (she didn't complete chore2)
    check("Alice balance +15 (bonus only)", alice_balance_post2 == alice_balance_pre2 + 15)

    # Contributions updated.
    r = await client.get(f"/api/v1/group-quests/{gq_id}/contributions", headers=a)
    contribs2 = (await r.get_json())["contributions"]
    alice_contrib = next(c2 for c2 in contribs2 if c2["member_id"] == alice_id)
    bob_contrib   = next(c2 for c2 in contribs2 if c2["member_id"] == bob_id)
    check("Alice contributed 1 chore", alice_contrib["completed_count"] == 1)
    check("Bob contributed 1 chore",   bob_contrib["completed_count"] == 1)

    # Progress shows complete.
    r = await client.get(f"/api/v1/group-quests/{gq_id}/progress", headers=a)
    p_data = await r.get_json()
    check("Progress is_complete = True", p_data["is_complete"] is True)

    # Cannot leave a completed quest.
    r = await client.delete(f"/api/v1/group-quests/{gq_id}/leave", headers=a)
    check("Leave completed quest => 409", r.status_code == 409)

    # Create another GQ to test leave before completion.
    r = await client.post("/api/v1/group-quests", json={
        "name": "Leave Test Quest",
        "chore_ids": [],
        "bonus_lumins": 0,
    }, headers=adm)
    leave_gq_id = (await r.get_json())["group_quest"]["id"]
    await client.post(f"/api/v1/group-quests/{leave_gq_id}/join", headers=b)
    r = await client.delete(f"/api/v1/group-quests/{leave_gq_id}/leave", headers=b)
    check("Leave incomplete quest => 200", r.status_code == 200)

    # Not-member leave => 409.
    r = await client.delete(f"/api/v1/group-quests/{leave_gq_id}/leave", headers=b)
    check("Leave when not-member => 409", r.status_code == 409)

    # Update GQ.
    r = await client.put(f"/api/v1/group-quests/{gq_id}", json={"name": "Family Clean-Up (done)"}, headers=adm)
    check("PUT /api/v1/group-quests/:id", r.status_code == 200)
    check("Name updated", (await r.get_json())["group_quest"]["name"] == "Family Clean-Up (done)")

    # Deactivate GQ.
    r = await client.delete(f"/api/v1/group-quests/{gq_id}", headers=adm)
    check("DELETE /api/v1/group-quests/:id", r.status_code == 200)

    # Role enforcement.
    r = await client.post("/api/v1/group-quests", json={"name": "Nope", "chore_ids": []}, headers=a)
    check("POST /api/v1/group-quests (child) => 403", r.status_code == 403)

    r = await client.put(f"/api/v1/group-quests/{leave_gq_id}", json={"name": "Hacked"}, headers=a)
    check("PUT /api/v1/group-quests/:id (child) => 403", r.status_code == 403)

    r = await client.delete(f"/api/v1/group-quests/{leave_gq_id}", headers=a)
    check("DELETE /api/v1/group-quests/:id (child) => 403", r.status_code == 403)

    # Views.
    r = await client.get("/quests", headers=a)
    check("GET /quests (HTML)", r.status_code == 200)

    r = await client.get("/group-quests", headers=a)
    check("GET /group-quests (HTML)", r.status_code == 200)
    check("Group quests page rendered", "group" in (await r.get_data(as_text=True)).lower())

    # Create a new GQ for detail view test (the completed one is deactivated).
    r = await client.post("/api/v1/group-quests", json={
        "name": "Detail View GQ",
        "chore_ids": [chore3_id],
        "bonus_lumins": 5,
        "member_ids": [alice_id],
    }, headers=adm)
    detail_gq_id = (await r.get_json())["group_quest"]["id"]
    r = await client.get(f"/group-quests/{detail_gq_id}", headers=a)
    check("GET /group-quests/:id (HTML)", r.status_code == 200)
    detail_body = await r.get_data(as_text=True)
    check("Detail page has chore pool heading", "pool" in detail_body.lower() or "chore" in detail_body.lower())

    return _CHECKS


def main() -> None:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", prefix="tasklings_smoke78_", delete=False)
    tmp.close()
    db_path = tmp.name
    try:
        ok = asyncio.run(run(db_path))
        print(f"\n{'─' * 60}")
        print(f"  {ok} checks passed.  Phase 7+8 smoke test PASSED.")
        print(f"{'─' * 60}\n")
    except AssertionError as exc:
        print(f"\n  FAIL: {exc}\n", file=sys.stderr)
        sys.exit(1)
    finally:
        for suffix in ("", "-wal", "-shm"):
            p = db_path + suffix
            if os.path.exists(p):
                os.unlink(p)


if __name__ == "__main__":
    main()
