"""
Solo Quest service.

Quest completion is chore-driven: when a member completes a chore assignment,
the caller should invoke `check_quest_completion` so we can detect if any quest
bonus has become earnable.

The bonus award is intentionally kept separate from the chore-level Lumin
credit so that each LuminTransaction has a distinct, auditable reason.
"""
from __future__ import annotations

from app.models import quests as quests_model
from app.models.db import fetch_one
from app.services.currency import credit_lumins


async def check_quest_completion(member_id: str, date: str) -> list[str]:
    """
    After a chore is completed, inspect every active quest assigned to this
    member. For each quest whose chores are ALL completed (status in
    'completed' or 'verified') on *date*, award the bonus_lumins if the bonus
    has not already been awarded.

    Returns a list of quest names for which a bonus was newly awarded this
    call (may be empty).

    The bonus award is atomic with the completion check: we re-read the quest
    inside the same request-scoped DB connection (WAL mode) so the check and
    credit are consistent.
    """
    quests = await quests_model.list_quests_for_member(member_id)
    newly_completed: list[str] = []

    for quest in quests:
        quest_id = quest["id"]
        bonus_lumins = quest["bonus_lumins"]

        if bonus_lumins <= 0:
            continue

        # Check whether the bonus has already been awarded for this quest.
        already = await fetch_one(
            """
            SELECT id FROM lumin_transaction
            WHERE member_id = ? AND reason = 'quest_bonus' AND reference_id = ?
            LIMIT 1
            """,
            (member_id, quest_id),
        )
        if already:
            continue

        # Load progress for today.
        progress = await quests_model.get_quest_progress(quest_id, member_id, date)
        if not progress:
            continue

        all_done = all(item["completed"] for item in progress)
        if all_done:
            await credit_lumins(
                member_id,
                bonus_lumins,
                reason="quest_bonus",
                reference_id=quest_id,
            )
            newly_completed.append(quest["name"])

    return newly_completed


async def complete_quest_chore(
    member_id: str,
    quest_id: str,
    chore_id: str,
    date: str,
) -> dict:
    """
    Complete a single chore within a solo quest context.

    1. Locate (or verify existence of) the pending chore_assignment for this
       member / chore / date.
    2. Mark it completed and credit its lumin_value.
    3. Check whether the quest is now fully complete and award the bonus.

    Returns::

        {
            "chore_completed": bool,
            "quest_completed": bool,
            "bonus_awarded": int,          # 0 if quest not newly completed
            "newly_completed_quests": list[str],
        }
    """
    from app.models import chores as chores_model
    from app.services.currency import credit_lumins as _credit

    # Find the assignment.
    assignment = await fetch_one(
        """
        SELECT ca.*, cd.lumin_value
        FROM chore_assignment ca
        JOIN chore_definition cd ON cd.id = ca.chore_id
        WHERE ca.member_id = ? AND ca.chore_id = ? AND ca.assigned_date = ?
        LIMIT 1
        """,
        (member_id, chore_id, date),
    )

    chore_completed = False
    if assignment and assignment["status"] == "pending":
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        await chores_model.update_assignment_status(
            assignment["id"],
            status="completed",
            completed_at=now,
            lumins_awarded=assignment["lumin_value"],
        )
        if assignment["lumin_value"] > 0:
            await _credit(
                member_id,
                assignment["lumin_value"],
                reason="chore_completed",
                reference_id=assignment["id"],
            )
        chore_completed = True

    newly_completed = await check_quest_completion(member_id, date)
    quest_name = None
    bonus = 0

    if newly_completed:
        quest = await quests_model.get_quest(quest_id)
        if quest and quest["name"] in newly_completed:
            quest_name = quest["name"]
            bonus = quest["bonus_lumins"]

    return {
        "chore_completed": chore_completed,
        "quest_completed": bool(quest_name),
        "bonus_awarded": bonus,
        "newly_completed_quests": newly_completed,
    }
