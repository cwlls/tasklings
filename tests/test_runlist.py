"""
Runlist / assignment integration tests.

Covers lazy generation, completion, lumin award, same-day uncomplete,
admin verify/skip, and the sync bulk-completion endpoint.
"""
from __future__ import annotations


async def _create_chore(client, adm, title, lumin_value=10, assignee_id=None):
    r = await client.post(
        "/api/v1/chores",
        json={"title": title, "chore_type": "constant", "lumin_value": lumin_value},
        headers=adm,
    )
    assert r.status_code == 201
    cid = (await r.get_json())["chore"]["id"]
    if assignee_id:
        await client.put(
            f"/api/v1/chores/{cid}/assignees",
            json={"member_ids": [assignee_id]},
            headers=adm,
        )
    return cid


async def _assignments(client, hdrs):
    r = await client.get("/api/v1/my/assignments", headers=hdrs)
    assert r.status_code == 200
    return (await r.get_json())["assignments"]


# ---------------------------------------------------------------------------
# Lazy generation
# ---------------------------------------------------------------------------

async def test_assignments_generated_on_first_fetch(client, admin_session, alice):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    cid = await _create_chore(client, adm, "Morning Chore", lumin_value=5, assignee_id=alice_id)

    result = await _assignments(client, a_hdrs)
    assert any(a["chore_id"] == cid for a in result)


async def test_assignment_generation_idempotent(client, admin_session, alice):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    await _create_chore(client, adm, "Idempotent Chore", assignee_id=alice_id)

    ids1 = {a["id"] for a in await _assignments(client, a_hdrs)}
    ids2 = {a["id"] for a in await _assignments(client, a_hdrs)}
    assert ids1 == ids2


# ---------------------------------------------------------------------------
# Complete
# ---------------------------------------------------------------------------

async def test_complete_awards_lumins(client, admin_session, alice):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    cid = await _create_chore(client, adm, "Sweep", lumin_value=7, assignee_id=alice_id)
    assigns = await _assignments(client, a_hdrs)
    aid = next(a["id"] for a in assigns if a["chore_id"] == cid)

    r = await client.post(f"/api/v1/my/assignments/{aid}/complete", headers=a_hdrs)
    assert r.status_code == 200
    assert (await r.get_json())["new_balance"] == 7


async def test_complete_already_completed_returns_409(client, admin_session, alice):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    cid = await _create_chore(client, adm, "Double Complete", assignee_id=alice_id)
    assigns = await _assignments(client, a_hdrs)
    aid = next(a["id"] for a in assigns if a["chore_id"] == cid)
    await client.post(f"/api/v1/my/assignments/{aid}/complete", headers=a_hdrs)
    r = await client.post(f"/api/v1/my/assignments/{aid}/complete", headers=a_hdrs)
    assert r.status_code == 409


async def test_wrong_member_cannot_complete(client, admin_session, alice, bob):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    _, b_hdrs = bob
    cid = await _create_chore(client, adm, "Alice Only", assignee_id=alice_id)
    assigns = await _assignments(client, a_hdrs)
    aid = next(a["id"] for a in assigns if a["chore_id"] == cid)

    r = await client.post(f"/api/v1/my/assignments/{aid}/complete", headers=b_hdrs)
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Uncomplete (same-day)
# ---------------------------------------------------------------------------

async def test_uncomplete_same_day(client, admin_session, alice):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    cid = await _create_chore(client, adm, "Undo Me", lumin_value=10, assignee_id=alice_id)
    assigns = await _assignments(client, a_hdrs)
    aid = next(a["id"] for a in assigns if a["chore_id"] == cid)

    await client.post(f"/api/v1/my/assignments/{aid}/complete", headers=a_hdrs)
    # Balance = 10.
    rb1 = await client.get(f"/api/v1/members/{alice_id}/balance", headers=a_hdrs)
    assert (await rb1.get_json())["balance"] == 10

    r = await client.post(f"/api/v1/my/assignments/{aid}/uncomplete", headers=a_hdrs)
    assert r.status_code == 200
    # Balance reversed back to 0.
    rb2 = await client.get(f"/api/v1/members/{alice_id}/balance", headers=a_hdrs)
    assert (await rb2.get_json())["balance"] == 0


# ---------------------------------------------------------------------------
# Admin verify / skip
# ---------------------------------------------------------------------------

async def test_admin_verify(client, admin_session, alice):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    cid = await _create_chore(client, adm, "Verify Me", assignee_id=alice_id)
    assigns = await _assignments(client, a_hdrs)
    aid = next(a["id"] for a in assigns if a["chore_id"] == cid)
    await client.post(f"/api/v1/my/assignments/{aid}/complete", headers=a_hdrs)

    r = await client.post(f"/api/v1/assignments/{aid}/verify", headers=adm)
    assert r.status_code == 200
    assert (await r.get_json())["assignment"]["status"] == "verified"


async def test_admin_skip(client, admin_session, alice):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    cid = await _create_chore(client, adm, "Skip Me", assignee_id=alice_id)
    assigns = await _assignments(client, a_hdrs)
    aid = next(a["id"] for a in assigns if a["chore_id"] == cid)

    r = await client.post(f"/api/v1/assignments/{aid}/skip", headers=adm)
    assert r.status_code == 200
    assert (await r.get_json())["assignment"]["status"] == "skipped"


# ---------------------------------------------------------------------------
# Sync bulk-completion endpoint
# ---------------------------------------------------------------------------

async def test_sync_completions_accepted(client, admin_session, alice):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    cid = await _create_chore(client, adm, "Sync Chore", lumin_value=6, assignee_id=alice_id)
    assigns = await _assignments(client, a_hdrs)
    aid = next(a["id"] for a in assigns if a["chore_id"] == cid)

    r = await client.post(
        "/api/v1/sync/completions",
        json=[{"assignment_id": aid}],
        headers=a_hdrs,
    )
    assert r.status_code == 200
    data = await r.get_json()
    assert any(a["assignment_id"] == aid for a in data["accepted"])
    assert data["rejected"] == []


async def test_sync_completions_already_done_rejected(client, admin_session, alice):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    cid = await _create_chore(client, adm, "Sync Already Done", assignee_id=alice_id)
    assigns = await _assignments(client, a_hdrs)
    aid = next(a["id"] for a in assigns if a["chore_id"] == cid)
    await client.post(f"/api/v1/my/assignments/{aid}/complete", headers=a_hdrs)

    r = await client.post(
        "/api/v1/sync/completions",
        json=[{"assignment_id": aid}],
        headers=a_hdrs,
    )
    assert r.status_code == 200
    data = await r.get_json()
    assert data["accepted"] == []
    assert any(item["reason"] == "already_completed" for item in data["rejected"])


async def test_sync_completions_wrong_member_rejected(client, admin_session, alice, bob):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    _, b_hdrs = bob
    cid = await _create_chore(client, adm, "Sync Bob Chore", assignee_id=alice_id)
    assigns = await _assignments(client, a_hdrs)
    aid = next(a["id"] for a in assigns if a["chore_id"] == cid)

    # Bob tries to sync Alice's assignment.
    r = await client.post(
        "/api/v1/sync/completions",
        json=[{"assignment_id": aid}],
        headers=b_hdrs,
    )
    assert r.status_code == 200
    data = await r.get_json()
    assert data["accepted"] == []
    assert any(item["reason"] == "forbidden" for item in data["rejected"])
