"""
Authentication tests: login, logout, me, token auth, role enforcement.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Login / logout
# ---------------------------------------------------------------------------

async def test_login_success(client):
    r = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "changeme"},
    )
    assert r.status_code == 200
    data = await r.get_json()
    assert data["member"]["username"] == "admin"
    assert "password_hash" not in data["member"]
    # Session cookie set.
    cookies = [h for h in r.headers.getlist("Set-Cookie") if "tasklings_session=" in h]
    assert cookies


async def test_login_wrong_password(client):
    r = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "wrong"},
    )
    assert r.status_code == 401


async def test_login_unknown_user(client):
    r = await client.post(
        "/api/v1/auth/login",
        json={"username": "nobody", "password": "x"},
    )
    assert r.status_code == 401


async def test_me_unauthenticated(client):
    r = await client.get("/api/v1/auth/me")
    assert r.status_code == 401


async def test_me_authenticated(client, admin_session):
    _, adm = admin_session
    r = await client.get("/api/v1/auth/me", headers=adm)
    assert r.status_code == 200
    data = await r.get_json()
    assert data["member"]["role"] == "parent"
    assert "password_hash" not in data["member"]


async def test_logout(client, admin_session):
    _, adm = admin_session
    r = await client.post("/api/v1/auth/logout", headers=adm)
    assert r.status_code == 200
    # After logout the session cookie is cleared.
    # me should now return 401 with the same cookie value.
    r2 = await client.get("/api/v1/auth/me", headers=adm)
    assert r2.status_code == 401


# ---------------------------------------------------------------------------
# Role enforcement
# ---------------------------------------------------------------------------

async def test_child_cannot_create_member(client, alice):
    _, a_hdrs = alice
    r = await client.post(
        "/api/v1/members",
        json={"username": "hacker", "password": "abcdef", "name": "Hacker", "role": "child"},
        headers=a_hdrs,
    )
    assert r.status_code == 403


async def test_child_cannot_access_transactions_admin(client, alice):
    _, a_hdrs = alice
    r = await client.get("/api/v1/transactions", headers=a_hdrs)
    assert r.status_code == 403


async def test_admin_can_set_password(client, admin_session, alice):
    admin_id, adm = admin_session
    alice_id, _ = alice
    r = await client.post(
        f"/api/v1/admin/members/{alice_id}/set-password",
        json={"new_password": "newpass123"},
        headers=adm,
    )
    assert r.status_code == 200
    # Can now log in with new password.
    from tests.conftest import _login
    sess = await _login(client, "alice", "newpass123")
    assert sess is not None


# ---------------------------------------------------------------------------
# API token auth
# ---------------------------------------------------------------------------

async def test_api_token_create_and_use(client, admin_session):
    _, adm = admin_session
    # Create token.
    r = await client.post(
        "/api/v1/tokens",
        json={"label": "test-token"},
        headers=adm,
    )
    assert r.status_code == 201
    data = await r.get_json()
    raw = data["token"]
    assert raw

    # Use token to authenticate.
    r2 = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert r2.status_code == 200

    # Revoke token.
    token_id = data["token_id"]
    r3 = await client.delete(f"/api/v1/tokens/{token_id}", headers=adm)
    assert r3.status_code == 200

    # Token no longer works.
    r4 = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert r4.status_code == 401


# ---------------------------------------------------------------------------
# Password hash never leaks
# ---------------------------------------------------------------------------

async def test_password_hash_not_in_member_list(client, admin_session):
    _, adm = admin_session
    r = await client.get("/api/v1/members", headers=adm)
    assert r.status_code == 200
    members = (await r.get_json())["members"]
    for m in members:
        assert "password_hash" not in m


async def test_password_hash_not_in_get_member(client, admin_session, alice):
    admin_id, adm = admin_session
    alice_id, _ = alice
    r = await client.get(f"/api/v1/members/{alice_id}", headers=adm)
    assert r.status_code == 200
    assert "password_hash" not in (await r.get_json())["member"]


# ---------------------------------------------------------------------------
# UUID path parameter validation
# ---------------------------------------------------------------------------

async def test_malformed_uuid_member_returns_404(client, admin_session):
    _, adm = admin_session
    r = await client.get("/api/v1/members/not-a-uuid", headers=adm)
    assert r.status_code == 404


async def test_malformed_uuid_chore_returns_404(client, admin_session):
    _, adm = admin_session
    r = await client.get("/api/v1/chores/totally-bogus", headers=adm)
    assert r.status_code == 404


async def test_malformed_uuid_store_item_returns_404(client, admin_session):
    _, adm = admin_session
    r = await client.get("/api/v1/store/not-a-valid-uuid", headers=adm)
    assert r.status_code == 404
