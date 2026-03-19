"""
Chore definition and assignment tests.
"""
from __future__ import annotations


async def _create_chore(client, adm, title="Do Dishes", lumin_value=10, chore_type="constant"):
    r = await client.post(
        "/api/v1/chores",
        json={"title": title, "chore_type": chore_type, "lumin_value": lumin_value},
        headers=adm,
    )
    assert r.status_code == 201
    return (await r.get_json())["chore"]["id"]


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

async def test_create_chore_admin(client, admin_session):
    _, adm = admin_session
    r = await client.post(
        "/api/v1/chores",
        json={"title": "Sweep", "chore_type": "constant", "lumin_value": 5},
        headers=adm,
    )
    assert r.status_code == 201
    data = await r.get_json()
    assert data["chore"]["title"] == "Sweep"
    assert data["chore"]["lumin_value"] == 5


async def test_create_chore_child_forbidden(client, alice):
    _, a_hdrs = alice
    r = await client.post(
        "/api/v1/chores",
        json={"title": "Hack", "chore_type": "constant", "lumin_value": 999},
        headers=a_hdrs,
    )
    assert r.status_code == 403


async def test_list_chores(client, admin_session):
    _, adm = admin_session
    await _create_chore(client, adm, "Chore A")
    await _create_chore(client, adm, "Chore B")
    r = await client.get("/api/v1/chores", headers=adm)
    assert r.status_code == 200
    chores = (await r.get_json())["chores"]
    titles = [c["title"] for c in chores]
    assert "Chore A" in titles
    assert "Chore B" in titles


async def test_get_chore(client, admin_session):
    _, adm = admin_session
    cid = await _create_chore(client, adm, "Vacuum")
    r = await client.get(f"/api/v1/chores/{cid}", headers=adm)
    assert r.status_code == 200
    assert (await r.get_json())["chore"]["title"] == "Vacuum"


async def test_update_chore(client, admin_session):
    _, adm = admin_session
    cid = await _create_chore(client, adm, "Old Name")
    r = await client.put(
        f"/api/v1/chores/{cid}",
        json={"title": "New Name", "lumin_value": 20},
        headers=adm,
    )
    assert r.status_code == 200
    assert (await r.get_json())["chore"]["title"] == "New Name"


async def test_deactivate_chore(client, admin_session):
    _, adm = admin_session
    cid = await _create_chore(client, adm, "To Delete")
    r = await client.delete(f"/api/v1/chores/{cid}", headers=adm)
    assert r.status_code == 200
    # Should no longer appear in active list.
    r2 = await client.get("/api/v1/chores", headers=adm)
    ids = [(await r2.get_json())["chores"]]
    active_ids = [c["id"] for c in (await r2.get_json())["chores"]]
    assert cid not in active_ids


# ---------------------------------------------------------------------------
# Assignees
# ---------------------------------------------------------------------------

async def test_set_and_get_assignees(client, admin_session, alice):
    _, adm = admin_session
    alice_id, _ = alice
    cid = await _create_chore(client, adm, "Dishes")
    r = await client.put(
        f"/api/v1/chores/{cid}/assignees",
        json={"member_ids": [alice_id]},
        headers=adm,
    )
    assert r.status_code == 200
    r2 = await client.get(f"/api/v1/chores/{cid}", headers=adm)
    detail = await r2.get_json()
    assert alice_id in detail["chore"]["assignee_ids"]


# ---------------------------------------------------------------------------
# Assignment generation (lazy on first GET /my/assignments)
# ---------------------------------------------------------------------------

async def test_assignment_generation_lazy(client, admin_session, alice):
    _, adm = admin_session
    alice_id, a_hdrs = alice

    cid = await _create_chore(client, adm, "Morning Sweep", lumin_value=7)
    await client.put(
        f"/api/v1/chores/{cid}/assignees",
        json={"member_ids": [alice_id]},
        headers=adm,
    )
    r = await client.get("/api/v1/my/assignments", headers=a_hdrs)
    assert r.status_code == 200
    data = await r.get_json()
    assert any(a["chore_id"] == cid for a in data["assignments"])


async def test_assignment_idempotent(client, admin_session, alice):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    cid = await _create_chore(client, adm, "Feed Cat")
    await client.put(
        f"/api/v1/chores/{cid}/assignees",
        json={"member_ids": [alice_id]},
        headers=adm,
    )
    r1 = await client.get("/api/v1/my/assignments", headers=a_hdrs)
    r2 = await client.get("/api/v1/my/assignments", headers=a_hdrs)
    ids1 = {a["id"] for a in (await r1.get_json())["assignments"]}
    ids2 = {a["id"] for a in (await r2.get_json())["assignments"]}
    assert ids1 == ids2


# ---------------------------------------------------------------------------
# Complete / uncomplete assignment
# ---------------------------------------------------------------------------

async def test_complete_assignment(client, admin_session, alice):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    cid = await _create_chore(client, adm, "Make Bed", lumin_value=8)
    await client.put(
        f"/api/v1/chores/{cid}/assignees",
        json={"member_ids": [alice_id]},
        headers=adm,
    )
    r = await client.get("/api/v1/my/assignments", headers=a_hdrs)
    assignments = (await r.get_json())["assignments"]
    assign = next(a for a in assignments if a["chore_id"] == cid)

    r2 = await client.post(
        f"/api/v1/my/assignments/{assign['id']}/complete",
        headers=a_hdrs,
    )
    assert r2.status_code == 200

    # Balance increased by lumin_value.
    rb = await client.get(f"/api/v1/members/{alice_id}/balance", headers=a_hdrs)
    assert (await rb.get_json())["balance"] == 8


async def test_complete_assignment_twice_rejected(client, admin_session, alice):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    cid = await _create_chore(client, adm, "Trash Out")
    await client.put(
        f"/api/v1/chores/{cid}/assignees",
        json={"member_ids": [alice_id]},
        headers=adm,
    )
    assignments = (await (await client.get("/api/v1/my/assignments", headers=a_hdrs)).get_json())["assignments"]
    assign = next(a for a in assignments if a["chore_id"] == cid)
    await client.post(f"/api/v1/my/assignments/{assign['id']}/complete", headers=a_hdrs)
    r2 = await client.post(f"/api/v1/my/assignments/{assign['id']}/complete", headers=a_hdrs)
    assert r2.status_code == 409


async def test_other_member_cannot_complete_assignment(client, admin_session, alice, bob):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    _, b_hdrs = bob
    cid = await _create_chore(client, adm, "Alice Only")
    await client.put(
        f"/api/v1/chores/{cid}/assignees",
        json={"member_ids": [alice_id]},
        headers=adm,
    )
    assignments = (await (await client.get("/api/v1/my/assignments", headers=a_hdrs)).get_json())["assignments"]
    assign = next(a for a in assignments if a["chore_id"] == cid)
    r = await client.post(f"/api/v1/my/assignments/{assign['id']}/complete", headers=b_hdrs)
    assert r.status_code == 403


async def test_admin_verify_assignment(client, admin_session, alice):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    cid = await _create_chore(client, adm, "Verify Me")
    await client.put(
        f"/api/v1/chores/{cid}/assignees",
        json={"member_ids": [alice_id]},
        headers=adm,
    )
    assignments = (await (await client.get("/api/v1/my/assignments", headers=a_hdrs)).get_json())["assignments"]
    assign = next(a for a in assignments if a["chore_id"] == cid)
    await client.post(f"/api/v1/my/assignments/{assign['id']}/complete", headers=a_hdrs)
    r = await client.post(f"/api/v1/assignments/{assign['id']}/verify", headers=adm)
    assert r.status_code == 200
    assert (await r.get_json())["assignment"]["status"] == "verified"
