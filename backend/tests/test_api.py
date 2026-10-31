import pytest

from app import runs
from app.config import Settings, get_settings
from app.main import app
from app.ranking import config
from tests.api_data import build_dataset

WINDOWED = ["/api/posts", "/api/competitors", "/api/insights"]


@pytest.fixture
def data(session):
    return build_dataset(session)


def ids(page):
    return [item["id"] for item in page["items"]]


def external_ids(client, **params):
    page = client.get("/api/posts", params=params).json()
    return [item["url"].rsplit("/", 1)[-1] for item in page["items"]]


# --- validation ------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["1", "0", "8", "365", "abc", "-7"])
def test_a_window_outside_7_30_90_is_a_422(client, data, bad):
    urls = [*WINDOWED, f"/api/competitors/{data.alpha.id}"]
    for url in urls:
        response = client.get(url, params={"window": bad})
        assert response.status_code == 422, url
    assert "window must be one of: 7, 30, 90" in client.get("/api/posts", params={"window": 1}).text


@pytest.mark.parametrize("window", [7, 30, 90])
def test_the_three_windows_are_accepted(client, data, window):
    for url in WINDOWED:
        assert client.get(url, params={"window": window}).status_code == 200


def test_the_default_window_is_7(client, data):
    assert client.get("/api/posts").json() == client.get("/api/posts", params={"window": 7}).json()


@pytest.mark.parametrize(
    "params",
    [
        {"platform": "tiktok"},
        {"topic": "nope"},
        {"hook_type": "nope"},
        {"format": "nope"},
        {"format": "reel"},  # the filter only knows the three groups
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"offset": 2**63},  # past SQLite's 64-bit integers: was a 500
        {"competitor_id": "abc"},
        {"competitor_id": 2**63},
    ],
)
def test_bad_post_filters_are_a_422(client, data, params):
    assert client.get("/api/posts", params=params).status_code == 422


def test_bad_insight_params_are_a_422(client, data):
    assert client.get("/api/insights", params={"group_by": "nope"}).status_code == 422
    assert client.get("/api/insights", params={"platform": "tiktok"}).status_code == 422
    assert client.get("/api/runs", params={"limit": 0}).status_code == 422


# --- /api/posts ------------------------------------------------------------------------------


def test_posts_are_ranked_best_first_and_only_ranked_posts_appear(client, data):
    page = client.get("/api/posts", params={"window": 7}).json()

    scores = [item["score"]["score"] for item in page["items"]]
    assert scores == sorted(scores, reverse=True)
    names = external_ids(client, window=7)
    assert set(names) == {"a1", "a2", "a3", "a4", "b1", "b2", "h1", "h2"}
    # not ranked: too new, not an active competitor, a hashtag post that is not US-looking
    assert not {"a-new", "c1", "h3", "h-new", "a-old"} & set(names)
    assert page["total"] == 8


def test_a_post_has_everything_a_card_needs(client, data):
    page = client.get("/api/posts", params={"window": 7, "competitor_id": data.alpha.id}).json()
    post = next(i for i in page["items"] if i["url"].endswith("/a1"))

    assert post["platform"] == "youtube"
    assert post["title"] == "Title a1"
    assert post["text_preview"] == "Caption of a1"
    assert post["format"] == "short_video"
    assert post["creator"]["name"] == "alpha"
    assert post["creator"]["competitor_id"] == data.alpha.id
    assert post["metrics"] == {"views": None, "likes": 100, "comments": 0, "shares": None}
    assert post["label"]["topic"] == "final_expense"
    assert post["label"]["hook_text"] == "Hook of a1"
    assert post["score"]["reason"].startswith("100 engagements")
    assert 0 <= post["score"]["score"] <= 100
    assert post["location"] == {"status": "us", "evidence": "channel country: US"}
    assert post["published_at"].endswith("Z")  # the API says it is UTC


def test_hashtag_posts_show_their_caption_evidence_and_no_competitor(client, data):
    page = client.get("/api/posts", params={"window": 7, "platform": "instagram"}).json()
    by_url = {item["url"].rsplit("/", 1)[-1]: item for item in page["items"]}

    assert set(by_url) == {"h1", "h2"}
    assert by_url["h1"]["location"] == {
        "status": "likely_us",
        "evidence": "US phone number 615-905-6050",
    }
    assert by_url["h2"]["location"]["status"] == "probable_us"
    assert by_url["h1"]["creator"]["competitor_id"] is None
    assert "usual" not in by_url["h1"]["score"]["reason"]


def test_filters_narrow_the_list(client, data):
    assert set(external_ids(client, platform="youtube")) == {"a1", "a2", "a3", "a4", "b1", "b2"}
    assert set(external_ids(client, platform="instagram")) == {"h1", "h2"}
    assert set(external_ids(client, topic="final_expense")) == {"a1", "a2"}
    assert set(external_ids(client, hook_type="warning")) == {"b1", "b2"}
    assert set(external_ids(client, format="image")) == {"h1", "h2"}
    assert set(external_ids(client, competitor_id=data.bravo.id)) == {"b1", "b2"}
    assert external_ids(client, topic="final_expense", platform="instagram") == []


def test_the_format_filter_groups_similar_formats(client, data):
    # a1 is a short video and a3 a Reel; a2 is a "video" next to the long videos; h2 is a carousel
    assert set(external_ids(client, format="short_video")) == {"a1", "a3"}
    assert set(external_ids(client, format="long_video")) == {"a2", "a4", "b1", "b2"}
    assert set(external_ids(client, format="image")) == {"h1", "h2"}


def test_filters_combine(client, data):
    names = external_ids(client, topic="iul", hook_type="question", competitor_id=data.alpha.id)
    assert names == ["a3"]


def test_the_window_decides_which_posts_are_in(client, data):
    assert "a-old" not in external_ids(client, window=7)
    assert "a-old" in external_ids(client, window=30)
    assert "a-old" in external_ids(client, window=90)


def test_paging(client, data):
    everything = external_ids(client, window=7, limit=100)
    page = client.get("/api/posts", params={"window": 7, "limit": 3, "offset": 3}).json()

    assert page["total"] == 8  # the total ignores limit and offset
    assert (page["limit"], page["offset"]) == (3, 3)
    assert [i["url"].rsplit("/", 1)[-1] for i in page["items"]] == everything[3:6]
    assert external_ids(client, window=7, limit=3, offset=9) == []


def test_too_new_counts_posts_that_would_be_ranked_in_a_few_hours(client, data):
    page = client.get("/api/posts", params={"window": 7}).json()
    assert page["too_new"] == 2  # a-new and h-new; c1-like posts of candidates never count
    assert client.get("/api/posts", params={"platform": "instagram"}).json()["too_new"] == 1
    assert client.get("/api/posts", params={"competitor_id": data.bravo.id}).json()["too_new"] == 0


def test_an_empty_result_is_still_a_valid_page(client, data):
    page = client.get("/api/posts", params={"topic": "annuities_retirement"}).json()
    assert page["items"] == []
    assert page["total"] == 0


# --- /api/competitors ------------------------------------------------------------------------


def test_the_leaderboard_hides_low_sample_competitors_by_default(client, data):
    page = client.get("/api/competitors", params={"window": 7}).json()

    assert [c["name"] for c in page["items"]] == ["alpha"]
    assert page["total"] == 1
    assert page["hidden_low_sample"] == 1  # bravo has 2 posts, 7 days want 3
    assert page["items"][0]["rank"] == 1


def test_low_sample_competitors_can_be_included_and_are_flagged(client, data):
    page = client.get("/api/competitors", params={"window": 7, "include_low_sample": True}).json()

    by_name = {c["name"]: c for c in page["items"]}
    assert set(by_name) == {"alpha", "bravo"}  # the candidate is never listed
    assert by_name["bravo"]["low_sample"] is True
    assert by_name["alpha"]["low_sample"] is False
    assert page["hidden_low_sample"] == 0
    scores = [c["score"] for c in page["items"]]
    assert scores == sorted(scores, reverse=True)


def test_a_competitor_lists_its_accounts_best_post_and_labels(client, data):
    item = client.get("/api/competitors", params={"window": 7}).json()["items"][0]

    assert item["kind"] == "agency"
    assert item["website"] == "https://alpha.test"
    assert item["posts_count"] == 4
    assert item["top_topic"] in {"final_expense", "iul"}
    assert item["best_post"]["url"].endswith("/a1")
    accounts = {a["platform"]: a for a in item["accounts"]}
    assert set(accounts) == {"youtube", "instagram"}
    assert accounts["instagram"]["location"] == {
        "status": "likely_us",
        "evidence": "US phone number 512-555-0142",
    }
    assert accounts["youtube"]["followers"] == 50000


def test_a_longer_window_counts_more_posts(client, data):
    seven = client.get("/api/competitors", params={"window": 7}).json()["items"][0]
    thirty = client.get("/api/competitors", params={"window": 30}).json()["items"][0]
    assert (seven["posts_count"], thirty["posts_count"]) == (4, 5)  # a-old joins at 30 days


def test_competitor_detail(client, data):
    detail = client.get(f"/api/competitors/{data.alpha.id}", params={"window": 7}).json()

    assert detail["window"] == 7
    assert detail["competitor"]["name"] == "alpha"
    assert detail["competitor"]["rank"] == 1
    assert [s["window"] for s in detail["scores_by_window"]] == [7, 30, 90]
    posts = [p["url"].rsplit("/", 1)[-1] for p in detail["top_posts"]]
    assert posts == ["a1", "a2", "a3", "a4"]  # its own ranked posts, best first
    assert all(p["creator"]["competitor_id"] == data.alpha.id for p in detail["top_posts"])


def test_a_low_sample_competitor_has_no_rank(client, data):
    detail = client.get(f"/api/competitors/{data.bravo.id}", params={"window": 7}).json()
    assert detail["competitor"]["low_sample"] is True
    assert detail["competitor"]["rank"] is None
    assert len(detail["top_posts"]) == 2


def test_a_candidate_has_a_detail_page_but_no_scores(client, data):
    detail = client.get(f"/api/competitors/{data.candidate.id}").json()
    assert detail["competitor"]["status"] == "candidate"
    assert detail["competitor"]["score"] is None
    assert detail["scores_by_window"] == []
    assert detail["top_posts"] == []


def test_an_unknown_competitor_is_a_404(client, data):
    assert client.get("/api/competitors/99999").status_code == 404


def test_a_competitor_id_too_big_for_sqlite_is_a_422(client, data):
    assert client.get(f"/api/competitors/{2**63}").status_code == 422
    assert client.get(f"/api/competitors/{2**63 - 1}").status_code == 404


# --- /api/insights ---------------------------------------------------------------------------


@pytest.fixture
def small_groups(monkeypatch):
    """The test data is tiny, so allow groups of 2 posts."""
    monkeypatch.setattr(config, "MIN_GROUP_SIZE", 2)


def test_insights_group_by_hook_and_hide_small_groups(client, data, small_groups):
    out = client.get("/api/insights", params={"window": 7, "group_by": "hook_type"}).json()

    groups = {g["value"]: g for g in out["groups"]}
    assert set(groups) == {"question", "warning"}
    assert groups["question"]["count"] == 2  # a1 and a3
    assert groups["question"]["avg_engagement"] == 80  # (100 + 60) / 2
    assert groups["question"]["label"] == "Opens with a question"
    scores = [g["avg_score"] for g in out["groups"]]
    assert scores == sorted(scores, reverse=True)
    # statistic and none have one post each
    assert (out["hidden_groups"], out["hidden_posts"]) == (2, 2)
    assert out["total_posts"] == 6  # hashtag posts have no labels, so they are not grouped here
    assert out["min_group_size"] == 2


def test_with_the_default_minimum_everything_is_hidden(client, data):
    out = client.get("/api/insights", params={"window": 7}).json()
    assert out["groups"] == []
    assert out["hidden_groups"] > 0
    assert out["min_group_size"] == config.MIN_GROUP_SIZE


def test_insights_group_by_topic(client, data, small_groups):
    out = client.get("/api/insights", params={"group_by": "topic"}).json()
    groups = {g["value"]: g["count"] for g in out["groups"]}
    assert groups == {"final_expense": 2, "iul": 2, "term_life": 2}


def test_insights_by_format_use_the_same_three_groups(client, data, small_groups):
    out = client.get("/api/insights", params={"group_by": "format"}).json()
    assert {g["value"]: g["count"] for g in out["groups"]} == {
        "long_video": 4,
        "short_video": 2,
        "image": 2,
    }
    assert out["groups"][0]["label"] in {
        "Videos longer than 3 minutes",
        "Videos of 3 minutes or less, and Reels",
        "Single images and image carousels",
    }


def test_insights_by_format_can_be_limited_to_a_platform(client, data, small_groups):
    out = client.get("/api/insights", params={"group_by": "format", "platform": "instagram"}).json()
    assert [(g["value"], g["count"]) for g in out["groups"]] == [("image", 2)]
    assert out["platform"] == "instagram"


# --- /api/meta, runs, keywords ---------------------------------------------------------------


def test_meta_describes_what_the_ui_can_pick(client, data):
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, youtube_api_key="k")

    meta = client.get("/api/meta").json()

    assert meta["windows"] == [7, 30, 90]
    assert meta["default_window"] == 7
    platforms = {p["id"]: p for p in meta["platforms"]}
    assert platforms["youtube"]["enabled"] is True
    assert platforms["instagram"]["enabled"] is False  # no Instagram keys in these settings
    assert platforms["youtube"]["posts"] == 9  # every youtube post is stored, ranked or not
    assert platforms["instagram"]["posts"] == 4
    taxonomy = meta["taxonomy"]
    assert taxonomy["version"] >= 1
    assert "final_expense" in [t["id"] for t in taxonomy["topics"]]
    assert "question" in [h["id"] for h in taxonomy["hooks"]]
    assert "book_call" in [c["id"] for c in taxonomy["ctas"]]
    assert [f["id"] for f in taxonomy["formats"]] == ["long_video", "short_video", "image"]
    thresholds = meta["thresholds"]
    assert thresholds["strong_score"] == 90
    assert thresholds["min_posts_by_window"] == {"7": 3, "30": 5, "90": 5}
    assert meta["counts"]["competitors"] == 2  # the candidate is not counted
    assert meta["counts"]["ranked_posts"] == 8
    assert meta["last_updated"].endswith("Z")


def test_meta_on_an_empty_database(client):
    meta = client.get("/api/meta").json()
    assert meta["last_updated"] is None
    assert meta["counts"] == {
        "competitors": 0,
        "posts": 0,
        "labeled_posts": 0,
        "ranked_posts": 0,
        "flex_posts": 0,
    }


def test_runs_come_newest_first(client, session, data):
    run = runs.start_run(session, "collect", "youtube")
    runs.finish_run(session, run, status=runs.PARTIAL, items_ok=3, items_failed=1, quota_used=7)

    items = client.get("/api/runs").json()

    assert items[0]["kind"] == "collect"
    assert (items[0]["status"], items[0]["quota_used"]) == ("partial", 7)
    assert items[0]["finished_at"].endswith("Z")
    assert items[1]["kind"] == "rank"
    assert [r["id"] for r in items] == sorted((r["id"] for r in items), reverse=True)
    assert len(client.get("/api/runs", params={"limit": 1}).json()) == 1


def test_a_fresh_database_has_no_keywords(client):
    # Nothing is built in: every search term and hashtag is added in the Sources tab.
    assert client.get("/api/keywords").json() == []


def test_keywords_are_listed_with_their_platform(client):
    client.post("/api/keywords", json={"term": "life insurance agent"})
    client.post("/api/keywords", json={"term": "lifeinsurance", "platform": "instagram"})

    items = client.get("/api/keywords").json()

    assert [(k["term"], k["platform"], k["active"]) for k in items] == [
        ("life insurance agent", None, True),
        ("lifeinsurance", "instagram", True),
    ]


# --- changing keywords and the hashtag budget ------------------------------------------------


@pytest.mark.parametrize(
    ("term", "platform", "stored"),
    [
        ("whole life insurance agent", None, "whole life insurance agent"),
        ("#FinalExpense", "instagram", "finalexpense"),
    ],
)
def test_search_terms_and_hashtags_can_be_added_toggled_and_deleted(client, term, platform, stored):
    added = client.post("/api/keywords", json={"term": term, "platform": platform})
    assert added.status_code == 201
    keyword = added.json()
    assert (keyword["term"], keyword["platform"], keyword["active"]) == (stored, platform, True)

    again = client.post("/api/keywords", json={"term": term.upper(), "platform": platform})
    assert again.status_code == 409

    off = client.patch(f"/api/keywords/{keyword['id']}", json={"active": False})
    assert (off.status_code, off.json()["active"]) == (200, False)

    assert client.delete(f"/api/keywords/{keyword['id']}").status_code == 204
    assert client.delete(f"/api/keywords/{keyword['id']}").status_code == 404
    assert client.patch(f"/api/keywords/{keyword['id']}", json={"active": True}).status_code == 404
    assert client.get("/api/keywords").json() == []


@pytest.mark.parametrize(
    "body",
    [
        {"term": "life insurance", "platform": "instagram"},  # a hashtag has no spaces
        {"term": "a"},  # too short
        {"term": "agent", "platform": "tiktok"},
        {"platform": "instagram"},  # no term
    ],
)
def test_bad_keywords_are_a_422(client, body):
    response = client.post("/api/keywords", json=body)
    assert response.status_code == 422


def test_a_keyword_id_too_big_for_sqlite_is_a_422(client):
    assert client.delete(f"/api/keywords/{2**63}").status_code == 422


def test_the_hashtag_budget_counts_different_hashtags_of_the_last_7_days(client, session):
    run = runs.start_run(session, "collect", "instagram")
    runs.finish_run(session, run, status=runs.OK, hashtags=["iul", "lifeinsurance"])
    run = runs.start_run(session, "collect", "instagram")
    runs.finish_run(session, run, status=runs.OK, hashtags=["iul"])  # same tag: same slot

    budget = client.get("/api/hashtag-budget").json()

    assert (budget["limit"], budget["used"], budget["free"]) == (30, 2, 28)
    assert {slot["tag"] for slot in budget["slots"]} == {"iul", "lifeinsurance"}
    assert budget["next_free_at"].endswith("Z")


def test_the_hashtag_budget_is_empty_when_30_hashtags_were_searched(client, session):
    run = runs.start_run(session, "collect", "instagram")
    runs.finish_run(session, run, status=runs.OK, hashtags=[f"tag{i}" for i in range(30)])

    budget = client.get("/api/hashtag-budget").json()

    assert (budget["used"], budget["free"]) == (30, 0)


# --- serving the built frontend --------------------------------------------------------------


def test_the_built_frontend_is_served_after_the_api_routes(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.main import mount_frontend

    (tmp_path / "index.html").write_text("<h1>the app</h1>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    small = FastAPI()

    @small.get("/api/health")
    def health():
        return {"status": "ok"}

    assert mount_frontend(small, tmp_path) is True
    with TestClient(small) as client:
        assert client.get("/api/health").json() == {"status": "ok"}  # the API still wins
        assert "the app" in client.get("/").text
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/api/nothing-here").status_code == 404


def test_without_a_build_nothing_is_mounted(tmp_path):
    from fastapi import FastAPI

    from app.main import mount_frontend

    small = FastAPI()
    assert mount_frontend(small, tmp_path) is False
    assert not any(route.name == "frontend" for route in small.routes)
