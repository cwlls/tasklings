"""
Assignment engine -- lazy daily generation of chore assignments.

Calling `ensure_assignments_for_today(household_id)` is idempotent: if
assignments already exist for the household's local "today", the call is a
no-op and returns immediately.

Rotation boundary logic:
  - daily   : advance every calendar day (always advance)
  - weekly  : advance when the date is a Monday (weekday == 0)
  - monthly : advance when the date is the 1st of the month

For constant chores the assignees come from the `chore_assignee` join table.
For rotating chores the current member is read from `rotation_schedule`.
"""
from __future__ import annotations

from datetime import date as Date, datetime, timezone
from zoneinfo import ZoneInfo

from app.models import chores as chores_model
from app.models import rotation as rotation_model
from app.models.household import get_household


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _today_for_timezone(tz_name: str) -> Date:
    """Return today's date in the given IANA timezone."""
    return datetime.now(ZoneInfo(tz_name)).date()


def _should_advance_rotation(frequency: str, target_date: Date) -> bool:
    """
    Return True if the rotation pointer should be advanced on *target_date*.

    We advance once at the start of each rotation period:
      - daily   : every day
      - weekly  : on Monday
      - monthly : on the 1st
    """
    if frequency == "daily":
        return True
    if frequency == "weekly":
        return target_date.weekday() == 0  # Monday
    if frequency == "monthly":
        return target_date.day == 1
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def generate_assignments_for_date(
    household_id: str, target_date: Date
) -> None:
    """
    Idempotently generate chore assignments for *target_date*.

    If any assignments already exist for this household on this date the
    function returns without creating duplicates.
    """
    date_str = target_date.isoformat()

    # Guard: already generated for this date.
    if await chores_model.assignments_exist_for_date(household_id, date_str):
        return

    chore_defs = await chores_model.list_chore_definitions(
        household_id, active_only=True
    )

    for chore in chore_defs:
        chore_id = chore["id"]
        chore_type = chore["chore_type"]

        if chore_type == "constant":
            member_ids = await chores_model.get_assignees_for_chore(chore_id)
            for member_id in member_ids:
                await chores_model.create_assignment(chore_id, member_id, date_str)

        elif chore_type == "rotating":
            frequency = chore["rotation_frequency"] or "daily"

            # Advance the rotation pointer when we cross a boundary.
            if _should_advance_rotation(frequency, target_date):
                member_id = await rotation_model.advance_rotation(chore_id)
            else:
                member_id = await rotation_model.get_current_rotation_member(chore_id)

            if member_id is not None:
                await chores_model.create_assignment(chore_id, member_id, date_str)


async def ensure_assignments_for_today(household_id: str) -> Date:
    """
    Lazy wrapper: look up the household timezone, compute today's local date,
    then generate assignments if they have not been generated yet.

    Returns today's date (in the household's timezone) so callers can use it
    without recomputing.
    """
    household = await get_household()
    tz_name = (household["timezone"] if household else None) or "America/Chicago"
    today = _today_for_timezone(tz_name)
    await generate_assignments_for_date(household_id, today)
    return today
