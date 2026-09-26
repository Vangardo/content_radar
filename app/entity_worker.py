from youtube_niche.auth import ApiKeyAuth
from youtube_niche.cache import Cache
from youtube_niche.youtube_client import APIError, QuotaExceeded
from .engine_adapter import RadarClient, ERRORS, Cancelled
from .entities import Entities


def refresh_entities(store, job, stop, client_type=RadarClient):
    entities = Entities(store)
    cache = Cache(str(store.path))
    client = None
    updated, missing = [], []
    status, error = "completed", None

    def check(_):
        if stop.is_set():
            raise Cancelled()

    def response(endpoint, params, data, at, cached, response_key):
        store.save_response(endpoint, data, at, response_key)
        for item in data.get("items", []):
            updated.append(item["id"])
            entities.link(
                endpoint, item["id"], job["credential_id"], at, job["owner_id"]
            )
            if endpoint == "videos" and item.get("snippet", {}).get("channelId"):
                entities.link(
                    "channels",
                    item["snippet"]["channelId"],
                    job["credential_id"],
                    at,
                    job["owner_id"],
                )

    try:
        key = store.keys.get(job["credential_id"])
        if not key:
            raise APIError("keyInvalid")
        budget = store.budget()
        client = client_type(
            ApiKeyAuth(key),
            cache,
            verbose=False,
            daily_quota=budget.unit_limit,
            daily_search_limit=budget.search_limit,
            reserve=0,
            force_endpoints={job["kind"]},
            on_response=response,
            before_request=check,
            conservative_charge=True,
            quota_timezone="America/Los_Angeles",
        )
        client.registry, client.credential_id = store.keys, job["credential_id"]
        for start in range(0, len(job["ids"]), 50):
            check(None)
            batch = job["ids"][start : start + 50]
            found = getattr(client, job["kind"])(batch)
            missing.extend(set(batch) - found.keys())
        if missing:
            status, error = (
                "partial",
                "YouTube не вернул часть объектов. Их предыдущие данные сохранены.",
            )
    except Cancelled:
        status, error = (
            "interrupted",
            "Обновление прервано. Уже полученные данные сохранены.",
        )
    except QuotaExceeded:
        status, error = (
            "waiting_quota",
            "YouTube сообщил об исчерпании квоты. Повторите после сброса лимита.",
        )
    except APIError as exc:
        status, error = (
            "partial" if updated else "failed",
            ERRORS.get(
                str(exc), "YouTube не вернул данные. Проверьте подключение ключа."
            ),
        )
    except Exception as exc:
        status, error = (
            "partial" if updated else "failed",
            f"Не удалось завершить обновление ({type(exc).__name__}).",
        )
    finally:
        entities.finish(
            job["id"],
            status,
            {
                "updated": len(updated),
                "requested": len(job["ids"]),
                "missing": sorted(missing),
                "general_units": client.general_attempts if client else 0,
                "search_calls": 0,
            },
            error,
        )
        if client:
            client.session.close()
        cache.close()
