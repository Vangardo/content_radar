import datetime as dt
from itertools import pairwise

from .changes import changes


def lifetime_metrics(video, fetched_at):
    """Use source time, never the later time at which a cached result is viewed."""
    try:
        published = dt.datetime.fromisoformat(
            video["published_at"].replace("Z", "+00:00")
        ).timestamp()
        days = max(0, (fetched_at - published) / 86400)
    except (ValueError, AttributeError, KeyError):
        days = None
    return {
        "age_days": days,
        "views_per_day": video["views"] / days
        if video.get("views") is not None and days and days > 0
        else None,
    }


def growth_metrics(snapshots):
    """Measured growth from retained observations, newest first."""
    rows = sorted(snapshots, key=lambda r: r["observed_at"], reverse=True)
    result = {
        "last_change": changes(rows, ("views", "likes", "comments")),
        "observed_vph": None,
        "interval_hours": None,
        "correction": False,
        "growth_status": "needs_snapshot",
        "view_delta": None,
        "like_delta": None,
        "comment_delta": None,
        "engagement_interval_hours": None,
    }
    if rows:
        previous = next(
            (r for r in rows[1:] if rows[0]["observed_at"] - r["observed_at"] >= 1800),
            None,
        )
        if previous is not None:
            result["engagement_interval_hours"] = (
                rows[0]["observed_at"] - previous["observed_at"]
            ) / 3600
            for field, output in (
                ("likes", "like_delta"),
                ("comments", "comment_delta"),
            ):
                if rows[0][field] is not None and previous[field] is not None:
                    result[output] = rows[0][field] - previous[field]
    if not rows or rows[0]["views"] is None:
        return {**result, "growth_status": "unknown"}
    if len(rows) < 2:
        return result
    # Match the shortest supported monitoring interval; shorter clicks aren't growth.
    baseline = next(
        (
            i
            for i, r in enumerate(rows[1:], 1)
            if rows[0]["observed_at"] - r["observed_at"] >= 1800
            and r["views"] is not None
        ),
        None,
    )
    segment = rows[: baseline + 1] if baseline else rows
    known = [r["views"] for r in segment if r["views"] is not None]
    if any(a < b for a, b in pairwise(known)):
        return {**result, "correction": True, "growth_status": "correction"}
    if baseline is None:
        return {**result, "growth_status": "needs_interval"}
    hours = (rows[0]["observed_at"] - rows[baseline]["observed_at"]) / 3600
    delta = rows[0]["views"] - rows[baseline]["views"]
    return {
        **result,
        "observed_vph": delta / hours if hours > 0 and delta >= 0 else None,
        "interval_hours": hours,
        "correction": delta < 0,
        "growth_status": "measured",
        "view_delta": delta,
    }
