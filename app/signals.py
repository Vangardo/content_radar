"""Explainable small-channel signals. No historical audience estimate or prediction."""

import math

DEFAULT_SMALL_LIMIT = 10_000
SUBSCRIBER_FLOOR = 1_000
MIN_SIGNAL_VPH = 100
MIN_SIGNAL_VIEWS = 1_000
CHANNEL_MAX_AGE = 86400


def channel_class(video, limit=DEFAULT_SMALL_LIMIT):
    subs = video.get("subs")
    source = video.get("channel_fetched_at")
    fetched = video.get("fetched_at")
    if subs is None or subs <= 0:
        return "unknown"
    if (
        source is not None
        and fetched is not None
        and fetched - source > CHANNEL_MAX_AGE
    ):
        return "stale"
    return "small" if subs <= limit else "large"


def trend_score(video):
    limit = video.get("small_channel_limit", DEFAULT_SMALL_LIMIT)
    if channel_class(video, limit) != "small" or video.get("included") is False:
        return None
    delta, hours = video.get("view_delta"), video.get("interval_hours")
    if (
        delta is None
        or hours is None
        or hours < 0.5
        or video.get("unavailable")
        or video.get("correction")
    ):
        return None
    conservative_vph = max(0, delta - 2 * math.sqrt(max(0, delta))) / hours
    return conservative_vph * 1000 / max(video["subs"], SUBSCRIBER_FLOOR)


def signal_metrics(video, limit=DEFAULT_SMALL_LIMIT):
    kind = channel_class(video, limit)
    subs, views, days = video.get("subs"), video.get("views"), video.get("age_days")
    ratio = views / subs if kind in {"small", "large"} and views is not None else None
    score = trend_score({**video, "small_channel_limit": limit})
    lifetime_score = None
    if (
        kind == "small"
        and views is not None
        and days is not None
        and not video.get("unavailable")
        and video.get("included") is not False
    ):
        # First-snapshot ordering is explicitly provisional, with a 1h age floor.
        lifetime_score = views / max(days * 24, 1) * 1000 / max(subs, SUBSCRIBER_FLOOR)
    if video.get("unavailable"):
        status = "unavailable"
    elif kind != "small":
        status = kind
    elif video.get("included") is False:
        status = "excluded"
    elif video.get("correction"):
        status = "correction"
    elif score is None:
        status = "candidate"
    elif (video.get("observed_vph") or 0) >= MIN_SIGNAL_VPH and (views or 0) >= max(
        subs, MIN_SIGNAL_VIEWS
    ):
        status = "breakout"
    else:
        status = "measured"
    return {
        "small_channel_limit": limit,
        "channel_class": kind,
        "small_channel": kind == "small",
        "views_per_subscriber": ratio,
        "trend_score": score,
        "candidate_score": lifetime_score,
        "signal_status": status,
        "signal_version": "small-v1",
    }


def best_per_channel(videos):
    seen = set()
    for video in videos:
        channel = video.get("channel_id") or video["video_id"]
        if channel not in seen:
            seen.add(channel)
            yield video
