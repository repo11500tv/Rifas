SCHEMA_PARTICIPANTS = """
CREATE TABLE IF NOT EXISTS participants (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL CHECK(length(name) BETWEEN 2 AND 150),
 email TEXT NOT NULL COLLATE NOCASE UNIQUE, password_hash TEXT NOT NULL,
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS credit_movements (
 id INTEGER PRIMARY KEY, participant_id INTEGER NOT NULL REFERENCES participants(id),
 amount_cents INTEGER NOT NULL CHECK(amount_cents != 0),
 movement_type TEXT NOT NULL CHECK(movement_type IN ('topup','consume','refund','adjustment')),
 reference TEXT NOT NULL UNIQUE, notes TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_credit_movements_participant ON credit_movements(participant_id,id);
CREATE TABLE IF NOT EXISTS password_reset_tokens (
 id INTEGER PRIMARY KEY, participant_id INTEGER NOT NULL REFERENCES participants(id),
 token_hash TEXT NOT NULL UNIQUE, expires_at INTEGER NOT NULL, used_at INTEGER,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS participant_closure_requests (
 id INTEGER PRIMARY KEY, participant_id INTEGER NOT NULL REFERENCES participants(id),
 status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected')),
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, resolved_at TEXT, resolved_by TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_closure_pending ON participant_closure_requests(participant_id) WHERE status='pending';
"""
