"""Disk cache (SQLite) keyed by request hash. Saves quota across re-runs."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any


class Cache:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT, ts REAL)"
        )
        self.conn.commit()

    @staticmethod
    def key(*parts: Any) -> str:
        raw = json.dumps(parts, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, key: str, max_age: float | None = None) -> Any | None:
        entry = self.get_entry(key, max_age)
        return entry[0] if entry is not None else None

    def get_entry(self, key: str, max_age: float | None = None) -> tuple[Any, float] | None:
        """Expose the original response time without changing existing keys/payloads."""
        row = self.conn.execute("SELECT v, ts FROM kv WHERE k=?", (key,)).fetchone()
        if not row:
            return None
        v, ts = row
        if max_age is not None and (time.time() - ts) > max_age:
            return None
        return json.loads(v), ts

    def set(self, key: str, value: Any) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO kv (k, v, ts) VALUES (?, ?, ?)",
            (key, json.dumps(value), time.time()),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
