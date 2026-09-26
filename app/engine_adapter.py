"""Winners-first collection using upstream transport/enrichment, without its scorer."""

from __future__ import annotations

import datetime as dt
import time
from types import SimpleNamespace

from youtube_niche.auth import ApiKeyAuth
from youtube_niche.cache import Cache
from youtube_niche.enrich import enrich
from youtube_niche.winners import _keyword_niches
from youtube_niche.youtube_client import APIError, QuotaExceeded, YouTubeClient
from .models import ScanConfig
from .metrics import lifetime_metrics
from .storage import Store, dumps
from .video_metadata import PUBLIC_VIDEO_PARTS, matches_format, metadata
from .channel_metadata import PUBLIC_CHANNEL_PARTS


class Cancelled(Exception):
    pass


ERRORS = {
    "keyInvalid": "YouTube отклонил ключ. Проверьте YouTube Data API key в настройках.",
    "badRequest": "YouTube отклонил параметры запроса. Проверьте регион и поисковые запросы.",
    "accessNotConfigured": "В Google Cloud нужно включить YouTube Data API v3 для проекта ключа.",
    "ipRefererBlocked": "Ограничения API key не разрешают запросы с этого компьютера.",
    "forbidden": "Доступ к YouTube API запрещён. Проверьте настройки проекта и ключа.",
    "networkUnavailable": "Не удалось подключиться к YouTube. Проверьте интернет и повторите запуск.",
}


class RadarClient(YouTubeClient):
    registry = None
    credential_id = "default"
    video_format = "all"

    def __init__(self, *args, **kwargs):
        self.attempts = 0
        self.search_attempts = 0
        self.general_attempts = 0
        super().__init__(*args, **kwargs)

    def _get(self, endpoint, params, cost):
        if endpoint not in {"search", "videos", "channels"}:
            raise APIError("sourceDisabled")
        if endpoint == "search" and self.video_format == "shorts":
            # API "short" is <4 minutes, not an official Shorts classification.
            params = {**params, "videoDuration": "short"}
        try:
            return super()._get(endpoint, params, cost)
        except QuotaExceeded:
            if self.registry:
                self.registry.block(self.credential_id, endpoint)
            raise

    def _guard(self, endpoint, units):
        if not self.registry:
            return super()._guard(endpoint, units)
        if self.registry.blocked(self.credential_id, endpoint):
            raise QuotaExceeded("Project quota exhausted")

    def _charge(self, endpoint, units):
        super()._charge(endpoint, units)
        if self.registry:
            self.registry.charge(self.credential_id, endpoint, units)
        self.attempts += 1
        if endpoint == "search":
            self.search_attempts += 1
        else:
            self.general_attempts += 1

    def videos(self, ids):
        ids = sorted(set(ids))
        result = {}
        for start in range(0, len(ids), 50):
            response = self._get(
                "videos",
                {
                    "part": PUBLIC_VIDEO_PARTS,
                    "id": ",".join(ids[start : start + 50]),
                    "maxWidth": 720,
                },
                cost=1,
            )
            result.update({v["id"]: v for v in response.get("items", [])})
        return result

    def channels(self, ids):
        result = {}
        ids = sorted(set(ids))
        for start in range(0, len(ids), 50):
            response = self._get(
                "channels",
                {"part": PUBLIC_CHANNEL_PARTS, "id": ",".join(ids[start : start + 50])},
                cost=1,
            )
            result.update({v["id"]: v for v in response.get("items", [])})
        return result


def filter_reasons(video: dict, config: ScanConfig):
    reasons = []
    if not matches_format(video, config.video_format):
        reasons.append("Не соответствует выбранному формату видео")
    if video.get("views") is None:
        reasons.append("Число просмотров недоступно")
    elif video["views"] < config.min_views:
        reasons.append("Меньше минимального числа просмотров")
    if config.max_subscribers:
        if video.get("subs") is None or video["subs"] <= 0:
            reasons.append("Размер канала неизвестен")
        elif video["subs"] > config.max_subscribers:
            reasons.append("Канал больше заданного ограничения")
    duration = video.get("duration_s")
    if (config.min_duration or config.max_duration) and duration is None:
        reasons.append("Длительность неизвестна")
    elif duration is not None:
        if duration < config.min_duration:
            reasons.append("Видео короче заданного ограничения")
        if config.max_duration and duration > config.max_duration:
            reasons.append("Видео длиннее заданного ограничения")
    if str(video.get("category_id")) in config.excluded_categories:
        reasons.append("Исключённая категория YouTube")
    if any(
        word.casefold() in video["title"].casefold() for word in config.excluded_words
    ):
        reasons.append("Исключённое слово в названии")
    return reasons


class EngineAdapter:
    def __init__(
        self, store: Store, run_id: str, key: str, stop, client_type=RadarClient
    ):
        self.store, self.run_id, self.stop = store, run_id, stop
        self.run = store.run(run_id)
        self.config = ScanConfig(**self.run["config"])
        self.raw_videos, self.raw_channels, self.times = {}, {}, {}
        self.initial_ids = {v["video_id"] for v in store.videos(run_id)}
        self.seen_ids = set()
        self.attempted_ids = set()
        self.unavailable = set()
        self.cache_reads = 0
        self.query_errors = 0
        self.cache = Cache(str(store.path))
        budget = store.budget()
        self.client = client_type(
            ApiKeyAuth(key),
            self.cache,
            daily_quota=budget.unit_limit,
            reserve=0,
            daily_search_limit=budget.search_limit,
            verbose=False,
            endpoint_ttls={"search": 6 * 3600, "videos": 3600, "channels": 86400},
            force_endpoints=(
                {"videos"}
                if self.run["kind"] in {"refresh", "monitor"}
                else {"search", "videos"}
            )
            if self.config.force
            else set(),
            on_response=self.response,
            before_request=lambda _: self.check(),
            conservative_charge=True,
            quota_timezone="America/Los_Angeles",
        )
        self.client.registry = getattr(store, "keys", None)
        self.client.credential_id = self.config.credential_id
        self.client.video_format = self.config.video_format

    def check(self):
        if self.stop.is_set() or self.store.cancelled(self.run_id):
            raise Cancelled()

    def response(self, endpoint, params, data, fetched_at, cached, response_key):
        self.cache_reads += int(cached)
        self.times[endpoint] = (fetched_at, cached)
        self.store.save_response(endpoint, data, fetched_at, response_key)
        target = (
            self.raw_videos
            if endpoint == "videos"
            else self.raw_channels
            if endpoint == "channels"
            else None
        )
        if target is not None:
            for item in data.get("items", []):
                target[item["id"]] = (item, fetched_at, cached)

    def records(self, ids):
        # Reuse the same upstream normalizer even after partial enrichment failed.
        local = SimpleNamespace(
            videos=lambda ids: {
                i: self.raw_videos[i][0] for i in ids if i in self.raw_videos
            },
            channels=lambda ids: {
                i: self.raw_channels[i][0] for i in ids if i in self.raw_channels
            },
        )
        return enrich(
            local,
            [{"id": {"videoId": i}} for i in ids],
            SimpleNamespace(enrich_n=len(ids), preserve_unknown=True),
        )

    def persist_records(self, ids, query):
        for video in self.records(ids):
            raw, fetched_at, cached = self.raw_videos[video["video_id"]]
            video.update(metadata(raw, fetched_at))
            channel_time = self.raw_channels.get(
                video["channel_id"], (None, fetched_at)
            )[1]
            reasons = filter_reasons(video, self.config)
            video.update(
                {
                    "queries": [query] if query else [],
                    "fetched_at": fetched_at,
                    "channel_fetched_at": channel_time,
                    "cached": cached,
                    "reasons": reasons,
                    "included": not reasons,
                    **lifetime_metrics(video, fetched_at),
                    **self.store.growth(video["video_id"], fetched_at),
                }
            )
            self.store.save_video(self.run_id, video)

    def collect(self, ids, query):
        try:
            pending = [i for i in ids if i not in self.attempted_ids]
            if pending:
                self.client.videos(pending)
                self.attempted_ids.update(pending)
                self.unavailable.update(set(pending) - self.raw_videos.keys())
            channels = {
                self.raw_videos[i][0]["snippet"]["channelId"]
                for i in ids
                if i in self.raw_videos
            }
            for cid, (payload, fetched) in self.store.cached_channels(channels).items():
                if cid not in self.raw_channels:
                    self.raw_channels[cid] = (
                        {
                            "id": cid,
                            "snippet": {"title": payload["title"]},
                            "statistics": {"subscriberCount": payload["subs"]},
                        },
                        fetched,
                        True,
                    )
            # Monitoring spends only videos.list units. Channel metadata is reused
            # for at most 24h, then explicitly shown as unknown until a search.
            missing = channels - self.raw_channels.keys()
            if missing and self.run["kind"] not in {"refresh", "monitor"}:
                self.client.channels(list(missing))
        finally:
            # Fresh video responses survive even if a later channels request hits quota.
            self.persist_records(ids, query)

    def search_queries(self):
        # A cached search window keeps page boundaries and cache keys consistent.
        now = dt.datetime.now(dt.timezone.utc)
        lower = (now - dt.timedelta(days=self.config.days)).timestamp()
        upper = now.timestamp()
        pages = self.config.max_results // 50
        self.store.update_run(self.run_id, total=len(self.config.seeds) * pages)
        for query in self.config.seeds:
            self.check()
            start = (
                self.store.search_start(self.run_id, query, lower)
                if self.run["kind"] == "append"
                else lower
            )
            iso = lambda ts: (
                dt.datetime.fromtimestamp(ts, dt.timezone.utc)
                .isoformat()
                .replace("+00:00", "Z")
            )
            after = iso(start)
            window_key = self.cache.key(
                "radar",
                "search-window",
                {
                    "query": query,
                    "after": after
                    if self.run["kind"] == "append"
                    else self.config.days,
                    "language": self.config.language,
                    "video_format": self.config.video_format,
                    "region": self.config.region,
                    "order": "date"
                    if self.run["kind"] == "append"
                    else self.config.order,
                },
            )
            window = (
                None
                if self.config.force
                else self.cache.get(window_key, max_age=6 * 3600)
            )
            window_until = window["until"] if window else upper
            if window and "start" in window:
                after = iso(window["start"])
            if window is None:
                self.cache.set(window_key, {"until": window_until, "start": start})
            before = iso(window_until)
            found, source_times = set(), []
            if self.run["kind"] == "append":
                streams = [("date", pages)]
            elif self.config.order == "mixed":
                streams = (
                    [("viewCount", (pages + 1) // 2), ("date", pages // 2)]
                    if pages > 1
                    else [("date", 1)]
                )
            else:
                streams = [(self.config.order, pages)]
            continuations = {}
            report = {
                "video_format": self.config.video_format,
                "pages_by_order": {},
                "scanned": 0,
                "unique": 0,
                "new": 0,
                "known": 0,
                "duplicates": 0,
                "pages": 0,
                "search_calls": 0,
                "cached_pages": 0,
                "has_more": False,
                "finished": False,
                "window_until": window_until,
                "published_after": after,
            }
            calls_before = self.client.search_attempts
            source_at = upper
            try:
                for order, page_budget in streams:
                    token, tokens = None, set()
                    for page in range(page_budget):
                        self.check()
                        self.store.update_run(
                            self.run_id,
                            stage=f"Поиск: {query} · страница {page + 1}/{pages}",
                        )
                        result = self.client.search(
                            query,
                            max_results=50,
                            order=order,
                            published_after=after,
                            published_before=before,
                            region=self.config.region,
                            relevance_language=self.config.language,
                            page_token=token,
                        )
                        source_at, cached = self.times["search"]
                        source_times.append(source_at)
                        report["pages_by_order"][order] = (
                            report["pages_by_order"].get(order, 0) + 1
                        )
                        ids = list(
                            dict.fromkeys(
                                i["id"]["videoId"]
                                for i in result.get("items", [])
                                if i.get("id", {}).get("videoId")
                            )
                        )
                        report["scanned"] += len(result.get("items", []))
                        for vid in ids:
                            if vid not in found:
                                report[
                                    "known"
                                    if vid in self.initial_ids or vid in self.seen_ids
                                    else "new"
                                ] += 1
                            found.add(vid)
                            self.seen_ids.add(vid)
                        report["unique"] = len(found)
                        report["duplicates"] = report["scanned"] - len(found)
                        report["pages"] += 1
                        report["cached_pages"] += int(cached)
                        report["cached"] = report["cached_pages"] == report["pages"]
                        report["fetched_at"] = source_at
                        token = result.get("nextPageToken")
                        continuations[order] = bool(token)
                        report["has_more"] = any(continuations.values())
                        self.store.update_run(
                            self.run_id,
                            stage=f"Статистика: {query} · страница {page + 1}",
                        )
                        self.collect(ids, query)
                        self.done += 1
                        self.store.update_run(self.run_id, done=self.done)
                        if not token:
                            break
                        if token in tokens:
                            report["pagination_warning"] = (
                                "YouTube повторил указатель страницы; поиск остановлен."
                            )
                            break
                        tokens.add(token)
                report["finished"] = True
                # Never advance an incremental watermark from an old cached search.
                report["window_until"] = min([window_until] + source_times)
            finally:
                report["search_calls"] = self.client.search_attempts - calls_before
                report["fetched_at"] = source_at
                self.store.save_query(self.run_id, query, report, source_at)

    def execute(self):
        status, error = "completed", None
        self.done = 0
        try:
            self.check()
            if self.run["kind"] in {"refresh", "monitor"}:
                videos = self.store.videos(self.run_id)
                ids = self.run["selection"] or [v["video_id"] for v in videos]
                if not ids:
                    raise APIError("noSavedVideos")
                batches = [ids[i : i + 50] for i in range(0, len(ids), 50)]
                self.store.update_run(self.run_id, total=len(batches))
                for index, batch in enumerate(batches):
                    self.check()
                    self.store.update_run(
                        self.run_id,
                        stage=f"Обновление статистики · пакет {index + 1}/{len(batches)}",
                    )
                    self.collect(batch, "")
                    self.done += 1
                    self.store.update_run(self.run_id, done=self.done)
            else:
                if self.run["kind"] == "scheduled_full":
                    # Audit the entire retained pool before discovery. Late bloomers
                    # can return even when YouTube search no longer includes them.
                    ids = sorted(self.initial_ids)
                    for index in range(0, len(ids), 50):
                        self.check()
                        self.store.update_run(
                            self.run_id, stage="Пересмотр накопленного списка"
                        )
                        self.collect(ids[index : index + 50], "")
                self.search_queries()
            self.check()
        except Cancelled:
            status = "interrupted" if self.stop.is_set() else "cancelled"
            error = "Выполнение остановлено. Полученные данные сохранены."
        except QuotaExceeded:
            status, error = (
                "waiting_quota",
                "Лимит запросов исчерпан. Данные сохранены. При включённом расписании следующий цикл состоится после сброса квоты.",
            )
        except APIError as exc:
            status = "partial" if self.raw_videos else "failed"
            error = ERRORS.get(
                str(exc),
                "YouTube не вернул данные. Проверьте ключ, доступ к API и параметры. Полученные данные сохранены.",
            )
        except Exception as exc:
            status = "partial" if self.raw_videos else "failed"
            # Never stringify HTTP exceptions: request URLs may contain credentials.
            error = f"Не удалось завершить исследование ({type(exc).__name__}). Сохранённые данные доступны."
        finally:
            self.store.mark_unavailable(self.run_id, self.unavailable)
            videos = self.store.videos(self.run_id)
            included = [v for v in videos if v["included"]]
            phrases = (
                _keyword_niches([v["title"] for v in included], 8, self.config.language)
                if self.config.extract_phrases
                else []
            )
            self.store.update_run(
                self.run_id,
                status=status,
                error=error,
                ended_at=time.time(),
                done=self.done,
                stage={
                    "completed": "Исследование завершено",
                    "waiting_quota": "Ожидание квоты",
                    "cancelled": "Отменено",
                    "interrupted": "Прервано",
                    "partial": "Частичный результат",
                    "failed": "Не удалось завершить",
                }[status],
                phrases_json=dumps(phrases),
                stats_json=dumps(
                    {
                        "videos": len(videos),
                        "included": len(included),
                        "excluded": len(videos) - len(included),
                        "cache_reads": self.cache_reads,
                        "network_requests": self.client.attempts,
                        "search_calls": self.client.search_attempts,
                        "general_units": self.client.general_attempts,
                        "new_videos": len(
                            {v["video_id"] for v in videos} - self.initial_ids
                        ),
                        "updated_videos": len(self.raw_videos),
                        "unavailable_videos": len(self.unavailable),
                        "requested_videos": len(self.attempted_ids),
                        "completeness": "complete"
                        if status == "completed"
                        else "partial"
                        if videos
                        else "none",
                    }
                ),
            )
            self.client.session.close()
            self.cache.close()
