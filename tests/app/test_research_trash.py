import time
import uuid

import pytest

from app.access import AccessTokens
from app.models import ScanConfig, ScheduleConfig
from app.storage import ResearchDeleted
from tests.app.test_product import setup, new, execute, offline  # noqa: F401


def test_delete_hides_all_operations_pauses_and_restores_history(setup):
    app, client, headers, transport = setup
    root = new(client, headers, monitor=True)
    execute(app, transport)
    child = client.post(
        f"/api/research/{root}/actions", headers=headers, json={"kind": "refresh"}
    ).json()["id"]
    execute(app, transport)
    store = app.state.store
    store.note("a", True, "Keep my selection")
    previous = store.videos(root)
    other = new(client, headers)
    execute(app, transport)
    assert client.delete(f"/api/research/{child}", headers=headers).status_code == 200
    assert store.research_deleted(root)
    with store.connect() as c:
        assert (
            c.execute(
                "SELECT enabled FROM app_schedules WHERE collection_id=?", (root,)
            ).fetchone()[0]
            == 0
        )
    boot = client.get("/api/bootstrap").json()
    assert all(r["collection_id"] != root for r in boot["runs"])
    assert [r["id"] for r in client.get("/api/research").json()["research"]] == [other]
    assert client.get("/api/research/trash").json()["research"][0]["id"] == root
    assert store.videos(root) == previous
    assert len(store.collection_runs(root)) == 2
    assert store.saved()[0]["note"] == "Keep my selection"
    assert (
        client.post(f"/api/research/{child}/restore", headers=headers).status_code
        == 200
    )
    assert client.get("/api/research/trash").json() == {"research": []}
    rows = client.get("/api/research").json()["research"]
    restored = next(r for r in rows if r["id"] == root)
    assert not restored["schedule"]["enabled"]
    assert client.get(f"/api/runs/{child}").status_code == 200


def test_delete_cancels_queue_and_prevents_stale_actions(setup):
    app, client, headers, transport = setup
    root = new(client, headers, monitor=True)
    store = app.state.store
    assert client.delete(f"/api/research/{root}", headers=headers).status_code == 200
    assert store.run(root)["status"] == "cancelled" and store.claim() is None
    assert store.cancelled(root)
    with pytest.raises(ResearchDeleted):
        store.create_run(ScanConfig(seeds=["query"]), uuid.uuid4().hex, "repeat", root)
    with pytest.raises(ResearchDeleted):
        store.create_run(ScanConfig(seeds=["query"]), store.run(root)["request_id"])
    from app.monitoring import Scheduler

    with pytest.raises(ResearchDeleted):
        Scheduler(store, app.state.vault).save(root, ScheduleConfig(enabled=True))
    for action in ("repeat", "append", "refresh"):
        assert (
            client.post(
                f"/api/runs/{root}/{action}",
                headers=headers,
                json={"request_id": uuid.uuid4().hex},
            ).status_code
            == 410
        )
    assert (
        client.put(
            f"/api/research/{root}/schedule", headers=headers, json={"enabled": True}
        ).status_code
        == 410
    )
    assert client.delete(f"/api/research/{root}", headers=headers).status_code == 200


def test_deleting_running_research_requests_cancellation(setup):
    app, client, headers, transport = setup
    root = new(client, headers)
    assert app.state.store.claim() == root
    assert client.delete(f"/api/research/{root}", headers=headers).status_code == 200
    assert app.state.store.run(root)["status"] == "running"
    assert app.state.store.cancelled(root)


def test_scheduler_handles_delete_between_selection_and_enqueue(setup, monkeypatch):
    from app.monitoring import Scheduler

    app, client, headers, transport = setup
    root = new(client, headers, monitor=True)
    execute(app, transport)
    store = app.state.store
    scheduler = Scheduler(store, app.state.vault)
    original = store.create_run

    def race(*args, **kwargs):
        store.trash_research(root)
        return original(*args, **kwargs)

    monkeypatch.setattr(store, "create_run", race)
    assert scheduler.tick(time.time() + 86400) is None
    assert len(store.collection_runs(root)) == 1


def test_trash_owner_and_scope_checks(setup):
    app, client, headers, transport = setup
    root = new(client, headers)
    assert client.delete(f"/api/research/{root}").status_code == 403
    with app.state.store.connect() as db:
        db.execute(
            "INSERT INTO app_users VALUES ('other','other','user',NULL,?,0)",
            (time.time(),),
        )
    tokens = AccessTokens(app.state.store)
    other = {
        "Authorization": "Bearer "
        + tokens.create("Other", "write", owner="other")["token"]
    }
    reader = {"Authorization": "Bearer " + tokens.create("Read", "read")["token"]}
    assert client.delete(f"/api/v1/research/{root}", headers=other).status_code == 404
    assert (
        client.post(f"/api/v1/research/{root}/restore", headers=other).status_code
        == 404
    )
    assert client.get("/api/v1/research/trash", headers=other).json() == {
        "research": []
    }
    assert client.delete(f"/api/v1/research/{root}", headers=reader).status_code == 403
    writer = {"Authorization": "Bearer " + tokens.create("Write", "write")["token"]}
    assert client.delete(f"/api/v1/research/{root}", headers=writer).status_code == 200
    assert (
        client.get("/api/v1/research/trash", headers=reader).json()["research"][0]["id"]
        == root
    )
    assert client.get(f"/api/v1/research/{root}", headers=writer).status_code == 410
    assert (
        client.post(f"/api/v1/research/{root}/restore", headers=writer).status_code
        == 200
    )
