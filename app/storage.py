from __future__ import annotations

import datetime as dt
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from zoneinfo import ZoneInfo

from .models import Budget, ENGINE_SHA, ScanConfig
from .metrics import growth_metrics, lifetime_metrics
from .signals import signal_metrics, DEFAULT_SMALL_LIMIT
from .video_metadata import metadata, video_format
from .channel_metadata import channel_metadata

ROOT = Path(__file__).resolve().parent.parent
RETENTION = 28 * 86400


class ResearchDeleted(ValueError):
    def __init__(self):
        super().__init__("Исследование удалено. Сначала восстановите его из корзины.")


def dumps(value):
    return json.dumps(value, ensure_ascii=False)


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def initialize(self):
        version = sqlite3.sqlite_version_info
        if version < (3, 51, 3) and version not in {(3, 44, 6), (3, 50, 7)}:
            raise RuntimeError(
                "Нужна SQLite 3.51.3+ либо исправленная 3.44.6/3.50.7; см. README_LOCAL.md"
            )
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(
                (ROOT / "migrations/001_initial.sql").read_text(encoding="utf-8")
            )
            version = int(
                conn.execute(
                    "SELECT value FROM app_meta WHERE key='schema_version'"
                ).fetchone()[0]
            )
            for number, filename in [
                (2, "002_collections.sql"),
                (3, "003_monitoring.sql"),
                (4, "004_product.sql"),
                (5, "005_entities.sql"),
                (6, "006_research_trash.sql"),
            ]:
                if version < number:
                    conn.executescript(
                        "BEGIN IMMEDIATE;\n"
                        + (ROOT / "migrations" / filename).read_text(encoding="utf-8")
                        + "\nCOMMIT;"
                    )
        self.purge()

    def recover(self):
        with self.connect() as conn:
            conn.execute(
                "UPDATE app_entity_jobs SET status='interrupted',ended_at=?,error='Прервано при перезапуске. Полученные данные сохранены.' WHERE status IN ('queued','running')",
                (time.time(),),
            )
            conn.execute(
                "UPDATE app_runs SET status='interrupted', ended_at=?, stage='Прерван при закрытии приложения', error='Сохранённые результаты доступны. Запустите повторное исследование.' WHERE status IN ('running','queued')",
                (time.time(),),
            )

    def setting(self, key, default=None):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT value FROM app_meta WHERE key=?", (key,)
            ).fetchone()
            return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO app_meta VALUES (?,?)", (key, dumps(value))
            )

    def budget(self):
        return Budget(**self.setting("budget", {}))

    def quota(self):
        now = dt.datetime.now(ZoneInfo("America/Los_Angeles"))
        reset = dt.datetime.combine(
            now.date() + dt.timedelta(days=1), dt.time(), now.tzinfo
        )
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM quota WHERE day=?", (now.date().isoformat(),)
            ).fetchone()
        return {
            **self.budget().model_dump(),
            "search_used": row["search_calls"] if row else 0,
            "units_used": row["units"] if row else 0,
            "reset_at": reset.timestamp(),
        }

    def create_run(
        self,
        config: ScanConfig,
        request_id: str,
        kind="discover",
        parent_id=None,
        selection=None,
        owner_id="admin",
    ):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT r.id,q.owner_id,r.collection_id FROM app_runs r JOIN app_research q ON q.id=r.collection_id WHERE r.request_id=?",
                (request_id,),
            ).fetchone()
            if row:
                if row[1] != owner_id:
                    raise ValueError("Идентификатор запроса уже используется")
                if conn.execute(
                    "SELECT 1 FROM app_research_trash WHERE collection_id=?", (row[2],)
                ).fetchone():
                    raise ResearchDeleted()
                return row[0]
            collection_id = None
            if parent_id:
                parent = conn.execute(
                    "SELECT collection_id FROM app_runs WHERE id=?", (parent_id,)
                ).fetchone()
                if not parent:
                    raise ValueError("Исследование не найдено")
                collection_id = parent[0]
                if conn.execute(
                    "SELECT 1 FROM app_research_trash WHERE collection_id=?",
                    (collection_id,),
                ).fetchone():
                    raise ResearchDeleted()
                parent_id = conn.execute(
                    "SELECT id FROM app_runs WHERE collection_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                    (collection_id,),
                ).fetchone()[0]
                if selection is not None:
                    known = {
                        r[0]
                        for r in conn.execute(
                            "SELECT video_id FROM app_run_videos WHERE run_id=? AND expires_at>?",
                            (parent_id, time.time()),
                        )
                    }
                    if not selection or not set(selection) <= known:
                        raise ValueError(
                            "Выбранные видео отсутствуют в актуальном списке. Обновите страницу."
                        )
            # Queue separate research independently; never overlap one collection.
            row = conn.execute(
                "SELECT id FROM app_runs WHERE collection_id=? AND status IN ('running','queued') LIMIT 1",
                (collection_id,),
            ).fetchone()
            if row:
                return row[0]
            config_json = dumps(config.model_dump())
            conn.execute(
                "INSERT INTO app_directions(name,language,config_json,updated_at) VALUES (?,?,?,?) ON CONFLICT(name,language) DO UPDATE SET config_json=excluded.config_json, updated_at=excluded.updated_at",
                (config.name, config.language, config_json, time.time()),
            )
            direction = conn.execute(
                "SELECT id FROM app_directions WHERE name=? AND language=?",
                (config.name, config.language),
            ).fetchone()[0]
            run_id = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO app_runs(id,request_id,direction_id,kind,parent_id,status,config_json,engine_sha,created_at,total) VALUES (?,?,?,?,?,'queued',?,?,?,?)",
                (
                    run_id,
                    request_id,
                    direction,
                    kind,
                    parent_id,
                    config_json,
                    ENGINE_SHA,
                    time.time(),
                    len(config.seeds),
                ),
            )
            conn.execute(
                "UPDATE app_runs SET collection_id=?,selection_json=? WHERE id=?",
                (
                    collection_id or run_id,
                    dumps(selection) if selection is not None else None,
                    run_id,
                ),
            )
            if not parent_id:
                conn.execute(
                    "INSERT INTO app_research VALUES (?,?,?,?)",
                    (run_id, owner_id, config.credential_id, time.time()),
                )
            else:
                conn.execute(
                    "UPDATE app_research SET credential_id=? WHERE id=?",
                    (config.credential_id, collection_id),
                )
            if parent_id:
                # Sort only IDs. Full YouTube metadata multiplied by many nightly
                # snapshots can otherwise exhaust SQLite's temporary filesystem.
                for row in conn.execute(
                    """WITH ranked AS (
                    SELECT v.rowid AS video_rowid,
                    ROW_NUMBER() OVER (PARTITION BY v.video_id ORDER BY r.created_at DESC,r.rowid DESC) AS rank
                    FROM app_run_videos v JOIN app_runs r ON v.run_id=r.id
                    WHERE r.collection_id=? AND r.id<>? AND v.expires_at>?
                    ) SELECT v.video_id,v.payload_json,v.expires_at
                    FROM ranked JOIN app_run_videos v ON v.rowid=ranked.video_rowid
                    WHERE ranked.rank=1""",
                    (collection_id, run_id, time.time()),
                ).fetchall():
                    payload = json.loads(row[1])
                    payload["inherited"] = True
                    conn.execute(
                        "INSERT INTO app_run_videos VALUES (?,?,?,?)",
                        (run_id, row[0], dumps(payload), row[2]),
                    )
                conn.execute(
                    "UPDATE app_runs SET data_expires_at=(SELECT MIN(expires_at) FROM app_run_videos WHERE run_id=?) WHERE id=?",
                    (run_id, run_id),
                )
            return run_id

    def claim(self):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT id FROM app_runs WHERE status='queued' AND collection_id NOT IN (SELECT collection_id FROM app_research_trash) ORDER BY created_at LIMIT 1"
            ).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE app_runs SET status='running', started_at=?, stage='Подключение к YouTube' WHERE id=?",
                (time.time(), row[0]),
            )
            return row[0]

    def refilter(self, run_id):
        """Apply research filters locally without changing API source times or TTL."""
        from .engine_adapter import filter_reasons

        run = self.run(run_id)
        config = ScanConfig(**run["config"])
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT video_id,payload_json FROM app_run_videos WHERE run_id=? AND expires_at>?",
                (run_id, time.time()),
            ).fetchall()
            included = 0
            for row in rows:
                video = json.loads(row[1])
                video["reasons"] = filter_reasons(video, config)
                video["included"] = not video["reasons"]
                included += video["included"]
                conn.execute(
                    "UPDATE app_run_videos SET payload_json=? WHERE run_id=? AND video_id=?",
                    (dumps(video), run_id, row[0]),
                )
            stats = {
                "videos": len(rows),
                "included": included,
                "excluded": len(rows) - included,
                "new_videos": 0,
                "updated_videos": 0,
                "search_calls": 0,
                "general_units": 0,
                "network_requests": 0,
            }
            conn.execute(
                "UPDATE app_runs SET status='completed',ended_at=?,stage='Фокус на малых каналах применён без API',stats_json=? WHERE id=?",
                (time.time(), dumps(stats), run_id),
            )

    def update_run(self, run_id, **fields):
        allowed = {
            "status",
            "stage",
            "done",
            "total",
            "error",
            "ended_at",
            "stats_json",
            "phrases_json",
            "data_expires_at",
        }
        if not fields or not fields.keys() <= allowed:
            raise ValueError("Unsupported run update")
        with self.connect() as conn:
            conn.execute(
                "UPDATE app_runs SET "
                + ",".join(f"{key}=?" for key in fields)
                + " WHERE id=?",
                (*fields.values(), run_id),
            )

    def cancel(self, run_id):
        with self.connect() as conn:
            conn.execute(
                "UPDATE app_runs SET cancel_requested=1 WHERE id=? AND status IN ('queued','running')",
                (run_id,),
            )

    def cancelled(self, run_id):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT cancel_requested FROM app_runs WHERE id=?", (run_id,)
            ).fetchone()
            return not row or bool(row[0])

    @staticmethod
    def _run(row):
        if not row:
            return None
        result = dict(row)
        result["selection"] = json.loads(result.pop("selection_json") or "null")
        for column, key in [
            ("config_json", "config"),
            ("stats_json", "stats"),
            ("phrases_json", "phrases"),
        ]:
            result[key] = json.loads(result.pop(column))
        result["expired"] = bool(
            result["data_expires_at"] and result["data_expires_at"] <= time.time()
        )
        if result["expired"]:
            result["phrases"] = []
        return result

    def runs(self, include_deleted=True):
        with self.connect() as conn:
            return [
                self._run(row)
                for row in conn.execute(
                    """SELECT * FROM app_runs WHERE (id IN
                    (SELECT id FROM app_runs ORDER BY created_at DESC LIMIT 200)
                    OR rowid IN (SELECT MAX(rowid) FROM app_runs GROUP BY collection_id))
                    AND (? OR collection_id NOT IN (SELECT collection_id FROM app_research_trash))
                    ORDER BY created_at DESC,rowid DESC""",
                    (int(include_deleted),),
                )
            ]

    def run(self, run_id):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM app_runs WHERE id=?", (run_id,)
            ).fetchone()
        return self._run(row)

    def research_deleted(self, collection_id):
        with self.connect() as conn:
            return bool(
                conn.execute(
                    "SELECT 1 FROM app_research_trash WHERE collection_id=?",
                    (collection_id,),
                ).fetchone()
            )

    def trash_research(self, ident, owner="admin", restore=False):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT q.id FROM app_research q JOIN app_runs r ON r.collection_id=q.id WHERE r.id=? AND q.owner_id=?",
                (ident, owner),
            ).fetchone()
            if not row:
                raise ValueError("Исследование не найдено")
            collection = row[0]
            if restore:
                conn.execute(
                    "DELETE FROM app_research_trash WHERE collection_id=?",
                    (collection,),
                )
            else:
                now = time.time()
                conn.execute(
                    "INSERT OR IGNORE INTO app_research_trash VALUES (?,?)",
                    (collection, now),
                )
                conn.execute(
                    "UPDATE app_schedules SET enabled=0,updated_at=?,last_message='Исследование в корзине' WHERE collection_id=?",
                    (now, collection),
                )
                conn.execute(
                    "UPDATE app_runs SET cancel_requested=1,status='cancelled',ended_at=?,stage='Исследование в корзине' WHERE collection_id=? AND status='queued'",
                    (now, collection),
                )
                conn.execute(
                    "UPDATE app_runs SET cancel_requested=1 WHERE collection_id=? AND status='running'",
                    (collection,),
                )
        return collection

    def research_trash(self, owner="admin"):
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT t.collection_id,t.deleted_at FROM app_research_trash t JOIN app_research q ON q.id=t.collection_id WHERE q.owner_id=? ORDER BY t.deleted_at DESC",
                (owner,),
            ).fetchall()
        result = []
        for row in rows:
            run = self.collection_runs(row[0])[0]
            result.append(
                {
                    "id": row[0],
                    "deleted_at": row[1],
                    "latest_id": run["id"],
                    "name": run["config"]["name"],
                    "language": run["config"]["language"],
                }
            )
        return result

    def collection_runs(self, run_id):
        with self.connect() as conn:
            return [
                self._run(r)
                for r in conn.execute(
                    "SELECT * FROM app_runs WHERE collection_id=(SELECT collection_id FROM app_runs WHERE id=?) ORDER BY created_at DESC,rowid DESC",
                    (run_id,),
                )
            ]

    def search_start(self, run_id, query, default):
        """A bounded full search establishes a baseline; incomplete append doesn't advance it."""
        requested_format = self.run(run_id)["config"].get("video_format", "all")
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT r.kind,q.payload_json,r.status FROM app_run_queries q JOIN app_runs r ON q.run_id=r.id WHERE r.collection_id=(SELECT collection_id FROM app_runs WHERE id=?) AND r.id<>? AND q.query=? AND q.expires_at>? ORDER BY r.created_at DESC,r.rowid DESC",
                (run_id, run_id, query, time.time()),
            ).fetchall()
        for row in rows:
            q = json.loads(row[1])
            if q.get("video_format", "all") != requested_format:
                continue
            finished = q.get("finished", row[2] == "completed")
            boundary = q.get("window_until", q.get("fetched_at"))
            if finished and boundary and (row[0] != "append" or not q.get("has_more")):
                return max(default, boundary - 86400)
        return default

    def cached_channels(self, ids):
        if not ids:
            return {}
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id,payload_json,fetched_at FROM app_channels WHERE expires_at>? AND fetched_at>?",
                (time.time(), time.time() - 86400),
            ).fetchall()
        return {r[0]: (json.loads(r[1]), r[2]) for r in rows if r[0] in ids}

    def directions(self):
        with self.connect() as conn:
            return [
                json.loads(row[0])
                for row in conn.execute(
                    "SELECT config_json FROM app_directions ORDER BY updated_at DESC LIMIT 30"
                )
            ]

    def save_response(self, endpoint, data, fetched_at, response_key):
        expires = fetched_at + RETENTION
        with self.connect() as conn:
            for item in data.get("items", []):
                ident = item.get("id")
                if not ident:
                    continue
                if endpoint == "videos":
                    payload = metadata(item, fetched_at)
                    conn.execute(
                        "INSERT INTO app_videos VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload_json=excluded.payload_json, fetched_at=excluded.fetched_at, expires_at=excluded.expires_at WHERE excluded.fetched_at>=app_videos.fetched_at",
                        (ident, dumps(payload), fetched_at, expires),
                    )
                    conn.execute(
                        "INSERT OR IGNORE INTO app_video_snapshots VALUES (?,?,?,?,?,?,?)",
                        (
                            ident,
                            fetched_at,
                            payload["views"],
                            payload["likes"],
                            payload["comments"],
                            response_key,
                            expires,
                        ),
                    )
                elif endpoint == "channels":
                    payload = channel_metadata(item, fetched_at)
                    conn.execute(
                        "INSERT INTO app_channels VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload_json=excluded.payload_json, fetched_at=excluded.fetched_at, expires_at=excluded.expires_at WHERE excluded.fetched_at>=app_channels.fetched_at",
                        (ident, dumps(payload), fetched_at, expires),
                    )
                    conn.execute(
                        "INSERT OR IGNORE INTO app_channel_snapshots VALUES (?,?,?,?,?,?,?)",
                        (
                            ident,
                            fetched_at,
                            payload["subs"],
                            payload["views"],
                            payload["video_count"],
                            dumps(payload),
                            expires,
                        ),
                    )

    def save_video(self, run_id, video):
        expiry = (
            min(
                video["fetched_at"],
                video.get("channel_fetched_at", video["fetched_at"]),
            )
            + RETENTION
        )
        with self.connect() as conn:
            owner = conn.execute(
                "SELECT q.owner_id,q.credential_id FROM app_research q JOIN app_runs r ON r.collection_id=q.id WHERE r.id=?",
                (run_id,),
            ).fetchone()
            if owner:
                for kind, ident in (
                    ("videos", video["video_id"]),
                    ("channels", video["channel_id"]),
                ):
                    if ident:
                        conn.execute(
                            "INSERT INTO app_entity_refs VALUES (?,?,?,?,?) ON CONFLICT(owner_id,kind,entity_id) DO UPDATE SET credential_id=excluded.credential_id,last_seen=MAX(app_entity_refs.last_seen,excluded.last_seen)",
                            (owner[0], kind, ident, owner[1], video["fetched_at"]),
                        )
            existing = conn.execute(
                "SELECT payload_json FROM app_run_videos WHERE run_id=? AND video_id=?",
                (run_id, video["video_id"]),
            ).fetchone()
            if existing:
                old = json.loads(existing[0])
                video["queries"] = list(
                    dict.fromkeys(old["queries"] + video["queries"])
                )
            video["inherited"] = False
            conn.execute(
                "INSERT OR REPLACE INTO app_run_videos VALUES (?,?,?,?)",
                (run_id, video["video_id"], dumps(video), expiry),
            )
            conn.execute(
                "UPDATE app_runs SET data_expires_at=(SELECT MIN(expires_at) FROM app_run_videos WHERE run_id=?) WHERE id=?",
                (run_id, run_id),
            )

    def save_query(self, run_id, query, payload, source_at):
        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO app_run_queries VALUES (?,?,?,?)",
                (run_id, query, dumps(payload), source_at + RETENTION),
            )

    def mark_unavailable(self, run_id, ids):
        with self.connect() as conn:
            for ident in ids:
                row = conn.execute(
                    "SELECT payload_json FROM app_run_videos WHERE run_id=? AND video_id=?",
                    (run_id, ident),
                ).fetchone()
                if row:
                    payload = json.loads(row[0])
                    payload["unavailable"] = True
                    conn.execute(
                        "UPDATE app_run_videos SET payload_json=? WHERE run_id=? AND video_id=?",
                        (dumps(payload), run_id, ident),
                    )

    def queries(self, run_id):
        with self.connect() as conn:
            return [
                {"query": row["query"], **json.loads(row["payload_json"])}
                for row in conn.execute(
                    "SELECT * FROM app_run_queries WHERE run_id=? AND expires_at>?",
                    (run_id, time.time()),
                )
            ]

    def growth(self, video_id, at):
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT observed_at,views,likes,comments FROM app_video_snapshots WHERE video_id=? AND observed_at<=? AND expires_at>? ORDER BY observed_at DESC",
                (video_id, at, time.time()),
            ).fetchall()
        return growth_metrics(rows)

    def videos(self, run_id):
        config = self.run(run_id)["config"]
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT v.video_id,v.payload_json,COALESCE(n.favorite,0) AS favorite,COALESCE(n.text,'') AS note FROM app_run_videos v LEFT JOIN app_notes n ON n.video_id=v.video_id WHERE run_id=? AND expires_at>?",
                (run_id, time.time()),
            ).fetchall()
        result = []
        for row in rows:
            video = json.loads(row["payload_json"])
            video.update(video_format(video))
            video.update(self.growth(row["video_id"], video["fetched_at"]))
            if video.get("unavailable"):
                video.update(
                    observed_vph=None,
                    view_delta=None,
                    interval_hours=None,
                    growth_status="unavailable",
                    like_delta=None,
                    comment_delta=None,
                    engagement_interval_hours=None,
                )
            video.update(favorite=bool(row["favorite"]), note=row["note"])
            video.update(
                signal_metrics(
                    video, config.get("max_subscribers") or DEFAULT_SMALL_LIMIT
                )
            )
            result.append(video)
        return result

    def note(self, video_id, favorite, text):
        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO app_notes VALUES (?,?,?,?)",
                (video_id, int(favorite), text, time.time()),
            )

    def saved(self):
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT n.*,v.payload_json FROM app_notes n LEFT JOIN app_videos v ON n.video_id=v.id AND v.expires_at>? WHERE n.favorite=1 OR n.text<>'' ORDER BY n.updated_at DESC",
                (time.time(),),
            ).fetchall()
        result = []
        for row in rows:
            payload = (
                json.loads(row["payload_json"])
                if row["payload_json"]
                else {"title": "Данные видео удалены по сроку хранения"}
            )
            if row["payload_json"]:
                payload.update(video_format(payload))
                payload.update(lifetime_metrics(payload, payload["fetched_at"]))
                payload.update(self.growth(row["video_id"], payload["fetched_at"]))
                with self.connect() as conn:
                    channel = conn.execute(
                        "SELECT payload_json FROM app_channels WHERE id=? AND expires_at>?",
                        (payload["channel_id"], time.time()),
                    ).fetchone()
                payload["subs"] = json.loads(channel[0])["subs"] if channel else None
                payload["views_per_subscriber"] = (
                    payload["views"] / payload["subs"]
                    if payload.get("views") is not None and (payload["subs"] or 0) > 0
                    else None
                )
            result.append(
                {
                    **payload,
                    "video_id": row["video_id"],
                    "favorite": bool(row["favorite"]),
                    "note": row["text"],
                }
            )
        return result

    def snapshots(self, video_id, at=None):
        with self.connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT observed_at,views,likes,comments FROM app_video_snapshots WHERE video_id=? AND expires_at>? AND observed_at<=? ORDER BY observed_at",
                    (video_id, time.time(), time.time() if at is None else at),
                )
            ]

    def purge(self):
        now = time.time()
        with self.connect() as conn:
            count = 0
            for table in (
                "app_run_videos",
                "app_run_queries",
                "app_video_snapshots",
                "app_videos",
                "app_channels",
                "app_channel_snapshots",
            ):
                count += conn.execute(
                    f"DELETE FROM {table} WHERE expires_at<=?", (now,)
                ).rowcount
            count += conn.execute(
                "DELETE FROM kv WHERE ts<=?", (now - RETENTION,)
            ).rowcount
            conn.execute(
                "DELETE FROM app_entity_jobs WHERE created_at<=? AND status NOT IN ('queued','running')",
                (now - RETENTION,),
            )
            conn.execute(
                "DELETE FROM app_entity_refs WHERE last_seen<=? AND NOT (kind='videos' AND owner_id='admin' AND entity_id IN (SELECT video_id FROM app_notes WHERE favorite=1 OR text<>'')) AND NOT (kind='channels' AND EXISTS (SELECT 1 FROM app_channel_notes n WHERE n.owner_id=app_entity_refs.owner_id AND n.channel_id=entity_id AND (n.favorite=1 OR n.text<>'')))",
                (now - RETENTION,),
            )
            conn.execute(
                "UPDATE app_runs SET phrases_json='[]' WHERE data_expires_at<=?", (now,)
            )
            return count
