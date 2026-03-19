"""
Currency service and transaction API tests.
"""
from __future__ import annotations


async def _balance(client, member_id: str, auth: dict) -> int:
    r = await client.get(f"/api/v1/members/{member_id}/balance", headers=auth)
    return (await r.get_json())["balance"]


async def test_admin_credit_adjust(client, admin_session, alice):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    r = await client.post(
        f"/api/v1/members/{alice_id}/lumins/adjust",
        json={"amount": 50, "reason": "bonus"},
        headers=adm,
    )
    assert r.status_code == 200
    assert (await r.get_json())["new_balance"] == 50
    assert await _balance(client, alice_id, a_hdrs) == 50


async def test_admin_debit_adjust(client, admin_session, alice):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    await client.post(
        f"/api/v1/members/{alice_id}/lumins/adjust",
        json={"amount": 30, "reason": "bonus"},
        headers=adm,
    )
    r = await client.post(
        f"/api/v1/members/{alice_id}/lumins/adjust",
        json={"amount": -10, "reason": "penalty"},
        headers=adm,
    )
    assert r.status_code == 200
    assert (await r.get_json())["new_balance"] == 20


async def test_overdraft_rejected(client, admin_session, alice):
    _, adm = admin_session
    alice_id, _ = alice
    # Alice starts at 0 -- try to deduct 1.
    r = await client.post(
        f"/api/v1/members/{alice_id}/lumins/adjust",
        json={"amount": -1, "reason": "penalty"},
        headers=adm,
    )
    assert r.status_code == 409


async def test_invalid_adjust_reason(client, admin_session, alice):
    _, adm = admin_session
    alice_id, _ = alice
    r = await client.post(
        f"/api/v1/members/{alice_id}/lumins/adjust",
        json={"amount": 10, "reason": "chore_completed"},  # not an admin reason
        headers=adm,
    )
    assert r.status_code == 400


async def test_child_cannot_adjust_lumins(client, admin_session, alice):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    r = await client.post(
        f"/api/v1/members/{alice_id}/lumins/adjust",
        json={"amount": 100, "reason": "bonus"},
        headers=a_hdrs,
    )
    assert r.status_code == 403


async def test_member_transactions_listing(client, admin_session, alice):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    await client.post(
        f"/api/v1/members/{alice_id}/lumins/adjust",
        json={"amount": 20, "reason": "bonus"},
        headers=adm,
    )
    r = await client.get(f"/api/v1/members/{alice_id}/transactions", headers=a_hdrs)
    assert r.status_code == 200
    txs = (await r.get_json())["transactions"]
    assert len(txs) >= 1
    assert txs[0]["amount"] == 20


async def test_household_transactions_admin_only(client, admin_session, alice):
    _, adm = admin_session
    _, a_hdrs = alice
    r_admin = await client.get("/api/v1/transactions", headers=adm)
    assert r_admin.status_code == 200
    r_child = await client.get("/api/v1/transactions", headers=a_hdrs)
    assert r_child.status_code == 403


async def test_ledger_accuracy_after_multiple_ops(client, admin_session, alice):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    await client.post(
        f"/api/v1/members/{alice_id}/lumins/adjust",
        json={"amount": 100, "reason": "bonus"}, headers=adm,
    )
    await client.post(
        f"/api/v1/members/{alice_id}/lumins/adjust",
        json={"amount": -30, "reason": "penalty"}, headers=adm,
    )
    await client.post(
        f"/api/v1/members/{alice_id}/lumins/adjust",
        json={"amount": 15, "reason": "adjustment"}, headers=adm,
    )
    assert await _balance(client, alice_id, a_hdrs) == 85
