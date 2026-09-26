from __future__ import annotations

import os
import hashlib
import secrets
import sqlite3
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, SecretStr
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .exports import export_run
from .grouping import group_videos
from .models import Budget, Note, PRESETS, ScanConfig, StartScan, ScheduleConfig
from .monitoring import trend_score
from .secrets import SecretStore
from .server_security import ServerConfig, ServerAuth, EncryptedVault
from .storage import ROOT, Store
from .worker import InstanceLock, Worker
from .credentials import KeyRegistry
from .access import AccessTokens


class Credential(BaseModel):
    api_key: SecretStr


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: SecretStr = Field(min_length=1, max_length=1000)


class Repeat(BaseModel):
    request_id: str = Field(pattern=r"^[a-zA-Z0-9-]{8,80}$")
    max_results: int | None = Field(default=None, ge=50, le=500)
    video_ids: list[str] | None = Field(default=None, min_length=1, max_length=10000)


class Focus(BaseModel):
    request_id: str = Field(pattern=r"^[a-zA-Z0-9-]{8,80}$")
    max_subscribers: int = Field(default=10000, ge=1, le=1_000_000_000)


def create_app(
    data_dir: Path | None = None,
    vault=None,
    engine_type=None,
    run_worker=True,
    test_mode=False,
    server_config=None,
):
    data_dir = data_dir or Path(os.environ.get("RADAR_DATA_DIR", ROOT / "data"))
    store = Store(data_dir / "radar.sqlite")
    encrypted_server = bool(server_config) or os.environ.get("RADAR_MODE") == "server"
    server_config = server_config or ServerConfig.from_env(data_dir / "local-auth.json")
    vault = vault or (
        EncryptedVault(data_dir, server_config.encryption_key)
        if server_config and encrypted_server
        else SecretStore(str(store.path.resolve()))
    )
    auth = ServerAuth(store, server_config) if server_config else None
    keys = KeyRegistry(store, vault)
    store.keys = keys
    tokens = AccessTokens(store)
    csrf = secrets.token_urlsafe(32)
    cookie_name = (
        "radar_" + hashlib.sha256(str(store.path.resolve()).encode()).hexdigest()[:12]
    )
    lock = InstanceLock(data_dir / "radar.lock")
    worker = Worker(
        store, vault, **({"engine_type": engine_type} if engine_type else {})
    )

    @asynccontextmanager
    async def lifespan(app):
        lock.acquire()
        try:
            store.initialize()
            keys.initialize()
            if auth:
                with store.connect() as c:
                    c.execute(
                        "UPDATE app_users SET username=?,password_hash=? WHERE id='admin'",
                        (server_config.username, server_config.password_hash),
                    )
            store.recover()
            if run_worker:
                worker.start()
            yield
        finally:
            if run_worker and worker.thread.is_alive():
                worker.close()
            lock.release()

    app = FastAPI(
        title="Topic Radar",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.store, app.state.vault, app.state.csrf = store, vault, csrf
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=server_config.hosts
        if server_config
        else ["127.0.0.1", "localhost", "testserver"],
    )
    app.mount("/static", StaticFiles(directory=ROOT / "app/static"), name="static")
    templates = Jinja2Templates(directory=ROOT / "app/templates")

    @app.middleware("http")
    async def protect(request: Request, call_next):
        try:
            too_large = int(request.headers.get("content-length", "0")) > 65536
        except ValueError:
            return JSONResponse(
                {"error": "Некорректный размер запроса"}, status_code=400
            )
        if too_large:
            return JSONResponse({"error": "Слишком большой запрос"}, status_code=413)
        external = request.url.path.startswith("/api/v1/")
        if external:
            scheme, _, token = request.headers.get("authorization", "").partition(" ")
            actor = tokens.verify(token) if scheme.lower() == "bearer" else None
            if not actor:
                return JSONResponse(
                    {"error": "Нужен действующий Bearer-токен"}, status_code=401
                )
            if (
                request.method not in {"GET", "HEAD", "OPTIONS"}
                and actor["scope"] != "write"
            ):
                return JSONResponse(
                    {"error": "Токен разрешает только чтение"}, status_code=403
                )
            request.state.owner_id = actor["owner_id"]
        public = request.url.path in {
            "/login",
            "/api/login",
            "/healthz",
        } or request.url.path.startswith("/static/")
        if (
            auth
            and not public
            and not external
            and not auth.valid(request.cookies.get(auth.cookie))
        ):
            return (
                JSONResponse(
                    {"error": "Войдите в рабочее пространство."}, status_code=401
                )
                if request.url.path.startswith("/api/")
                else RedirectResponse("/login", status_code=303)
            )
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not external:
            origin = request.headers.get("origin")
            expected = f"{request.url.scheme}://{request.url.netloc}"
            if (origin and origin != expected) or request.headers.get(
                "sec-fetch-site"
            ) == "cross-site":
                return JSONResponse(
                    {"error": "Запрос с другого сайта отклонён."}, status_code=403
                )
            if not secrets.compare_digest(
                request.headers.get("x-csrf-token", ""), csrf
            ) or not secrets.compare_digest(request.cookies.get(cookie_name, ""), csrf):
                return JSONResponse(
                    {"error": "Обновите страницу и повторите действие."},
                    status_code=403,
                )
            if int(request.headers.get("content-length", "0")) > 65536:
                return JSONResponse(
                    {"error": "Слишком большой запрос."}, status_code=413
                )
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' https://i.ytimg.com; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        # Pydantic's default response can echo an invalid secret input.
        return JSONResponse(
            {
                "error": "Проверьте параметры формы: название, запросы, регион и числовые ограничения."
            },
            status_code=422,
        )

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    @app.exception_handler(sqlite3.Error)
    async def storage_error(request, exc):
        logging.getLogger(__name__).error(
            "Database request failed (%s, code=%s)",
            type(exc).__name__, getattr(exc, "sqlite_errorcode", None),
        )
        return JSONResponse(
            {"error": "Хранилище временно недоступно. Попробуйте позже. Если ошибка повторяется, требуется проверка сервера."},
            status_code=503,
        )

    from .storage import ResearchDeleted

    @app.exception_handler(ResearchDeleted)
    async def deleted_research(request, exc):
        return JSONResponse({"error": str(exc)}, status_code=410)

    def get_run(run_id):
        run = store.run(run_id)
        if not run:
            raise HTTPException(404, "Исследование не найдено.")
        if store.research_deleted(run["collection_id"]):
            raise ResearchDeleted()
        return run

    def require_key(ident="default"):
        if not keys.available(ident):
            raise HTTPException(
                400, "Сначала сохраните YouTube Data API key в настройках."
            )

    def render(request, view="scan", run_id=""):
        response = templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "csrf": csrf,
                "view": view,
                "run_id": run_id,
                "test_mode": test_mode,
                "server_mode": bool(auth),
            },
        )
        response.set_cookie(
            cookie_name,
            csrf,
            httponly=True,
            samesite="strict",
            secure=bool(server_config and server_config.secure_cookies),
        )
        return response

    @app.get("/healthz")
    def health():
        alive = not run_worker or (worker.thread.is_alive() and not worker.storage_error)
        return JSONResponse({"ok": alive}, status_code=200 if alive else 503)

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request):
        if not auth:
            return RedirectResponse("/")
        response = templates.TemplateResponse(
            request=request, name="login.html", context={"csrf": csrf}
        )
        response.set_cookie(
            cookie_name,
            csrf,
            httponly=True,
            samesite="strict",
            secure=server_config.secure_cookies,
        )
        return response

    @app.post("/api/login")
    def login(body: Login):
        if not auth:
            raise HTTPException(404, "Вход доступен только в серверном режиме")
        token, status = auth.login(body.username, body.password.get_secret_value())
        if status != 200:
            raise HTTPException(
                status,
                "Слишком много попыток. Повторите через 5 минут."
                if status == 429
                else "Неверный логин или пароль",
            )
        response = JSONResponse({"ok": True})
        response.set_cookie(
            auth.cookie,
            token,
            max_age=43200,
            secure=server_config.secure_cookies,
            httponly=True,
            samesite="strict",
        )
        return response

    @app.post("/api/logout")
    def logout(request: Request):
        if auth:
            auth.logout(request.cookies.get(auth.cookie, ""))
        response = JSONResponse({"ok": True})
        if auth:
            response.delete_cookie(
                auth.cookie,
                secure=server_config.secure_cookies,
                httponly=True,
                samesite="strict",
            )
        return response

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        return render(request, "dashboard")

    @app.get("/new", response_class=HTMLResponse)
    def new_research(request: Request):
        return render(request, "scan")

    @app.get("/api-help", response_class=HTMLResponse)
    def api_help(request: Request):
        return render(request, "api-help")

    @app.get("/history", response_class=HTMLResponse)
    def history(request: Request):
        return render(request, "history")

    @app.get("/trash", response_class=HTMLResponse)
    def trash_page(request: Request):
        return render(request, "trash")

    @app.get("/saved", response_class=HTMLResponse)
    def saved_page(request: Request):
        return render(request, "saved")

    @app.get("/posts", response_class=HTMLResponse)
    def posts_page(request: Request):
        return render(request, "posts")

    @app.get("/channels", response_class=HTMLResponse)
    def channel_list_page(request: Request):
        return render(request, "channels")

    @app.get("/channels/{channel_id}", response_class=HTMLResponse)
    def channel_page(request: Request, channel_id: str):
        return render(request, "channel", channel_id)

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request):
        return render(request, "settings")

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    def run_page(request: Request, run_id: str):
        get_run(run_id)
        return render(request, "run", run_id)

    @app.get("/api/bootstrap")
    def bootstrap():
        return {
            "credential": vault.status(),
            "credentials": keys.list(),
            "quota": store.quota(),
            "presets": PRESETS,
            "directions": store.directions(),
            "runs": store.runs(include_deleted=False),
            "worker_alive": worker.thread.is_alive(),
            "worker_error": worker.storage_error,
            "schedules": worker.scheduler.all(),
            "server_mode": bool(auth),
            "now": time.time(),
        }

    @app.put("/api/credential")
    def credential(body: Credential):
        key = body.api_key.get_secret_value().strip()
        if (
            len(key) < 20
            or len(key) > 200
            or not all(c.isalnum() or c in "_-" for c in key)
        ):
            raise HTTPException(
                422,
                "Введите API key из Google Cloud. OAuth access token здесь не используется.",
            )
        try:
            meta = keys.metadata("default")
            keys.save(meta["name"], meta["project_id"], key, "default")
        except Exception:
            raise HTTPException(
                503, "Не удалось сохранить ключ в системном хранилище."
            ) from None
        return vault.status()

    @app.delete("/api/credential")
    def delete_credential():
        with store.connect() as conn:
            if conn.execute(
                "SELECT 1 FROM app_entity_jobs WHERE credential_id='default' AND status IN ('queued','running') LIMIT 1"
            ).fetchone():
                raise HTTPException(
                    409, "Дождитесь завершения точечного обновления с этим ключом"
                )
        if any(r["status"] in {"queued", "running"} for r in store.runs()):
            raise HTTPException(
                409, "Сначала отмените текущий запуск, затем удалите ключ."
            )
        try:
            vault.delete()
        except Exception:
            raise HTTPException(
                503, "Не удалось удалить ключ из системного хранилища."
            ) from None
        return vault.status()

    @app.put("/api/budget")
    def budget(body: Budget):
        store.set_setting("budget", body.model_dump())
        return store.quota()

    @app.post("/api/runs")
    def start(body: StartScan):
        if not keys.available(body.config.credential_id):
            raise HTTPException(400, "Добавьте или выберите действующий API-ключ")
        if not body.config.seeds:
            raise HTTPException(422, "Добавьте хотя бы один поисковый запрос.")
        if (
            body.config.max_duration
            and body.config.max_duration < body.config.min_duration
        ):
            raise HTTPException(
                422, "Максимальная длительность должна быть не меньше минимальной."
            )
        ident = store.create_run(body.config, body.request_id)
        worker.wake.set()
        return {"id": ident}

    @app.get("/api/runs/{run_id}")
    def run_result(run_id: str):
        run = get_run(run_id)
        videos = store.videos(run_id)
        for video in videos:
            video["trend_score"] = trend_score(video)
        history = store.collection_runs(run_id)
        return {
            "run": run,
            "videos": videos,
            "queries": store.queries(run_id),
            "quota": store.quota(),
            "monitoring": worker.scheduler.summary(run["collection_id"], videos),
            "groups": group_videos(videos)
            if run["config"].get("extract_phrases", True)
            else [],
            "collection": {
                "id": run["collection_id"],
                "latest_id": history[0]["id"],
                "runs": history,
            },
        }

    @app.put("/api/runs/{run_id}/schedule")
    def schedule(run_id: str, body: ScheduleConfig):
        run = get_run(run_id)
        if body.enabled:
            require_key(run["config"].get("credential_id", "default"))
        result = worker.scheduler.save(run["collection_id"], body)
        worker.wake.set()
        return result

    @app.post("/api/runs/{run_id}/focus")
    def focus(run_id: str, body: Focus):
        get_run(run_id)
        latest = store.collection_runs(run_id)[0]
        config = ScanConfig(
            **{
                **latest["config"],
                "max_subscribers": body.max_subscribers,
                "order": "mixed",
                "force": False,
            }
        )
        ident = store.create_run(config, body.request_id, "refilter", latest["id"])
        worker.wake.set()
        return {"id": ident}

    @app.post("/api/runs/{run_id}/cancel")
    def cancel(run_id: str):
        get_run(run_id)
        store.cancel(run_id)
        return {"ok": True}

    @app.post("/api/runs/{run_id}/repeat")
    def repeat(run_id: str, body: Repeat):
        return extend(run_id, body, "repeat")

    @app.post("/api/runs/{run_id}/append")
    def append(run_id: str, body: Repeat):
        return extend(run_id, body, "append")

    def extend(run_id, body, kind):
        run = get_run(run_id)
        # Use the current collection configuration even from an old history link.
        run = store.collection_runs(run["id"])[0]
        require_key(run["config"].get("credential_id", "default"))
        config = ScanConfig(
            **{
                **run["config"],
                "force": True,
                **({"max_results": body.max_results} if body.max_results else {}),
            }
        )
        ident = store.create_run(config, body.request_id, kind, run["id"])
        worker.wake.set()
        return {"id": ident}

    @app.post("/api/runs/{run_id}/refresh")
    def refresh(run_id: str, body: Repeat):
        run = get_run(run_id)
        run = store.collection_runs(run["id"])[0]
        require_key(run["config"].get("credential_id", "default"))
        if not store.videos(run["id"]):
            raise HTTPException(400, "Нет сохранённых видео для обновления.")
        config = ScanConfig(**{**run["config"], "force": True})
        try:
            ident = store.create_run(
                config,
                body.request_id,
                "refresh",
                run["id"],
                list(dict.fromkeys(body.video_ids))
                if body.video_ids is not None
                else None,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        worker.wake.set()
        return {"id": ident}

    @app.get("/api/runs/{run_id}/export/{format}")
    def export(run_id: str, format: str, group_id: str | None = None):
        if format not in {"csv", "json", "md"}:
            raise HTTPException(404, "Формат не поддерживается.")
        run = get_run(run_id)
        videos = store.videos(run_id)
        groups = (
            group_videos(videos) if run["config"].get("extract_phrases", True) else []
        )
        if group_id:
            selected = next((g for g in groups if g["id"] == group_id), None)
            if not selected:
                raise HTTPException(404, "Группа не найдена")
            videos = [v for v in videos if v["video_id"] in selected["video_ids"]]
            groups = [selected]
        content, media_type = export_run(
            run, videos, store.queries(run_id), format, groups
        )
        return Response(
            content,
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="radar-{run["id"][:8]}.{format}"'
            },
        )

    @app.put("/api/videos/{video_id}/note")
    def note(video_id: str, body: Note):
        if not video_id.isalnum() and not all(
            c.isalnum() or c in "_-" for c in video_id
        ):
            raise HTTPException(422, "Некорректный ID видео.")
        if len(video_id) > 64:
            raise HTTPException(422, "Некорректный ID видео.")
        store.note(video_id, body.favorite, body.text)
        return {"ok": True}

    @app.get("/api/videos/{video_id}/snapshots")
    def snapshots(video_id: str, run_id: str | None = None):
        if run_id:
            if not store.run(run_id):
                raise HTTPException(404, "Исследование не найдено")
            video = next(
                (v for v in store.videos(run_id) if v["video_id"] == video_id), None
            )
            if video is None:
                raise HTTPException(404, "Видео не найдено в исследовании")
            return store.snapshots(video_id, video["fetched_at"])
        return store.snapshots(video_id)

    @app.get("/api/saved")
    def saved():
        return store.saved()

    @app.post("/api/purge")
    def purge():
        return {"deleted": store.purge()}

    from .product import install_product

    install_product(app, store, keys, tokens, worker, auth)
    from .entity_api import install_entities

    install_entities(app, store, keys, worker)
    from .catalog import install_catalog

    install_catalog(app, store)
    return app


app = create_app()
