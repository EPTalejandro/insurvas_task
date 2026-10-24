"""A fake YouTube API for tests, built on httpx.MockTransport and sanitized fixtures."""

import json
from pathlib import Path

import httpx

FIXTURES = Path(__file__).parent / "fixtures"
QUOTA_BODY = {"error": {"code": 403, "errors": [{"reason": "quotaExceeded"}]}}
FORBIDDEN_BODY = {"error": {"code": 403, "errors": [{"reason": "forbidden"}]}}


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


class FakeYouTube:
    def __init__(self) -> None:
        self.search = load("youtube_search")
        self.channels = load("youtube_channels")
        self.playlist = load("youtube_playlist_items")
        self.videos = load("youtube_videos")
        self.calls: list[tuple[str, dict]] = []
        self.search_errors: dict[str, tuple[int, dict]] = {}  # query -> (status, body)
        self.failing_playlists: set[str] = set()

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handle))

    def calls_to(self, path: str) -> int:
        return sum(1 for called, _ in self.calls if called == path)

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/youtube/v3")
        params = dict(request.url.params)
        self.calls.append((path, params))

        if path == "/search":
            if params["q"] in self.search_errors:
                status, body = self.search_errors[params["q"]]
                return httpx.Response(status, json=body)
            return httpx.Response(200, json=self.search)
        if path == "/channels":
            wanted = params["id"].split(",")
            items = [c for c in self.channels["items"] if c["id"] in wanted]
            return httpx.Response(200, json={"items": items})
        if path == "/playlistItems":
            if params["playlistId"] in self.failing_playlists:
                return httpx.Response(404, json={"error": {"message": "playlistNotFound"}})
            return httpx.Response(200, json=self.playlist)
        if path == "/videos":
            wanted = params["id"].split(",")
            items = [v for v in self.videos["items"] if v["id"] in wanted]
            return httpx.Response(200, json={"items": items})
        return httpx.Response(404, json={"error": {"message": "unknown path"}})
