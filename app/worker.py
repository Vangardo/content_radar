from __future__ import annotations

import logging
import sqlite3
import threading
import time

from .engine_adapter import EngineAdapter, RadarClient
from .monitoring import Scheduler
from .entities import Entities
from .entity_worker import refresh_entities


class InstanceLock:
    """OS releases this lock after crashes; two app processes must not share a worker."""

    def __init__(self, path):
        self.path, self.file = path, None

    def acquire(self):
        import os

        self.file = self.path.open("a+b")
        self.file.seek(0)
        self.file.write(b"0")
        self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            self.file = None
            raise RuntimeError(
                "Topic Radar уже работает с этой базой. Откройте существующее окно."
            ) from None

    def release(self):
        if self.file:
            self.file.close()


class Worker:
    def __init__(self, store, vault, engine_type=EngineAdapter):
        self.store, self.vault, self.engine_type = store, vault, engine_type
        self.scheduler = Scheduler(store, vault)
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.thread = threading.Thread(
            target=self.loop, name="radar-worker", daemon=True
        )
        self.last_seen = time.time()
        self.entities = Entities(store)
        self.storage_error = None
        self.last_purge = time.time()
        self.last_schedule = 0

    def start(self):
        self.thread.start()

    def close(self):
        self.stop.set()
        self.wake.set()
        self.thread.join(timeout=30)

    def poll(self):
        """Poll transactional claims and schedules before any external API work."""
        run_id = self.store.claim()
        if run_id:
            return run_id, None
        if time.time() - self.last_purge > 3600:
            self.store.purge()
            self.last_purge = time.time()
        job = self.entities.claim()
        if job:
            return None, job
        if time.time() - self.last_schedule >= 5:
            self.scheduler.tick()
            self.last_schedule = time.time()
        return None, None

    def loop(self):
        while not self.stop.is_set():
            self.last_seen = time.time()
            try:
                run_id, job = self.poll()
                self.storage_error = None
            except (sqlite3.Error, OSError) as exc:
                # Claims and scheduled run creation roll back on failure. Retry
                # polling, not an in-flight YouTube request, after a bounded delay.
                self.storage_error = "Мониторинг ждёт доступа к хранилищу. Повторная проверка через 30 секунд."
                logging.getLogger(__name__).error(
                    "Worker polling failed (%s); retrying in 30 seconds", type(exc).__name__
                )
                self.stop.wait(30)
                continue
            if run_id:
                try:
                    if self.store.run(run_id)["kind"] == "refilter":
                        if self.store.cancelled(run_id):
                            self.store.update_run(
                                run_id,
                                status="cancelled",
                                ended_at=time.time(),
                                stage="Отменено",
                            )
                        else:
                            self.store.refilter(run_id)
                        continue
                    key = (
                        self.store.keys.get(
                            self.store.run(run_id)["config"].get(
                                "credential_id", "default"
                            )
                        )
                        if hasattr(self.store, "keys")
                        else self.vault.get()
                    )
                    if not key:
                        raise RuntimeError("Missing credential")
                    self.engine_type(self.store, run_id, key, self.stop).execute()
                except Exception as exc:
                    self.store.update_run(
                        run_id,
                        status="failed",
                        stage="Ошибка запуска",
                        ended_at=time.time(),
                        error=f"Не удалось запустить исследование ({type(exc).__name__}). Проверьте подключение ключа.",
                    )
                continue
            if job:
                refresh_entities(
                    self.store,
                    job,
                    self.stop,
                    getattr(self.engine_type, "entity_client_type", RadarClient),
                )
                continue
            self.wake.wait(0.5)
            self.wake.clear()
