"""Persistent two-speed scheduling, run by the existing single worker."""

from __future__ import annotations

import math
import time

from .models import ScanConfig, ScheduleConfig
from .storage import ResearchDeleted
from .signals import trend_score, best_per_channel, channel_class, DEFAULT_SMALL_LIMIT


def select_monitor(videos, limit, now, minutes):
    eligible = [
        v
        for v in videos
        if now - v["fetched_at"] >= minutes * 60
        and channel_class(v, v.get("small_channel_limit", DEFAULT_SMALL_LIMIT))
        == "small"
        and not v.get("unavailable")
    ]
    # Low views need a second chance; explicit content exclusions do not.
    candidates = [
        v
        for v in eligible
        if v.get("growth_status") in {"needs_snapshot", "needs_interval"}
        and not set(v.get("reasons", []))
        - {
            "Меньше минимального числа просмотров",
            "Число просмотров недоступно",
        }
    ]
    leaders = list(
        best_per_channel(
            sorted(
                [
                    v
                    for v in eligible
                    if v.get("included") and trend_score(v) is not None
                ],
                key=lambda v: (trend_score(v), v["video_id"]),
                reverse=True,
            )
        )
    )[:limit]
    return list(dict.fromkeys(v["video_id"] for v in leaders + candidates))


class Scheduler:
    def __init__(self, store, vault):
        self.store, self.vault = store, vault

    def get(self, collection_id):
        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT * FROM app_schedules WHERE collection_id=?", (collection_id,)
            ).fetchone()
        return (
            dict(row)
            if row
            else {
                "collection_id": collection_id,
                **ScheduleConfig().model_dump(),
                "next_full": None,
                "next_monitor": None,
                "last_message": "Расписание выключено",
            }
        )

    def all(self):
        with self.store.connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM app_schedules WHERE collection_id NOT IN (SELECT collection_id FROM app_research_trash) ORDER BY MIN(next_full,next_monitor)"
                )
            ]

    def save(self, collection_id, config: ScheduleConfig, now=None):
        now = time.time() if now is None else now
        history = self.store.collection_runs(collection_id)
        if not history:
            raise ValueError("Исследование не найдено")
        last_full = next(
            (
                r
                for r in history
                if r["kind"] in {"discover", "repeat", "scheduled_full"}
                and r["status"] == "completed"
            ),
            None,
        )
        next_full = max(
            now,
            (last_full["ended_at"] if last_full else history[0]["created_at"])
            + config.full_hours * 3600,
        )
        videos = self.store.videos(history[0]["id"])
        next_monitor = max(
            now,
            min(
                (v["fetched_at"] + config.monitor_minutes * 60 for v in videos),
                default=now + config.monitor_minutes * 60,
            ),
        )
        # First due tick may be immediate; selection still enforces source age.
        with self.store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute(
                "SELECT 1 FROM app_research_trash WHERE collection_id=?",
                (collection_id,),
            ).fetchone():
                raise ResearchDeleted()
            conn.execute(
                """INSERT INTO app_schedules(collection_id,enabled,full_hours,monitor_minutes,top_limit,next_full,next_monitor,updated_at)
                VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(collection_id) DO UPDATE SET
                enabled=excluded.enabled,full_hours=excluded.full_hours,monitor_minutes=excluded.monitor_minutes,
                top_limit=excluded.top_limit,next_full=excluded.next_full,next_monitor=excluded.next_monitor,
                updated_at=excluded.updated_at,last_message=''""",
                (
                    collection_id,
                    int(config.enabled),
                    config.full_hours,
                    config.monitor_minutes,
                    config.top_limit,
                    next_full,
                    next_monitor,
                    now,
                ),
            )
        return self.get(collection_id)

    def update(self, ident, **fields):
        allowed = {"next_full", "next_monitor", "launched_run", "last_message"}
        if not fields or not fields.keys() <= allowed:
            raise ValueError("Unsupported schedule update")
        with self.store.connect() as conn:
            conn.execute(
                "UPDATE app_schedules SET "
                + ",".join(k + "=?" for k in fields)
                + " WHERE collection_id=?",
                (*fields.values(), ident),
            )

    def finish(self, schedule, run, now):
        fields = {"launched_run": None, "last_message": run["stage"]}
        key = "next_full" if run["kind"] == "scheduled_full" else "next_monitor"
        delay = (
            schedule["full_hours"] * 3600
            if key == "next_full"
            else schedule["monitor_minutes"] * 60
        )
        fields[key] = now + delay
        if run["status"] == "waiting_quota":
            fields[key] = max(now + 60, self.store.quota()["reset_at"])
        if run["kind"] == "scheduled_full" and run["status"] == "completed":
            fields["next_monitor"] = now + schedule["monitor_minutes"] * 60
        self.update(schedule["collection_id"], **fields)

    def tick(self, now=None):
        now = time.time() if now is None else now
        for s in self.all():
            if s["launched_run"]:
                run = self.store.run(s["launched_run"])
                if run and run["status"] in {"queued", "running"}:
                    continue
                if run:
                    self.finish(s, run, now)
                else:
                    self.update(s["collection_id"], launched_run=None)
                continue
            if not s["enabled"] or min(s["next_full"], s["next_monitor"]) > now:
                continue
            if any(r["status"] in {"queued", "running"} for r in self.store.runs()):
                return None
            history = self.store.collection_runs(s["collection_id"])
            if not history:
                continue
            latest = history[0]
            registry = getattr(self.store, "keys", None)
            credential = latest["config"].get("credential_id", "default")
            if not (
                registry.available(credential)
                if registry
                else self.vault.status()["configured"]
            ):
                self.update(
                    s["collection_id"],
                    next_monitor=now + 1800,
                    next_full=max(s["next_full"], now + 1800),
                    last_message="Нужен сохранённый ключ YouTube API",
                )
                continue
            quota = self.store.quota()
            full = s["next_full"] <= now
            search_cost = len(latest["config"]["seeds"]) * math.ceil(
                latest["config"]["max_results"] / 50
            )
            if full and (
                registry.blocked(credential, "search")
                if registry
                else search_cost > quota["search_limit"] - quota["search_used"]
            ):
                self.update(
                    s["collection_id"],
                    next_full=quota["reset_at"],
                    last_message="Поиск ждёт сброса квоты; замеры по ID продолжаются",
                )
                full = False
            if not full and s["next_monitor"] > now:
                continue
            selection = (
                None
                if full
                else select_monitor(
                    self.store.videos(latest["id"]),
                    s["top_limit"],
                    now,
                    s["monitor_minutes"],
                )
            )
            if not full and not selection:
                self.update(
                    s["collection_id"],
                    next_monitor=now + 60,
                    last_message="Нет подходящих малых каналов для замера сейчас; ожидаем следующий интервал или широкий пересмотр",
                )
                continue
            cost = 1 if full else math.ceil(len(selection) / 50)
            if (
                registry.blocked(credential, "videos")
                if registry
                else cost > quota["unit_limit"] - quota["units_used"]
            ):
                self.update(
                    s["collection_id"],
                    next_monitor=quota["reset_at"],
                    next_full=max(s["next_full"], quota["reset_at"]),
                    last_message="Замеры ждут сброса общей квоты",
                )
                continue
            kind = "scheduled_full" if full else "monitor"
            due = s["next_full"] if full else s["next_monitor"]
            request_id = f"schedule-{s['collection_id']}-{kind}-{int(due)}"
            try:
                ident = self.store.create_run(
                    ScanConfig(**{**latest["config"], "force": True}),
                    request_id,
                    kind,
                    latest["id"],
                    selection,
                )
            except ResearchDeleted:
                # A UI deletion can commit after this tick read the schedule.
                continue
            run = self.store.run(ident)
            if run["request_id"] == request_id:
                self.update(
                    s["collection_id"],
                    launched_run=ident,
                    last_message="Широкий поиск и пересмотр списка"
                    if full
                    else f"Замер {len(selection)} видео: лидеры и новые кандидаты",
                )
                return ident
        return None

    def summary(self, collection_id, videos):
        schedule = self.get(collection_id)
        now = time.time()
        selected = set(
            select_monitor(
                videos, schedule["top_limit"], now, schedule["monitor_minutes"]
            )
        )
        return {
            **schedule,
            "due_video_ids": sorted(selected),
            "active_video_ids": select_monitor(
                videos, schedule["top_limit"], float("inf"), schedule["monitor_minutes"]
            ),
            "candidate_count": len(
                select_monitor(videos, 0, float("inf"), schedule["monitor_minutes"])
            ),
        }
