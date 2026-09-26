from youtube_niche.enrich import to_int

PUBLIC_CHANNEL_PARTS = "snippet,statistics,contentDetails,brandingSettings,topicDetails,status,localizations"


def channel_metadata(item, at):
    snippet, stats = item.get("snippet", {}), item.get("statistics", {})
    return {
        "id": item["id"],
        "title": snippet.get("title", ""),
        "description": snippet.get("description", ""),
        "custom_url": snippet.get("customUrl"),
        "published_at": snippet.get("publishedAt"),
        "country": snippet.get("country"),
        "subs": None
        if stats.get("hiddenSubscriberCount")
        else to_int(stats.get("subscriberCount")),
        "views": to_int(stats.get("viewCount")),
        "video_count": to_int(stats.get("videoCount")),
        "fetched_at": at,
        "metadata_version": 1,
        "youtube": item,
    }
