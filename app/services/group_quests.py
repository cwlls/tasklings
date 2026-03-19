"""
Group Quest service.

Wraps the group_quests model with higher-level logic: membership validation,
claim mechanics, completion checking, and bonus distribution.
"""
from __future__ import annotations

from app.models import group_quests as gq_model
from app.models.db import fetch_one
from app.services.currency import credit_lumins


class AlreadyMemberError(Exception):
    """Member is already enrolled in the group quest."""


class NotMemberError(Exception):
    """Member is not enrolled in the group quest."""


class QuestAlreadyCompleteError(Exception):
    """Cannot leave a quest that has already been completed."""


class ChoreAlreadyCompleteError(Exception):
    """The chore has already been completed by another member."""


async def _is_member(group_quest_id: str, member_id: str) -> bool:
    row = await fetch_one(
        "SELECT 1 FROM group_quest_member WHERE group_quest_id = ? AND member_id = ?",
        (group_quest_id, member_id),
    )
    return row is not None


async def join_group_quest(member_id: str, group_quest_id: str) -> None:
    """
    Self-enroll *member_id* in *group_quest_id*.
    Raises AlreadyMemberError if already enrolled.
    """
    if await _is_member(group_quest_id, member_id):
        raise AlreadyMemberError("Already enrolled in this group quest")
    await gq_model.add_member(group_quest_id, member_id, joined_by="self")


async def leave_group_quest(member_id: str, group_quest_id: str) -> None:
    """
    Remove *member_id* from *group_quest_id*.
    Raises NotMemberError if not enrolled.
    Raises QuestAlreadyCompleteError if the quest is fully done (no leaving).
    """
    if not await _is_member(group_quest_id, member_id):
        raise NotMemberError("Not enrolled in this group quest")
    if await gq_model.is_complete(group_quest_id):
        raise QuestAlreadyCompleteError("Cannot leave a completed group quest")
    await gq_model.remove_member(group_quest_id, member_id)


async def claim_chore(
    member_id: str, group_quest_id: str, chore_id: str
) -> dict:
    """
    Claim a chore as a soft social signal.  Non-blocking: if someone else
    already has a claim, this overwrites it (the spec says non-blocking).
    Returns the current claim state after the operation.
    """
    await gq_model.claim_chore(group_quest_id, chore_id, member_id)
    row = await fetch_one(
        """
        SELECT gqc.claimed_by, fm.name AS claimed_by_name
        FROM group_quest_chore gqc
        LEFT JOIN family_member fm ON fm.id = gqc.claimed_by
        WHERE gqc.group_quest_id = ? AND gqc.chore_id = ?
        """,
        (group_quest_id, chore_id),
    )
    return dict(row) if row else {}


async def release_claim(
    member_id: str, group_quest_id: str, chore_id: str
) -> None:
    """Release a claim only if it belongs to *member_id*. Silent no-op otherwise."""
    await gq_model.release_claim(group_quest_id, chore_id, member_id)


async def complete_chore(
    member_id: str, group_quest_id: str, chore_id: str
) -> dict:
    """
    Complete a chore from the shared pool.

    Steps:
      1. Verify member is enrolled.
      2. Insert completion row (returns False if already done).
      3. Award the chore's lumin_value to the completing member.
      4. Check if the quest is now fully complete.
      5. If complete, award bonus_lumins to ALL enrolled members.

    Returns::

        {
            "completed": bool,
            "quest_complete": bool,
            "bonus_awarded": int,       # per-member bonus (0 if not complete)
            "reward_description": str | None,
        }
    """
    if not await _is_member(group_quest_id, member_id):
        raise NotMemberError("Not enrolled in this group quest")

    # Get the chore's lumin_value for awarding.
    chore_row = await fetch_one(
        """
        SELECT cd.lumin_value, cd.id
        FROM group_quest_chore gqc
        JOIN chore_definition cd ON cd.id = gqc.chore_id
        WHERE gqc.group_quest_id = ? AND gqc.chore_id = ?
        """,
        (group_quest_id, chore_id),
    )

    success = await gq_model.complete_chore(group_quest_id, chore_id, member_id)
    if not success:
        raise ChoreAlreadyCompleteError("This chore has already been completed")

    # Award the chore-level Lumins to the completing member.
    lumin_value = chore_row["lumin_value"] if chore_row else 0
    if lumin_value > 0:
        await credit_lumins(
            member_id,
            lumin_value,
            reason="chore_completed",
            reference_id=chore_id,
        )

    quest_complete = await gq_model.is_complete(group_quest_id)
    bonus_awarded = 0
    reward_description = None

    if quest_complete:
        quest = await gq_model.get_group_quest(group_quest_id)
        bonus_lumins = quest["bonus_lumins"] if quest else 0
        reward_description = quest["reward_description"] if quest else None

        if bonus_lumins > 0:
            # Award bonus to every enrolled member.
            from app.models.db import fetch_all
            enrolled = await fetch_all(
                "SELECT member_id FROM group_quest_member WHERE group_quest_id = ?",
                (group_quest_id,),
            )
            for row in enrolled:
                await credit_lumins(
                    row["member_id"],
                    bonus_lumins,
                    reason="group_quest_bonus",
                    reference_id=group_quest_id,
                )
            bonus_awarded = bonus_lumins

    return {
        "completed": True,
        "quest_complete": quest_complete,
        "bonus_awarded": bonus_awarded,
        "reward_description": reward_description,
    }
