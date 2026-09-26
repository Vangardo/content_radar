"""Synthetic multi-page catalog, shared by offline tests and visual preview."""

import json
import time
import uuid

from app.entities import Entities
from app.models import ScanConfig
from app.video_metadata import metadata


def seed_catalog(store, count=63, research_count=23):
    at = time.time() - 60
    research = []
    for i in range(research_count):
        ident = store.create_run(
            ScanConfig(name=f"Исследование {i + 1:02d}", seeds=["cinema"], min_views=0),
            uuid.uuid4().hex,
        )
        store.update_run(
            ident,
            status="completed",
            ended_at=at,
            stats_json=json.dumps({"videos": count}),
        )
        research.append(ident)
    entities = Entities(store)
    channels, videos = [], []
    for i in range(count):
        channel = f"fixture-channel-{i:03d}"
        channels.append(
            {
                "id": channel,
                "snippet": {"title": f"Канал {i + 1:02d}"},
                "statistics": {
                    "subscriberCount": str(500 + i * 300),
                    "viewCount": str(10000 + i * 1000),
                    "videoCount": "30",
                },
            }
        )
        entities.link("channels", channel, "default", at)
        item = {
            "id": f"fixture-{i:03d}",
            "snippet": {
                "title": f"Видео {i + 1:02d} · Премьеры кино",
                "channelId": channel,
                "channelTitle": f"Канал {i + 1:02d}",
                "description": "Подробное описание #премьера",
                "tags": ["cinema"],
                "publishedAt": "2026-09-23T12:00:00Z",
            },
            "statistics": {
                "viewCount": str(1000 + i * 100),
                "likeCount": str(i + 2),
                "commentCount": str(i),
            },
            "contentDetails": {"duration": "PT45S" if i % 2 else "PT10M"},
            "player": {"embedWidth": "1080", "embedHeight": "1920"},
        }
        videos.append(item)
        entities.link("videos", item["id"], "default", at)
    store.save_response("channels", {"items": channels}, at - 3600, "fixture-before")
    store.save_response("channels", {"items": channels}, at, "fixture-now")
    store.save_response("videos", {"items": videos}, at - 3600, "fixture-before")
    for i, item in enumerate(videos):
        item["statistics"]["viewCount"] = str(1500 + i * 200)
    store.save_response("videos", {"items": videos}, at, "fixture-now")
    for item in videos:
        payload = {
            **metadata(item, at),
            "queries": ["cinema"],
            "subs": 2000,
            "channel_fetched_at": at,
            "included": True,
            "reasons": [],
        }
        store.save_video(research[0], payload)
        if research_count > 1:
            store.save_video(research[1], payload.copy())
    store.note(videos[0]["id"], True, "Сохранённая идея")
    return research
