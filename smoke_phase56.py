"""
Phase 5 + 6 smoke test -- Lumins Ledger and Store.

Covers:
  Phase 5 -- Transaction API
    - GET /api/v1/transactions           (admin, household-wide)
    - GET /api/v1/members/:id/balance    (admin, self, other-child forbidden)
    - GET /api/v1/members/:id/transactions (admin, self, pagination)
    - POST /api/v1/members/:id/lumins/adjust (bonus, penalty, adjustment)
    - Invalid adjust reasons rejected
    - Penalty that would overdraft rejected

  Phase 6 -- Store
    - Create global item
    - Create member-targeted item
    - Visibility: child sees only their item + globals; other child sees only globals
    - GET /api/v1/store/:id (visible and not-visible)
    - PUT /api/v1/store/:id (update)
    - PUT /api/v1/store/:id/visibility (replace)
    - Purchase success (balance deducted, purchase row created)
    - Purchase with insufficient balance => 402
    - Purchase out-of-stock item => 409
    - Purchase unavailable item => 410
    - GET /api/v1/purchases (my purchases)
    - GET /api/v1/purchases/:id (owner and admin can read; other child cannot)
    - POST /api/v1/purchases/:id/redeem (admin)
    - Redeem already-redeemed => 409
    - DELETE /api/v1/store/:id (soft deactivate)
    - Store views: GET /store renders HTML, GET /purchases renders HTML
    - HTMX store view partial
    - HTMX purchase action returns HTML partial
    - Manual Lumin adjustment: bonus, penalty, overdraft guard
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
    """Auth headers for a session cookie."""
    return {"Cookie": f"tasklings_session={session}"}


async def create_child(client, adm: dict, username: str, name: str) -> tuple[str, str]:
    """Create a child member, return (member_id, session_cookie)."""
    r = await client.post(
        "/api/v1/members",
        json={"username": username, "password": "kidpass1", "name": name, "role": "child"},
        headers=adm,
    )
    assert r.status_code == 201, f"create_child failed: {await r.get_data(as_text=True)}"
    member_id = (await r.get_json())["member"]["id"]
    session = await login(client, username, "kidpass1")
    assert session is not None
    return member_id, session


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run(db_path: str) -> int:
    cfg = Config(BCRYPT_ROUNDS=4, DATABASE_PATH=db_path, TESTING=True)
    app = create_app(cfg)
    async with app.test_app():
        pass

    client = app.test_client(use_cookies=False)
    assert client.cookie_jar is None

    # ── Auth ─────────────────────────────────────────────────────────────────
    admin_session = await login(client, *SEED_ADMIN)
    check("Admin login", admin_session is not None)
    adm = ah(admin_session)

    child1_id, c1_sess = await create_child(client, adm, "alice", "Alice")
    child2_id, c2_sess = await create_child(client, adm, "bob", "Bob")
    c1 = ah(c1_sess)
    c2 = ah(c2_sess)

    # ── Phase 5: give members some Lumins first ───────────────────────────────
    print("\n── Phase 5: Transaction API ────────────────────────────────────────")

    # Bonus adjustment
    r = await client.post(
        f"/api/v1/members/{child1_id}/lumins/adjust",
        json={"amount": 100, "reason": "bonus"},
        headers=adm,
    )
    check("POST adjust +100 bonus", r.status_code == 200)
    data = await r.get_json()
    check("New balance = 100", data["new_balance"] == 100)

    # Penalty
    r = await client.post(
        f"/api/v1/members/{child1_id}/lumins/adjust",
        json={"amount": -20, "reason": "penalty"},
        headers=adm,
    )
    check("POST adjust -20 penalty", r.status_code == 200)
    check("New balance = 80", (await r.get_json())["new_balance"] == 80)

    # Overdraft guard: try to penalise more than balance
    r = await client.post(
        f"/api/v1/members/{child1_id}/lumins/adjust",
        json={"amount": -999, "reason": "penalty"},
        headers=adm,
    )
    check("Overdraft penalty => 409", r.status_code == 409)

    # Invalid reason
    r = await client.post(
        f"/api/v1/members/{child1_id}/lumins/adjust",
        json={"amount": 10, "reason": "chore_completed"},
        headers=adm,
    )
    check("Invalid reason => 400", r.status_code == 400)

    # Zero amount
    r = await client.post(
        f"/api/v1/members/{child1_id}/lumins/adjust",
        json={"amount": 0, "reason": "bonus"},
        headers=adm,
    )
    check("Zero amount => 400", r.status_code == 400)

    # GET balance (admin)
    r = await client.get(f"/api/v1/members/{child1_id}/balance", headers=adm)
    check("GET /members/:id/balance (admin)", r.status_code == 200)
    check("Balance is 80", (await r.get_json())["balance"] == 80)

    # GET balance (self)
    r = await client.get(f"/api/v1/members/{child1_id}/balance", headers=c1)
    check("GET /members/:id/balance (self)", r.status_code == 200)

    # GET balance (other child) => 403
    r = await client.get(f"/api/v1/members/{child1_id}/balance", headers=c2)
    check("GET /members/:id/balance (other child) => 403", r.status_code == 403)

    # GET member transactions (self)
    r = await client.get(f"/api/v1/members/{child1_id}/transactions", headers=c1)
    check("GET /members/:id/transactions (self)", r.status_code == 200)
    txns = (await r.get_json())["transactions"]
    check("Two transactions recorded", len(txns) == 2)

    # GET member transactions (admin)
    r = await client.get(f"/api/v1/members/{child1_id}/transactions", headers=adm)
    check("GET /members/:id/transactions (admin)", r.status_code == 200)

    # GET member transactions (other child) => 403
    r = await client.get(f"/api/v1/members/{child1_id}/transactions", headers=c2)
    check("GET /members/:id/transactions (other child) => 403", r.status_code == 403)

    # Pagination params
    r = await client.get(
        f"/api/v1/members/{child1_id}/transactions?limit=1&offset=0",
        headers=adm,
    )
    check("Pagination limit=1 returns 1 row", len((await r.get_json())["transactions"]) == 1)

    # GET /api/v1/transactions (household-wide, admin)
    r = await client.get("/api/v1/transactions", headers=adm)
    check("GET /api/v1/transactions (admin)", r.status_code == 200)
    all_txns = (await r.get_json())["transactions"]
    check("Household ledger has >= 2 entries", len(all_txns) >= 2)

    # Non-admin cannot access household ledger
    r = await client.get("/api/v1/transactions", headers=c1)
    check("GET /api/v1/transactions (child) => 403", r.status_code == 403)

    # ── Phase 6: Store ────────────────────────────────────────────────────────
    print("\n── Phase 6: Store CRUD ─────────────────────────────────────────────")

    # Give child2 some Lumins too
    await client.post(
        f"/api/v1/members/{child2_id}/lumins/adjust",
        json={"amount": 50, "reason": "bonus"},
        headers=adm,
    )

    # Create a global item (no member_ids)
    r = await client.post(
        "/api/v1/store",
        json={"title": "Extra Screen Time", "description": "30 minutes", "price": 20, "stock": None},
        headers=adm,
    )
    check("POST /api/v1/store (global item)", r.status_code == 201)
    global_item = (await r.get_json())["item"]
    global_item_id = global_item["id"]
    check("Global item has no member_ids", global_item["member_ids"] == [])
    check("is_global = True", global_item["is_global"] is True)

    # Create a targeted item (only alice)
    r = await client.post(
        "/api/v1/store",
        json={
            "title": "Alice's Reward",
            "price": 50,
            "member_ids": [child1_id],
        },
        headers=adm,
    )
    check("POST /api/v1/store (targeted item)", r.status_code == 201)
    targeted_item = (await r.get_json())["item"]
    targeted_item_id = targeted_item["id"]
    check("Targeted item has alice in member_ids", child1_id in targeted_item["member_ids"])

    # Create a finite-stock item
    r = await client.post(
        "/api/v1/store",
        json={"title": "Limited Badge", "price": 10, "stock": 1},
        headers=adm,
    )
    check("POST /api/v1/store (finite stock)", r.status_code == 201)
    limited_item_id = (await r.get_json())["item"]["id"]

    # Create an unavailable item
    r = await client.post(
        "/api/v1/store",
        json={"title": "Coming Soon", "price": 5, "is_available": False},
        headers=adm,
    )
    check("POST /api/v1/store (unavailable)", r.status_code == 201)
    unavail_item_id = (await r.get_json())["item"]["id"]

    # ── Visibility filtering ──────────────────────────────────────────────────
    print("\n── Phase 6: Visibility filtering ───────────────────────────────────")

    # Alice (child1) should see: global_item, targeted_item, limited_item (not unavail)
    r = await client.get("/api/v1/store", headers=c1)
    check("GET /api/v1/store (alice)", r.status_code == 200)
    alice_items = {i["id"] for i in (await r.get_json())["items"]}
    check("Alice sees global item", global_item_id in alice_items)
    check("Alice sees targeted item", targeted_item_id in alice_items)
    check("Alice sees limited item", limited_item_id in alice_items)
    check("Alice does not see unavailable item", unavail_item_id not in alice_items)

    # Bob (child2) should see: global_item, limited_item (not targeted, not unavail)
    r = await client.get("/api/v1/store", headers=c2)
    check("GET /api/v1/store (bob)", r.status_code == 200)
    bob_items = {i["id"] for i in (await r.get_json())["items"]}
    check("Bob sees global item", global_item_id in bob_items)
    check("Bob does not see alice's targeted item", targeted_item_id not in bob_items)
    check("Bob does not see unavailable item", unavail_item_id not in bob_items)

    # Admin sees all items
    r = await client.get("/api/v1/store", headers=adm)
    check("GET /api/v1/store (admin sees all)", r.status_code == 200)
    admin_items = {i["id"] for i in (await r.get_json())["items"]}
    check("Admin sees unavailable item", unavail_item_id in admin_items)
    check("Admin sees targeted item", targeted_item_id in admin_items)

    # GET single item -- bob cannot see targeted item
    r = await client.get(f"/api/v1/store/{targeted_item_id}", headers=c2)
    check("GET /api/v1/store/:id (bob, alice's item) => 404", r.status_code == 404)

    # GET single item -- alice can
    r = await client.get(f"/api/v1/store/{targeted_item_id}", headers=c1)
    check("GET /api/v1/store/:id (alice, her item) => 200", r.status_code == 200)

    # ── Update and visibility replacement ────────────────────────────────────
    print("\n── Phase 6: Update / visibility replace ────────────────────────────")

    r = await client.put(
        f"/api/v1/store/{global_item_id}",
        json={"title": "Extra Screen Time (Updated)", "price": 25},
        headers=adm,
    )
    check("PUT /api/v1/store/:id", r.status_code == 200)
    check("Title updated", (await r.get_json())["item"]["title"] == "Extra Screen Time (Updated)")

    # Replace visibility: make targeted item global
    r = await client.put(
        f"/api/v1/store/{targeted_item_id}/visibility",
        json={"member_ids": []},
        headers=adm,
    )
    check("PUT /api/v1/store/:id/visibility (clear => global)", r.status_code == 200)
    check("is_global = True", (await r.get_json())["is_global"] is True)

    # Bob can now see it
    r = await client.get("/api/v1/store", headers=c2)
    bob_items_after = {i["id"] for i in (await r.get_json())["items"]}
    check("Bob sees newly-global item", targeted_item_id in bob_items_after)

    # ── Purchase flow ─────────────────────────────────────────────────────────
    print("\n── Phase 6: Purchase flow ──────────────────────────────────────────")

    # Alice buys the global item (price=25, alice has 80)
    r = await client.post(f"/api/v1/store/{global_item_id}/purchase", headers=c1)
    check("POST /api/v1/store/:id/purchase (success)", r.status_code == 201)
    purchase = (await r.get_json())["purchase"]
    purchase_id = purchase["id"]
    check("Purchase price_paid = 25", purchase["price_paid"] == 25)

    # Balance deducted
    r = await client.get(f"/api/v1/members/{child1_id}/balance", headers=c1)
    check("Balance deducted after purchase", (await r.get_json())["balance"] == 55)

    # Insufficient balance: alice tries to buy Alice's Reward (price=50, balance=55 now -- wait, targeted is now global at 50)
    # Bob has 50, tries limited badge (price 10) -- succeeds, depletes stock
    r = await client.post(f"/api/v1/store/{limited_item_id}/purchase", headers=c2)
    check("Bob buys last limited badge", r.status_code == 201)

    # Out of stock: alice tries same limited badge
    r = await client.post(f"/api/v1/store/{limited_item_id}/purchase", headers=c1)
    check("Out of stock => 409", r.status_code == 409)

    # Unavailable item
    r = await client.post(f"/api/v1/store/{unavail_item_id}/purchase", headers=c1)
    check("Unavailable item => 410", r.status_code == 410)

    # Insufficient balance: bob has 40 left, targeted item costs 50
    r = await client.post(f"/api/v1/store/{targeted_item_id}/purchase", headers=c2)
    check("Insufficient balance => 402", r.status_code == 402)

    # ── Purchases list / detail ───────────────────────────────────────────────
    print("\n── Phase 6: Purchases list / detail ────────────────────────────────")

    r = await client.get("/api/v1/purchases", headers=c1)
    check("GET /api/v1/purchases (alice)", r.status_code == 200)
    alice_purchases = (await r.get_json())["purchases"]
    check("Alice has 1 purchase", len(alice_purchases) == 1)
    check("item_title present", bool(alice_purchases[0].get("item_title")))

    r = await client.get(f"/api/v1/purchases/{purchase_id}", headers=c1)
    check("GET /api/v1/purchases/:id (owner)", r.status_code == 200)

    r = await client.get(f"/api/v1/purchases/{purchase_id}", headers=adm)
    check("GET /api/v1/purchases/:id (admin)", r.status_code == 200)

    r = await client.get(f"/api/v1/purchases/{purchase_id}", headers=c2)
    check("GET /api/v1/purchases/:id (other child) => 403", r.status_code == 403)

    # ── Redemption ────────────────────────────────────────────────────────────
    print("\n── Phase 6: Redemption ─────────────────────────────────────────────")

    r = await client.post(f"/api/v1/purchases/{purchase_id}/redeem", headers=adm)
    check("POST /api/v1/purchases/:id/redeem (admin)", r.status_code == 200)
    check("Status = redeemed", (await r.get_json())["purchase"]["status"] == "redeemed")

    # Double-redeem => 409
    r = await client.post(f"/api/v1/purchases/{purchase_id}/redeem", headers=adm)
    check("Double-redeem => 409", r.status_code == 409)

    # Non-admin cannot redeem
    r = await client.post(f"/api/v1/purchases/{purchase_id}/redeem", headers=c1)
    check("Redeem (child) => 403", r.status_code == 403)

    # ── Soft-delete ───────────────────────────────────────────────────────────
    print("\n── Phase 6: Soft delete ────────────────────────────────────────────")

    r = await client.delete(f"/api/v1/store/{global_item_id}", headers=adm)
    check("DELETE /api/v1/store/:id", r.status_code == 200)

    # No longer visible to children
    r = await client.get("/api/v1/store", headers=c1)
    alice_after = {i["id"] for i in (await r.get_json())["items"]}
    check("Deactivated item not visible to alice", global_item_id not in alice_after)

    # Admin still sees it (list_all includes unavailable)
    r = await client.get("/api/v1/store", headers=adm)
    admin_after = {i["id"] for i in (await r.get_json())["items"]}
    check("Deactivated item still in admin list", global_item_id in admin_after)

    # ── Store views (HTML) ────────────────────────────────────────────────────
    print("\n── Phase 6: Store views ────────────────────────────────────────────")

    r = await client.get("/store", headers=c1)
    check("GET /store (HTML)", r.status_code == 200)
    body = await r.get_data(as_text=True)
    check("Store page has store-grid", "store-grid" in body)
    check("Store page shows balance", "lumin-display" in body)

    # HTMX partial
    r = await client.get("/store", headers={**c1, "HX-Request": "true"})
    check("GET /store HTMX partial", r.status_code == 200)
    partial = await r.get_data(as_text=True)
    check("Partial has store-grid", "store-grid" in partial)
    check("Partial has no <html>", "<html" not in partial)

    # Purchases page
    r = await client.get("/purchases", headers=c1)
    check("GET /purchases (HTML)", r.status_code == 200)
    check("Purchases page rendered", "purchase" in (await r.get_data(as_text=True)).lower())

    # HTMX buy action (returns HTML partial, not JSON)
    # Use targeted_item_id (global now, price=50, alice has 55)
    r = await client.post(
        f"/store/{targeted_item_id}/buy",
        headers={**c1, "HX-Request": "true"},
    )
    check("HTMX buy action returns 200", r.status_code == 200)
    htmx_body = await r.get_data(as_text=True)
    check("HTMX buy response has store-card", "store-card" in htmx_body)

    # ── Role enforcement ──────────────────────────────────────────────────────
    print("\n── Role enforcement ────────────────────────────────────────────────")

    r = await client.post("/api/v1/store", json={"title": "Nope", "price": 1}, headers=c1)
    check("POST /api/v1/store (child) => 403", r.status_code == 403)

    r = await client.put(f"/api/v1/store/{targeted_item_id}", json={"price": 1}, headers=c1)
    check("PUT /api/v1/store/:id (child) => 403", r.status_code == 403)

    r = await client.delete(f"/api/v1/store/{targeted_item_id}", headers=c1)
    check("DELETE /api/v1/store/:id (child) => 403", r.status_code == 403)

    r = await client.post(
        f"/api/v1/members/{child2_id}/lumins/adjust",
        json={"amount": 10, "reason": "bonus"},
        headers=c1,
    )
    check("POST adjust (child) => 403", r.status_code == 403)

    return _CHECKS


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", prefix="tasklings_smoke56_", delete=False)
    tmp.close()
    db_path = tmp.name
    try:
        ok = asyncio.run(run(db_path))
        print(f"\n{'─' * 60}")
        print(f"  {ok} checks passed.  Phase 5+6 smoke test PASSED.")
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
