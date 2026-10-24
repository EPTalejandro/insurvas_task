"""A fake Instagram Graph API for tests, built on httpx.MockTransport and fixtures."""

import httpx

from app.config import Settings
from tests.youtube_fake import load

TOKEN = "SECRET-TOKEN"
HASHTAG_ID = "17841562972126518"
TOKEN_EXPIRED = {"error": {"message": "Session has expired", "type": "OAuthException", "code": 190}}
TOO_MUCH_DATA = {"error": {"code": 1, "message": "Please reduce the amount of data you're asking"}}


def make_settings(**overrides) -> Settings:
    values = {
        "ig_access_token": TOKEN,
        "ig_user_id": "1784",
        "meta_graph_version": "v23.0",
    }
    return Settings(_env_file=None, **{**values, **overrides})


class FakeInstagram:
    def __init__(self) -> None:
        self.search = load("instagram_hashtag_search")
        self.page1 = load("instagram_top_media_page1")
        self.page2 = load("instagram_top_media_page2")
        self.calls: list[tuple[str, dict]] = []
        self.token_expired = False
        self.hashtag_missing = False
        self.fail_page1 = False
        self.fail_page2 = False
        self.max_page_size: int | None = None  # larger pages fail like the real API

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handle))

    def calls_to(self, name: str) -> int:
        return sum(1 for called, _ in self.calls if called == name)

    def page_sizes(self) -> list[int]:
        return [int(params["limit"]) for name, params in self.calls if name == "top_media"]

    def queries(self) -> list[str]:
        return [params["q"] for name, params in self.calls if name == "ig_hashtag_search"]

    def handle(self, request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        params = dict(request.url.params)
        self.calls.append((name, params))

        if self.token_expired:
            return httpx.Response(400, json=TOKEN_EXPIRED)
        if name == "ig_hashtag_search":
            data = {"data": []} if self.hashtag_missing else self.search
            return httpx.Response(200, json=data)
        if name == "top_media":
            too_big = self.max_page_size is not None and int(params["limit"]) > self.max_page_size
            if too_big:
                return httpx.Response(500, json=TOO_MUCH_DATA)
            if "after" not in params:
                if self.fail_page1:
                    return httpx.Response(500, json=TOO_MUCH_DATA)
                return httpx.Response(200, json=self.page1)
            if self.fail_page2:
                return httpx.Response(500, json=TOO_MUCH_DATA)
            return httpx.Response(200, json=self.page2)
        return httpx.Response(404, json={"error": {"message": "unknown path"}})
