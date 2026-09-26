"""Read-only, owned video catalog. Pagination never calls YouTube."""

import json
import math
import time
from collections import defaultdict
from typing import Literal

from fastapi import Query, Request

from .metrics import growth_metrics, lifetime_metrics
from .video_metadata import video_format

Sort = Literal[
    "observed_vph",
    "views",
    "likes",
    "comments",
    "views_per_subscriber",
    "published_at",
    "fetched_at",
    "title",
    "subs",
]


def video_catalog(
    store,
    owner,
    *,
    page=1,
    per_page=20,
    q="",
    sort="observed_vph",
    order="desc",
    format="all",
    scope="all",
    research="",
):
    now = time.time()
    with store.connect() as c:
        # Keep totals and their observation history consistent during a worker update.
        c.execute("BEGIN")
        # Canonical IDs are unique even when many research snapshots contain a video.
        records = c.execute(
            """SELECT v.id,v.payload_json,v.fetched_at,
                      ch.payload_json AS channel_json,ch.fetched_at AS channel_at,
                      COALESCE(n.favorite,0) AS favorite,COALESCE(n.text,'') AS note
               FROM app_videos v JOIN app_entity_refs e
                 ON e.entity_id=v.id AND e.kind='videos' AND e.owner_id=?
               LEFT JOIN app_channels ch
                 ON ch.id=json_extract(v.payload_json,'$.channel_id') AND ch.expires_at>?
               LEFT JOIN app_notes n ON n.video_id=v.id AND ?='admin'
               WHERE v.expires_at>? AND (?='' OR EXISTS (
                 SELECT 1 FROM app_run_videos rv JOIN app_runs r ON r.id=rv.run_id
                 JOIN app_research re ON re.id=r.collection_id
                 WHERE rv.video_id=v.id AND re.id=? AND re.owner_id=?
                   AND rv.expires_at>? AND re.id NOT IN
                     (SELECT collection_id FROM app_research_trash)))""",
            (owner, now, owner, now, research, research, owner, now),
        ).fetchall()
        # Batch observations instead of issuing several database queries for every row.
        snapshots = defaultdict(list)
        for r in c.execute(
            """SELECT s.video_id,s.observed_at,s.views,s.likes,s.comments
               FROM app_video_snapshots s JOIN app_videos v ON v.id=s.video_id
               JOIN app_entity_refs e ON e.entity_id=v.id AND e.kind='videos'
               WHERE e.owner_id=? AND v.expires_at>? AND s.expires_at>?
                 AND s.observed_at<=v.fetched_at ORDER BY s.observed_at DESC""",
            (owner, now, now),
        ):
            snapshots[r["video_id"]].append(r)
    rows = []
    query = q.strip().casefold()
    for r in records:
        payload = json.loads(r["payload_json"])
        channel = json.loads(r["channel_json"]) if r["channel_json"] else {}
        # A stale channel total must not assert that an author is still small.
        subs = channel.get("subs") if (r["channel_at"] or 0) >= now - 86400 else None
        fmt = video_format(payload)
        if format == "shorts" and not (
            fmt["video_format"] == "shorts" or fmt["shorts_candidate"]
        ):
            continue
        if format in {"video", "unknown"} and fmt["video_format"] != format:
            continue
        if scope == "small" and (subs is None or subs > 10000):
            continue
        if scope == "favorites" and not r["favorite"]:
            continue
        if (
            query
            and query
            not in " ".join(
                str(payload.get(k) or "")
                for k in (
                    "title",
                    "channel_title",
                    "description",
                    "tags",
                    "hashtags",
                )
            ).casefold()
        ):
            continue
        # Large raw metadata/descriptions are available in the existing detail endpoint.
        item = {
            k: payload.get(k)
            for k in (
                "title",
                "channel_id",
                "channel_title",
                "published_at",
                "views",
                "likes",
                "comments",
                "duration_s",
            )
        }
        item.update(
            video_id=r["id"],
            fetched_at=r["fetched_at"],
            subs=subs,
            favorite=bool(r["favorite"]),
            note=r["note"],
            **fmt,
        )
        item["views_per_subscriber"] = (
            item["views"] / subs
            if item["views"] is not None and subs and subs > 0
            else None
        )
        item.update(lifetime_metrics(item, r["fetched_at"]))
        item.update(growth_metrics(snapshots[r["id"]]))
        rows.append(item)
    # Missing values stay last in both directions, with a deterministic ID tie-breaker.
    rows.sort(key=lambda v: v["video_id"])
    present = [v for v in rows if v.get(sort) is not None]
    missing = [v for v in rows if v.get(sort) is None]
    present.sort(
        key=lambda v: v[sort].casefold() if isinstance(v[sort], str) else v[sort],
        reverse=order == "desc",
    )
    rows = present + missing
    total = len(rows)
    pages = max(1, math.ceil(total / per_page))
    page = min(page, pages)
    return {
        "items": rows[(page - 1) * per_page : page * per_page],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": pages,
    }


def install_catalog(app, store):
    @app.get("/api/posts")
    @app.get("/api/v1/posts")
    def posts(
        request: Request,
        page: int = Query(1, ge=1),
        per_page: int = Query(20, ge=1, le=100),
        q: str = Query("", max_length=300),
        sort: Sort = "observed_vph",
        order: Literal["asc", "desc"] = "desc",
        format: Literal["all", "shorts", "video", "unknown"] = "all",
        scope: Literal["all", "small", "favorites"] = "all",
        research: str = Query("", max_length=64),
    ):
        return video_catalog(
            store,
            getattr(request.state, "owner_id", "admin"),
            page=page,
            per_page=per_page,
            q=q,
            sort=sort,
            order=order,
            format=format,
            scope=scope,
            research=research,
        )
