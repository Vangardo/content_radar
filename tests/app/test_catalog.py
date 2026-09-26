# ruff: noqa: F811
# Imported pytest fixtures are intentionally reused by parameter name.
import time

import pytest

from app.access import AccessTokens
from app.entities import Entities
from tests.app.test_product import offline, setup  # noqa: F401
from tests.catalog_fixture import seed_catalog


def test_catalog_pages_dedup_sort_filters_and_no_youtube(setup):
    app, c, _h, transport = setup
    research = seed_catalog(app.state.store)
    before = list(transport.params)
    first = c.get("/api/posts").json()
    second = c.get("/api/posts?page=2").json()
    assert first["total"] == 63 and first["pages"] == 4
    assert len(first["items"]) == len(second["items"]) == 20
    assert {v["video_id"] for v in first["items"]}.isdisjoint(
        v["video_id"] for v in second["items"]
    )
    last = c.get("/api/posts?page=999").json()
    assert last["page"] == 4 and len(last["items"]) == 3
    for order in ("asc", "desc"):
        rows = c.get(f"/api/posts?sort=views&order={order}&per_page=100").json()[
            "items"
        ]
        assert [v["views"] for v in rows] == sorted(
            [v["views"] for v in rows], reverse=order == "desc"
        )
    assert c.get("/api/posts?format=shorts").json()["total"] == 31
    assert c.get("/api/posts?format=video").json()["total"] == 32
    assert c.get("/api/posts?scope=small").json()["total"] == 32
    assert c.get("/api/posts?scope=favorites").json()["total"] == 1
    assert c.get("/api/posts", params={"q": "#ПРЕМЬЕРА"}).json()["total"] == 63
    assert c.get("/api/posts?q=does-not-exist&page=90").json() == {
        "items": [],
        "page": 1,
        "per_page": 20,
        "pages": 1,
        "total": 0,
    }
    assert c.get("/api/posts", params={"research": research[0]}).json()["total"] == 63
    assert c.get("/api/posts", params={"research": research[-1]}).json()["total"] == 0
    assert not any(
        k in first["items"][0] for k in ("youtube", "description", "credential_id")
    )
    assert transport.params == before
    app.state.store.trash_research(research[0])
    assert c.get("/api/posts").json()["total"] == 63
    assert c.get("/api/posts", params={"research": research[0]}).json()["total"] == 0


def test_catalog_growth_matches_detail_and_nulls_remain_last(setup):
    app, c, _h, _t = setup
    seed_catalog(app.state.store, count=3, research_count=1)
    store = app.state.store
    with store.connect() as db:
        db.execute("DELETE FROM app_video_snapshots WHERE video_id='fixture-000'")
    for order in ("asc", "desc"):
        rows = c.get(f"/api/posts?sort=observed_vph&order={order}").json()["items"]
        assert rows[-1]["observed_vph"] is None
        for v in rows:
            detail = Entities(store).detail("videos", v["video_id"])["entity"]
            for field in (
                "observed_vph",
                "last_change",
                "interval_hours",
                "video_format",
            ):
                assert v[field] == detail[field]
    with store.connect() as db:
        db.execute("UPDATE app_channels SET fetched_at=?", (time.time() - 90000,))
        db.execute("UPDATE app_videos SET expires_at=0 WHERE id='fixture-002'")
    assert c.get("/api/posts?scope=small").json()["total"] == 0
    assert c.get("/api/posts").json()["total"] == 2


def test_catalog_owner_scope_and_read_only_api(setup):
    app, c, _h, _t = setup
    research = seed_catalog(app.state.store, count=2, research_count=1)
    with app.state.store.connect() as db:
        db.execute(
            "INSERT INTO app_users VALUES ('other','other','user',NULL,?,0)",
            (time.time(),),
        )
    access = AccessTokens(app.state.store)
    other = access.create("Other", "read", owner="other")
    headers = {"Authorization": "Bearer " + other["token"]}
    assert c.get("/api/v1/posts", headers=headers).json()["total"] == 0
    assert (
        c.get(
            "/api/v1/posts", params={"research": research[0]}, headers=headers
        ).json()["total"]
        == 0
    )
    reader = access.create("Reader", "read")
    assert (
        c.get(
            "/api/v1/posts", headers={"Authorization": "Bearer " + reader["token"]}
        ).json()["total"]
        == 2
    )
    assert c.get("/api/v1/posts").status_code == 401
    assert 'data-view="posts"' in c.get("/posts").text


@pytest.mark.parametrize(
    "query",
    [
        "page=0",
        "per_page=101",
        "per_page=-1",
        "sort=bad",
        "order=bad",
        "format=bad",
        "scope=bad",
    ],
)
def test_catalog_rejects_invalid_pagination_and_filters(setup, query):
    assert setup[1].get("/api/posts?" + query).status_code == 422
