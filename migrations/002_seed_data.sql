-- Migration 002: Seed data
--
-- Inserts a default household and a parent admin account so the app is
-- usable immediately after first run.
--
-- IMPORTANT: Change the admin password on first login.
-- The password below is bcrypt("changeme", rounds=12).
--
-- Hardcoded UUIDs are used so subsequent runs of this migration (if the
-- IF NOT EXISTS guard is ever bypassed) remain idempotent.

INSERT OR IGNORE INTO household (id, name, timezone, created_at)
VALUES (
    'a1b2c3d4-0001-0001-0001-000000000001',
    'My Family',
    'America/Chicago',
    '2026-01-01T00:00:00+00:00'
);

-- Default admin account
-- username: admin
-- password: changeme  <-- CHANGE THIS ON FIRST LOGIN
INSERT OR IGNORE INTO family_member (
    id,
    household_id,
    username,
    password_hash,
    name,
    avatar,
    role,
    color,
    balance,
    is_active,
    created_at
) VALUES (
    'a1b2c3d4-0002-0002-0002-000000000002',
    'a1b2c3d4-0001-0001-0001-000000000001',
    'admin',
    '$2b$12$rwqrwrarw.w1HC7OG8nURuay1n2l9O6zqwP16l49N2VBvVcgFhsk2',
    'Admin',
    '',
    'parent',
    '#4A90D9',
    0,
    1,
    '2026-01-01T00:00:00+00:00'
);

-- Sample chore definitions
INSERT OR IGNORE INTO chore_definition (id, household_id, title, description, icon, lumin_value, chore_type, rotation_frequency, is_active, created_at)
VALUES
    (
        'c0000000-0001-0001-0001-000000000001',
        'a1b2c3d4-0001-0001-0001-000000000001',
        'Make bed',
        'Straighten sheets, fluff pillows, tuck everything in.',
        '🛏️',
        5,
        'constant',
        NULL,
        1,
        '2026-01-01T00:00:00+00:00'
    ),
    (
        'c0000000-0002-0002-0002-000000000002',
        'a1b2c3d4-0001-0001-0001-000000000001',
        'Take out trash',
        'Empty all bins and take bags to the outdoor bin.',
        '🗑️',
        15,
        'rotating',
        'weekly',
        1,
        '2026-01-01T00:00:00+00:00'
    ),
    (
        'c0000000-0003-0003-0003-000000000003',
        'a1b2c3d4-0001-0001-0001-000000000001',
        'Wash dishes',
        'Wash, rinse, and dry all dishes in the sink.',
        '🍽️',
        10,
        'constant',
        NULL,
        1,
        '2026-01-01T00:00:00+00:00'
    );
