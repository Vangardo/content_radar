"""Monitor-facing API and personal-token integration surface."""

import time
import uuid
from collections import defaultdict
from statistics import median
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field, SecretStr

from .grouping import group_videos
from .models import ScanConfig, ScheduleConfig
from .signals import best_per_channel


CATEGORIES = {
    "1": "Кино и анимация",
    "2": "Автомобили",
    "10": "Музыка",
    "15": "Животные",
    "17": "Спорт",
    "19": "Путешествия",
    "20": "Игры",
    "22": "Люди и блоги",
    "23": "Юмор",
    "24": "Развлечения",
    "25": "Новости и политика",
    "26": "Советы и стиль",
    "27": "Образование",
    "28": "Наука и технологии",
    "29": "Общество и благотворительность",
}


class NewResearch(BaseModel):
    config: ScanConfig
    request_id: str = Field(
        default_factory=lambda: uuid.uuid4().hex, pattern=r"^[a-zA-Z0-9-]{8,80}$"
    )
    monitor: bool = False
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)


class KeyInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    project_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    api_key: SecretStr


class KeyMetadata(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    project_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")


class TokenInput(BaseModel):
    name: str = Field(default="MCP Hub", min_length=1, max_length=80)
    scope: Literal["read", "write"] = "read"
    days: int = Field(default=90, ge=1, le=365)


class Action(BaseModel):
    kind: Literal["refresh", "repeat", "append"] = "refresh"
    request_id: str = Field(
        default_factory=lambda: uuid.uuid4().hex, pattern=r"^[a-zA-Z0-9-]{8,80}$"
    )


def install_product(app, store, keys, tokens, worker, auth):
    def owner(request):
        return getattr(request.state, "owner_id", "admin")

    def owned(ident, request):
        run = store.run(ident)
        if run:
            ident = run["collection_id"]
        with store.connect() as c:
            r = c.execute(
                "SELECT * FROM app_research WHERE id=? AND owner_id=?",
                (ident, owner(request)),
            ).fetchone()
        if not r:
            raise HTTPException(404, "Исследование не найдено")
        if store.research_deleted(ident):
            raise HTTPException(
                410, "Исследование в корзине. Сначала восстановите его."
            )
        return store.collection_runs(ident)[0]

    def check_key(ident, request):
        try:
            keys.metadata(ident, owner(request))
            if not keys.available(ident):
                raise ValueError("Добавьте или выберите доступный API-ключ")
        except ValueError as e:
            raise HTTPException(400, str(e)) from None

    def results(latest):
        videos = store.videos(latest["id"])
        return {
            "run": latest,
            "videos": videos,
            "groups": group_videos(videos)
            if latest["config"].get("extract_phrases", True)
            else [],
            "monitoring": worker.scheduler.summary(latest["collection_id"], videos),
        }

    @app.get("/api/v1/research/{ident}/videos/{video_id}")
    def research_video(ident: str, video_id: str, request: Request):
        latest = owned(ident, request)
        video = next(
            (v for v in store.videos(latest["id"]) if v["video_id"] == video_id), None
        )
        if video is None:
            raise HTTPException(404, "Видео не найдено в исследовании")
        return {
            "video": video,
            "snapshots": store.snapshots(video_id, video["fetched_at"]),
        }

    @app.get("/api/research")
    @app.get("/api/v1/research")
    def research_list(request: Request):
        with store.connect() as c:
            ids = [
                r[0]
                for r in c.execute(
                    "SELECT id FROM app_research WHERE owner_id=? AND id NOT IN (SELECT collection_id FROM app_research_trash) ORDER BY created_at DESC",
                    (owner(request),),
                )
            ]
        rows = []
        for ident in ids:
            latest = store.collection_runs(ident)[0]
            vs = store.videos(latest["id"])
            small = [
                v
                for v in vs
                if v["small_channel"] and v["included"] and not v.get("unavailable")
            ]
            ranked = sorted(
                small,
                key=lambda v: (
                    v["trend_score"] is not None,
                    v["trend_score"] or v["candidate_score"] or 0,
                ),
                reverse=True,
            )
            schedule = worker.scheduler.get(ident)
            rows.append(
                {
                    "id": ident,
                    "latest_id": latest["id"],
                    "name": latest["config"]["name"],
                    "config": latest["config"],
                    "status": latest["status"],
                    "error": latest["error"],
                    "created_at": latest["created_at"],
                    "last_observed_at": max(
                        (v["fetched_at"] for v in vs), default=None
                    ),
                    "videos": len(vs),
                    "small_videos": len(small),
                    "channels": len({v["channel_id"] for v in small}),
                    "breakouts": sum(v["signal_status"] == "breakout" for v in small),
                    "leaders": list(best_per_channel(ranked))[:3],
                    "schedule": schedule,
                    "is_monitor": schedule["next_full"] is not None,
                }
            )
        return {"research": rows}

    @app.get("/api/research/trash")
    @app.get("/api/v1/research/trash")
    def research_trash(request: Request):
        return {"research": store.research_trash(owner(request))}

    @app.delete("/api/research/{ident}")
    @app.delete("/api/v1/research/{ident}")
    def research_delete(ident: str, request: Request):
        try:
            collection = store.trash_research(ident, owner(request))
        except ValueError as e:
            raise HTTPException(404, str(e)) from None
        worker.wake.set()
        return {"id": collection, "deleted": True}

    @app.post("/api/research/{ident}/restore")
    @app.post("/api/v1/research/{ident}/restore")
    def research_restore(ident: str, request: Request):
        try:
            collection = store.trash_research(ident, owner(request), restore=True)
        except ValueError as e:
            raise HTTPException(404, str(e)) from None
        return {"id": collection, "deleted": False}

    @app.post("/api/research")
    @app.post("/api/v1/research")
    def research_create(body: NewResearch, request: Request):
        if body.config.credential_id == "default" and not keys.available("default"):
            available = [
                k
                for k in keys.list()
                if k["configured"] and k["enabled"] and k["owner_id"] == owner(request)
            ]
            if len(available) == 1:
                body.config = body.config.model_copy(
                    update={"credential_id": available[0]["id"]}
                )
        check_key(body.config.credential_id, request)
        if (
            body.config.max_duration
            and body.config.max_duration < body.config.min_duration
        ):
            raise HTTPException(422, "Проверьте длительность")
        try:
            ident = store.create_run(
                body.config, body.request_id, owner_id=owner(request)
            )
        except ValueError as e:
            raise HTTPException(409, str(e)) from None
        if body.monitor and worker.scheduler.get(ident)["next_full"] is None:
            worker.scheduler.save(
                ident, body.schedule.model_copy(update={"enabled": True})
            )
        worker.wake.set()
        return {"id": ident, "url": "/runs/" + ident}

    @app.get("/api/v1/research/{ident}")
    def research_result(ident: str, request: Request):
        return results(owned(ident, request))

    @app.post("/api/research/{ident}/actions")
    @app.post("/api/v1/research/{ident}/actions")
    def research_action(ident: str, body: Action, request: Request):
        run = owned(ident, request)
        config = ScanConfig(**{**run["config"], "force": True})
        check_key(config.credential_id, request)
        if body.kind == "refresh" and not store.videos(run["id"]):
            raise HTTPException(400, "Сначала выполните поиск")
        try:
            ident = store.create_run(
                config, body.request_id, body.kind, run["id"], owner_id=owner(request)
            )
        except ValueError as e:
            raise HTTPException(409, str(e)) from None
        worker.wake.set()
        return {"id": ident}

    @app.put("/api/research/{ident}/schedule")
    @app.put("/api/v1/research/{ident}/schedule")
    def research_schedule(ident: str, body: ScheduleConfig, request: Request):
        run = owned(ident, request)
        if body.enabled:
            check_key(run["config"].get("credential_id", "default"), request)
        result = worker.scheduler.save(run["collection_id"], body)
        worker.wake.set()
        return result

    @app.put("/api/research/{ident}/config")
    @app.put("/api/v1/research/{ident}/config")
    def research_config(ident: str, body: ScanConfig, request: Request):
        run = owned(ident, request)
        check_key(body.credential_id, request)
        if run["status"] in {"running", "queued"}:
            raise HTTPException(409, "Дождитесь завершения операции")
        ident = store.create_run(
            body, uuid.uuid4().hex, "refilter", run["id"], owner_id=owner(request)
        )
        worker.wake.set()
        return {"id": ident}

    @app.get("/api/research/{ident}/chart")
    @app.get("/api/v1/research/{ident}/chart")
    def research_chart(
        ident: str,
        request: Request,
        kind: Literal["videos", "channels", "topics"] = "videos",
        run_id: str | None = None,
    ):
        run = owned(ident, request)
        if run_id:
            historical = store.run(run_id)
            if not historical or historical["collection_id"] != run["collection_id"]:
                raise HTTPException(404, "Снимок не найден")
            run = historical
        vs = [
            v
            for v in store.videos(run["id"])
            if v["small_channel"] and v["included"] and not v.get("unavailable")
        ]
        vs.sort(
            key=lambda v: (
                v["trend_score"] is not None,
                v["trend_score"] or v["candidate_score"] or 0,
            ),
            reverse=True,
        )
        groups = group_videos(vs) if run["config"].get("extract_phrases", True) else []
        buckets = defaultdict(list)
        for v in vs:
            if kind == "videos":
                buckets[(v["video_id"], v["title"])].append(v)
            elif kind == "channels":
                buckets[(v["channel_id"], v["channel_title"])].append(v)
            else:
                for g in groups:
                    if v["video_id"] in g["video_ids"]:
                        buckets[(g["id"], g["title"])].append(v)
        series = []
        for (ident, label), members in list(buckets.items())[:5]:
            points = defaultdict(dict)
            for v in members:
                snapshots = [
                    s
                    for s in store.snapshots(v["video_id"])
                    if s["views"] is not None and s["observed_at"] <= v["fetched_at"]
                ]
                for index in range(max(0, len(snapshots) - 100), len(snapshots)):
                    snapshot = snapshots[index]
                    ts = snapshot["observed_at"]
                    baseline = next(
                        (
                            j
                            for j in range(index - 1, -1, -1)
                            if ts - snapshots[j]["observed_at"] >= 1800
                        ),
                        None,
                    )
                    if baseline is not None and all(
                        snapshots[j]["views"] >= snapshots[j - 1]["views"]
                        for j in range(baseline + 1, index + 1)
                    ):
                        rate = (snapshot["views"] - snapshots[baseline]["views"]) / (
                            (ts - snapshots[baseline]["observed_at"]) / 3600
                        )
                        x = ts if kind == "videos" else int(ts // 600) * 600
                        points[x][v["video_id"]] = (v["channel_id"], rate)
            data = []
            for ts, observations in sorted(points.items()):
                channels = defaultdict(list)
                for cid, value in observations.values():
                    channels[cid].append(value)
                data.append(
                    {
                        "at": ts,
                        "value": median(median(values) for values in channels.values()),
                        "video_count": len(observations),
                    }
                )
            series.append({"id": ident, "label": label, "points": data})
        return {
            "kind": kind,
            "unit": "просмотров/час",
            "aggregation": "Каждая точка — измеренный темп. Для каналов и тем: медиана наблюдаемых видео по каналам в 10-минутном окне, не весь трафик канала.",
            "series": series,
        }

    @app.get("/api/categories")
    def categories():
        return CATEGORIES

    @app.get("/api/keys")
    def list_keys():
        return keys.list()

    @app.get("/api/v1/credentials")
    def credential_names(request: Request):
        return [
            {
                k: row[k]
                for k in (
                    "id",
                    "name",
                    "project_id",
                    "configured",
                    "enabled",
                    "search_used",
                    "units_used",
                    "search_blocked",
                    "general_blocked",
                )
            }
            for row in keys.list()
            if row["owner_id"] == owner(request)
        ]

    @app.post("/api/keys")
    def add_key(body: KeyInput):
        try:
            first = not keys.metadata("default")["fingerprint"] and not keys.available(
                "default"
            )
            ident = keys.save(
                body.name,
                body.project_id,
                body.api_key.get_secret_value().strip(),
                "default" if first else None,
            )
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        except Exception:
            raise HTTPException(
                503, "Не удалось сохранить ключ в защищённом хранилище"
            ) from None
        return {"id": ident}

    @app.put("/api/keys/{ident}")
    def key_metadata(ident: str, body: KeyMetadata):
        try:
            keys.rename_project(ident, body.name, body.project_id)
        except ValueError as e:
            raise HTTPException(404, str(e)) from None
        return {"ok": True}

    @app.delete("/api/keys/{ident}")
    def disable_key(ident: str):
        with store.connect() as c:
            if c.execute(
                "SELECT 1 FROM app_entity_jobs WHERE credential_id=? AND status IN ('queued','running') LIMIT 1",
                (ident,),
            ).fetchone():
                raise HTTPException(
                    409, "Дождитесь завершения точечного обновления с этим ключом"
                )
        if any(
            r["status"] in {"queued", "running"}
            and r["config"].get("credential_id", "default") == ident
            for r in store.runs()
        ):
            raise HTTPException(
                409, "Сначала дождитесь завершения запуска с этим ключом"
            )
        try:
            keys.disable(ident)
        except ValueError as e:
            raise HTTPException(404, str(e)) from None
        return {"ok": True}

    @app.post("/api/keys/{ident}/enable")
    def enable_key(ident: str):
        try:
            keys.metadata(ident)
        except ValueError as e:
            raise HTTPException(404, str(e)) from None
        with store.connect() as c:
            c.execute("UPDATE app_credentials SET enabled=1 WHERE id=?", (ident,))
        return {"ok": True}

    @app.get("/api/access-tokens")
    def list_tokens():
        return tokens.list()

    @app.post("/api/access-tokens")
    def add_token(body: TokenInput):
        if not auth:
            raise HTTPException(400, "Сначала настройте вход администратора")
        return tokens.create(body.name, body.scope, body.days)

    @app.delete("/api/access-tokens/{ident}")
    def revoke_token(ident: str):
        tokens.revoke(ident)
        return {"ok": True}

    @app.get("/api/v1/me")
    def me(request: Request):
        return {"owner_id": owner(request)}

    @app.get("/api/v1/openapi.json")
    def openapi():
        schema = app.openapi()
        return {
            **schema,
            "paths": {
                p: v for p, v in schema["paths"].items() if p.startswith("/api/v1/")
            },
            "security": [{"BearerAuth": []}],
            "components": {
                **schema.get("components", {}),
                "securitySchemes": {"BearerAuth": {"type": "http", "scheme": "bearer"}},
            },
        }
