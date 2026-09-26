import json
import threading
import time
import uuid

import pytest

from app.access import AccessTokens
from app.changes import changes
from app.entities import Entities
from app.entity_worker import refresh_entities
from app.storage import ROOT, Store, RETENTION
from tests.app.test_product import setup, new, execute, offline  # noqa: F401
from tests.app_support import engine_with, FixtureTransport


def test_signed_changes_rates_null_zero_and_subsecond():
    fields = ("views", "likes", "comments")
    a = {"observed_at": 1000, "views": 100, "likes": 0, "comments": None}
    b = {"observed_at": 2800, "views": 90, "likes": 5, "comments": 4}
    result = changes([a, b], fields)
    assert result["metrics"]["views"] == {
        "value": 90,
        "previous": 100,
        "delta": -10,
        "percent": -10.0,
        "per_hour": -20,
    }
    assert result["metrics"]["likes"]["percent"] is None
    assert result["metrics"]["likes"]["per_hour"] == 10
    assert result["metrics"]["comments"]["delta"] is None
    assert changes([a], fields)["metrics"]["views"]["delta"] is None
    b["observed_at"] = 1000.5
    assert changes([a, b], fields)["short_interval"]
    assert changes([a, b], fields)["metrics"]["views"]["per_hour"] is None


def test_migration_preserves_old_channels_without_inventing_totals(tmp_path):
    s = Store(tmp_path / "migration.sqlite")
    at = time.time() - 3600
    with s.connect() as c:
        for path in sorted((ROOT / "migrations").glob("00[1-4]_*.sql")):
            c.executescript(path.read_text(encoding="utf-8"))
        c.execute(
            "INSERT INTO app_channels VALUES (?,?,?,?)",
            (
                "legacy",
                json.dumps({"id": "legacy", "title": "Old", "subs": 990}),
                at,
                at + RETENTION,
            ),
        )
    s.initialize()
    s.initialize()
    snapshots = Entities(s).channel_snapshots("legacy")
    assert len(snapshots) == 1 and snapshots[0]["subs"] == 990
    assert snapshots[0]["views"] is None and snapshots[0]["video_count"] is None


def prepare(setup):
    app, c, h, t = setup
    ident = new(c, h)
    execute(app, t)
    return app, c, h, t, ident, Entities(app.state.store)


def perform(app, t, entities):
    job = entities.claim()
    assert job
    refresh_entities(
        app.state.store, job, threading.Event(), engine_with(t).entity_client_type
    )
    return entities.job(job["id"])


def test_channel_detail_history_cache_missing_and_asof(setup):
    app, c, h, t, ident, e = prepare(setup)
    channel = e.channels()[0]["id"]
    now = time.time()
    raw = {
        "id": channel,
        "snippet": {"title": "Channel", "description": "<b>untrusted</b>"},
        "statistics": {
            "subscriberCount": "2100",
            "viewCount": "100000",
            "videoCount": "25",
        },
    }
    app.state.store.save_response("channels", {"items": [raw]}, now, "one")
    app.state.store.save_response("channels", {"items": [raw]}, now, "cached")
    raw["statistics"].update(
        subscriberCount="2090", viewCount="101000", videoCount="24"
    )
    app.state.store.save_response("channels", {"items": [raw]}, now + 1800, "two")
    earlier = e.channel_snapshots(channel, now)
    assert len(earlier) == 2  # first synthetic discovery + first full metadata
    changes_now = e.detail("channels", channel)["entity"]["last_change"]
    assert changes_now["metrics"]["subs"]["delta"] == -10
    assert changes_now["metrics"]["views"]["per_hour"] == 2000
    assert changes_now["metrics"]["video_count"]["delta"] == -1
    raw["statistics"]["hiddenSubscriberCount"] = True
    app.state.store.save_response("channels", {"items": [raw]}, now + 3600, "hidden")
    assert e.detail("channels", channel)["entity"]["subs"] is None
    assert (
        e.detail("channels", channel)["entity"]["last_change"]["metrics"]["subs"][
            "delta"
        ]
        is None
    )
    assert c.get("/api/entities/channels/" + channel).status_code == 200


def test_exact_video_refresh_quota_and_immutable_research(setup):
    app, c, h, t, ident, e = prepare(setup)
    original = app.state.store.videos(ident)
    t.views += 100
    before = len(t.calls)
    response = c.post(
        "/api/entities/videos/refresh",
        headers=h,
        json={"ids": ["a"], "request_id": "specific-video-123"},
    )
    assert response.status_code == 200, response.text
    job = perform(app, t, e)
    assert job["status"] == "completed" and job["result"]["updated"] == 1
    assert job["result"]["general_units"] == 1 and job["result"]["search_calls"] == 0
    assert t.calls[before:] == ["videos"]
    assert app.state.store.videos(ident) == original
    assert e.detail("videos", "a")["entity"]["views"] == t.views
    again = c.post(
        "/api/entities/videos/refresh",
        headers=h,
        json={"ids": ["a"], "request_id": "specific-video-123"},
    )
    assert again.json()["id"] == job["id"]
    assert e.claim() is None


def test_favorites_and_channel_refresh_really_bypass_cache(setup):
    app, c, h, t, ident, e = prepare(setup)
    channel = e.channels()[0]["id"]
    r = c.put(
        "/api/entities/channels/" + channel + "/note",
        headers=h,
        json={"favorite": True, "text": "keep"},
    )
    assert r.status_code == 200
    before = len(t.params)
    response = c.post(
        "/api/entities/channels/refresh", headers=h, json={"favorites": True}
    )
    assert response.status_code == 200, response.text
    result = perform(app, t, e)
    assert result["status"] == "completed" and result["result"]["updated"] == 1
    assert [ep for ep, p in t.params[before:]] == ["channels"]
    p = t.params[-1][1]
    assert p["id"] == channel and "brandingSettings" in p["part"]
    assert len(e.channel_snapshots(channel)) == 2
    assert e.detail("channels", channel)["entity"]["note"] == "keep"
    app.state.store.note("a", True, "a note")
    app.state.store.note("b", False, "note only")
    response = c.post(
        "/api/entities/videos/refresh", headers=h, json={"favorites": True}
    )
    assert response.status_code == 200
    job = perform(app, t, e)
    assert job["ids"] == ["a"]


def test_job_dedup_conflicting_request_and_owner_access(setup):
    app, c, h, t, ident, e = prepare(setup)
    body = {"ids": ["a"], "request_id": "dedup-refresh-123"}
    one = c.post("/api/entities/videos/refresh", headers=h, json=body).json()["id"]
    two = c.post(
        "/api/entities/videos/refresh",
        headers=h,
        json={**body, "request_id": "another-request-123"},
    ).json()["id"]
    assert one == two
    assert (
        c.post(
            "/api/entities/videos/refresh", headers=h, json={**body, "ids": ["b"]}
        ).status_code
        == 400
    )
    assert (
        c.post(
            "/api/entities/videos/refresh", headers=h, json={"ids": ["not-owned"]}
        ).status_code
        == 404
    )
    assert c.post("/api/entities/videos/refresh", json=body).status_code == 403
    assert (
        c.post("/api/entities/search/refresh", headers=h, json=body).status_code == 422
    )
    with app.state.store.connect() as db:
        db.execute(
            "INSERT INTO app_users VALUES ('other','other','user',NULL,?,0)",
            (time.time(),),
        )
    other = AccessTokens(app.state.store).create("Other", "write", owner="other")
    auth = {"Authorization": "Bearer " + other["token"]}
    assert c.get("/api/v1/entities/channels", headers=auth).json() == {"channels": []}
    assert c.get("/api/v1/entities/videos/a", headers=auth).status_code == 404
    assert c.get("/api/v1/entities/jobs/" + one, headers=auth).status_code == 404
    assert (
        c.post("/api/v1/entities/videos/refresh", headers=auth, json=body).status_code
        == 404
    )
    reader = AccessTokens(app.state.store).create("Reader", "read")
    assert (
        c.post(
            "/api/v1/entities/videos/refresh",
            headers={"Authorization": "Bearer " + reader["token"]},
            json=body,
        ).status_code
        == 403
    )


def test_missing_and_quota_do_not_zero_old_values(setup):
    app, c, h, t, ident, e = prepare(setup)
    old = e.detail("videos", "a")["entity"]["views"]
    t.missing = {"a"}
    e.enqueue("videos", ["a"], "default", uuid.uuid4().hex)
    job = perform(app, t, e)
    assert job["status"] == "partial" and job["result"]["missing"] == ["a"]
    assert e.detail("videos", "a")["entity"]["views"] == old
    t.missing = set()
    t.failure = "videos"
    e.enqueue("videos", ["a"], "default", uuid.uuid4().hex)
    job = perform(app, FixtureTransport(failure="videos"), e)
    assert job["status"] == "waiting_quota"
    assert e.detail("videos", "a")["entity"]["views"] == old


def test_purge_preserves_favorite_identity_and_recovery(setup):
    app, c, h, t, ident, e = prepare(setup)
    channel = e.channels()[0]["id"]
    e.channel_note(channel, True, "saved")
    e.enqueue("channels", [channel], "default", "recover-refresh-123")
    e.claim()
    app.state.store.recover()
    with app.state.store.connect() as db:
        assert (
            db.execute("SELECT status FROM app_entity_jobs").fetchone()[0]
            == "interrupted"
        )
        db.execute("UPDATE app_channels SET expires_at=0")
        db.execute("UPDATE app_channel_snapshots SET expires_at=0")
        db.execute("UPDATE app_entity_refs SET last_seen=0")
    app.state.store.purge()
    assert e.detail("channels", channel)["entity"]["expired"]
    assert e.detail("channels", channel)["snapshots"] == []
    assert e.favorites("channels") == [channel]


def test_batch_refresh_51_channels_costs_two_and_protects_active_key(setup):
    app, c, h, t, ident, e = prepare(setup)
    ids = [f"batch-channel-{i}" for i in range(51)]
    for channel in ids:
        e.link("channels", channel, "default", time.time())
    r = c.post("/api/entities/channels/refresh", headers=h, json={"ids": ids})
    assert r.status_code == 200 and r.json()["estimated_units"] == 2
    assert c.delete("/api/keys/default", headers=h).status_code == 409
    assert c.delete("/api/credential", headers=h).status_code == 409
    before = len(t.params)
    job = perform(app, t, e)
    assert job["status"] == "completed" and job["result"]["updated"] == 51
    assert job["result"]["general_units"] == 2
    calls = t.params[before:]
    assert [ep for ep, _ in calls] == ["channels", "channels"]
    assert [len(p["id"].split(",")) for _, p in calls] == [50, 1]
    assert all(len(e.channel_snapshots(channel)) == 1 for channel in ids)


def test_migration_backfills_owned_channel_and_video_refs(setup):
    app, c, h, t, ident, e = prepare(setup)
    with app.state.store.connect() as db:
        for table in (
            "app_research_trash",
            "app_entity_refs",
            "app_entity_jobs",
            "app_channel_notes",
            "app_channel_snapshots",
        ):
            db.execute(f"DROP TABLE {table}")
        db.execute("UPDATE app_meta SET value='4' WHERE key='schema_version'")
    app.state.store.initialize()
    assert e.reference("videos", "a")["credential_id"] == "default"
    assert e.reference("channels", "channela")["owner_id"] == "admin"
    assert len(e.channels()) == 2
