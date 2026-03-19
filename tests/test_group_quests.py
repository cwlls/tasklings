"""
Group quest tests.
"""
from __future__ import annotations


async def _create_chore(client, adm, title, lumin_value=5):
    r = await client.post(
        "/api/v1/chores",
        json={"title": title, "chore_type": "constant", "lumin_value": lumin_value},
        headers=adm,
    )
    assert r.status_code == 201
    return (await r.get_json())["chore"]["id"]


async def _give(client, adm, member_id, amount):
    await client.post(
        f"/api/v1/members/{member_id}/lumins/adjust",
        json={"amount": amount, "reason": "bonus"},
        headers=adm,
    )


async def _balance(client, member_id, hdrs):
    r = await client.get(f"/api/v1/members/{member_id}/balance", headers=hdrs)
    return (await r.get_json())["balance"]


async def test_create_group_quest(client, admin_session, alice):
    _, adm = admin_session
    alice_id, _ = alice
    c1 = await _create_chore(client, adm, "GQ Chore A")
    r = await client.post(
        "/api/v1/group-quests",
        json={
            "name": "Family Quest",
            "bonus_lumins": 20,
            "chore_ids": [c1],
            "member_ids": [alice_id],
        },
        headers=adm,
    )
    assert r.status_code == 201
    data = await r.get_json()
    assert data["group_quest"]["name"] == "Family Quest"
    assert len(data["group_quest"]["chores"]) == 1


async def test_child_cannot_create_group_quest(client, alice):
    _, a_hdrs = alice
    r = await client.post(
        "/api/v1/group-quests",
        json={"name": "Nope", "chore_ids": []},
        headers=a_hdrs,
    )
    assert r.status_code == 403


async def test_join_and_leave(client, admin_session, alice, bob):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    bob_id, b_hdrs = bob
    r = await client.post(
        "/api/v1/group-quests",
        json={"name": "Join Test", "chore_ids": [], "member_ids": [alice_id]},
        headers=adm,
    )
    gq_id = (await r.get_json())["group_quest"]["id"]

    # Bob joins.
    rj = await client.post(f"/api/v1/group-quests/{gq_id}/join", headers=b_hdrs)
    assert rj.status_code == 200

    # Double join -> 409.
    rj2 = await client.post(f"/api/v1/group-quests/{gq_id}/join", headers=b_hdrs)
    assert rj2.status_code == 409

    # Bob leaves.
    rl = await client.delete(f"/api/v1/group-quests/{gq_id}/leave", headers=b_hdrs)
    assert rl.status_code == 200

    # Leave again (not a member) -> 409.
    rl2 = await client.delete(f"/api/v1/group-quests/{gq_id}/leave", headers=b_hdrs)
    assert rl2.status_code == 409


async def test_claim_and_release(client, admin_session, alice, bob):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    bob_id, b_hdrs = bob
    c1 = await _create_chore(client, adm, "Claim Chore")
    r = await client.post(
        "/api/v1/group-quests",
        json={"name": "Claim Quest", "chore_ids": [c1], "member_ids": [alice_id, bob_id]},
        headers=adm,
    )
    gq_id = (await r.get_json())["group_quest"]["id"]

    # Alice claims.
    rc = await client.post(f"/api/v1/group-quests/{gq_id}/chores/{c1}/claim", headers=a_hdrs)
    assert rc.status_code == 200
    assert (await rc.get_json())["claim"]["claimed_by"] == alice_id

    # Bob overwrites (non-blocking).
    rc2 = await client.post(f"/api/v1/group-quests/{gq_id}/chores/{c1}/claim", headers=b_hdrs)
    assert rc2.status_code == 200
    assert (await rc2.get_json())["claim"]["claimed_by"] == bob_id

    # Alice tries to release -- not her claim, silent no-op.
    rr = await client.delete(f"/api/v1/group-quests/{gq_id}/chores/{c1}/claim", headers=a_hdrs)
    assert rr.status_code == 200

    # Claim still bob's.
    prog = (await (await client.get(f"/api/v1/group-quests/{gq_id}/progress", headers=a_hdrs)).get_json())["chores"]
    chore_prog = next(p for p in prog if p["chore_id"] == c1)
    assert chore_prog["claimed_by"] == bob_id


async def test_complete_chore_awards_lumins_and_bonus(client, admin_session, alice, bob):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    bob_id, b_hdrs = bob
    c1 = await _create_chore(client, adm, "Pool Chore 1", lumin_value=5)
    c2 = await _create_chore(client, adm, "Pool Chore 2", lumin_value=8)
    r = await client.post(
        "/api/v1/group-quests",
        json={
            "name": "Bonus Quest",
            "bonus_lumins": 15,
            "chore_ids": [c1, c2],
            "member_ids": [alice_id, bob_id],
        },
        headers=adm,
    )
    gq_id = (await r.get_json())["group_quest"]["id"]

    # Alice completes c1.
    rc1 = await client.post(f"/api/v1/group-quests/{gq_id}/chores/{c1}/complete", headers=a_hdrs)
    assert rc1.status_code == 200
    d1 = await rc1.get_json()
    assert d1["completed"] is True
    assert d1["quest_complete"] is False

    alice_bal_before_bonus = await _balance(client, alice_id, a_hdrs)
    bob_bal_before = await _balance(client, bob_id, b_hdrs)

    # Bob completes c2 (last chore -> quest complete).
    rc2 = await client.post(f"/api/v1/group-quests/{gq_id}/chores/{c2}/complete", headers=b_hdrs)
    assert rc2.status_code == 200
    d2 = await rc2.get_json()
    assert d2["quest_complete"] is True
    assert d2["bonus_awarded"] == 15

    # Bob gets c2 lumin_value + bonus.
    assert await _balance(client, bob_id, b_hdrs) == bob_bal_before + 8 + 15
    # Alice gets only the bonus (didn't complete c2).
    assert await _balance(client, alice_id, a_hdrs) == alice_bal_before_bonus + 15


async def test_double_complete_chore_rejected(client, admin_session, alice, bob):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    bob_id, b_hdrs = bob
    c1 = await _create_chore(client, adm, "Double Chore")
    r = await client.post(
        "/api/v1/group-quests",
        json={"name": "Double Test", "chore_ids": [c1], "member_ids": [alice_id, bob_id]},
        headers=adm,
    )
    gq_id = (await r.get_json())["group_quest"]["id"]

    await client.post(f"/api/v1/group-quests/{gq_id}/chores/{c1}/complete", headers=a_hdrs)
    r2 = await client.post(f"/api/v1/group-quests/{gq_id}/chores/{c1}/complete", headers=b_hdrs)
    assert r2.status_code == 409


async def test_non_member_cannot_complete(client, admin_session, alice, bob):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    _, b_hdrs = bob
    c1 = await _create_chore(client, adm, "Members Only")
    r = await client.post(
        "/api/v1/group-quests",
        json={"name": "Exclusive", "chore_ids": [c1], "member_ids": [alice_id]},
        headers=adm,
    )
    gq_id = (await r.get_json())["group_quest"]["id"]

    r2 = await client.post(f"/api/v1/group-quests/{gq_id}/chores/{c1}/complete", headers=b_hdrs)
    assert r2.status_code == 403


async def test_contribution_tracking(client, admin_session, alice, bob):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    bob_id, b_hdrs = bob
    c1 = await _create_chore(client, adm, "Contrib A")
    c2 = await _create_chore(client, adm, "Contrib B")
    r = await client.post(
        "/api/v1/group-quests",
        json={"name": "Contrib Quest", "chore_ids": [c1, c2], "member_ids": [alice_id, bob_id]},
        headers=adm,
    )
    gq_id = (await r.get_json())["group_quest"]["id"]

    await client.post(f"/api/v1/group-quests/{gq_id}/chores/{c1}/complete", headers=a_hdrs)
    await client.post(f"/api/v1/group-quests/{gq_id}/chores/{c2}/complete", headers=b_hdrs)

    r_c = await client.get(f"/api/v1/group-quests/{gq_id}/contributions", headers=a_hdrs)
    contribs = (await r_c.get_json())["contributions"]
    alice_c = next(c for c in contribs if c["member_id"] == alice_id)
    bob_c = next(c for c in contribs if c["member_id"] == bob_id)
    assert alice_c["completed_count"] == 1
    assert bob_c["completed_count"] == 1


async def test_cannot_leave_completed_quest(client, admin_session, alice):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    # Quest with no chores -> immediately complete after creation? No -- it's
    # complete only once all chores are done. With 0 chores it's trivially
    # complete. Use 1 chore and complete it.
    c1 = await _create_chore(client, adm, "Leave Test Chore")
    r = await client.post(
        "/api/v1/group-quests",
        json={"name": "Leave Test", "chore_ids": [c1], "member_ids": [alice_id]},
        headers=adm,
    )
    gq_id = (await r.get_json())["group_quest"]["id"]
    await client.post(f"/api/v1/group-quests/{gq_id}/chores/{c1}/complete", headers=a_hdrs)

    rl = await client.delete(f"/api/v1/group-quests/{gq_id}/leave", headers=a_hdrs)
    assert rl.status_code == 409


async def test_progress_is_complete_flag(client, admin_session, alice):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    c1 = await _create_chore(client, adm, "Complete Flag Chore")
    r = await client.post(
        "/api/v1/group-quests",
        json={"name": "Flag Quest", "chore_ids": [c1], "member_ids": [alice_id]},
        headers=adm,
    )
    gq_id = (await r.get_json())["group_quest"]["id"]

    prog_before = await client.get(f"/api/v1/group-quests/{gq_id}/progress", headers=a_hdrs)
    assert (await prog_before.get_json())["is_complete"] is False

    await client.post(f"/api/v1/group-quests/{gq_id}/chores/{c1}/complete", headers=a_hdrs)
    prog_after = await client.get(f"/api/v1/group-quests/{gq_id}/progress", headers=a_hdrs)
    assert (await prog_after.get_json())["is_complete"] is True
