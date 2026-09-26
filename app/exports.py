import csv
import io
import json
from html import escape
from urllib.parse import quote
from .monitoring import trend_score


def export_run(run, videos, queries, format, groups=None):
    videos = [{**v, "trend_score": trend_score(v)} for v in videos]
    rows = [
        {
            "title": v["title"],
            "description": v.get("description"),
            "tags": json.dumps(v["tags"], ensure_ascii=False) if "tags" in v else None,
            "hashtags": " ".join(v.get("hashtags", [])),
            "duration_s": v.get("duration_s"),
            "video_format": v.get("video_format"),
            "format_reason": v.get("format_reason"),
            "shorts_candidate": v.get("shorts_candidate"),
            "language": v.get("lang"),
            "url": "https://www.youtube.com/watch?v=" + quote(v["video_id"], safe=""),
            "channel": v.get("channel_title"),
            "views": v.get("views"),
            "likes": v.get("likes"),
            "comments": v.get("comments"),
            "previous_observed_at": v.get("last_change", {}).get("from_at"),
            "last_interval_hours": v.get("last_change", {}).get("interval_hours"),
            "last_view_delta": v.get("last_change", {})
            .get("metrics", {})
            .get("views", {})
            .get("delta"),
            "last_like_delta": v.get("last_change", {})
            .get("metrics", {})
            .get("likes", {})
            .get("delta"),
            "last_comment_delta": v.get("last_change", {})
            .get("metrics", {})
            .get("comments", {})
            .get("delta"),
            "like_delta": v.get("like_delta"),
            "comment_delta": v.get("comment_delta"),
            "engagement_interval_hours": v.get("engagement_interval_hours"),
            "subscribers": v.get("subs"),
            "small_channel_limit": v.get("small_channel_limit"),
            "channel_class": v.get("channel_class"),
            "views_per_subscriber": v.get("views_per_subscriber"),
            "signal_status": v.get("signal_status"),
            "candidate_score": v.get("candidate_score"),
            "published_at": v.get("published_at"),
            "fetched_at": v.get("fetched_at"),
            "views_per_day": v.get("views_per_day"),
            "observed_views_per_hour": v.get("observed_vph"),
            "trend_score": v.get("trend_score"),
            "interval_hours": v.get("interval_hours"),
            "view_delta": v.get("view_delta"),
            "growth_status": v.get("growth_status"),
            "inherited": v.get("inherited", False),
            "group": "; ".join(
                g["title"] for g in (groups or []) if v["video_id"] in g["video_ids"]
            ),
            "included": v.get("included"),
            "queries": "; ".join(v.get("queries", [])),
            "exclusions": "; ".join(v.get("reasons", [])),
            "favorite": v.get("favorite"),
            "note": v.get("note", ""),
        }
        for v in videos
    ]
    if format == "json":
        return json.dumps(
            {"run": run, "queries": queries, "videos": videos, "groups": groups or []},
            ensure_ascii=False,
            indent=2,
        ), "application/json"
    if format == "csv":
        stream = io.StringIO(newline="")
        fields = list(rows[0]) if rows else ["title", "url", "views", "fetched_at"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            # Spreadsheet cells must not execute titles/notes as formulas.
            writer.writerow(
                {
                    k: "'" + v
                    if isinstance(v, str)
                    and v.lstrip().startswith(("=", "+", "-", "@"))
                    else v
                    for k, v in row.items()
                }
            )
        return "\ufeff" + stream.getvalue(), "text/csv"
    lines = [
        "# Topic Radar",
        "",
        escape(run["config"]["name"]),
        "",
        "Выборка YouTube Data API. Просмотры/день — среднее за жизнь, не измеренный суточный рост.",
        "",
    ]
    for row in rows:
        title = (
            row["title"]
            .replace("\n", " ")
            .replace("[", "\\[")
            .replace("]", "\\]")
            .replace("<", "&lt;")
        )
        lines.extend(
            [
                f"- [{title}]({row['url']})",
                f"  Просмотры: {row['views']}; канал: {escape(row['channel'] or '')}; источник (Unix UTC): {row['fetched_at']}",
                f"  Подписчики: {row['subscribers']}; просмотры/подписчики: {row['views_per_subscriber']}; сигнал: {row['signal_status']}; рейтинг роста: {row['trend_score']}",
                f"  Средний темп с публикации: {row['views_per_day']}; измеренный прирост/час: {row['observed_views_per_hour']}; интервал (ч): {row['interval_hours']}",
                f"  Формат: {row['video_format']}; {escape(row['format_reason'] or '')}; длительность: {row['duration_s']} с",
                f"  Лайки: {row['likes']}; комментарии: {row['comments']}; прирост: {row['like_delta']} / {row['comment_delta']}; интервал (ч): {row['engagement_interval_hours']}",
                f"  Теги: {escape(row['tags'] or '')}; хэштеги: {escape(row['hashtags'])}",
                "  Описание:\n"
                + "\n".join(
                    "    " + escape(line)
                    for line in (row["description"] or "").splitlines()
                ),
                "",
            ]
        )
    return "\n".join(lines), "text/markdown"
