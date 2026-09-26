CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS app_directions (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, language TEXT NOT NULL,
 config_json TEXT NOT NULL, updated_at REAL NOT NULL, UNIQUE(name, language)
);
CREATE TABLE IF NOT EXISTS app_runs (
 id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, direction_id INTEGER,
 kind TEXT NOT NULL, parent_id TEXT, status TEXT NOT NULL,
 config_json TEXT NOT NULL, engine_sha TEXT NOT NULL, created_at REAL NOT NULL,
 started_at REAL, ended_at REAL, stage TEXT NOT NULL DEFAULT 'В очереди',
 done INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 0,
 cancel_requested INTEGER NOT NULL DEFAULT 0, error TEXT,
 stats_json TEXT NOT NULL DEFAULT '{}', phrases_json TEXT NOT NULL DEFAULT '[]',
 data_expires_at REAL, FOREIGN KEY(direction_id) REFERENCES app_directions(id)
);
CREATE INDEX IF NOT EXISTS app_runs_recent ON app_runs(created_at DESC);
CREATE TABLE IF NOT EXISTS app_videos (
 id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, fetched_at REAL NOT NULL, expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS app_channels (
 id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, fetched_at REAL NOT NULL, expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS app_video_snapshots (
 video_id TEXT NOT NULL, observed_at REAL NOT NULL, views INTEGER, likes INTEGER,
 comments INTEGER, response_key TEXT NOT NULL, expires_at REAL NOT NULL,
 PRIMARY KEY(video_id, observed_at)
);
CREATE TABLE IF NOT EXISTS app_run_videos (
 run_id TEXT NOT NULL REFERENCES app_runs(id) ON DELETE CASCADE,
 video_id TEXT NOT NULL, payload_json TEXT NOT NULL, expires_at REAL NOT NULL,
 PRIMARY KEY(run_id, video_id)
);
CREATE TABLE IF NOT EXISTS app_run_queries (
 run_id TEXT NOT NULL REFERENCES app_runs(id) ON DELETE CASCADE, query TEXT NOT NULL,
 payload_json TEXT NOT NULL, expires_at REAL NOT NULL, PRIMARY KEY(run_id, query)
);
CREATE TABLE IF NOT EXISTS app_notes (
 video_id TEXT PRIMARY KEY, favorite INTEGER NOT NULL DEFAULT 0,
 text TEXT NOT NULL DEFAULT '', updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS quota (day TEXT PRIMARY KEY, units INTEGER, search_calls INTEGER DEFAULT 0);
INSERT OR IGNORE INTO app_meta VALUES ('schema_version', '1');
