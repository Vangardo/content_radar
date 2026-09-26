"""Metadata and quota accounting; secret values remain in the vault."""

import datetime as dt
import hashlib
import time
import uuid
from zoneinfo import ZoneInfo


class KeyRegistry:
    def __init__(self, store, vault):
        self.store, self.vault = store, vault

    def slot(self, ident):
        if ident == "default":
            return self.vault
        if hasattr(self.vault, "named"):
            return self.vault.named(ident)
        # Dependency-injected in-memory vaults in isolated tests only.
        if not hasattr(self.vault, "slots"):
            self.vault.slots = {}
        if ident not in self.vault.slots:
            self.vault.slots[ident] = type(self.vault)()
        return self.vault.slots[ident]

    def metadata(self, ident, owner="admin"):
        with self.store.connect() as c:
            row = c.execute(
                "SELECT * FROM app_credentials WHERE id=? AND owner_id=?",
                (ident, owner),
            ).fetchone()
        if not row:
            raise ValueError("Ключ не найден")
        return dict(row)

    def get(self, ident="default"):
        meta = self.metadata(ident)
        return self.slot(ident).get() if meta["enabled"] else None

    def available(self, ident):
        try:
            return bool(self.get(ident))
        except Exception:
            return False

    def initialize(self):
        if self.available("default"):
            digest = hashlib.sha256(self.get().encode()).hexdigest()
            with self.store.connect() as c:
                c.execute(
                    "UPDATE app_credentials SET fingerprint=? WHERE id='default'",
                    (digest,),
                )

    def save(self, name, project, key, ident=None):
        if (
            len(key) < 20
            or len(key) > 200
            or not all(c.isalnum() or c in "_-" for c in key)
        ):
            raise ValueError("Нужен YouTube Data API key из Google Cloud")
        digest = hashlib.sha256(key.encode()).hexdigest()
        ident = ident or uuid.uuid4().hex
        with self.store.connect() as c:
            if c.execute(
                "SELECT 1 FROM app_credentials WHERE fingerprint=? AND id<>?",
                (digest, ident),
            ).fetchone():
                raise ValueError("Этот ключ уже добавлен")
        self.slot(ident).save(key)
        with self.store.connect() as c:
            c.execute(
                "INSERT INTO app_credentials VALUES (?,'admin',?,?,?,1,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,project_id=excluded.project_id,fingerprint=excluded.fingerprint,enabled=1",
                (ident, name.strip(), project.strip().lower(), digest, time.time()),
            )
        return ident

    def rename_project(self, ident, name, project):
        previous = self.metadata(ident)
        with self.store.connect() as c:
            c.execute(
                "INSERT OR IGNORE INTO app_quota_blocks SELECT ?,day,bucket FROM app_quota_blocks WHERE project_id=?",
                (project.strip().lower(), previous["project_id"]),
            )
            c.execute(
                "UPDATE app_credentials SET name=?,project_id=? WHERE id=?",
                (name.strip(), project.strip().lower(), ident),
            )

    def disable(self, ident):
        self.metadata(ident)
        with self.store.connect() as c:
            c.execute("UPDATE app_credentials SET enabled=0 WHERE id=?", (ident,))

    @staticmethod
    def day():
        return dt.datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()

    def charge(self, ident, endpoint, units):
        with self.store.connect() as c:
            c.execute(
                "INSERT INTO app_key_usage VALUES (?,?,?,?) ON CONFLICT(key_id,day) DO UPDATE SET search_calls=search_calls+excluded.search_calls,units=units+excluded.units",
                (
                    ident,
                    self.day(),
                    int(endpoint == "search"),
                    0 if endpoint == "search" else max(1, units),
                ),
            )

    def block(self, ident, endpoint):
        project = self.metadata(ident)["project_id"]
        with self.store.connect() as c:
            c.execute(
                "INSERT OR IGNORE INTO app_quota_blocks VALUES (?,?,?)",
                (project, self.day(), "search" if endpoint == "search" else "general"),
            )

    def blocked(self, ident, endpoint):
        project = self.metadata(ident)["project_id"]
        with self.store.connect() as c:
            return bool(
                c.execute(
                    "SELECT 1 FROM app_quota_blocks WHERE project_id=? AND day=? AND bucket=?",
                    (
                        project,
                        self.day(),
                        "search" if endpoint == "search" else "general",
                    ),
                ).fetchone()
            )

    def list(self):
        with self.store.connect() as c:
            rows = [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM app_credentials WHERE owner_id='admin' ORDER BY created_at,id"
                )
            ]
            usage = {
                r["key_id"]: dict(r)
                for r in c.execute(
                    "SELECT * FROM app_key_usage WHERE day=?", (self.day(),)
                )
            }
        for r in rows:
            own = usage.get(r["id"], {})
            project_keys = [k["id"] for k in rows if k["project_id"] == r["project_id"]]
            r.update(
                configured=self.available(r["id"]),
                search_used=own.get("search_calls", 0),
                units_used=own.get("units", 0),
                project_search_used=sum(
                    usage.get(k, {}).get("search_calls", 0) for k in project_keys
                ),
                project_units_used=sum(
                    usage.get(k, {}).get("units", 0) for k in project_keys
                ),
                search_blocked=self.blocked(r["id"], "search"),
                general_blocked=self.blocked(r["id"], "videos"),
            )
            r["fingerprint"] = (r["fingerprint"] or "")[:10]
        return rows
