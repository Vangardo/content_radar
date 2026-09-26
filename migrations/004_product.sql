CREATE TABLE app_users (
 id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, role TEXT NOT NULL DEFAULT 'admin',
 password_hash TEXT, created_at REAL NOT NULL, disabled INTEGER NOT NULL DEFAULT 0
);
INSERT INTO app_users(id,username,created_at) VALUES ('admin','admin',unixepoch());
CREATE TABLE app_credentials (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES app_users(id),
 name TEXT NOT NULL, project_id TEXT NOT NULL, fingerprint TEXT,
 enabled INTEGER NOT NULL DEFAULT 1, created_at REAL NOT NULL
);
INSERT INTO app_credentials VALUES ('default','admin','Основной ключ','default',NULL,1,unixepoch());
CREATE TABLE app_research (
 id TEXT PRIMARY KEY REFERENCES app_runs(id), owner_id TEXT NOT NULL REFERENCES app_users(id),
 credential_id TEXT NOT NULL REFERENCES app_credentials(id), created_at REAL NOT NULL
);
INSERT INTO app_research SELECT collection_id,'admin','default',MIN(created_at) FROM app_runs GROUP BY collection_id;
CREATE TABLE app_key_usage (
 key_id TEXT NOT NULL REFERENCES app_credentials(id), day TEXT NOT NULL,
 search_calls INTEGER NOT NULL DEFAULT 0, units INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(key_id,day)
);
INSERT INTO app_key_usage SELECT 'default',day,search_calls,units FROM quota;
CREATE TABLE app_quota_blocks (
 project_id TEXT NOT NULL, day TEXT NOT NULL, bucket TEXT NOT NULL,
 PRIMARY KEY(project_id,day,bucket)
);
CREATE TABLE app_access_tokens (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES app_users(id), name TEXT NOT NULL,
 token_hash TEXT UNIQUE NOT NULL, scope TEXT NOT NULL,
 created_at REAL NOT NULL, expires_at REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0
);
UPDATE app_meta SET value='4' WHERE key='schema_version';
