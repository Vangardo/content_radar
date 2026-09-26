import csv
import io
import json
import time

import pytest

from app.access import AccessTokens
from app.exports import export_run
from app.models import ScanConfig
from app.monitoring import select_monitor
from app.video_metadata import metadata, video_format
from tests.app.test_collections import no_network, run, store  # noqa: F401
from tests.app.test_product import setup, new, execute  # noqa: F401
from tests.app_support import MetadataPages


@pytest.mark.parametrize(
    "seconds,published,player,kind,candidate",
    [
        (
            180,
            "2026-09-24",
            {"embedWidth": "405", "embedHeight": "720"},
            "shorts",
            False,
        ),
        (
            180,
            "2026-09-24",
            {"embedWidth": "720", "embedHeight": "720"},
            "shorts",
            False,
        ),
        (
            181,
            "2026-09-24",
            {"embedWidth": "405", "embedHeight": "720"},
            "video",
            False,
        ),
        (30, "2026-09-24", {"embedWidth": "720", "embedHeight": "405"}, "video", False),
        (61, "2024-10-14", {"embedWidth": "405", "embedHeight": "720"}, "video", False),
        (
            60,
            "2024-10-14",
            {"embedWidth": "405", "embedHeight": "720"},
            "shorts",
            False,
        ),
        (
            61,
            "2024-10-15",
            {"embedWidth": "405", "embedHeight": "720"},
            "shorts",
            False,
        ),
        (90, "2026-09-24", {}, "unknown", True),
        (
            30,
            "2026-09-24",
            {"embedHtml": '<iframe width="405" height="720"></iframe>'},
            "unknown",
            True,
        ),
        (None, "2026-09-24", {}, "unknown", False),
        (0, "2026-09-24", {}, "unknown", False),
        (100, "", {"embedWidth": "405", "embedHeight": "720"}, "unknown", True),
    ],
)
def test_format_is_conservative(seconds, published, player, kind, candidate):
    v = {
        "duration_s": seconds,
        "published_at": published,
        "youtube": {"player": player},
    }
    result = video_format(v)
    assert result["video_format"] == kind
    assert result["shorts_candidate"] is candidate


def test_live_and_thumbnail_shape_are_not_shorts():
    v = {
        "duration_s": 30,
        "published_at": "2026-09-24",
        "youtube": {"snippet": {"thumbnails": {"high": {"width": 100, "height": 200}}}},
    }
    assert video_format(v)["video_format"] == "unknown"
    v["youtube"]["liveStreamingDetails"] = {"actualStartTime": "2026-09-24T00:00:00Z"}
    assert video_format(v)["video_format"] == "video"


def test_metadata_keeps_raw_optional_fields_and_distinguishes_missing_zero():
    raw = {
        "id": "v",
        "snippet": {"title": "#КИНО", "description": "#Кино #Shorts", "tags": ["tag"]},
        "statistics": {"commentCount": "0"},
        "topicDetails": {"topicIds": ["example"]},
    }
    v = metadata(raw, 100)
    assert v["youtube"] == raw and v["hashtags"] == ["#КИНО", "#Shorts"]
    assert v["likes"] is None and v["views"] is None and v["comments"] == 0
    assert "tags" not in metadata({"id": "v"}, 100)["youtube"]


def test_search_shorts_filters_cache_and_monitoring(store):
    t = MetadataPages()
    first = run(store, t, video_format="all")
    before = len(t.params)
    shorts = run(store, t, video_format="shorts")
    assert store.run(shorts)["status"] == "completed"
    searches = [p for e, p in t.params[before:] if e == "search"]
    assert len(searches) == 2 and all(p["videoDuration"] == "short" for p in searches)
    videos = {v["video_id"]: v for v in store.videos(shorts)}
    assert videos["a"]["included"] and not videos["b"]["included"]
    assert videos["c"]["shorts_candidate"] and videos["c"]["included"]
    assert set(select_monitor(list(videos.values()), 50, time.time() + 1801, 30)) == {
        "a",
        "c",
    }
    assert all("description" in v and "youtube" in v for v in videos.values())
    assert all(
        p["maxWidth"] == 720
        and "player" in p["part"]
        and "fileDetails" not in p["part"]
        for e, p in t.params
        if e == "videos"
    )
    assert store.queries(shorts)[0]["video_format"] == "shorts"
    cached = run(store, t, video_format="shorts")
    assert store.run(cached)["stats"]["network_requests"] == 0
    assert len(store.snapshots("a")) == 1
    ordinary = run(store, t, video_format="videos")
    assert [v["video_id"] for v in store.videos(ordinary) if v["included"]] == ["b"]
    # Changing format must not advance append from the previous format's window.
    append = store.create_run(
        ScanConfig(seeds=["query"], video_format="shorts"),
        "append-format-123",
        "append",
        first,
    )
    assert store.search_start(append, "query", 12) == 12


def test_engagement_history_is_bounded_nullable_and_keeps_corrections(store):
    now = time.time()
    for offset, views, likes, comments in [
        (-3600, 1000, "50", "10"),
        (-1800, 1200, "49", None),
        (0, 1400, "80", "15"),
    ]:
        item = {
            "id": "v",
            "statistics": {
                "viewCount": views,
                "likeCount": likes,
                "commentCount": comments,
            },
        }
        store.save_response("videos", {"items": [item]}, now + offset, str(offset))
    g = store.growth("v", now - 1800)
    assert g["like_delta"] == -1 and g["comment_delta"] is None
    assert g["engagement_interval_hours"] == 0.5
    assert len(store.snapshots("v", now - 1800)) == 2
    assert store.snapshots("v", now - 1800)[-1]["comments"] is None
    assert store.growth("v", now)["like_delta"] == 31
    assert store.growth("v", now)["comment_delta"] is None
    assert store.growth("v", now - 3600)["like_delta"] is None


def test_old_metadata_is_immutable_after_refresh_and_exports_roundtrip(store):
    t = MetadataPages()
    first = run(store, t)
    old = store.videos(first)[0]
    refreshed = run(store, t, first, "refresh", force=True)
    assert store.videos(first)[0]["youtube"] == old["youtube"]
    v = store.videos(refreshed)[0]
    v["description"] = "=1+1\nmultiline, text"
    v["tags"] = ["a,b", '"tag"']
    config = store.run(refreshed)
    exported, _ = export_run(config, [v], [], "json")
    assert json.loads(exported)["videos"][0]["youtube"] == v["youtube"]
    exported, _ = export_run(config, [v], [], "csv")
    row = next(csv.DictReader(io.StringIO(exported.lstrip("\ufeff"))))
    assert row["description"] == "'=1+1\nmultiline, text"
    assert json.loads(row["tags"]) == v["tags"] and int(row["comments"]) == 32
    exported, _ = export_run(config, [v], [], "md")
    assert "multiline, text" in exported and "комментарии: 32" in exported


def test_detail_api_owner_scope_and_snapshot_boundary(setup):
    app, c, h, _ = setup
    t = MetadataPages()
    ident = new(c, h)
    execute(app, t)
    store = app.state.store
    observed = store.videos(ident)[0]["fetched_at"]
    store.save_response(
        "videos",
        {"items": [{"id": "a", "statistics": {"viewCount": "999999"}}]},
        observed + 100,
        "later",
    )
    reader = AccessTokens(store).create("Reader", "read")
    auth = {"Authorization": "Bearer " + reader["token"]}
    response = c.get(f"/api/v1/research/{ident}/videos/a", headers=auth)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["video"]["description"].startswith("Описание")
    assert len(data["snapshots"]) == 1 and "likes" in data["snapshots"][0]
    assert len(c.get(f"/api/videos/a/snapshots?run_id={ident}").json()) == 1
    assert (
        c.get(f"/api/v1/research/{ident}/videos/foreign", headers=auth).status_code
        == 404
    )
    assert c.get("/api/videos/a/snapshots?run_id=unknown").status_code == 404
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO app_users VALUES ('other','other','user',NULL,?,0)",
            (time.time(),),
        )
    token = AccessTokens(store).create("other", "read", owner="other")
    assert (
        c.get(
            f"/api/v1/research/{ident}/videos/a",
            headers={"Authorization": "Bearer " + token["token"]},
        ).status_code
        == 404
    )
