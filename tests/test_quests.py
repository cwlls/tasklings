"""
Solo quest tests.
"""
from __future__ import annotations


async def _create_chore(client, adm, title, lumin_value=5, assignee_id=None):
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


async def _trigger_assignments(client, hdrs):
    await client.get("/api/v1/my/assignments", headers=hdrs)


async def test_create_quest(client, admin_session, alice):
    _, adm = admin_session
    alice_id, _ = alice
    cid = await _create_chore(client, adm, "Sweep", assignee_id=alice_id)
    r = await client.post(
        "/api/v1/quests",
        json={"name": "Morning Quest", "member_id": alice_id, "chore_ids": [cid], "bonus_lumins": 10},
        headers=adm,
    )
    assert r.status_code == 201
    data = await r.get_json()
    assert data["quest"]["name"] == "Morning Quest"
    assert len(data["quest"]["chores"]) == 1


async def test_child_cannot_create_quest(client, alice):
    _, a_hdrs = alice
    r = await client.post(
        "/api/v1/quests",
        json={"name": "Nope", "member_id": "x", "chore_ids": []},
        headers=a_hdrs,
    )
    assert r.status_code == 403


async def test_member_sees_own_quest_only(client, admin_session, alice, bob):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    bob_id, b_hdrs = bob
    cid = await _create_chore(client, adm, "Alice Chore", assignee_id=alice_id)
    r = await client.post(
        "/api/v1/quests",
        json={"name": "Alice Quest", "member_id": alice_id, "chore_ids": [cid]},
        headers=adm,
    )
    quest_id = (await r.get_json())["quest"]["id"]

    r_a = await client.get("/api/v1/quests", headers=a_hdrs)
    assert any(q["id"] == quest_id for q in (await r_a.get_json())["quests"])
    r_b = await client.get("/api/v1/quests", headers=b_hdrs)
    assert not any(q["id"] == quest_id for q in (await r_b.get_json())["quests"])


async def test_quest_progress(client, admin_session, alice):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    c1 = await _create_chore(client, adm, "Step 1", lumin_value=5, assignee_id=alice_id)
    c2 = await _create_chore(client, adm, "Step 2", lumin_value=5, assignee_id=alice_id)
    await _trigger_assignments(client, a_hdrs)
    r = await client.post(
        "/api/v1/quests",
        json={"name": "Two-Chore Quest", "member_id": alice_id, "chore_ids": [c1, c2], "bonus_lumins": 15},
        headers=adm,
    )
    quest_id = (await r.get_json())["quest"]["id"]

    prog = (await (await client.get(f"/api/v1/quests/{quest_id}/progress", headers=a_hdrs)).get_json())["progress"]
    assert len(prog) == 2
    assert not any(p["completed"] for p in prog)


async def test_quest_completion_awards_bonus(client, admin_session, alice):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    cid = await _create_chore(client, adm, "Solo Chore", lumin_value=5, assignee_id=alice_id)
    await _trigger_assignments(client, a_hdrs)
    r = await client.post(
        "/api/v1/quests",
        json={"name": "Bonus Quest", "member_id": alice_id, "chore_ids": [cid], "bonus_lumins": 20},
        headers=adm,
    )
    quest_id = (await r.get_json())["quest"]["id"]

    rc = await client.post(f"/api/v1/quests/{quest_id}/chores/{cid}/complete", headers=a_hdrs)
    assert rc.status_code == 200
    result = await rc.get_json()
    assert result["quest_completed"] is True
    assert result["bonus_awarded"] == 20

    # Balance = 5 (chore) + 20 (bonus).
    rb = await client.get(f"/api/v1/members/{alice_id}/balance", headers=a_hdrs)
    assert (await rb.get_json())["balance"] == 25


async def test_quest_bonus_idempotent(client, admin_session, alice):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    cid = await _create_chore(client, adm, "Idempotent Chore", lumin_value=5, assignee_id=alice_id)
    await _trigger_assignments(client, a_hdrs)
    r = await client.post(
        "/api/v1/quests",
        json={"name": "Idempotent Quest", "member_id": alice_id, "chore_ids": [cid], "bonus_lumins": 10},
        headers=adm,
    )
    quest_id = (await r.get_json())["quest"]["id"]

    await client.post(f"/api/v1/quests/{quest_id}/chores/{cid}/complete", headers=a_hdrs)
    r2 = await client.post(f"/api/v1/quests/{quest_id}/chores/{cid}/complete", headers=a_hdrs)
    result2 = await r2.get_json()
    # Second call: chore already done, no extra bonus.
    assert result2["chore_completed"] is False
    assert result2["bonus_awarded"] == 0

    rb = await client.get(f"/api/v1/members/{alice_id}/balance", headers=a_hdrs)
    assert (await rb.get_json())["balance"] == 15  # 5 + 10, not 30


async def test_update_and_deactivate_quest(client, admin_session, alice):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    r = await client.post(
        "/api/v1/quests",
        json={"name": "Temp Quest", "member_id": alice_id, "chore_ids": []},
        headers=adm,
    )
    quest_id = (await r.get_json())["quest"]["id"]

    r2 = await client.put(f"/api/v1/quests/{quest_id}", json={"name": "Updated"}, headers=adm)
    assert r2.status_code == 200
    assert (await r2.get_json())["quest"]["name"] == "Updated"

    r3 = await client.delete(f"/api/v1/quests/{quest_id}", headers=adm)
    assert r3.status_code == 200
    quests = (await (await client.get("/api/v1/quests", headers=a_hdrs)).get_json())["quests"]
    assert not any(q["id"] == quest_id for q in quests)
