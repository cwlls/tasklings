"""
Currency service -- Lumin balance management.

All mutations go through here to ensure the ledger (lumin_transaction) and
the denormalized balance cache (family_member.balance) stay in sync within
a single DB transaction.
"""
from __future__ import annotations

from app.models import members as members_model
from app.models import transactions as tx_model


class InsufficientBalanceError(Exception):
    """Raised when a debit would push the balance below zero."""


async def credit_lumins(
    member_id: str,
    amount: int,
    reason: str,
    reference_id: str | None = None,
) -> int:
    """
    Add *amount* Lumins to a member's balance and append a ledger entry.

    `amount` must be positive.
    Returns the new balance.
    """
    if amount <= 0:
        raise ValueError(f"credit_lumins requires a positive amount, got {amount}")

    await tx_model.create_transaction(member_id, amount, reason, reference_id)
    new_balance = await members_model.update_balance(member_id, amount)
    return new_balance


async def debit_lumins(
    member_id: str,
    amount: int,
    reason: str,
    reference_id: str | None = None,
) -> int:
    """
    Subtract *amount* Lumins from a member's balance and append a ledger entry.

    `amount` must be positive (it is negated internally).
    Raises InsufficientBalanceError if the resulting balance would go below 0.
    Returns the new balance.
    """
    if amount <= 0:
        raise ValueError(f"debit_lumins requires a positive amount, got {amount}")

    try:
        new_balance = await members_model.update_balance(member_id, -amount)
    except ValueError as exc:
        raise InsufficientBalanceError(str(exc)) from exc

    await tx_model.create_transaction(member_id, -amount, reason, reference_id)
    return new_balance


async def adjust_lumins(
    member_id: str,
    amount: int,
    reason: str,
    reference_id: str | None = None,
) -> int:
    """
    Admin adjustment -- amount may be positive or negative.
    Raises InsufficientBalanceError if a negative adjustment would go below zero.
    Returns the new balance.
    """
    if amount == 0:
        row = await members_model.get_member_by_id(member_id)
        if row is None:
            raise ValueError(f"Member {member_id!r} not found")
        return row["balance"]

    if amount > 0:
        return await credit_lumins(member_id, amount, reason, reference_id)
    else:
        return await debit_lumins(member_id, -amount, reason, reference_id)


async def get_balance(member_id: str) -> int:
    """Return the current Lumin balance for a member."""
    row = await members_model.get_member_by_id(member_id)
    if row is None:
        raise ValueError(f"Member {member_id!r} not found")
    return row["balance"]
