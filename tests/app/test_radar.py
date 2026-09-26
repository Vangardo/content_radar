import concurrent.futures
import datetime as dt
import json
import threading
import time
import uuid
from zoneinfo import ZoneInfo

import pytest
import requests
from fastapi.testclient import TestClient

from app.engine_adapter import RadarClient
from app.main import create_app
from app.models import ScanConfig
from app.storage import Store
from app.worker import InstanceLock
from youtube_niche.cache import Cache
from youtube_niche.topics import radar_tokens
from youtube_niche.winners import _keyword_niches
from tests.app_support import FixtureTransport, MemoryVault, engine_with


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected live network request")

    monkeypatch.setattr(requests.Session, "request", forbidden)


@pytest.fixture
def store(tmp_path):
    obj = Store(tmp_path / "radar.sqlite")
    obj.initialize()
    return obj


def config(**kwargs):
    return ScanConfig(
        **{
            "name": "Тестовое исследование",
            "profile": "film",
            "language": "ru",
            "seeds": ["ИИ агенты"],
            "max_results": 50,
            **kwargs,
        }
    )


def scan(store, transport=None, cfg=None):
    transport = transport or FixtureTransport()
    ident = store.create_run(cfg or config(), uuid.uuid4().hex)
    store.claim()
    engine_with(transport)(store, ident, "test-secret-key", threading.Event()).execute()
    return ident, transport


@pytest.mark.parametrize(
    "profile,language",
    [(p, lang) for p in ("ai", "tech", "film") for lang in ("ru", "en")],
)
def test_profiles_work_without_optional_sources(store, profile, language, monkeypatch):
    import youtube_niche.llm as llm
    import youtube_niche.cli as cli

    monkeypatch.setattr(llm, "make_llm", lambda *a: pytest.fail("LLM called"))
    monkeypatch.setattr(
        cli, "analyze_topic", lambda *a, **k: pytest.fail("Scorer called")
    )
    ident, transport = scan(store, cfg=config(profile=profile, language=language))
    assert store.run(ident)["status"] == "completed"
    rows = store.videos(ident)
    assert len(rows) == 3 and sum(v["included"] for v in rows) == 2
    assert rows[0]["title"].startswith("ИИ агенты")
    assert rows[2]["views"] is None
    assert transport.calls == ["search", "videos", "channels"]
    assert store.queries(ident)[0]["scanned"] == 3  # not YouTube's estimated 100000
    assert store.queries(ident)[0]["has_more"]


def test_cached_runs_no_duplicate_snapshots_at_zero_budget(store):
    first, transport = scan(store)
    store.set_setting("budget", {"search_limit": 0, "unit_limit": 0})
    second, _ = scan(store, transport)
    assert store.run(second)["status"] == "completed"
    assert store.run(second)["stats"]["network_requests"] == 0
    assert (
        store.run(second)["stats"]["cache_reads"] == 2
    )  # channels reused from fresh normalized cache
    assert len(store.snapshots("fixture001")) == 1
    assert store.videos(first)[0]["fetched_at"] == store.videos(second)[0]["fetched_at"]
    assert store.videos(second)[0]["observed_vph"] is None


def test_refresh_no_search_actual_growth_and_original_run_immutable(store):
    first, transport = scan(store)
    with store.connect() as conn:
        conn.execute("UPDATE app_video_snapshots SET observed_at=observed_at-7200")
    original = store.videos(first)
    transport.views += 9000
    second = store.create_run(config(force=True), uuid.uuid4().hex, "refresh", first)
    store.claim()
    engine_with(transport)(store, second, "test", threading.Event()).execute()
    assert transport.calls.count("search") == 1
    assert len(store.snapshots("fixture001")) == 2
    fresh = store.videos(second)[0]
    assert fresh["observed_vph"] > 0
    assert fresh["interval_hours"] > 0
    assert store.videos(first) == original


def test_counter_correction_and_missing_stats(store):
    first, transport = scan(store)
    transport.views = 1000
    second, _ = scan(store, transport, config(force=True))
    video = store.videos(second)[0]
    assert video["correction"] and video["observed_vph"] is None


def test_partial_enrichment_survives_channel_quota(store):
    ident, _ = scan(store, FixtureTransport(failure="channels"))
    assert store.run(ident)["status"] == "waiting_quota"
    assert len(store.videos(ident)) == 3
    assert store.videos(ident)[0]["subs"] is None
    assert store.quota()["units_used"] == 2


@pytest.mark.parametrize(
    "empty,failure,status",
    [
        (True, None, "completed"),
        (False, "auth", "failed"),
        (False, "search", "waiting_quota"),
    ],
)
def test_empty_auth_and_quota_are_distinct(store, empty, failure, status):
    ident, _ = scan(store, FixtureTransport(empty=empty, failure=failure))
    assert store.run(ident)["status"] == status
    assert store.videos(ident) == []


def test_film_ru_and_versions_not_discarded(store):
    ident, _ = scan(store)
    assert store.videos(ident)[0]["included"]  # trailer, category 1 and Russian
    assert radar_tokens("GPT-5.1 и GPT-5.2 в 2026", "ru") == [
        "gpt-5.1",
        "gpt-5.2",
        "2026",
    ]
    assert "5" in radar_tokens("Модель 5", "ru")
    assert _keyword_niches(["ИИ агенты GPT-5.1", "ИИ агенты GPT-5.1"], 5, "ru")


def test_filters_keep_excluded_evidence(store):
    ident, _ = scan(store, cfg=config(excluded_categories=["1"]))
    assert not any(v["included"] for v in store.videos(ident))
    assert all(
        "Исключённая категория YouTube" in v["reasons"] for v in store.videos(ident)
    )


def test_idempotency_concurrent_clicks_and_recovery(store):
    request_id = uuid.uuid4().hex
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(lambda _: store.create_run(config(), request_id), range(4)))
    assert len(set(ids)) == 1
    assert store.create_run(config(), uuid.uuid4().hex) != ids[0]
    store.claim()
    store.recover()
    assert store.run(ids[0])["status"] == "interrupted"
    assert store.create_run(config(), request_id) == ids[0]


def test_cancel_before_network(store):
    ident = store.create_run(config(), uuid.uuid4().hex)
    store.cancel(ident)
    transport = FixtureTransport()
    engine_with(transport)(store, ident, "test", threading.Event()).execute()
    assert store.run(ident)["status"] == "cancelled"
    assert not transport.calls


def test_source_timestamp_does_not_reset_on_cache_read(tmp_path):
    cache = Cache(str(tmp_path / "cache.sqlite"))
    cache.set("key", {"value": 4})
    first = cache.get_entry("key")
    assert cache.get("key") == first[0]
    assert cache.get_entry("key")[1] == first[1]
    cache.close()


def test_purge_removes_api_data_preserves_notes_and_configs(store):
    ident, _ = scan(store)
    store.note("fixture001", True, "Моя независимая идея")
    with store.connect() as conn:
        for table in (
            "app_run_videos",
            "app_run_queries",
            "app_video_snapshots",
            "app_videos",
            "app_channels",
        ):
            conn.execute(f"UPDATE {table} SET expires_at=0")
        conn.execute("UPDATE kv SET ts=0")
        conn.execute("UPDATE app_runs SET data_expires_at=1")
    assert store.videos(ident) == []  # expired records hidden even before purge
    assert store.purge() > 0
    assert store.saved()[0]["note"] == "Моя независимая идея"
    assert store.run(ident)["config"]["seeds"] == ["ИИ агенты"]
    assert store.run(ident)["phrases"] == []
    with store.connect() as conn:
        assert conn.execute("SELECT count(*) FROM kv").fetchone()[0] == 0


def test_pacific_quota_day_dst(store):
    cache = Cache(str(store.path))
    client = RadarClient(
        None, cache, cache_only=True, quota_timezone="America/Los_Angeles"
    )
    assert (
        client._today()
        == dt.datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
    )
    for day in (
        dt.datetime(2026, 3, 8, tzinfo=ZoneInfo("America/Los_Angeles")),
        dt.datetime(2026, 11, 1, tzinfo=ZoneInfo("America/Los_Angeles")),
    ):
        next_day = dt.datetime.combine(
            day.date() + dt.timedelta(days=1), dt.time(), day.tzinfo
        )
        assert (next_day.timestamp() - day.timestamp()) / 3600 in (23, 25)
    client.session.close()
    cache.close()


def test_instance_lock_rejects_second_process_owner(tmp_path):
    first, second = InstanceLock(tmp_path / "lock"), InstanceLock(tmp_path / "lock")
    first.acquire()
    try:
        with pytest.raises(RuntimeError):
            second.acquire()
    finally:
        first.release()


def test_web_full_flow_secrets_exports_and_csrf(tmp_path):
    vault = MemoryVault()
    app = create_app(tmp_path, vault, engine_with(FixtureTransport()))
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        headers = {"X-CSRF-Token": app.state.csrf}
        key = "SyntheticTestKeyForOfflineTestsOnly123"
        assert client.put("/api/credential", json={"api_key": key}).status_code == 403
        assert (
            client.put(
                "/api/credential",
                headers={**headers, "Origin": "https://evil.example"},
                json={"api_key": key},
            ).status_code
            == 403
        )
        assert (
            client.put(
                "/api/credential", headers=headers, json={"api_key": key}
            ).status_code
            == 200
        )
        assert key not in client.get("/api/bootstrap").text
        invalid = client.put(
            "/api/credential", headers=headers, json={"api_key": {"secret": key}}
        )
        assert invalid.status_code == 422 and key not in invalid.text
        result = client.post(
            "/api/runs",
            headers=headers,
            json={"config": config().model_dump(), "request_id": uuid.uuid4().hex},
        )
        ident = result.json()["id"]
        for _ in range(100):
            result = client.get("/api/runs/" + ident).json()
            if result["run"]["status"] not in ("running", "queued"):
                break
            time.sleep(0.02)
        assert result["run"]["status"] == "completed"
        assert len(result["videos"]) == 3
        for route in ("/", "/history", "/settings", "/saved", "/runs/" + ident):
            page = client.get(route)
            assert page.status_code == 200
            assert key not in page.text
            assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
        client.put(
            "/api/videos/fixture001/note",
            headers=headers,
            json={"favorite": True, "text": '=HYPERLINK("bad")'},
        )
        for fmt in ("csv", "json", "md"):
            response = client.get(f"/api/runs/{ident}/export/{fmt}")
            assert response.status_code == 200 and key not in response.text
            if fmt == "csv":
                assert "'=HYPERLINK" in response.text
        assert client.get("/api/saved").json()[0]["favorite"]
        assert client.delete("/api/credential", headers=headers).status_code == 200
        assert vault.key is None
        assert key.encode() not in (tmp_path / "radar.sqlite").read_bytes()


def test_forbidden_sources_blocked(store):
    cache = Cache(str(store.path))
    client = RadarClient(None, cache, cache_only=True)
    with pytest.raises(Exception, match="sourceDisabled"):
        client._get("commentThreads", {}, 1)
    cache.close()


def test_retry_attempts_are_charged_and_secrets_are_not_reported(store, monkeypatch):
    import youtube_niche.youtube_client as module

    monkeypatch.setattr(module.time, "sleep", lambda _: None)

    class FailingTransport(FixtureTransport):
        def get(self, *args, **kwargs):
            raise requests.ConnectionError(
                "https://example.invalid?key=SHOULD_NOT_LEAK"
            )

    ident, _ = scan(store, FailingTransport())
    assert store.run(ident)["status"] == "failed"
    assert "SHOULD_NOT_LEAK" not in json.dumps(store.run(ident))
    assert store.quota()["search_used"] == 4
    assert store.run(ident)["stats"]["network_requests"] == 4


def test_cancellation_after_first_query_preserves_partial_data(store):
    ident = store.create_run(config(seeds=["first", "second"]), uuid.uuid4().hex)
    store.claim()
    transport = FixtureTransport()
    engine = engine_with(transport)(store, ident, "test", threading.Event())
    original = engine.collect

    def cancel_after_collect(*args):
        original(*args)
        store.cancel(ident)

    engine.collect = cancel_after_collect
    engine.execute()
    assert store.run(ident)["status"] == "cancelled"
    assert store.run(ident)["done"] == 1
    assert len(store.videos(ident)) == 3
    assert transport.calls.count("search") == 1


def test_pacific_day_does_not_follow_warsaw_midnight(store, monkeypatch):
    import youtube_niche.youtube_client as module

    real_datetime = dt.datetime

    class FrozenDateTime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            fixed = real_datetime(2026, 9, 24, 0, 30, tzinfo=dt.timezone.utc)
            return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)

    monkeypatch.setattr(module.dt, "datetime", FrozenDateTime)
    cache = Cache(str(store.path))
    client = RadarClient(
        None, cache, cache_only=True, quota_timezone="America/Los_Angeles"
    )
    assert client._today() == "2026-09-23"
    assert (
        store.quota()["reset_at"]
        == real_datetime(2026, 9, 24, 7, tzinfo=dt.timezone.utc).timestamp()
    )
    cache.close()


def test_saved_metrics_and_notes_survive_reopening_database(store):
    ident, _ = scan(store)
    store.note("fixture001", True, "Моя заметка")
    second = Store(store.path)
    second.initialize()
    saved = second.saved()[0]
    assert saved["note"] == "Моя заметка"
    assert saved["views_per_day"] > 0
    assert saved["subs"] == 2000
    assert second.run(ident)["status"] == "completed"


def test_expired_metadata_has_no_renderable_payload(store):
    ident, _ = scan(store)
    store.note("fixture001", True, "Оставить мою идею")
    with store.connect() as conn:
        conn.execute("UPDATE app_videos SET expires_at=0")
    saved = store.saved()[0]
    assert saved["title"] == "Данные видео удалены по сроку хранения"
    assert "views" not in saved
    assert saved["note"] == "Оставить мою идею"
