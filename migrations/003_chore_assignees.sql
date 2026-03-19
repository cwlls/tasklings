-- Migration 003: Chore assignee join table
-- Defines which members receive each constant chore on daily generation.
-- Rotating chores use rotation_schedule instead.

CREATE TABLE IF NOT EXISTS chore_assignee (
    chore_id  TEXT NOT NULL REFERENCES chore_definition(id) ON DELETE CASCADE,
    member_id TEXT NOT NULL REFERENCES family_member(id)    ON DELETE CASCADE,
    PRIMARY KEY (chore_id, member_id)
);

CREATE INDEX IF NOT EXISTS idx_chore_assignee_chore   ON chore_assignee(chore_id);
CREATE INDEX IF NOT EXISTS idx_chore_assignee_member  ON chore_assignee(member_id);
