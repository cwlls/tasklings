-- Migration 001: Initial schema
-- All UUIDs stored as TEXT.
-- All datetimes stored as ISO 8601 TEXT strings.
-- All booleans stored as INTEGER (0/1).
-- Foreign keys enforced via PRAGMA (set in db.py).

-- ---------------------------------------------------------------------------
-- Household
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS household (
    id         TEXT NOT NULL PRIMARY KEY,
    name       TEXT NOT NULL,
    timezone   TEXT NOT NULL DEFAULT 'America/Chicago',
    created_at TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- Family Member
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS family_member (
    id            TEXT    NOT NULL PRIMARY KEY,
    household_id  TEXT    NOT NULL REFERENCES household(id) ON DELETE CASCADE,
    username      TEXT    NOT NULL,
    password_hash TEXT    NOT NULL,
    name          TEXT    NOT NULL,
    avatar        TEXT    NOT NULL DEFAULT '',
    role          TEXT    NOT NULL CHECK (role IN ('parent', 'child')),
    color         TEXT    NOT NULL DEFAULT '#4A90D9',
    balance       INTEGER NOT NULL DEFAULT 0,
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT    NOT NULL,
    UNIQUE (household_id, username)
);

-- ---------------------------------------------------------------------------
-- Auth Session
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS auth_session (
    id         TEXT    NOT NULL PRIMARY KEY,
    member_id  TEXT    NOT NULL REFERENCES family_member(id) ON DELETE CASCADE,
    created_at TEXT,
    expires_at TEXT,
    is_revoked INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_auth_session_member ON auth_session(member_id);

-- ---------------------------------------------------------------------------
-- API Token
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS api_token (
    id         TEXT    NOT NULL PRIMARY KEY,
    member_id  TEXT    NOT NULL REFERENCES family_member(id) ON DELETE CASCADE,
    token_hash TEXT    NOT NULL UNIQUE,
    label      TEXT,
    created_at TEXT,
    expires_at TEXT,
    is_revoked INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_api_token_member ON api_token(member_id);

-- ---------------------------------------------------------------------------
-- Password Reset Token
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS password_reset_token (
    id         TEXT NOT NULL PRIMARY KEY,
    member_id  TEXT NOT NULL REFERENCES family_member(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    used_at    TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_prt_member ON password_reset_token(member_id);

-- ---------------------------------------------------------------------------
-- Chore Definition
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chore_definition (
    id                 TEXT    NOT NULL PRIMARY KEY,
    household_id       TEXT    NOT NULL REFERENCES household(id) ON DELETE CASCADE,
    title              TEXT    NOT NULL,
    description        TEXT    NOT NULL DEFAULT '',
    icon               TEXT    NOT NULL DEFAULT '',
    lumin_value        INTEGER NOT NULL DEFAULT 0,
    chore_type         TEXT    NOT NULL CHECK (chore_type IN ('constant', 'rotating')),
    rotation_frequency TEXT             CHECK (rotation_frequency IN ('daily', 'weekly', 'monthly')),
    is_active          INTEGER NOT NULL DEFAULT 1,
    created_at         TEXT
);

CREATE INDEX IF NOT EXISTS idx_chore_def_household ON chore_definition(household_id);

-- ---------------------------------------------------------------------------
-- Chore Assignment
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chore_assignment (
    id             TEXT    NOT NULL PRIMARY KEY,
    chore_id       TEXT    NOT NULL REFERENCES chore_definition(id) ON DELETE CASCADE,
    member_id      TEXT    NOT NULL REFERENCES family_member(id) ON DELETE CASCADE,
    assigned_date  TEXT    NOT NULL,
    status         TEXT    NOT NULL DEFAULT 'pending'
                           CHECK (status IN ('pending', 'completed', 'verified', 'skipped')),
    completed_at   TEXT,
    verified_by    TEXT             REFERENCES family_member(id),
    lumins_awarded INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_chore_assign_member_date
    ON chore_assignment(member_id, assigned_date);

CREATE INDEX IF NOT EXISTS idx_chore_assign_chore_date
    ON chore_assignment(chore_id, assigned_date);

-- ---------------------------------------------------------------------------
-- Rotation Schedule
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rotation_schedule (
    id          TEXT    NOT NULL PRIMARY KEY,
    chore_id    TEXT    NOT NULL REFERENCES chore_definition(id) ON DELETE CASCADE,
    member_id   TEXT    NOT NULL REFERENCES family_member(id) ON DELETE CASCADE,
    order_index INTEGER NOT NULL,
    current     INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_rotation_chore ON rotation_schedule(chore_id);

-- ---------------------------------------------------------------------------
-- Quest (Solo)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS quest (
    id           TEXT    NOT NULL PRIMARY KEY,
    household_id TEXT    NOT NULL REFERENCES household(id) ON DELETE CASCADE,
    name         TEXT    NOT NULL,
    description  TEXT    NOT NULL DEFAULT '',
    member_id    TEXT    NOT NULL REFERENCES family_member(id) ON DELETE CASCADE,
    bonus_lumins INTEGER NOT NULL DEFAULT 0,
    is_active    INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_quest_member ON quest(member_id);

-- ---------------------------------------------------------------------------
-- Quest Chore (join)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS quest_chore (
    quest_id TEXT    NOT NULL REFERENCES quest(id) ON DELETE CASCADE,
    chore_id TEXT    NOT NULL REFERENCES chore_definition(id) ON DELETE CASCADE,
    "order"  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (quest_id, chore_id)
);

-- ---------------------------------------------------------------------------
-- Group Quest
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS group_quest (
    id                 TEXT    NOT NULL PRIMARY KEY,
    household_id       TEXT    NOT NULL REFERENCES household(id) ON DELETE CASCADE,
    name               TEXT    NOT NULL,
    description        TEXT    NOT NULL DEFAULT '',
    bonus_lumins       INTEGER NOT NULL DEFAULT 0,
    reward_description TEXT,
    deadline           TEXT,
    is_active          INTEGER NOT NULL DEFAULT 1,
    created_at         TEXT
);

CREATE INDEX IF NOT EXISTS idx_group_quest_household ON group_quest(household_id);

-- ---------------------------------------------------------------------------
-- Group Quest Member (join)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS group_quest_member (
    group_quest_id TEXT NOT NULL REFERENCES group_quest(id) ON DELETE CASCADE,
    member_id      TEXT NOT NULL REFERENCES family_member(id) ON DELETE CASCADE,
    joined_at      TEXT NOT NULL,
    joined_by      TEXT NOT NULL CHECK (joined_by IN ('self', 'admin')),
    PRIMARY KEY (group_quest_id, member_id)
);

-- ---------------------------------------------------------------------------
-- Group Quest Chore (join -- the shared pool)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS group_quest_chore (
    group_quest_id TEXT    NOT NULL REFERENCES group_quest(id) ON DELETE CASCADE,
    chore_id       TEXT    NOT NULL REFERENCES chore_definition(id) ON DELETE CASCADE,
    "order"        INTEGER NOT NULL DEFAULT 0,
    claimed_by     TEXT             REFERENCES family_member(id),
    claimed_at     TEXT,
    PRIMARY KEY (group_quest_id, chore_id)
);

-- ---------------------------------------------------------------------------
-- Group Quest Completion
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS group_quest_completion (
    id             TEXT NOT NULL PRIMARY KEY,
    group_quest_id TEXT NOT NULL REFERENCES group_quest(id) ON DELETE CASCADE,
    chore_id       TEXT NOT NULL REFERENCES chore_definition(id) ON DELETE CASCADE,
    completed_by   TEXT NOT NULL REFERENCES family_member(id) ON DELETE CASCADE,
    completed_at   TEXT NOT NULL,
    UNIQUE (group_quest_id, chore_id)
);

CREATE INDEX IF NOT EXISTS idx_gqcompletion_quest ON group_quest_completion(group_quest_id);

-- ---------------------------------------------------------------------------
-- Store Item
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS store_item (
    id           TEXT    NOT NULL PRIMARY KEY,
    household_id TEXT    NOT NULL REFERENCES household(id) ON DELETE CASCADE,
    title        TEXT    NOT NULL,
    description  TEXT    NOT NULL DEFAULT '',
    icon         TEXT    NOT NULL DEFAULT '',
    price        INTEGER NOT NULL,
    is_available INTEGER NOT NULL DEFAULT 1,
    stock        INTEGER,               -- NULL = unlimited
    created_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_store_item_household ON store_item(household_id);

-- ---------------------------------------------------------------------------
-- Store Item Visibility (join)
-- No rows for an item = global (visible to all). Rows present = restricted.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS store_item_visibility (
    store_item_id TEXT NOT NULL REFERENCES store_item(id) ON DELETE CASCADE,
    member_id     TEXT NOT NULL REFERENCES family_member(id) ON DELETE CASCADE,
    PRIMARY KEY (store_item_id, member_id)
);

-- ---------------------------------------------------------------------------
-- Purchase
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS purchase (
    id           TEXT    NOT NULL PRIMARY KEY,
    item_id      TEXT    NOT NULL REFERENCES store_item(id) ON DELETE RESTRICT,
    member_id    TEXT    NOT NULL REFERENCES family_member(id) ON DELETE CASCADE,
    price_paid   INTEGER NOT NULL,
    status       TEXT    NOT NULL DEFAULT 'purchased'
                         CHECK (status IN ('purchased', 'redeemed', 'expired')),
    purchased_at TEXT    NOT NULL,
    redeemed_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_purchase_member ON purchase(member_id);

-- ---------------------------------------------------------------------------
-- Lumin Transaction (append-only ledger)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lumin_transaction (
    id           TEXT    NOT NULL PRIMARY KEY,
    member_id    TEXT    NOT NULL REFERENCES family_member(id) ON DELETE CASCADE,
    amount       INTEGER NOT NULL,
    reason       TEXT    NOT NULL CHECK (reason IN (
                     'chore_completed',
                     'quest_bonus',
                     'group_quest_bonus',
                     'purchase',
                     'bonus',
                     'penalty',
                     'adjustment'
                 )),
    reference_id TEXT,
    created_at   TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lumin_tx_member ON lumin_transaction(member_id);
