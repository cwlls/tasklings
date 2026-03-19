"""
Auth data-access layer: sessions, API tokens, password reset tokens.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import aiosqlite

from app.models.db import fetch_one, fetch_all, execute


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Auth Sessions
# ---------------------------------------------------------------------------

async def create_session(member_id: str, expires_at: str) -> str:
    """Create a new auth session. Returns the session id (stored in cookie)."""
    session_id = str(uuid.uuid4())
    now = _now_iso()
    await execute(
        """
        INSERT INTO auth_session (id, member_id, created_at, expires_at, is_revoked)
        VALUES (?, ?, ?, ?, 0)
        """,
        (session_id, member_id, now, expires_at),
    )
    return session_id


async def get_session(session_id: str) -> aiosqlite.Row | None:
    """
    Return the session row if it exists, has not expired, and has not been revoked.
    Returns None otherwise.
    """
    now = _now_iso()
    return await fetch_one(
        """
        SELECT * FROM auth_session
        WHERE id = ?
          AND is_revoked = 0
          AND (expires_at IS NULL OR expires_at > ?)
        """,
        (session_id, now),
    )


async def revoke_session(session_id: str) -> None:
    """Revoke a session (explicit logout)."""
    await execute(
        "UPDATE auth_session SET is_revoked = 1 WHERE id = ?",
        (session_id,),
    )


# ---------------------------------------------------------------------------
# API Tokens
# ---------------------------------------------------------------------------

async def create_api_token(
    member_id: str,
    token_hash: str,
    label: str,
    expires_at: str | None = None,
) -> str:
    """Insert a new API token row. Returns the token id."""
    token_id = str(uuid.uuid4())
    now = _now_iso()
    await execute(
        """
        INSERT INTO api_token (id, member_id, token_hash, label, created_at, expires_at, is_revoked)
        VALUES (?, ?, ?, ?, ?, ?, 0)
        """,
        (token_id, member_id, token_hash, label, now, expires_at),
    )
    return token_id


async def get_api_token_by_hash(token_hash: str) -> aiosqlite.Row | None:
    """Return the token row if valid (not expired, not revoked)."""
    now = _now_iso()
    return await fetch_one(
        """
        SELECT * FROM api_token
        WHERE token_hash = ?
          AND is_revoked = 0
          AND (expires_at IS NULL OR expires_at > ?)
        """,
        (token_hash, now),
    )


async def list_api_tokens(household_id: str) -> list[aiosqlite.Row]:
    """Return all API tokens for members belonging to the given household."""
    return await fetch_all(
        """
        SELECT t.*
        FROM api_token t
        JOIN family_member m ON m.id = t.member_id
        WHERE m.household_id = ?
        ORDER BY t.created_at DESC
        """,
        (household_id,),
    )


async def revoke_api_token(token_id: str) -> None:
    """Revoke an API token by id."""
    await execute(
        "UPDATE api_token SET is_revoked = 1 WHERE id = ?",
        (token_id,),
    )


# ---------------------------------------------------------------------------
# Password Reset Tokens
# ---------------------------------------------------------------------------

async def create_reset_token(
    member_id: str, token_hash: str, expires_at: str
) -> str:
    """Insert a password reset token. Returns the token id."""
    token_id = str(uuid.uuid4())
    now = _now_iso()
    await execute(
        """
        INSERT INTO password_reset_token (id, member_id, token_hash, expires_at, used_at, created_at)
        VALUES (?, ?, ?, ?, NULL, ?)
        """,
        (token_id, member_id, token_hash, expires_at, now),
    )
    return token_id


async def get_reset_token_by_hash(token_hash: str) -> aiosqlite.Row | None:
    """Return the reset token row if unexpired and unused."""
    now = _now_iso()
    return await fetch_one(
        """
        SELECT * FROM password_reset_token
        WHERE token_hash = ?
          AND used_at IS NULL
          AND expires_at > ?
        """,
        (token_hash, now),
    )


async def get_active_reset_token_for_member(member_id: str) -> aiosqlite.Row | None:
    """Return the most recent active (unexpired, unused) reset token for a member."""
    now = _now_iso()
    return await fetch_one(
        """
        SELECT * FROM password_reset_token
        WHERE member_id = ?
          AND used_at IS NULL
          AND expires_at > ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (member_id, now),
    )


async def mark_reset_token_used(token_id: str) -> None:
    """Mark a reset token as consumed."""
    await execute(
        "UPDATE password_reset_token SET used_at = ? WHERE id = ?",
        (_now_iso(), token_id),
    )
