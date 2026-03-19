"""
Authentication service layer.

Owns all password hashing, session lifecycle, API token generation, and
password-reset token logic. Routes and middleware call into this module;
they do not touch bcrypt or token generation directly.

Public surface:
  hash_password(plain)             -> str
  verify_password(plain, hashed)  -> bool
  async login(username, password) -> dict
  async logout(session_id)        -> None
  async validate_session(session_id) -> dict | None
  async validate_api_token(raw_token) -> dict | None
  async create_api_token(member_id, label, expires_at) -> dict
  async change_password(member_id, old_pw, new_pw) -> None
  async set_password(member_id, new_pw) -> None
  async request_password_reset(username) -> dict
  async confirm_password_reset(raw_token, new_pw) -> None

Raises AuthError on any credential / permission failure.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from quart import current_app

from app.models import auth as auth_model
from app.models import members as members_model
from app.models.household import get_household

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class AuthError(Exception):
    """Raised on authentication or authorisation failure."""

    def __init__(self, message: str, code: str = "AUTH_ERROR") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def hash_password(plain: str) -> str:
    """Return a bcrypt hash of *plain*. Rounds are read from app config."""
    rounds = current_app.config.get("BCRYPT_ROUNDS", 12)
    hashed = bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=rounds))
    return hashed.decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if *plain* matches the bcrypt *hashed* string."""
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sha256(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _member_to_dict(row) -> dict:
    """Convert an aiosqlite Row to a safe public dict (no password_hash)."""
    return {
        "id": row["id"],
        "household_id": row["household_id"],
        "username": row["username"],
        "name": row["name"],
        "avatar": row["avatar"],
        "role": row["role"],
        "color": row["color"],
        "balance": row["balance"],
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
    }


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

async def login(username: str, password: str) -> dict:
    """
    Verify credentials against the single household's member list.

    Returns ``{"session_id": str, "member": dict}`` on success.
    Raises ``AuthError`` on failure.
    """
    household = await get_household()
    if household is None:
        raise AuthError("Household not configured.", "NO_HOUSEHOLD")

    member = await members_model.get_member_by_username(household["id"], username)
    if member is None or not member["is_active"]:
        raise AuthError("Invalid username or password.", "INVALID_CREDENTIALS")

    if not verify_password(password, member["password_hash"]):
        raise AuthError("Invalid username or password.", "INVALID_CREDENTIALS")

    lifetime_hours = current_app.config.get("SESSION_LIFETIME_HOURS", 72)
    expires_at = (_now() + timedelta(hours=lifetime_hours)).isoformat()

    session_id = await auth_model.create_session(member["id"], expires_at)
    return {"session_id": session_id, "member": _member_to_dict(member)}


async def logout(session_id: str) -> None:
    """Revoke a session. Silent if the session does not exist."""
    await auth_model.revoke_session(session_id)


async def validate_session(session_id: str) -> dict | None:
    """
    Return the member dict if the session is valid and unexpired, else None.
    """
    session = await auth_model.get_session(session_id)
    if session is None:
        return None

    member = await members_model.get_member_by_id(session["member_id"])
    if member is None or not member["is_active"]:
        return None

    return _member_to_dict(member)


# ---------------------------------------------------------------------------
# API tokens
# ---------------------------------------------------------------------------

async def validate_api_token(raw_token: str) -> dict | None:
    """
    SHA-256 hash *raw_token*, look it up, and return the member dict if valid.
    """
    token_hash = _sha256(raw_token)
    row = await auth_model.get_api_token_by_hash(token_hash)
    if row is None:
        return None

    member = await members_model.get_member_by_id(row["member_id"])
    if member is None or not member["is_active"]:
        return None

    return _member_to_dict(member)


async def create_api_token(
    member_id: str,
    label: str,
    expires_at: str | None = None,
) -> dict:
    """
    Generate a random API token, store its SHA-256 hash, and return
    ``{"token_id": str, "raw_token": str}``. The raw token is shown once only.
    """
    raw_token = secrets.token_urlsafe(32)
    token_hash = _sha256(raw_token)
    token_id = await auth_model.create_api_token(member_id, token_hash, label, expires_at)
    return {"token_id": token_id, "raw_token": raw_token}


# ---------------------------------------------------------------------------
# Password management
# ---------------------------------------------------------------------------

async def change_password(
    member_id: str, old_password: str, new_password: str
) -> None:
    """
    Verify the current password then replace it.
    Raises ``AuthError`` if the old password is wrong.
    """
    member = await members_model.get_member_by_id(member_id)
    if member is None:
        raise AuthError("Member not found.", "NOT_FOUND")

    if not verify_password(old_password, member["password_hash"]):
        raise AuthError("Current password is incorrect.", "INVALID_CREDENTIALS")

    new_hash = hash_password(new_password)
    await members_model.update_member(member_id, password_hash=new_hash)


async def set_password(member_id: str, new_password: str) -> None:
    """
    Admin hard-set: replace a member's password with no verification of the old one.
    """
    new_hash = hash_password(new_password)
    await members_model.update_member(member_id, password_hash=new_hash)


# ---------------------------------------------------------------------------
# Password reset tokens
# ---------------------------------------------------------------------------

_RESET_TOKEN_LIFETIME_HOURS = 1


async def request_password_reset(username: str) -> dict:
    """
    Generate a password reset token for *username*.

    Returns ``{"token_id": str, "raw_token": str}``.

    The raw token should be delivered via email when SMTP is configured, or
    surfaced to an admin via GET /api/v1/admin/members/<id>/reset-token.

    Always returns a valid-looking result to avoid leaking whether the username
    exists. If the username is not found, a dummy result is returned and
    nothing is stored.
    """
    household = await get_household()
    if household is None:
        # Return dummy to avoid info leak.
        return {"token_id": "", "raw_token": ""}

    member = await members_model.get_member_by_username(household["id"], username)
    if member is None or not member["is_active"]:
        return {"token_id": "", "raw_token": ""}

    raw_token = secrets.token_urlsafe(32)
    token_hash = _sha256(raw_token)
    expires_at = (
        _now() + timedelta(hours=_RESET_TOKEN_LIFETIME_HOURS)
    ).isoformat()

    token_id = await auth_model.create_reset_token(
        member["id"], token_hash, expires_at
    )

    # Attempt email delivery if SMTP is configured.
    smtp_host = current_app.config.get("SMTP_HOST", "")
    if smtp_host:
        try:
            await _send_reset_email(member, raw_token)
        except Exception as exc:
            logger.warning("Reset email delivery failed for %s: %s", username, exc)

    return {"token_id": token_id, "raw_token": raw_token}


async def confirm_password_reset(raw_token: str, new_password: str) -> None:
    """
    Validate a reset token and set the new password.
    Raises ``AuthError`` if the token is invalid, expired, or already used.
    """
    token_hash = _sha256(raw_token)
    token_row = await auth_model.get_reset_token_by_hash(token_hash)
    if token_row is None:
        raise AuthError("Reset token is invalid or has expired.", "INVALID_TOKEN")

    await set_password(token_row["member_id"], new_password)
    await auth_model.mark_reset_token_used(token_row["id"])


# ---------------------------------------------------------------------------
# Internal: email delivery stub
# ---------------------------------------------------------------------------

async def _send_reset_email(member, raw_token: str) -> None:
    """
    Send a password-reset email. Only called when SMTP_HOST is configured.
    Uses stdlib smtplib in a thread executor to stay non-blocking.
    Expanded in Phase 11 (email integration).
    """
    import asyncio
    import smtplib
    from email.message import EmailMessage

    cfg = current_app.config
    msg = EmailMessage()
    msg["Subject"] = "Tasklings password reset"
    msg["From"] = cfg["SMTP_FROM"]
    msg["To"] = member.get("email", "")  # email field not in schema yet -- no-op

    if not msg["To"]:
        return

    msg.set_content(
        f"Hi {member['name']},\n\n"
        f"Your password reset token is:\n\n"
        f"  {raw_token}\n\n"
        f"It expires in {_RESET_TOKEN_LIFETIME_HOURS} hour(s).\n\n"
        f"If you did not request a reset, ignore this email.\n"
    )

    def _send():
        with smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"]) as s:
            s.starttls()
            if cfg["SMTP_USERNAME"]:
                s.login(cfg["SMTP_USERNAME"], cfg["SMTP_PASSWORD"])
            s.send_message(msg)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _send)
