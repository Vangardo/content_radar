-- Historical runs remain immutable snapshots. Related runs share a collection.
ALTER TABLE app_runs ADD COLUMN collection_id TEXT;
ALTER TABLE app_runs ADD COLUMN selection_json TEXT;
WITH RECURSIVE roots(id, root) AS (
 SELECT id, id FROM app_runs WHERE parent_id IS NULL
    OR parent_id NOT IN (SELECT id FROM app_runs)
 UNION ALL
 SELECT r.id, roots.root FROM app_runs r JOIN roots ON r.parent_id=roots.id
)
UPDATE app_runs SET collection_id=COALESCE((SELECT root FROM roots WHERE roots.id=app_runs.id),id);
CREATE INDEX app_runs_collection ON app_runs(collection_id, created_at DESC);
UPDATE app_meta SET value='2' WHERE key='schema_version';
