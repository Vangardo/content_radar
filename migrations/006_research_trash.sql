CREATE TABLE app_research_trash (
 collection_id TEXT PRIMARY KEY REFERENCES app_research(id), deleted_at REAL NOT NULL
);
UPDATE app_meta SET value='6' WHERE key='schema_version';
