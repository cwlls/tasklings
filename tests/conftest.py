"""
pytest fixtures for Tasklings test suite.

Each test gets an isolated SQLite database (temp file, deleted after test).
The app is spun up via `async with app.test_app()` which fires before_serving
(runs migrations, seeds the household).
"""
from __future__ import annotations

import os
import tempfile

import pytest
import pytest_asyncio

from app import create_app
from app.config import Config


# ---------------------------------------------------------------------------
# App / DB fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def app():
    """Fresh Quart app with an isolated temp-file SQLite DB."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", prefix="tasklings_test_", delete=False)
    tmp.close()
    db_path = tmp.name
    cfg = Config(BCRYPT_ROUNDS=4, DATABASE_PATH=db_path, TESTING=True)
    application = create_app(cfg)
    async with application.test_app():
        pass
    yield application
    # Cleanup DB files.
    for suffix in ("", "-wal", "-shm"):
        p = db_path + suffix
        if os.path.exists(p):
            os.unlink(p)


@pytest_asyncio.fixture
async def client(app):
    """Test client with cookies disabled (we carry cookies manually)."""
    return app.test_client(use_cookies=False)


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

async def _login(client, username: str, password: str) -> str | None:
    """Login and return the raw session cookie value, or None on failure."""
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


def _auth(session: str) -> dict:
    return {"Cookie": f"tasklings_session={session}"}


# ---------------------------------------------------------------------------
# Seed fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def admin_session(client):
    """Return (admin_id, auth_headers) for the seeded admin account."""
    sess = await _login(client, "admin", "changeme")
    assert sess, "Admin login failed"
    headers = _auth(sess)
    r = await client.get("/api/v1/auth/me", headers=headers)
    data = await r.get_json()
    return data["member"]["id"], headers


@pytest_asyncio.fixture
async def household_id(client, admin_session):
    """Return the household id."""
    _, adm = admin_session
    r = await client.get("/api/v1/household", headers=adm)
    data = await r.get_json()
    return data["household"]["id"]


async def _create_child(client, adm_headers: dict, username: str, name: str) -> tuple[str, dict]:
    """Create a child member and return (member_id, auth_headers)."""
    r = await client.post(
        "/api/v1/members",
        json={"username": username, "password": "kid1234", "name": name, "role": "child"},
        headers=adm_headers,
    )
    assert r.status_code == 201, await r.get_data(as_text=True)
    mid = (await r.get_json())["member"]["id"]
    sess = await _login(client, username, "kid1234")
    assert sess
    return mid, _auth(sess)


@pytest_asyncio.fixture
async def alice(client, admin_session):
    _, adm = admin_session
    return await _create_child(client, adm, "alice", "Alice")


@pytest_asyncio.fixture
async def bob(client, admin_session):
    _, adm = admin_session
    return await _create_child(client, adm, "bob", "Bob")
