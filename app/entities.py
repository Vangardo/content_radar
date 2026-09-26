"""Owned entity catalog and durable refresh jobs consumed by the existing worker."""

import json
import time
import uuid

from .changes import changes
from .metrics import lifetime_metrics
from .storage import dumps
from .video_metadata import video_format


class Entities:
    def __init__(self, store):
        self.store = store

    def reference(self, kind, ident, owner="admin"):
        with self.store.connect() as c:
            r = c.execute(
                "SELECT * FROM app_entity_refs WHERE owner_id=? AND kind=? AND entity_id=?",
                (owner, kind, ident),
            ).fetchone()
        if not r:
            raise ValueError("Объект не найден в вашем пространстве")
        return dict(r)

    def link(self, kind, ident, credential, at, owner="admin"):
        with self.store.connect() as c:
            c.execute(
                "INSERT INTO app_entity_refs VALUES (?,?,?,?,?) ON CONFLICT(owner_id,kind,entity_id) DO UPDATE SET credential_id=excluded.credential_id,last_seen=MAX(app_entity_refs.last_seen,excluded.last_seen)",
                (owner, kind, ident, credential, at),
            )

    def channel_snapshots(self, ident, at=None):
        with self.store.connect() as c:
            return [
                dict(r)
                for r in c.execute(
                    "SELECT observed_at,subs,views,video_count FROM app_channel_snapshots WHERE channel_id=? AND expires_at>? AND observed_at<=? ORDER BY observed_at",
                    (ident, time.time(), time.time() if at is None else at),
                )
            ]

    def detail(self, kind, ident, owner="admin"):
        ref = self.reference(kind, ident, owner)
        table = "app_channels" if kind == "channels" else "app_videos"
        with self.store.connect() as c:
            r = c.execute(
                f"SELECT payload_json,fetched_at FROM {table} WHERE id=? AND expires_at>?",
                (ident, time.time()),
            ).fetchone()
            payload = (
                json.loads(r[0])
                if r
                else {"id": ident, "title": ident, "fetched_at": None}
            )
            payload["fetched_at"] = r[1] if r else None
            payload["credential_id"] = ref["credential_id"]
            payload["expired"] = r is None
            if kind == "channels":
                note = c.execute(
                    "SELECT favorite,text FROM app_channel_notes WHERE owner_id=? AND channel_id=?",
                    (owner, ident),
                ).fetchone()
            else:
                note = (
                    c.execute(
                        "SELECT favorite,text FROM app_notes WHERE video_id=?", (ident,)
                    ).fetchone()
                    if owner == "admin"
                    else None
                )
                payload["video_id"] = ident
                channel = c.execute(
                    "SELECT payload_json FROM app_channels WHERE id=? AND expires_at>?",
                    (payload.get("channel_id"), time.time()),
                ).fetchone()
                payload["subs"] = (
                    json.loads(channel[0]).get("subs") if channel else None
                )
            payload.update(
                favorite=bool(note and note[0]), note=note[1] if note else ""
            )
        snapshots = (
            self.channel_snapshots(ident, payload["fetched_at"])
            if kind == "channels"
            else self.store.snapshots(ident, payload["fetched_at"])
        )
        payload["last_change"] = changes(
            snapshots,
            ("subs", "views", "video_count")
            if kind == "channels"
            else ("views", "likes", "comments"),
        )
        if kind == "videos" and not payload["expired"]:
            payload["views_per_subscriber"] = (
                payload["views"] / payload["subs"]
                if payload.get("views") is not None and (payload.get("subs") or 0) > 0
                else None
            )
            payload.update(video_format(payload))
            payload.update(lifetime_metrics(payload, payload["fetched_at"]))
            payload.update(self.store.growth(ident, payload["fetched_at"]))
        return {"entity": payload, "snapshots": snapshots}

    def channels(self, owner="admin"):
        with self.store.connect() as c:
            ids = [
                r[0]
                for r in c.execute(
                    "SELECT entity_id FROM app_entity_refs WHERE owner_id=? AND kind='channels' ORDER BY last_seen DESC",
                    (owner,),
                )
            ]
        return [self.detail("channels", ident, owner)["entity"] for ident in ids]

    def channel_videos(self, ident, owner="admin"):
        self.reference("channels", ident, owner)
        with self.store.connect() as c:
            ids = [
                r[0]
                for r in c.execute(
                    "SELECT v.id FROM app_videos v JOIN app_entity_refs e ON e.entity_id=v.id AND e.kind='videos' WHERE e.owner_id=? AND v.expires_at>? AND json_extract(v.payload_json,'$.channel_id')=? ORDER BY v.fetched_at DESC",
                    (owner, time.time(), ident),
                )
            ]
        return [self.detail("videos", v, owner)["entity"] for v in ids]

    def channel_note(self, ident, favorite, text, owner="admin"):
        self.reference("channels", ident, owner)
        with self.store.connect() as c:
            c.execute(
                "INSERT OR REPLACE INTO app_channel_notes VALUES (?,?,?,?,?)",
                (owner, ident, int(favorite), text, time.time()),
            )

    def favorites(self, kind, owner="admin"):
        with self.store.connect() as c:
            if kind == "channels":
                return [
                    r[0]
                    for r in c.execute(
                        "SELECT channel_id FROM app_channel_notes WHERE owner_id=? AND favorite=1",
                        (owner,),
                    )
                ]
            return (
                [
                    r[0]
                    for r in c.execute(
                        "SELECT video_id FROM app_notes WHERE favorite=1"
                    )
                ]
                if owner == "admin"
                else []
            )

    def enqueue(self, kind, ids, credential, request_id, owner="admin"):
        ids = sorted(set(ids))
        if not ids:
            raise ValueError("Нет объектов для обновления")
        for ident in ids:
            self.reference(kind, ident, owner)
        encoded = dumps(ids)
        with self.store.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            old = c.execute(
                "SELECT id,kind,ids_json,credential_id FROM app_entity_jobs WHERE owner_id=? AND request_id=?",
                (owner, request_id),
            ).fetchone()
            if old:
                if tuple(old)[1:] != (kind, encoded, credential):
                    raise ValueError(
                        "Этот request_id уже использован для другого действия"
                    )
                return old[0]
            pending = c.execute(
                "SELECT id FROM app_entity_jobs WHERE owner_id=? AND kind=? AND ids_json=? AND credential_id=? AND status IN ('queued','running')",
                (owner, kind, encoded, credential),
            ).fetchone()
            if pending:
                return pending[0]
            ident = uuid.uuid4().hex
            c.execute(
                "INSERT INTO app_entity_jobs (id,request_id,owner_id,kind,ids_json,credential_id,created_at) VALUES (?,?,?,?,?,?,?)",
                (ident, request_id, owner, kind, encoded, credential, time.time()),
            )
            return ident

    def job(self, ident, owner="admin"):
        with self.store.connect() as c:
            row = c.execute(
                "SELECT * FROM app_entity_jobs WHERE id=? AND owner_id=?",
                (ident, owner),
            ).fetchone()
        if not row:
            raise ValueError("Обновление не найдено")
        result = dict(row)
        result["ids"] = json.loads(result.pop("ids_json"))
        result["result"] = json.loads(result.pop("result_json"))
        return result

    def claim(self):
        with self.store.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            r = c.execute(
                "SELECT id,owner_id FROM app_entity_jobs WHERE status='queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if not r:
                return None
            c.execute("UPDATE app_entity_jobs SET status='running' WHERE id=?", (r[0],))
        return self.job(r[0], r[1])

    def finish(self, ident, status, result, error=None):
        with self.store.connect() as c:
            c.execute(
                "UPDATE app_entity_jobs SET status=?,result_json=?,error=?,ended_at=? WHERE id=?",
                (status, dumps(result), error, time.time(), ident),
            )
