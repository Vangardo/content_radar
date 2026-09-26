import datetime as dt
import json
import sqlite3
import threading
import time
import uuid

import pytest
import requests
from fastapi.testclient import TestClient

from app.grouping import group_videos
from app.main import create_app
from app.models import ScanConfig
from app.storage import Store, ROOT
from tests.app_support import MemoryVault, Pages, engine_with


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(
        requests.Session, "request", lambda *a, **kw: pytest.fail("Live request")
    )


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "radar.sqlite")
    s.initialize()
    return s


def run(s, transport, parent=None, kind="discover", selection=None, **config):
    cfg = ScanConfig(
        **{"seeds": ["query"], "max_results": 100, "order": "viewCount", **config}
    )
    ident = s.create_run(cfg, uuid.uuid4().hex, kind, parent, selection)
    s.claim()
    engine_with(transport)(s, ident, "synthetic-secret", threading.Event()).execute()
    return ident


def test_two_pages_use_50_and_deduplicate_before_enrichment(store):
    t = Pages()
    ident = run(store, t)
    assert store.run(ident)["status"] == "completed"
    searches = [p for e, p in t.params if e == "search"]
    assert len(searches) == 2 and all(p["maxResults"] == 50 for p in searches)
    assert searches[1]["pageToken"] == "1"
    assert searches[0]["publishedBefore"] == searches[1]["publishedBefore"]
    assert len(store.videos(ident)) == 3
    requested = [v for e, p in t.params if e == "videos" for v in p["id"].split(",")]
    assert sorted(requested) == ["a", "b", "c"]
    q = store.queries(ident)[0]
    assert (
        q["scanned"],
        q["unique"],
        q["new"],
        q["known"],
        q["duplicates"],
        q["search_calls"],
    ) == (4, 3, 3, 0, 1, 2)
    assert not q["has_more"]


def test_three_queries_300_ids_six_searches_and_six_stat_batches(store):
    t = Pages(
        {
            q: [[q + str(i) for i in range(50)], [q + str(i) for i in range(50, 100)]]
            for q in ["a", "b", "c"]
        }
    )
    ident = run(store, t, seeds=["a", "b", "c"])
    assert len(store.videos(ident)) == 300
    assert t.calls.count("search") == 6 and t.calls.count("videos") == 6
    assert store.quota()["search_used"] == 6
    before = len(t.calls)
    refreshed = run(store, t, ident, "refresh", force=True)
    assert t.calls[before:] == ["videos"] * 6
    assert store.run(refreshed)["stats"]["general_units"] == 6
    assert store.quota()["search_used"] == 6


def test_pagination_cache_needs_no_quota_and_depth_limits_pages(store):
    t = Pages()
    first = run(store, t)
    store.set_setting("budget", {"search_limit": 0, "unit_limit": 0})
    second = run(store, t)
    assert store.run(second)["status"] == "completed"
    assert store.run(second)["stats"]["network_requests"] == 0
    assert store.queries(second)[0]["cached_pages"] == 2
    assert len(store.snapshots("a")) == 1
    assert len(store.videos(first)) == len(store.videos(second))
    limited = run(store, t, max_results=25)
    assert len(store.videos(limited)) == 2
    assert store.queries(limited)[0]["has_more"]


def test_append_preserves_old_records_queries_and_notes(store):
    t = Pages()
    first = run(store, t)
    old = store.videos(first)
    store.note("a", True, "идея")
    t.pages = {"query": [["b", "d"]], "second": [["d", "e"]]}
    second = run(store, t, first, "append", force=True, seeds=["query", "second"])
    vs = {v["video_id"]: v for v in store.videos(second)}
    assert set(vs) == {"a", "b", "c", "d", "e"}
    assert vs["a"]["inherited"] and vs["a"]["note"] == "идея"
    assert vs["d"]["queries"] == ["query", "second"]
    assert store.run(second)["stats"]["new_videos"] == 2
    assert all(p["order"] == "date" for e, p in t.params[-6:] if e == "search")
    assert {q["query"]: q["new"] for q in store.queries(second)} == {
        "query": 1,
        "second": 1,
    }
    assert {v["video_id"] for v in store.videos(first)} == {v["video_id"] for v in old}
    assert all(not v["inherited"] for v in store.videos(first))


def test_selected_refresh_and_old_link_use_latest_collection(store):
    t = Pages()
    first = run(store, t, min_views=99999999)
    second = run(store, t, first, "append", force=True)
    before = len(t.calls)
    third = run(store, t, first, "refresh", selection=["b"], force=True)
    assert store.run(third)["parent_id"] == second
    assert t.calls[before:] == ["videos"]
    vs = {v["video_id"]: v for v in store.videos(third)}
    assert (
        set(vs) == {"a", "b", "c"} and vs["a"]["inherited"] and not vs["b"]["inherited"]
    )
    assert vs["b"]["queries"] == ["query"]
    with pytest.raises(ValueError):
        store.create_run(
            ScanConfig(seeds=["query"]),
            uuid.uuid4().hex,
            "refresh",
            third,
            ["not-member"],
        )
    before = len(t.calls)
    fourth = run(store, t, third, "refresh", force=True, min_views=99999999)
    assert store.run(fourth)["stats"]["updated_videos"] == 3
    assert t.calls[before:] == ["videos"]


def test_partial_page_and_cancel_keep_previous_and_fresh_data(store):
    first = run(store, Pages())
    t = Pages({"query": [["new"], ["never"]]}, fail_page=1)
    second = run(store, t, first, "append", force=True)
    assert store.run(second)["status"] == "waiting_quota"
    assert {v["video_id"] for v in store.videos(second)} == {"a", "b", "c", "new"}
    q = store.queries(second)[0]
    assert q["pages"] == 1 and q["search_calls"] == 2 and not q["finished"]
    assert store.queries(first)[0]["finished"]
    t = Pages()
    ident = store.create_run(
        ScanConfig(seeds=["query"], force=True), uuid.uuid4().hex, "repeat", second
    )
    store.claim()
    e = engine_with(t)(store, ident, "test", threading.Event())
    collect = e.collect

    def cancel_after(*args):
        collect(*args)
        store.cancel(ident)

    e.collect = cancel_after
    e.execute()
    assert store.run(ident)["status"] == "cancelled"
    assert t.calls.count("search") == 1
    assert len(store.videos(ident)) == 4


def test_incremental_window_overlap_and_no_advancement_on_truncation(store):
    first = run(store, Pages())
    anchor = store.queries(first)[0]["window_until"]
    t = Pages({"query": [["d"], ["e"]]})
    second = run(store, t, first, "append", force=True, max_results=50)
    p = next(p for e, p in t.params if e == "search")
    assert (
        abs(
            dt.datetime.fromisoformat(
                p["publishedAfter"].replace("Z", "+00:00")
            ).timestamp()
            - (anchor - 86400)
        )
        < 0.01
    )
    assert store.queries(second)[0]["has_more"]
    assert store.search_start(second, "query", 0) == anchor - 86400
    third = store.create_run(
        ScanConfig(seeds=["query"]), uuid.uuid4().hex, "append", second
    )
    assert store.search_start(third, "query", 0) == anchor - 86400


def test_missing_video_is_not_deleted_or_zeroed_and_expiry_not_extended(store):
    t = Pages()
    first = run(store, t)
    original = {v["video_id"]: v for v in store.videos(first)}
    t.missing = {"a"}
    second = run(store, t, first, "refresh", force=True)
    vs = {v["video_id"]: v for v in store.videos(second)}
    assert vs["a"]["unavailable"]
    assert vs["a"]["observed_vph"] is None
    assert vs["a"]["views"] == original["a"]["views"]
    assert vs["a"]["fetched_at"] == original["a"]["fetched_at"]
    with store.connect() as c:
        before = c.execute(
            "SELECT expires_at FROM app_run_videos WHERE run_id=? AND video_id='a'",
            (first,),
        ).fetchone()[0]
        after = c.execute(
            "SELECT expires_at FROM app_run_videos WHERE run_id=? AND video_id='a'",
            (second,),
        ).fetchone()[0]
        assert before == after


def add_snapshot(store, at, views):
    with store.connect() as c:
        c.execute(
            "INSERT INTO app_video_snapshots VALUES ('growth',?,?,NULL,NULL,'test',?)",
            (at, views, time.time() + 86400),
        )


def test_growth_minimum_interval_baseline_zero_and_correction(store):
    now = time.time()
    add_snapshot(store, now - 7200, 100)
    add_snapshot(store, now - 30, 200)
    assert store.growth("growth", now - 30)["observed_vph"] > 0
    add_snapshot(store, now, 210)
    g = store.growth("growth", now)
    assert (
        g["interval_hours"] == 2 and g["view_delta"] == 110 and g["observed_vph"] == 55
    )
    add_snapshot(store, now + 3600, 210)
    assert store.growth("growth", now + 3600)["observed_vph"] == 0
    add_snapshot(store, now + 3601, 190)
    assert store.growth("growth", now + 3601)["correction"]
    add_snapshot(store, now + 7202, 220)
    assert store.growth("growth", now + 7202)["observed_vph"] is not None


def test_second_snapshot_under_30_minutes_is_not_a_growth_signal(store):
    now = time.time()
    add_snapshot(store, now, 100)
    add_snapshot(store, now + 1, 150)
    assert store.growth("growth", now + 1)["observed_vph"] is None
    assert store.growth("growth", now + 1)["growth_status"] == "needs_interval"


def test_30_minute_boundary_has_measured_rate(store):
    now = time.time()
    add_snapshot(store, now, 100)
    add_snapshot(store, now + 1799, 900)
    assert store.growth("growth", now + 1799)["observed_vph"] is None
    add_snapshot(store, now + 1800, 1000)
    assert store.growth("growth", now + 1800)["observed_vph"] == 1800


def test_legacy_completed_query_establishes_append_watermark(store):
    first = run(store, Pages())
    fetched = time.time()
    with store.connect() as conn:
        conn.execute(
            "UPDATE app_run_queries SET payload_json=? WHERE run_id=?",
            (json.dumps({"fetched_at": fetched, "scanned": 25}), first),
        )
    second = store.create_run(
        ScanConfig(seeds=["query"]), uuid.uuid4().hex, "append", first
    )
    assert store.search_start(second, "query", 0) == fetched - 86400


def video(title, i, channel=None, **extra):
    return {
        "title": title,
        "video_id": str(i),
        "channel_id": channel or str(i),
        "included": True,
        "subs": 2000,
        "views_per_day": 100,
        **extra,
    }


def test_obvious_groups_aliases_years_formats_and_channel_balance():
    vs = [
        video("Resident Evil 2026 movie scene", 1, "clips", observed_vph=10000),
        video("Resident Evil 2026 movie scene", 2, "clips", observed_vph=10000),
        video("Обитель зла 2026 обзор", 3, "review", observed_vph=100),
        video("Resident Evil - Movie Review", 4, "other"),
    ]
    g = group_videos(vs)[0]
    assert g["video_count"] == 4 and g["channel_count"] == 3
    assert g["observed_vph"] == 5050 and g["measured_channels"] == 2
    assert not group_videos(
        [video("10 новых фильмов 2026", 1), video("10 новых фильмов 2026", 2)]
    )
    assert not group_videos(
        [video("Resident Evil 2026", 1, "same"), video("Resident Evil 2026", 2, "same")]
    )
    years = [
        video("Resident Evil 2002 review", 1),
        video("Resident Evil 2026 review", 2),
        video("Resident Evil review", 3),
    ]
    assert not group_videos(years)
    games = [
        video("Resident Evil 2026 movie review", 1),
        video("Resident Evil 2026 gameplay", 2),
    ]
    assert not group_videos(games)
    cliff = [
        video("Новые похождения Клиффа Бута — Русский трейлер (2026)", 1),
        video("Новые похождения Клиффа Бута - Русский трейлер (4K, 2026)", 2),
    ]
    assert group_videos(cliff)[0]["video_count"] == 2


def test_migration_preserves_legacy_history_notes_and_is_repeatable(tmp_path):
    p = tmp_path / "old.sqlite"
    c = sqlite3.connect(p)
    c.executescript((ROOT / "migrations/001_initial.sql").read_text())
    cfg = json.dumps(ScanConfig(seeds=["query"]).model_dump())
    for i, parent in [("old", None), ("refresh", "old")]:
        c.execute(
            "INSERT INTO app_runs(id,request_id,kind,parent_id,status,config_json,engine_sha,created_at) VALUES (?,?,?,?,'completed',?,'sha',?)",
            (i, i, "refresh" if parent else "discover", parent, cfg, time.time()),
        )
    c.execute("INSERT INTO app_notes VALUES ('v',1,'keep',?)", (time.time(),))
    c.commit()
    c.close()
    s = Store(p)
    s.initialize()
    s.initialize()
    assert s.run("old")["collection_id"] == s.run("refresh")["collection_id"] == "old"
    assert s.saved()[0]["note"] == "keep"
    assert s.run("old")["status"] == "completed"


def test_legacy_partial_refresh_does_not_drop_earlier_members(store):
    first = run(store, Pages())
    second = run(store, Pages(), first, "refresh", force=True)
    # Prior app versions stored only refreshed/included rows in a refresh run.
    with store.connect() as c:
        c.execute(
            "DELETE FROM app_run_videos WHERE run_id=? AND video_id='c'", (second,)
        )
    third = run(store, Pages(), second, "refresh", force=True)
    assert {v["video_id"] for v in store.videos(third)} == {"a", "b", "c"}


def test_http_modes_selection_group_export_and_idempotency(tmp_path):
    vault = MemoryVault()
    vault.save("synthetic-secret-value")
    t = Pages()
    app = create_app(tmp_path, vault, engine_with(t))
    with TestClient(app) as client:
        client.get("/")
        headers = {"X-CSRF-Token": app.state.csrf}

        def post(path, **body):
            return client.post(
                path, headers=headers, json={"request_id": uuid.uuid4().hex, **body}
            )

        def wait(ident):
            for _ in range(100):
                r = client.get("/api/runs/" + ident).json()
                if r["run"]["status"] not in {"queued", "running"}:
                    return r
                time.sleep(0.02)
            pytest.fail("Worker timeout")

        first = post(
            "/api/runs",
            config=ScanConfig(seeds=["query"], order="viewCount").model_dump(),
        ).json()["id"]
        result = wait(first)
        assert len(result["groups"]) == 1
        group = result["groups"][0]["id"]
        exported = client.get(f"/api/runs/{first}/export/json?group_id={group}").json()
        assert len(exported["videos"]) == 3 and exported["groups"][0]["id"] == group
        assert (
            client.get(f"/api/runs/{first}/export/json?group_id=invalid").status_code
            == 404
        )
        assert post(f"/api/runs/{first}/refresh", video_ids=[]).status_code == 422
        assert (
            post(f"/api/runs/{first}/refresh", video_ids=["foreign"]).status_code == 400
        )
        before = len(t.calls)
        second = post(f"/api/runs/{first}/refresh", video_ids=["a"]).json()["id"]
        wait(second)
        assert t.calls[before:] == ["videos"]
        t.pages = {"query": [["a", "new"]]}
        third = post(f"/api/runs/{first}/append", max_results=50).json()["id"]
        r = wait(third)
        assert len(r["videos"]) == 4 and r["run"]["parent_id"] == second
        assert (
            client.get("/api/runs/" + first).json()["collection"]["latest_id"] == third
        )
        fourth = post(f"/api/runs/{third}/repeat", max_results=100).json()["id"]
        r = wait(fourth)
        assert r["run"]["config"]["max_results"] == 100 and len(r["videos"]) == 4
        assert r["run"]["stats"]["search_calls"] == 1
        assert "synthetic-secret-value" not in json.dumps(r)
