import json
import sqlite3
import time
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import ScanConfig
from app.storage import Store
from app.worker import Worker
from tests.app_support import MemoryVault


def test_inheritance_keeps_latest_complete_metadata_and_older_members(tmp_path):
    store = Store(tmp_path / "history.sqlite")
    store.initialize()
    config = ScanConfig(seeds=["query"])
    now = time.time()
    root = store.create_run(config, "root")
    store.update_run(root, status="completed")
    other = store.create_run(config, "other-collection")
    store.update_run(other, status="completed")
    # Several large API responses per video, plus a legacy partial last snapshot.
    history = [root]
    for i in range(8):
        run = store.create_run(config, f"history-{i}", "refresh", history[-1])
        store.update_run(run, status="completed")
        history.append(run)
        payload = {
            "video_id": "a",
            "description": "большое описание " * 16000,
            "revision": i,
        }
        with store.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO app_run_videos VALUES (?,?,?,?)",
                (run, "a", json.dumps(payload), now + 86400),
            )
            db.execute("UPDATE app_runs SET created_at=? WHERE id=?", (now, run))
    with store.connect() as db:
        db.execute(
            "INSERT INTO app_run_videos VALUES (?,?,?,?)",
            (root, "legacy-only", '{"video_id":"legacy-only"}', now + 86400),
        )
        db.execute(
            "INSERT INTO app_run_videos VALUES (?,?,?,?)",
            (other, "foreign", '{"video_id":"foreign"}', now + 86400),
        )
        db.execute(
            "INSERT INTO app_run_videos VALUES (?,?,?,?)",
            (history[-1], "expired", '{"video_id":"expired"}', now - 1),
        )
        before = db.execute(
            "SELECT payload_json FROM app_run_videos WHERE run_id=? AND video_id='a'",
            (history[-1],),
        ).fetchone()[0]
    result = store.create_run(config, "after-night", "refresh", history[-1])
    with store.connect() as db:
        rows = {
            r[0]: json.loads(r[1])
            for r in db.execute(
                "SELECT video_id,payload_json FROM app_run_videos WHERE run_id=?",
                (result,),
            )
        }
        assert (
            db.execute(
                "SELECT payload_json FROM app_run_videos WHERE run_id=? AND video_id='a'",
                (history[-1],),
            ).fetchone()[0]
            == before
        )
    assert set(rows) == {"a", "legacy-only"}
    assert rows["a"] == {**json.loads(before), "inherited": True}


@pytest.mark.parametrize("stage", ["claim", "purge", "entities", "schedule"])
def test_worker_retries_storage_polling_without_dying_or_calling_youtube(
    tmp_path, monkeypatch, stage
):
    store = Store(tmp_path / "worker.sqlite")
    store.initialize()
    engine = Mock()
    worker = Worker(store, MemoryVault(), engine)
    worker.last_purge = 0
    calls, errors, waits = [], [], []

    def fail_once():
        calls.append(stage)
        if len(calls) == 1:
            raise sqlite3.OperationalError("database or disk is full")
        if stage == "schedule":
            worker.stop.set()

    monkeypatch.setattr(worker.scheduler, "tick", worker.stop.set)
    target, name = {
        "claim": (store, "claim"),
        "purge": (store, "purge"),
        "entities": (worker.entities, "claim"),
        "schedule": (worker.scheduler, "tick"),
    }[stage]
    monkeypatch.setattr(target, name, fail_once)

    def backoff(seconds):
        waits.append(seconds)
        errors.append(worker.storage_error)
        return False

    monkeypatch.setattr(worker.stop, "wait", backoff)
    worker.wake.set()
    worker.loop()
    assert waits == [30] and errors[0]
    assert calls == [stage, stage] and worker.storage_error is None
    engine.assert_not_called()


def test_storage_error_is_json_and_degraded_worker_is_visible(tmp_path, monkeypatch):
    vault = MemoryVault()
    vault.save("synthetic-fixture-key")
    monkeypatch.setattr(
        Worker, "poll", Mock(side_effect=sqlite3.OperationalError("disk full"))
    )
    app = create_app(tmp_path, vault)
    with TestClient(app) as client:
        client.get("/")
        bootstrap = client.get("/api/bootstrap").json()
        assert bootstrap["worker_alive"] and bootstrap["worker_error"]
        assert client.get("/healthz").status_code == 503
        monkeypatch.setattr(
            app.state.store,
            "create_run",
            Mock(side_effect=sqlite3.OperationalError("private diagnostic")),
        )
        response = client.post(
            "/api/research",
            headers={"X-CSRF-Token": app.state.csrf},
            json={"config": {"seeds": ["query"]}, "request_id": "failing-create-123"},
        )
        assert response.status_code == 503
        assert response.headers["content-type"].startswith("application/json")
        assert "Хранилище" in response.json()["error"]
        assert "private diagnostic" not in response.text
