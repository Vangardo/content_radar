"""Core small-creator selection; all transport is synthetic and offline."""

import json
import threading
import time
import uuid

import pytest
import requests
from fastapi.testclient import TestClient

from app.grouping import group_videos
from app.main import create_app
from app.models import ScanConfig
from app.monitoring import select_monitor
from app.signals import channel_class, signal_metrics, trend_score
from app.storage import Store
from tests.app_support import FakeResponse, MemoryVault, Pages, engine_with


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(
        requests.Session, "request", lambda *a, **k: pytest.fail("Live API forbidden")
    )


def video(ident="a", **extra):
    raw = dict(
        video_id=ident,
        channel_id=ident,
        title="Resident Evil 2026 movie review",
        subs=2000,
        views=5000,
        age_days=1,
        fetched_at=100,
        channel_fetched_at=100,
        view_delta=1000,
        interval_hours=1,
        observed_vph=1000,
        growth_status="measured",
        included=True,
        views_per_day=5000,
    )
    raw.update(extra)
    return {**raw, **signal_metrics(raw)}


def test_defaults_and_legacy_unrestricted_focus():
    assert ScanConfig(seeds=["query"]).max_subscribers == 10000
    assert ScanConfig(seeds=["query"], max_subscribers=0).max_subscribers == 10000
    assert ScanConfig(seeds=["query"]).order == "mixed"


@pytest.mark.parametrize(
    "subs,expected",
    [
        (None, "unknown"),
        (0, "unknown"),
        (9999, "small"),
        (10000, "small"),
        (10001, "large"),
    ],
)
def test_size_boundary_unknown_not_small(subs, expected):
    v = video(subs=subs)
    assert v["channel_class"] == expected
    assert (trend_score(v) is not None) == (expected == "small")
    assert (v["views_per_subscriber"] is None) == (expected == "unknown")


def test_channel_data_freshness_at_snapshot_and_custom_limit():
    v = video(fetched_at=90000)
    assert v["channel_class"] == "stale" and v["trend_score"] is None
    assert channel_class(video(), 1000) == "large"
    assert signal_metrics(video(subs=20000), 30000)["small_channel"]


def test_relative_rank_floor_noise_and_lifetime_not_current_growth():
    assert trend_score(video(subs=2000)) > trend_score(video(subs=10000))
    assert trend_score(video(subs=10)) == trend_score(video(subs=1000))
    assert trend_score(video(view_delta=1)) == 0
    assert trend_score(video(subs=1000000, view_delta=1000000)) is None
    v = video(views=1000000, view_delta=None, interval_hours=None, observed_vph=None)
    assert v["signal_status"] == "candidate" and v["candidate_score"] > 0
    assert v["trend_score"] is None
    assert video(views=5000, observed_vph=99)["signal_status"] == "measured"
    assert video(views=1000, observed_vph=100)["signal_status"] == "measured"
    assert video(views=2000, observed_vph=100)["signal_status"] == "breakout"
    assert video(correction=True)["signal_status"] == "correction"
    assert video(unavailable=True)["trend_score"] is None


def test_monitor_excludes_big_unknown_and_content_exclusions_but_retries_low_views():
    vs = [
        video("small"),
        video("same", channel_id="small", view_delta=5000),
        video("big", subs=20000),
        video("hidden", subs=None),
        video(
            "tiny",
            views=100,
            included=False,
            view_delta=None,
            interval_hours=None,
            growth_status="needs_snapshot",
            reasons=["Меньше минимального числа просмотров"],
        ),
        video(
            "excluded",
            included=False,
            growth_status="needs_snapshot",
            reasons=["Исключённое слово в названии"],
        ),
    ]
    assert set(select_monitor(vs, 50, 2000, 30)) == {"same", "tiny"}
    assert not select_monitor(
        [video("big", subs=20000, growth_status="needs_snapshot")], 50, 2000, 30
    )


def test_groups_need_two_small_channels_and_count_each_once():
    a, b = video("a"), video("b")
    big = video("big", subs=1000000, views=10000000)
    assert not group_videos([a, big])
    assert not group_videos([a, video("same", channel_id="a")])
    g = group_videos([a, b, big, video("dup", channel_id="a")])[0]
    assert g["channel_count"] == g["breakout_channels"] == 2
    assert "big" not in g["video_ids"]
    assert g["trend_score"] == trend_score(a)


class MixedPages(Pages):
    def get(self, url, params, headers, timeout):
        if url.endswith("/search"):
            self.calls.append("search")
            self.params.append(
                ("search", {k: v for k, v in params.items() if k != "key"})
            )
            stream = params["order"]
            page = int(params.get("pageToken", "0"))
            ids = ["shared", f"{stream}{page}"]
            return FakeResponse(
                {
                    "items": [{"id": {"videoId": v}} for v in ids],
                    "nextPageToken": str(page + 1),
                }
            )
        return super().get(url, params, headers, timeout)


@pytest.mark.parametrize(
    "depth,orders",
    [
        (50, ["date"]),
        (100, ["viewCount", "date"]),
        (200, ["viewCount", "viewCount", "date", "date"]),
    ],
)
def test_mixed_discovery_same_budget_pagination_and_id_dedup(tmp_path, depth, orders):
    s = Store(tmp_path / "radar.sqlite")
    s.initialize()
    t = MixedPages()
    cfg = ScanConfig(seeds=["query"], max_results=depth)
    ident = s.create_run(cfg, uuid.uuid4().hex)
    assert s.claim() == ident
    engine_with(t)(s, ident, "synthetic", threading.Event()).execute()
    assert s.run(ident)["status"] == "completed"
    search = [p for e, p in t.params if e == "search"]
    assert [p["order"] for p in search] == orders
    assert all(p["maxResults"] == 50 for p in search)
    if depth == 200:
        assert [p.get("pageToken") for p in search] == [None, "1", None, "1"]
    ids = [i for e, p in t.params if e == "videos" for i in p["id"].split(",")]
    assert len(ids) == len(set(ids)) == len(orders) + 1
    assert s.run(ident)["stats"]["search_calls"] == depth // 50
    assert s.queries(ident)[0]["pages_by_order"] == {
        order: orders.count(order) for order in set(orders)
    }
    before = len(t.params)
    append = s.create_run(cfg, uuid.uuid4().hex, "append", ident)
    s.claim()
    engine_with(t)(s, append, "synthetic", threading.Event()).execute()
    assert {p["order"] for e, p in t.params[before:] if e == "search"} == {"date"}


def test_focus_worker_offline_preserves_raw_history_snapshots_notes_ttl_and_quota(
    tmp_path,
):
    s = Store(tmp_path / "radar.sqlite")
    s.initialize()
    cfg = ScanConfig(seeds=["query"], max_subscribers=50000, order="viewCount")
    original = s.create_run(cfg, uuid.uuid4().hex)
    s.claim()
    engine_with(Pages())(s, original, "synthetic", threading.Event()).execute()
    s.note("a", True, "My idea")
    # One large, one small and one unknown channel in the stored sample.
    with s.connect() as conn:
        for ident, subs in [("a", 50000), ("b", 2000), ("c", None)]:
            row = conn.execute(
                "SELECT payload_json FROM app_run_videos WHERE run_id=? AND video_id=?",
                (original, ident),
            ).fetchone()
            v = json.loads(row[0])
            v["subs"] = subs
            conn.execute(
                "UPDATE app_run_videos SET payload_json=? WHERE run_id=? AND video_id=?",
                (json.dumps(v), original, ident),
            )

    def snapshot():
        with s.connect() as conn:
            return {
                table: [tuple(r) for r in conn.execute("SELECT * FROM " + table)]
                for table in ["app_video_snapshots", "app_notes", "app_run_queries"]
            }

    before = snapshot()
    original_videos = s.videos(original)
    quota = s.quota()
    with s.connect() as conn:
        source = [
            tuple(r)
            for r in conn.execute(
                "SELECT video_id,payload_json,expires_at FROM app_run_videos WHERE run_id=? ORDER BY video_id",
                (original,),
            )
        ]

    def forbidden(*args, **kwargs):
        pytest.fail("Local refilter must not create an API engine")

    app = create_app(tmp_path, MemoryVault(), forbidden)
    with TestClient(app) as client:
        client.get("/")
        body = {"request_id": uuid.uuid4().hex, "max_subscribers": 10000}
        url = f"/api/runs/{original}/focus"
        assert client.post(url, json=body).status_code == 403
        headers = {"X-CSRF-Token": app.state.csrf}
        result = client.post(url, json=body, headers=headers)
        assert result.status_code == 200
        latest = result.json()["id"]
        for _ in range(100):
            data = client.get(f"/api/runs/{latest}").json()
            if data["run"]["status"] not in {"queued", "running"}:
                break
            time.sleep(0.02)
        assert data["run"]["status"] == "completed"
        assert data["run"]["config"]["max_subscribers"] == 10000
        assert data["run"]["stats"]["network_requests"] == 0
        assert [v["video_id"] for v in data["videos"] if v["included"]] == ["b"]
        assert not data["groups"]
        assert not data["monitoring"]["enabled"]
        assert client.post(url, json=body, headers=headers).json()["id"] == latest
        assert (
            client.post(
                url, json={**body, "max_subscribers": 0}, headers=headers
            ).status_code
            == 422
        )
        for fmt in ["json", "csv", "md"]:
            exported = client.get(f"/api/runs/{latest}/export/{fmt}")
            assert exported.status_code == 200 and "2000" in exported.text
    assert snapshot() == before
    assert s.quota() == quota
    assert s.videos(original) == original_videos
    with s.connect() as conn:
        after = [
            tuple(r)
            for r in conn.execute(
                "SELECT video_id,payload_json,expires_at FROM app_run_videos WHERE run_id=? ORDER BY video_id",
                (original,),
            )
        ]
        inherited = [
            tuple(r)
            for r in conn.execute(
                "SELECT video_id,expires_at FROM app_run_videos WHERE run_id=? ORDER BY video_id",
                (latest,),
            )
        ]
    assert after == source
    assert inherited == [(r[0], r[2]) for r in source]
    assert [v["fetched_at"] for v in s.videos(latest)] == [
        v["fetched_at"] for v in original_videos
    ]
