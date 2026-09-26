"""Synthetic transport fixtures. Never loaded by the production application."""

import datetime as dt
import hashlib

from app.engine_adapter import EngineAdapter, RadarClient


class MemoryVault:
    def __init__(self):
        self.key = None

    def get(self):
        return self.key

    def save(self, key):
        self.key = key

    def delete(self):
        self.key = None

    def status(self):
        return {
            "configured": bool(self.key),
            "fingerprint": hashlib.sha256(self.key.encode()).hexdigest()[:10]
            if self.key
            else None,
            "error": None,
        }


class FakeResponse:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status

    def json(self):
        return self.data


class FixtureTransport:
    def __init__(self, failure=None, empty=False, views=180000):
        self.calls = []
        self.failure, self.empty, self.views = failure, empty, views

    def get(self, url, params, headers, timeout):
        endpoint = url.rsplit("/", 1)[-1]
        self.calls.append(endpoint)
        if self.failure == endpoint:
            return FakeResponse(
                {"error": {"errors": [{"reason": "quotaExceeded"}]}}, 403
            )
        if self.failure == "auth":
            return FakeResponse({"error": {"errors": [{"reason": "keyInvalid"}]}}, 400)
        if self.empty:
            return FakeResponse({"items": []})
        if endpoint == "search":
            return FakeResponse(
                {
                    "items": [
                        {"id": {"videoId": f"fixture00{i}"}} for i in range(1, 4)
                    ],
                    "nextPageToken": "next",
                    "pageInfo": {"totalResults": 100000},
                }
            )
        if endpoint == "videos":
            items = []
            for i, vid in enumerate(params["id"].split(",")):
                items.append(
                    {
                        "id": vid,
                        "snippet": {
                            "title": [
                                "ИИ агенты GPT-5.1: новый трейлер",
                                "ИИ агенты GPT-5.1 для работы",
                                "GPT-5.2 обзор",
                            ][i % 3],
                            "channelTitle": "Тестовый канал " + str(i + 1),
                            "channelId": "channel" + vid,
                            "publishedAt": (
                                dt.datetime.now(dt.timezone.utc)
                                - dt.timedelta(days=2 + i)
                            ).isoformat(),
                            "categoryId": "1",
                            "defaultAudioLanguage": "ru",
                        },
                        "statistics": {
                            "viewCount": str(self.views + i * 3000),
                            "likeCount": "1500",
                        }
                        if i != 2
                        else {},
                        "contentDetails": {"duration": "PT8M20S"},
                    }
                )
            return FakeResponse({"items": items})
        if endpoint == "channels":
            return FakeResponse(
                {
                    "items": [
                        {
                            "id": cid,
                            "snippet": {"title": "Тестовый канал"},
                            "statistics": {"subscriberCount": "2000"},
                        }
                        for cid in params["id"].split(",")
                    ]
                }
            )
        raise AssertionError("Forbidden source called: " + endpoint)

    def close(self):
        pass


def engine_with(transport):
    class Client(RadarClient):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.session = transport

    class Engine(EngineAdapter):
        entity_client_type = Client

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs, client_type=Client)

    return Engine


class Pages(FixtureTransport):
    def __init__(self, pages=None, fail_page=None):
        super().__init__()
        self.pages = pages or {"query": [["a", "b"], ["b", "c"]]}
        self.params = []
        self.fail_page = fail_page
        self.missing = set()

    def get(self, url, params, headers, timeout):
        endpoint = url.rsplit("/", 1)[-1]
        self.params.append((endpoint, {k: v for k, v in params.items() if k != "key"}))
        if endpoint == "search":
            self.calls.append(endpoint)
            page = int(params.get("pageToken", "0"))
            if page == self.fail_page:
                return FakeResponse(
                    {"error": {"errors": [{"reason": "quotaExceeded"}]}}, 403
                )
            pages = self.pages[params["q"]]
            data = {"items": [{"id": {"videoId": v}} for v in pages[page]]}
            if page + 1 < len(pages):
                data["nextPageToken"] = str(page + 1)
            return FakeResponse(data)
        response = super().get(url, params, headers, timeout)
        if endpoint == "videos":
            response.data["items"] = [
                v for v in response.data["items"] if v["id"] not in self.missing
            ]
            for v in response.data["items"]:
                # Stable synthetic metadata independent of batch position.
                v["statistics"] = {"viewCount": str(self.views)}
                v["snippet"]["title"] = "Resident Evil (2026) - Movie Review"
        return response


class MetadataPages(Pages):
    def get(self, url, params, headers, timeout):
        response = super().get(url, params, headers, timeout)
        if url.endswith("/channels"):
            for channel in response.data["items"]:
                channel["snippet"].update(
                    description="Канал для проверки мониторинга. <script>не выполнять</script>",
                    country="US",
                    customUrl="@fixture-channel",
                    publishedAt="2020-01-01T00:00:00Z",
                )
                channel["statistics"].update(
                    viewCount=str(self.views * 10), videoCount="31"
                )
        if url.endswith("/videos"):
            for v in response.data["items"]:
                v["snippet"].update(
                    description="Описание\n#Кино #кино #Shorts <script>bad()</script>",
                    tags=["кино", "new, release"],
                )
                v["contentDetails"]["duration"] = "PT2M30S"
                v["player"] = {
                    "embedWidth": "405",
                    "embedHeight": "720",
                    "embedHtml": '<iframe src="https://youtube.com/embed/test"></iframe>',
                }
                v["statistics"]["commentCount"] = "32"
                v["status"] = {"embeddable": False}
                if v["id"] == "b":
                    v["player"] = {"embedWidth": "720", "embedHeight": "405"}
                if v["id"] == "c":
                    v.pop("player")
        return response
