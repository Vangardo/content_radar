"""Public video metadata and conservative Shorts inference (API has no isShort)."""

import re

from youtube_niche.enrich import iso_duration_seconds, to_int


PUBLIC_VIDEO_PARTS = (
    "snippet,statistics,contentDetails,status,topicDetails,recordingDetails,"
    "liveStreamingDetails,localizations,paidProductPlacementDetails,player"
)


def video_format(video):
    """Only explicit player dimensions indicate aspect ratio; thumbnails do not."""
    raw = video.get("youtube", {})
    snippet = raw.get("snippet", {})
    duration = video.get("duration_s")
    published = video.get("published_at") or ""
    player = raw.get("player", {})
    width, height = to_int(player.get("embedWidth")), to_int(player.get("embedHeight"))
    kind, reason, candidate = "unknown", "Недостаточно данных о длительности", False
    if raw.get("liveStreamingDetails") or snippet.get("liveBroadcastContent") in {
        "live",
        "upcoming",
    }:
        kind, reason = "video", "Трансляция или запись трансляции"
    elif duration is not None and duration > 0:
        limit = 180 if published[:10] >= "2024-10-15" else 60
        if duration > 180 or (published and duration > limit):
            kind, reason = (
                "video",
                "Длительность превышает предел Shorts для даты публикации",
            )
        elif width and height and width > height:
            kind, reason = "video", "Горизонтальные пропорции видео"
        elif width and height and width <= height and (published or duration <= 60):
            kind, reason = (
                "shorts",
                "Вероятный Shorts: вертикальное или квадратное видео подходящей длительности",
            )
        else:
            candidate = True
            reason = (
                "Подходит по длительности; API не сообщил пропорции или дату публикации"
            )
    return {
        "video_format": kind,
        "format_reason": reason,
        "shorts_candidate": candidate,
    }


def matches_format(video, requested):
    fmt = video_format(video)
    if requested == "shorts":
        return fmt["video_format"] == "shorts" or fmt["shorts_candidate"]
    if requested == "videos":
        return fmt["video_format"] == "video"
    return True


def metadata(item, fetched_at):
    snippet, stats = item.get("snippet", {}), item.get("statistics", {})
    description = snippet.get("description", "")
    tags = snippet.get("tags", [])
    hashtags, seen = [], set()
    for tag in re.findall(
        r"(?<!\w)#[\w]+", snippet.get("title", "") + "\n" + description
    ):
        if tag.casefold() not in seen:
            seen.add(tag.casefold())
            hashtags.append(tag)
    video = {
        "metadata_version": 1,
        "video_id": item["id"],
        "title": snippet.get("title", ""),
        "description": description,
        "tags": tags,
        "hashtags": hashtags,
        "channel_id": snippet.get("channelId", ""),
        "channel_title": snippet.get("channelTitle", ""),
        "published_at": snippet.get("publishedAt"),
        "views": to_int(stats.get("viewCount")),
        "likes": to_int(stats.get("likeCount")),
        "comments": to_int(stats.get("commentCount")),
        "duration_s": iso_duration_seconds(
            item.get("contentDetails", {}).get("duration")
        ),
        "category_id": snippet.get("categoryId"),
        "lang": snippet.get("defaultAudioLanguage") or snippet.get("defaultLanguage"),
        "fetched_at": fetched_at,
        # Preserve the complete returned resource, including optional/unfamiliar fields.
        # This object never contains the request or its API key.
        "youtube": item,
    }
    return {**video, **video_format(video)}
