"""A fake Instagram Graph API for tests, built on httpx.MockTransport and fixtures."""

import re
from datetime import UTC, datetime, timedelta

import httpx

from app.config import Settings
from tests.youtube_fake import load

TOKEN = "SECRET-TOKEN"
HASHTAG_ID = "17841562972126518"
TOKEN_EXPIRED = {"error": {"message": "Session has expired", "type": "OAuthException", "code": 190}}
TOO_MUCH_DATA = {"error": {"code": 1, "message": "Please reduce the amount of data you're asking"}}


INVALID_ACCOUNT = {
    "error": {
        "message": "Invalid user id",
        "type": "OAuthException",
        "code": 110,
        "error_subcode": 2207013,
    }
}
RATE_LIMITED = {
    "error": {"message": "(#4) Application request limit reached", "code": 4, "is_transient": True}
}
UNSUPPORTED_FIELD = {"error": {"message": "(#100) Unsupported field", "code": 100}}
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


def media(
    media_id, *, days=1, likes=10, comments=0, kind="IMAGE", product="FEED", views=None, images=True
):
    """One Business Discovery media item, `days` old at NOW."""
    item = {
        "id": media_id,
        "caption": f"Caption of {media_id}",
        "media_type": kind,
        "media_product_type": product,
        "like_count": likes,
        "comments_count": comments,
        "permalink": f"https://www.instagram.com/p/{media_id}/",
        "timestamp": (NOW - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S+0000"),
    }
    if views is not None:
        item["view_count"] = views
    if images:
        # Like the real API: a video's media_url is the video file, its preview is thumbnail_url.
        if kind == "VIDEO":
            item["media_url"] = f"https://cdn.test/{media_id}.mp4"
            item["thumbnail_url"] = f"https://cdn.test/{media_id}-thumb.jpg"
        else:
            item["media_url"] = f"https://cdn.test/{media_id}.jpg"
    return item


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
        self.rate_limited_after_search = False
        self.hashtag_missing = False
        self.fail_page1 = False
        self.fail_page2 = False
        self.max_page_size: int | None = None  # larger pages fail like the real API
        # Business Discovery: handle -> profile fields and pages of media
        self.accounts: dict[str, dict] = {}
        self.max_account_page_size: int | None = None
        self.account_failure: tuple[int, dict] | None = None  # every account call fails

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handle))

    def add_account(self, handle, *, name=None, bio=None, website=None, followers=1000, pages=()):
        """An account Business Discovery can read. `pages` is a list of lists of media()."""
        self.accounts[handle] = {
            "id": f"id-{handle}",
            "username": handle,
            "name": name or handle,
            "biography": bio,
            "website": website,
            "followers_count": followers,
            "pages": [list(page) for page in pages],
        }

    def account_calls(self) -> list[dict]:
        return [
            params
            for name, params in self.calls
            if "business_discovery" in params.get("fields", "")
        ]

    def account_page_sizes(self) -> list[int]:
        sizes = []
        for params in self.account_calls():
            found = re.search(r"media\.limit\((\d+)\)", params["fields"])
            if found:
                sizes.append(int(found.group(1)))
        return sizes

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
        if self.rate_limited_after_search and name == "top_media":
            return httpx.Response(403, json=RATE_LIMITED)
        fields = params.get("fields", "")
        if "business_discovery.username(" in fields:
            return self.business_discovery(fields)
        if name == "ig_hashtag_search":
            data = {"data": []} if self.hashtag_missing else self.search
            return httpx.Response(200, json=data)
        if name == "top_media":
            if "thumbnail_url" in params.get("fields", ""):
                return httpx.Response(400, json=UNSUPPORTED_FIELD)  # hashtag media has none
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

    def business_discovery(self, fields: str) -> httpx.Response:
        if self.account_failure:
            status, body = self.account_failure
            return httpx.Response(status, json=body)
        handle = re.search(r"business_discovery\.username\(([^)]+)\)", fields).group(1)
        account = self.accounts.get(handle)
        if account is None:
            return httpx.Response(400, json=INVALID_ACCOUNT)
        profile = {k: v for k, v in account.items() if k != "pages"}
        if "media." in fields:
            limit = int(re.search(r"media\.limit\((\d+)\)", fields).group(1))
            if self.max_account_page_size is not None and limit > self.max_account_page_size:
                return httpx.Response(500, json=TOO_MUCH_DATA)
            after = re.search(r"\.after\(([^)]+)\)", fields)
            index = int(after.group(1)) if after else 0
            pages = account["pages"]
            paging = {"cursors": {"after": str(index + 1)}}
            if index + 1 < len(pages):
                paging["next"] = "https://graph.facebook.com/next"
            profile["media"] = {
                "data": pages[index] if index < len(pages) else [],
                "paging": paging,
            }
        return httpx.Response(200, json={"business_discovery": profile, "id": "1784"})
