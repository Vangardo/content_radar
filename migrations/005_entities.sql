CREATE TABLE app_channel_snapshots (
 channel_id TEXT NOT NULL, observed_at REAL NOT NULL,
 subs INTEGER, views INTEGER, video_count INTEGER,
 payload_json TEXT NOT NULL, expires_at REAL NOT NULL,
 PRIMARY KEY(channel_id,observed_at)
);
-- Legacy channels contain only title/subscribers. Never invent historical totals.
INSERT INTO app_channel_snapshots
 SELECT id,fetched_at,json_extract(payload_json,'$.subs'),NULL,NULL,payload_json,expires_at
 FROM app_channels WHERE expires_at>unixepoch();
CREATE TABLE app_entity_refs (
 owner_id TEXT NOT NULL REFERENCES app_users(id), kind TEXT NOT NULL, entity_id TEXT NOT NULL,
 credential_id TEXT NOT NULL REFERENCES app_credentials(id), last_seen REAL NOT NULL,
 PRIMARY KEY(owner_id,kind,entity_id)
);
INSERT OR IGNORE INTO app_entity_refs
 SELECT q.owner_id,'videos',v.video_id,q.credential_id,r.created_at
 FROM app_run_videos v JOIN app_runs r ON r.id=v.run_id JOIN app_research q ON q.id=r.collection_id
 WHERE v.expires_at>unixepoch() ORDER BY r.created_at DESC;
INSERT OR IGNORE INTO app_entity_refs
 SELECT q.owner_id,'channels',json_extract(v.payload_json,'$.channel_id'),q.credential_id,r.created_at
 FROM app_run_videos v JOIN app_runs r ON r.id=v.run_id JOIN app_research q ON q.id=r.collection_id
 WHERE v.expires_at>unixepoch() AND COALESCE(json_extract(v.payload_json,'$.channel_id'),'')<>'' ORDER BY r.created_at DESC;
INSERT OR IGNORE INTO app_entity_refs SELECT 'admin','videos',video_id,'default',updated_at FROM app_notes;
CREATE TABLE app_channel_notes (
 owner_id TEXT NOT NULL REFERENCES app_users(id), channel_id TEXT NOT NULL,
 favorite INTEGER NOT NULL DEFAULT 0, text TEXT NOT NULL DEFAULT '', updated_at REAL NOT NULL,
 PRIMARY KEY(owner_id,channel_id)
);
CREATE TABLE app_entity_jobs (
 id TEXT PRIMARY KEY, request_id TEXT NOT NULL, owner_id TEXT NOT NULL REFERENCES app_users(id),
 kind TEXT NOT NULL, ids_json TEXT NOT NULL, credential_id TEXT NOT NULL REFERENCES app_credentials(id),
 status TEXT NOT NULL DEFAULT 'queued', created_at REAL NOT NULL, ended_at REAL,
 result_json TEXT NOT NULL DEFAULT '{}', error TEXT,
 UNIQUE(owner_id,request_id)
);
UPDATE app_meta SET value='5' WHERE key='schema_version';
