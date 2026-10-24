import pytest

from app.collectors.youtube_parsers import (
    best_thumbnail,
    parse_channel,
    parse_iso_duration,
    parse_video,
    to_int,
    uploads_playlist_id,
    video_format,
)
from tests.youtube_fake import load


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("PT19M4S", 1144),
        ("PT45S", 45),
        ("PT1H", 3600),
        ("PT1H2M3S", 3723),
        ("P1DT1H", 90000),
        ("P0D", 0),
        ("", None),
        (None, None),
        ("19:04", None),
        ("PT", None),
    ],
)
def test_parse_iso_duration(text, seconds):
    assert parse_iso_duration(text) == seconds


def test_short_video_limit_is_180_seconds():
    assert video_format(180) == "short_video"
    assert video_format(181) == "long_video"
    assert video_format(None) is None


def test_to_int_keeps_unknown_as_none():
    assert to_int("297") == 297
    assert to_int("0") == 0
    assert to_int(None) is None
    assert to_int("n/a") is None


def test_best_thumbnail_prefers_larger_sizes():
    assert best_thumbnail({"default": {"url": "d"}, "high": {"url": "h"}}) == "h"
    assert best_thumbnail({}) is None


def test_uploads_playlist_id():
    assert uploads_playlist_id("UCabc123") == "UUabc123"
    assert uploads_playlist_id("XYZ") is None


def test_parse_video_with_hidden_likes_and_escaped_title():
    item = load("youtube_videos")["items"][0]
    video = parse_video(item)
    assert video["title"] == "Don't buy term life until you watch this"
    assert video["format"] == "short_video"
    assert video["views"] == 12000
    assert video["comments"] == 35
    assert video["likes"] is None  # hidden by the creator, not zero
    assert video["shares"] is None
    assert video["thumbnail_url"] == "https://img.test/short_high.jpg"
    assert video["url"] == "https://www.youtube.com/watch?v=vid_short"
    assert video["published_at"].year == 2026


def test_parse_video_skips_live_and_upcoming():
    item = load("youtube_videos")["items"][0]
    for state in ("live", "upcoming"):
        item["snippet"]["liveBroadcastContent"] = state
        assert parse_video(item) is None


def test_parse_channel_reads_handle_url_and_followers():
    agent = parse_channel(load("youtube_channels")["items"][0])
    assert agent["handle"] == "@janedoefe"
    assert agent["url"] == "https://www.youtube.com/@janedoefe"
    assert agent["followers"] == 5200
    assert agent["country"] == "US"


def test_parse_channel_hidden_subscribers_are_none():
    gamer = parse_channel(load("youtube_channels")["items"][3])
    assert gamer["followers"] is None
    assert gamer["country"] is None  # owners often leave the country empty
