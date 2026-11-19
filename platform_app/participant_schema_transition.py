SCHEMA_PARTICIPANTS_TRANSITION = """
CREATE TABLE IF NOT EXISTS participants (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK(length(name) BETWEEN 2 AND 150),
    email TEXT NOT NULL COLLATE NOCASE UNIQUE,
    phone TEXT UNIQUE,
    legacy_pending INTEGER NOT NULL DEFAULT 0
        CHECK(legacy_pending IN (0,1)),
    email_verified INTEGER NOT NULL DEFAULT 0
        CHECK(email_verified IN (0,1)),
    phone_verified INTEGER NOT NULL DEFAULT 0
        CHECK(phone_verified IN (0,1)),
    preferred_login TEXT NOT NULL DEFAULT 'email'
        CHECK(preferred_login IN ('email','sms')),
    active INTEGER NOT NULL DEFAULT 1
        CHECK(active IN (0,1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK(phone IS NOT NULL OR legacy_pending=1)
);

CREATE TABLE IF NOT EXISTS participant_codes (
    id INTEGER PRIMARY KEY,
    participant_id INTEGER NOT NULL
        REFERENCES participants(id),
    channel TEXT NOT NULL
        CHECK(channel IN ('email','sms')),
    purpose TEXT NOT NULL
        CHECK(purpose IN ('register','login','verify','recovery')),
    code_hash TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    used_at INTEGER,
    attempts INTEGER NOT NULL DEFAULT 0
        CHECK(attempts BETWEEN 0 AND 5),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_participant_codes_lookup
ON participant_codes(participant_id,channel,purpose,expires_at);

CREATE TABLE IF NOT EXISTS credit_movements (
    id INTEGER PRIMARY KEY,
    participant_id INTEGER NOT NULL
        REFERENCES participants(id),
    amount_cents INTEGER NOT NULL CHECK(amount_cents != 0),
    movement_type TEXT NOT NULL
        CHECK(movement_type IN ('topup','consume','refund','adjustment')),
    reference TEXT NOT NULL UNIQUE,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_credit_movements_participant
ON credit_movements(participant_id,id);

CREATE TABLE IF NOT EXISTS participant_closure_requests (
    id INTEGER PRIMARY KEY,
    participant_id INTEGER NOT NULL
        REFERENCES participants(id),
    status TEXT NOT NULL
        CHECK(status IN ('pending','approved','rejected')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT,
    resolved_by TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_closure_pending
ON participant_closure_requests(participant_id)
WHERE status='pending';
"""
