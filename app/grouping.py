"""Conservative title groups, not semantic classification or trend predictions."""

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from statistics import median
from .signals import channel_class, DEFAULT_SMALL_LIMIT

ALIASES = json.loads(
    Path(__file__).with_name("topic_aliases.json").read_text(encoding="utf-8")
)
VERSION = (
    "titles-v2-small-"
    + hashlib.sha256(json.dumps(ALIASES, sort_keys=True).encode()).hexdigest()[:8]
)
GENERIC = {
    "кино",
    "фильм",
    "фильма",
    "фильмов",
    "новых",
    "новые",
    "новый",
    "сериал",
    "сериалы",
    "сериалов",
    "премьера",
    "русский",
    "трейлер",
    "обзор",
    "дубляж",
    "субтитры",
    "movie",
    "movies",
    "review",
    "trailer",
    "official",
    "new",
    "the",
    "of",
    "and",
    "для",
    "работы",
    "видео",
    "сцена",
    "сцены",
    "момент",
}


def normalized(text):
    return " ".join(re.findall(r"[\w]+(?:[.-]\d+)*", text.casefold().replace("ё", "е")))


def candidate(title):
    text = normalized(title)
    qualifiers = re.findall(
        r"\b(?:19|20)\d{2}\b|\b\d+\s+(?:сезон|часть)\b|\b(?:season|part)\s+\d+\b", text
    )
    suffix = " · ".join(sorted(set(qualifiers)))
    for label, aliases in ALIASES.items():
        if any(
            re.search(r"(?<!\w)" + re.escape(normalized(alias)) + r"(?!\w)", text)
            for alias in aliases
        ):
            # Do not merge video game gameplay with film reviews of a franchise.
            medium = (
                " · игра"
                if re.search(r"\b(gameplay|игра|игры|прохождение)\b", text)
                else ""
            )
            numbered = re.search(r"(?:resident evil|обитель зла)\s+(\d{1,2})\b", text)
            part = " · часть " + numbered[1] if numbered else ""
            return label + medium + part, suffix
    product = re.search(r"\bgpt[- ]?\d+(?:\.\d+)+\b", title, flags=re.I)
    if product:
        return product[0].upper(), suffix
    # Recognizable title boundaries; no fuzzy similarity or arbitrary n-gram merge.
    clean = re.sub(r"#\w+", "", title).strip()
    if "|" in clean:
        clean = clean.rsplit("|", 1)[-1].strip()
    clean = re.split(
        r"\s+[—–-]\s+|\b(?:русский|официальный|финальный)\s+(?:тизер[- ]?)?трейлер\b|\b(?:movie review|official trailer|обзор фильма)\b",
        clean,
        maxsplit=1,
        flags=re.I,
    )[0]
    clean = re.sub(r"\([^)]*\)|\[[^]]*\]", " ", clean)
    clean = re.sub(r"[«»\"“”]", "", clean).strip(" -—–")
    words = normalized(clean).split()
    meaningful = [w for w in words if w not in GENERIC and not w.isdigit()]
    if len(meaningful) < 2 or len(words) > 9:
        return None
    # Collections such as '10 новых фильмов' describe a format, not a work.
    if any(w in {"фильмов", "сериалов", "movies"} for w in words):
        return None
    return clean, suffix


def group_videos(videos):
    candidates, qualifiers = [], defaultdict(set)
    for video in videos:
        if video.get("included") is False or video.get("unavailable"):
            continue
        if (
            channel_class(video, video.get("small_channel_limit", DEFAULT_SMALL_LIMIT))
            != "small"
        ):
            continue
        item = candidate(video["title"])
        if item:
            label, suffix = item
            key = normalized(label)
            qualifiers[key].add(suffix)
            candidates.append((key, label, suffix, video))
    buckets, labels = defaultdict(list), {}
    for key, label, suffix, video in candidates:
        known = qualifiers[key] - {""}
        if not suffix and len(known) == 1:
            suffix = next(iter(known))
        group_key = (key, suffix)
        buckets[group_key].append(video)
        labels.setdefault(group_key, label + (" · " + suffix if suffix else ""))
    groups = []
    for key, members in buckets.items():
        channels = defaultdict(list)
        for v in members:
            if v.get("channel_id"):
                channels[v["channel_id"]].append(v)
        if len(channels) < 2:
            continue
        rates = [
            median(v["views_per_day"] for v in vs if v.get("views_per_day") is not None)
            for vs in channels.values()
            if any(v.get("views_per_day") is not None for v in vs)
        ]
        growth = [
            median(v["observed_vph"] for v in vs if v.get("observed_vph") is not None)
            for vs in channels.values()
            if any(v.get("observed_vph") is not None for v in vs)
        ]
        scores = [
            max(v["trend_score"] for v in vs if v.get("trend_score") is not None)
            for vs in channels.values()
            if any(v.get("trend_score") is not None for v in vs)
        ]
        groups.append(
            {
                "id": hashlib.sha256(repr(key).encode()).hexdigest()[:16],
                "title": labels[key],
                "video_ids": [v["video_id"] for v in members],
                "video_count": len(members),
                "channel_count": len(channels),
                "measured_channels": len(growth),
                "breakout_channels": sum(
                    any(v.get("signal_status") == "breakout" for v in vs)
                    for vs in channels.values()
                ),
                "trend_score": median(scores) if scores else None,
                "observed_vph": median(growth) if growth else None,
                "views_per_day": median(rates) if rates else None,
                "version": VERSION,
            }
        )
    return sorted(
        groups,
        key=lambda g: (
            -g["breakout_channels"],
            -(g["trend_score"] or 0),
            -g["channel_count"],
            -(g["views_per_day"] or 0),
            g["id"],
        ),
    )
