import threading
import time

import pytest
import requests
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import ScanConfig, ScheduleConfig
from app.monitoring import Scheduler, select_monitor, trend_score
from app.storage import Store
from tests.app_support import MemoryVault, Pages, engine_with


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(
        requests.Session, "request", lambda *a, **kw: pytest.fail("Live request")
    )


@pytest.fixture
def setup(tmp_path, monkeypatch):
    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    store = Store(tmp_path / "radar.sqlite")
    store.initialize()
    vault = MemoryVault()
    vault.save("synthetic-fixture-key")
    transport = Pages()
    engine = engine_with(transport)

    def execute(ident):
        assert store.claim() == ident
        engine(store, ident, vault.get(), threading.Event()).execute()
        assert store.run(ident)["status"] == "completed"

    first = store.create_run(
        ScanConfig(seeds=["query"], order="viewCount"), "test-first-run"
    )
    execute(first)
    scheduler = Scheduler(store, vault)
    return store, scheduler, transport, clock, execute, first


def test_first_repeat_top_selection_and_full_audit(setup):
    store, scheduler, transport, clock, execute, first = setup
    scheduler.save(first, ScheduleConfig(enabled=True))
    assert scheduler.tick() is None  # too soon for a real measurement
    clock[0] += 1801
    transport.views += 1000
    ident = scheduler.tick()
    assert store.run(ident)["kind"] == "monitor"
    assert set(store.run(ident)["selection"]) == {"a", "b", "c"}
    assert scheduler.tick() is None  # no duplicate queued job
    before = len(transport.calls)
    execute(ident)
    assert transport.calls[before:] == ["videos"]
    assert all(v["observed_vph"] > 0 for v in store.videos(ident))
    scheduler.tick()
    assert scheduler.get(first)["next_monitor"] == clock[0] + 1800
    # Search stops returning old a/b/c; the broad audit must still refresh them.
    transport.pages = {"query": [["new"]]}
    clock[0] += 4 * 3600
    before = len(transport.params)
    full = scheduler.tick()
    assert store.run(full)["kind"] == "scheduled_full"
    execute(full)
    requested = [
        v
        for endpoint, p in transport.params[before:]
        if endpoint == "videos"
        for v in p["id"].split(",")
    ]
    assert sorted(requested) == ["a", "b", "c", "new"]
    assert set(v["video_id"] for v in store.videos(full)) == {"a", "b", "c", "new"}
    assert store.run(full)["stats"]["new_videos"] == 1


def test_quota_does_not_block_cheap_monitor_and_restart_pause(setup):
    store, scheduler, transport, clock, execute, first = setup
    scheduler.save(first, ScheduleConfig(enabled=True))
    clock[0] += 5 * 3600
    store.set_setting("budget", {"search_limit": 0, "unit_limit": 10000})
    ident = scheduler.tick()
    assert store.run(ident)["kind"] == "monitor"
    assert scheduler.get(first)["next_full"] == store.quota()["reset_at"]
    # Simulate process exit/restart with queued work; don't replay a burst.
    store.recover()
    second = Scheduler(store, scheduler.vault)
    assert second.tick() is None
    assert second.get(first)["next_monitor"] > clock[0]
    second.save(first, ScheduleConfig(enabled=False))
    clock[0] += 86400
    assert second.tick() is None
    assert len(store.runs()) == 2


def test_zero_general_budget_waits_until_reset_and_no_key_waits(setup):
    store, scheduler, _, clock, _, first = setup
    scheduler.save(first, ScheduleConfig(enabled=True))
    clock[0] += 2000
    store.set_setting("budget", {"search_limit": 100, "unit_limit": 0})
    assert scheduler.tick() is None
    assert scheduler.get(first)["next_monitor"] == store.quota()["reset_at"]
    scheduler.vault.delete()
    clock[0] += 86400
    assert scheduler.tick() is None
    assert "ключ" in scheduler.get(first)["last_message"]


def test_pending_run_reconciles_after_crash_between_enqueue_and_save(setup):
    store, scheduler, _, clock, _, first = setup
    scheduler.save(first, ScheduleConfig(enabled=True))
    clock[0] += 2000
    ident = scheduler.tick()
    scheduler.update(first, launched_run=None)  # crash before saving pointer
    store.recover()
    assert scheduler.tick() == ident  # persisted idempotency key, not new API work
    scheduler.tick()
    assert len(store.runs()) == 2


def test_ranking_noise_new_candidates_filter_and_late_promotion():
    def v(i, delta, *, included=True, status="measured", at=100):
        return {
            "video_id": str(i),
            "subs": 2000,
            "view_delta": delta,
            "interval_hours": 0.5 if delta is not None else None,
            "included": included,
            "growth_status": status,
            "fetched_at": at,
        }

    videos = [v(i, 1000 - i) for i in range(100)]
    newcomer = v("new", None, included=False, status="needs_snapshot")
    videos += [
        newcomer,
        v("noise", 1),
        v("excluded", 100000, included=False),
        v("fresh", None, status="needs_snapshot", at=1999),
    ]
    selected = select_monitor(videos, 50, 2000, 30)
    assert len(selected) == 51 and "new" in selected and "0" in selected
    assert (
        "noise" not in selected
        and "excluded" not in selected
        and "fresh" not in selected
    )
    assert trend_score(v("tiny", 1)) == 0
    videos[99]["view_delta"] = 100000
    assert "99" in select_monitor(videos, 50, 2000, 30)


def test_schedule_api_persists_without_implicitly_enabling(tmp_path):
    vault = MemoryVault()
    vault.save("synthetic-fixture-key")
    app = create_app(tmp_path, vault, run_worker=False)
    with TestClient(app) as client:
        client.get("/")
        headers = {"x-csrf-token": app.state.csrf}
        ident = app.state.store.create_run(ScanConfig(seeds=["query"]), "api-first-run")
        assert not client.get(f"/api/runs/{ident}").json()["monitoring"]["enabled"]
        assert (
            client.put(
                f"/api/runs/{ident}/schedule",
                headers=headers,
                json={"enabled": True, "monitor_minutes": 1},
            ).status_code
            == 422
        )
        assert (
            client.put(
                f"/api/runs/{ident}/schedule",
                headers=headers,
                json={"enabled": True, "full_hours": 6, "top_limit": 50},
            ).status_code
            == 200
        )
        assert client.get(f"/api/runs/{ident}").json()["monitoring"]["full_hours"] == 6
    with TestClient(create_app(tmp_path, vault, run_worker=False)) as client:
        assert client.get(f"/api/runs/{ident}").json()["monitoring"]["enabled"]
