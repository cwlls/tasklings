"""
Store service and API tests.

Actual API paths:
  GET  /api/v1/store                        -- list visible items
  POST /api/v1/store                        -- create item (admin)
  GET  /api/v1/store/<item_id>              -- get one item
  PUT  /api/v1/store/<item_id>              -- update (admin)
  DELETE /api/v1/store/<item_id>            -- deactivate (admin)
  PUT  /api/v1/store/<item_id>/visibility   -- set visibility (admin)
  POST /api/v1/store/<item_id>/purchase     -- buy (returns 201)
  POST /api/v1/store/purchases/<id>/redeem  -- redeem (admin)

Error codes:
  InsufficientBalanceError  -> 402
  OutOfStockError           -> 409
  ItemNotAvailableError     -> 410
  ItemNotVisibleError       -> 404
"""
from __future__ import annotations


async def _give(client, adm, member_id: str, amount: int) -> None:
    r = await client.post(
        f"/api/v1/members/{member_id}/lumins/adjust",
        json={"amount": amount, "reason": "bonus"},
        headers=adm,
    )
    assert r.status_code == 200


async def _create_item(client, adm, title="Widget", price=10,
                       stock=None, available=True) -> str:
    body: dict = {"title": title, "price": price, "is_available": available}
    if stock is not None:
        body["stock"] = stock
    r = await client.post("/api/v1/store", json=body, headers=adm)
    assert r.status_code == 201, await r.get_data(as_text=True)
    return (await r.get_json())["item"]["id"]


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

async def test_create_store_item_admin(client, admin_session):
    _, adm = admin_session
    r = await client.post(
        "/api/v1/store",
        json={"title": "Prize", "price": 50},
        headers=adm,
    )
    assert r.status_code == 201
    assert (await r.get_json())["item"]["title"] == "Prize"


async def test_create_store_item_child_forbidden(client, alice):
    _, a_hdrs = alice
    r = await client.post(
        "/api/v1/store",
        json={"title": "Hack", "price": 0},
        headers=a_hdrs,
    )
    assert r.status_code == 403


async def test_list_store_items(client, admin_session, alice):
    _, adm = admin_session
    _, a_hdrs = alice
    await _create_item(client, adm, "Book")
    r = await client.get("/api/v1/store", headers=a_hdrs)
    assert r.status_code == 200
    items = (await r.get_json())["items"]
    assert any(i["title"] == "Book" for i in items)


async def test_update_store_item(client, admin_session):
    _, adm = admin_session
    item_id = await _create_item(client, adm, "Old Title", price=5)
    r = await client.put(
        f"/api/v1/store/{item_id}",
        json={"title": "New Title", "price": 15},
        headers=adm,
    )
    assert r.status_code == 200
    d = await r.get_json()
    assert d["item"]["title"] == "New Title"
    assert d["item"]["price"] == 15


# ---------------------------------------------------------------------------
# Visibility
# ---------------------------------------------------------------------------

async def test_global_item_visible_to_all(client, admin_session, alice, bob):
    _, adm = admin_session
    _, a_hdrs = alice
    _, b_hdrs = bob
    await _create_item(client, adm, "Global Prize")
    items_a = (await (await client.get("/api/v1/store", headers=a_hdrs)).get_json())["items"]
    items_b = (await (await client.get("/api/v1/store", headers=b_hdrs)).get_json())["items"]
    assert any(i["title"] == "Global Prize" for i in items_a)
    assert any(i["title"] == "Global Prize" for i in items_b)


async def test_targeted_item_visible_only_to_target(client, admin_session, alice, bob):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    _, b_hdrs = bob

    r = await client.post("/api/v1/store", json={"title": "Alice Special", "price": 5}, headers=adm)
    item_id = (await r.get_json())["item"]["id"]
    await client.put(
        f"/api/v1/store/{item_id}/visibility",
        json={"member_ids": [alice_id]},
        headers=adm,
    )

    items_b = (await (await client.get("/api/v1/store", headers=b_hdrs)).get_json())["items"]
    assert not any(i["title"] == "Alice Special" for i in items_b)
    items_a = (await (await client.get("/api/v1/store", headers=a_hdrs)).get_json())["items"]
    assert any(i["title"] == "Alice Special" for i in items_a)


# ---------------------------------------------------------------------------
# Purchase flow
# ---------------------------------------------------------------------------

async def test_purchase_success(client, admin_session, alice):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    await _give(client, adm, alice_id, 100)
    item_id = await _create_item(client, adm, "Cool Toy", price=30)

    r = await client.post(f"/api/v1/store/{item_id}/purchase", headers=a_hdrs)
    assert r.status_code == 201
    assert (await r.get_json())["purchase"]["status"] == "purchased"

    # Balance deducted.
    rb = await client.get(f"/api/v1/members/{alice_id}/balance", headers=a_hdrs)
    assert (await rb.get_json())["balance"] == 70


async def test_purchase_insufficient_balance(client, admin_session, alice):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    item_id = await _create_item(client, adm, "Expensive", price=999)
    # Alice starts at 0; expect 402 Insufficient Balance.
    r = await client.post(f"/api/v1/store/{item_id}/purchase", headers=a_hdrs)
    assert r.status_code == 402


async def test_purchase_out_of_stock(client, admin_session, alice, bob):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    bob_id, b_hdrs = bob
    await _give(client, adm, alice_id, 50)
    await _give(client, adm, bob_id, 50)
    item_id = await _create_item(client, adm, "Limited", price=10, stock=1)

    r1 = await client.post(f"/api/v1/store/{item_id}/purchase", headers=a_hdrs)
    assert r1.status_code == 201
    r2 = await client.post(f"/api/v1/store/{item_id}/purchase", headers=b_hdrs)
    assert r2.status_code == 409  # OutOfStock


async def test_purchase_unavailable_item(client, admin_session, alice):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    await _give(client, adm, alice_id, 100)
    item_id = await _create_item(client, adm, "Unavailable", price=5, available=False)
    r = await client.post(f"/api/v1/store/{item_id}/purchase", headers=a_hdrs)
    assert r.status_code == 410  # ItemNotAvailable


# ---------------------------------------------------------------------------
# Redemption
# ---------------------------------------------------------------------------

async def test_redeem_purchase(client, admin_session, alice):
    _, adm = admin_session
    alice_id, a_hdrs = alice
    await _give(client, adm, alice_id, 50)
    item_id = await _create_item(client, adm, "Redeemable", price=10)
    rp = await client.post(f"/api/v1/store/{item_id}/purchase", headers=a_hdrs)
    purchase_id = (await rp.get_json())["purchase"]["id"]

    r = await client.post(f"/api/v1/purchases/{purchase_id}/redeem", headers=adm)
    assert r.status_code == 200
    assert (await r.get_json())["purchase"]["status"] == "redeemed"
