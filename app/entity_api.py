import uuid
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field
from .entities import Entities
from .models import Note

Kind = Literal["videos", "channels"]


class RefreshEntities(BaseModel):
    ids: list[str] = Field(default_factory=list, max_length=10000)
    favorites: bool = False
    credential_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9-]{1,64}$")
    request_id: str = Field(
        default_factory=lambda: uuid.uuid4().hex, pattern=r"^[a-zA-Z0-9-]{8,80}$"
    )


def install_entities(app, store, keys, worker):
    entities = Entities(store)

    def owner(request):
        return getattr(request.state, "owner_id", "admin")

    def read(kind, ident, request):
        try:
            return entities.detail(kind, ident, owner(request))
        except ValueError as e:
            raise HTTPException(404, str(e)) from None

    @app.get("/api/entities/channels")
    @app.get("/api/v1/entities/channels")
    def channels(request: Request):
        return {"channels": entities.channels(owner(request))}

    @app.get("/api/entities/jobs/{ident}")
    @app.get("/api/v1/entities/jobs/{ident}")
    def job(ident: str, request: Request):
        try:
            return entities.job(ident, owner(request))
        except ValueError as e:
            raise HTTPException(404, str(e)) from None

    @app.get("/api/entities/{kind}/{ident}")
    @app.get("/api/v1/entities/{kind}/{ident}")
    def detail(kind: Kind, ident: str, request: Request):
        result = read(kind, ident, request)
        if kind == "channels":
            result["videos"] = entities.channel_videos(ident, owner(request))
        return result

    @app.put("/api/entities/channels/{ident}/note")
    @app.put("/api/v1/entities/channels/{ident}/note")
    def note(ident: str, body: Note, request: Request):
        read("channels", ident, request)
        entities.channel_note(ident, body.favorite, body.text, owner(request))
        return {"ok": True}

    @app.post("/api/entities/{kind}/refresh")
    @app.post("/api/v1/entities/{kind}/refresh")
    def refresh(kind: Kind, body: RefreshEntities, request: Request):
        who = owner(request)
        if body.favorites and body.ids:
            raise HTTPException(400, "Выберите конкретные объекты или избранное")
        ids = (
            entities.favorites(kind, who)
            if body.favorites
            else list(dict.fromkeys(body.ids))
        )
        if not ids or len(ids) > 10000:
            raise HTTPException(
                400, "Нет объектов для обновления или выбрано больше 10 000"
            )
        try:
            references = [entities.reference(kind, ident, who) for ident in ids]
        except ValueError as e:
            raise HTTPException(404, str(e)) from None
        credential = body.credential_id or references[0]["credential_id"]
        try:
            keys.metadata(credential, who)
            if not keys.available(credential):
                raise ValueError("Выберите доступный API-ключ")
            ident = entities.enqueue(kind, ids, credential, body.request_id, who)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        worker.wake.set()
        return {
            "id": ident,
            "requested": len(ids),
            "estimated_units": (len(ids) + 49) // 50,
        }
