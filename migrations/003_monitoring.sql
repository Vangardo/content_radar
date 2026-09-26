CREATE TABLE app_schedules (
 collection_id TEXT PRIMARY KEY,
 enabled INTEGER NOT NULL DEFAULT 0,
 full_hours INTEGER NOT NULL DEFAULT 4,
 monitor_minutes INTEGER NOT NULL DEFAULT 30,
 top_limit INTEGER NOT NULL DEFAULT 100,
 next_full REAL NOT NULL,
 next_monitor REAL NOT NULL,
 launched_run TEXT,
 last_message TEXT NOT NULL DEFAULT '',
 updated_at REAL NOT NULL
);
CREATE TABLE app_sessions (token_hash TEXT PRIMARY KEY, expires_at REAL NOT NULL, credential_version TEXT NOT NULL);
CREATE TABLE app_login_attempts (attempted_at REAL NOT NULL);
UPDATE app_meta SET value='3' WHERE key='schema_version';
