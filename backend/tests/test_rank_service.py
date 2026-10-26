from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models import Competitor, CompetitorScore, Creator, Label, Post, PostScore, Run
from app.ranking.service import rank_all

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


def add_competitor(session, name, *, status="active", followers=1000, relevant=True):
    competitor = Competitor(name=name, kind="agent", status=status)
    creator = Creator(
        competitor=competitor,
        platform="youtube",
        external_id=name,
        handle=name,
        name=name,
        followers=followers,
        is_relevant=relevant,
    )
    session.add(creator)
    session.flush()
    return competitor, creator


def add_post(
    session, creator, external_id, *, days, likes=10, topic=None, relevant=True, flex=False
):
    post = Post(
        creator_id=creator.id,
        platform="youtube",
        external_id=external_id,
        url=f"https://example.com/{external_id}",
        # SQLite hands datetimes back without a timezone, so store them the same way.
        published_at=(NOW - timedelta(days=days)).replace(tzinfo=None),
        likes=likes,
        comments=0,
    )
    session.add(post)
    session.flush()
    if topic:
        session.add(
            Label(
                post_id=post.id,
                topic=topic,
                hook_type="question",
                labeler="rules",
                taxonomy_version=1,
                is_relevant=relevant,
                is_flex=flex,
            )
        )
    return post


def test_scores_are_written_for_every_window(session):
    _, creator = add_competitor(session, "jane")
    add_post(session, creator, "a", days=0.5)
    add_post(session, creator, "b", days=3)
    add_post(session, creator, "c", days=20)
    session.commit()

    run = rank_all(session, NOW)

    counts = {}
    for score in session.scalars(select(PostScore)):
        counts[score.window_days] = counts.get(score.window_days, 0) + 1
    assert counts == {7: 2, 30: 3, 90: 3}
    assert (run.kind, run.status, run.items_ok) == ("rank", "ok", 8)
    assert "7d: 2 posts, 1 competitors" in run.message


def test_competitor_scores_have_labels_best_post_and_low_sample(session):
    competitor, creator = add_competitor(session, "jane")
    best = add_post(session, creator, "best", days=1, likes=100, topic="iul")
    add_post(session, creator, "ok", days=2, likes=20, topic="iul")
    session.commit()

    rank_all(session, NOW)

    row = session.get(CompetitorScore, (competitor.id, 7))
    assert row.posts_count == 2
    assert row.best_post_id == best.id
    assert row.top_topic == "iul"
    assert row.top_hook == "question"
    assert row.low_sample is True  # 7-day windows want at least 3 posts


def test_posts_of_inactive_competitors_are_not_ranked(session):
    _, active = add_competitor(session, "active")
    _, candidate = add_competitor(session, "candidate", status="candidate")
    add_post(session, active, "a", days=2)
    add_post(session, candidate, "b", days=2)
    session.commit()

    rank_all(session, NOW)

    ranked = {s.post_id for s in session.scalars(select(PostScore))}
    assert ranked == {session.scalars(select(Post).where(Post.external_id == "a")).one().id}


def test_irrelevant_labels_and_creators_are_not_ranked(session):
    _, creator = add_competitor(session, "jane")
    _, hidden = add_competitor(session, "hidden", relevant=False)
    add_post(session, creator, "off-topic", days=2, topic="other", relevant=False)
    add_post(session, creator, "unlabeled", days=2)
    add_post(session, hidden, "hidden-post", days=2)
    session.commit()

    rank_all(session, NOW)

    ranked = {s.post_id for s in session.scalars(select(PostScore))}
    unlabeled = session.scalars(select(Post).where(Post.external_id == "unlabeled")).one()
    assert ranked == {unlabeled.id}


def test_posts_older_than_90_days_are_ignored(session):
    _, creator = add_competitor(session, "jane")
    add_post(session, creator, "old", days=120)
    session.commit()

    rank_all(session, NOW)

    assert session.scalars(select(PostScore)).all() == []


def test_ranking_twice_replaces_the_scores(session):
    _, creator = add_competitor(session, "jane")
    post = add_post(session, creator, "a", days=2, likes=10)
    session.commit()
    rank_all(session, NOW)

    post.likes = 500
    session.commit()
    rank_all(session, NOW)

    rows = session.scalars(select(PostScore).where(PostScore.window_days == 7)).all()
    assert len(rows) == 1
    assert rows[0].adjusted_engagement > 100
    assert len(session.scalars(select(Run).where(Run.kind == "rank")).all()) == 2


def test_posts_of_accounts_without_an_active_competitor_are_not_ranked(session):
    creator = Creator(platform="youtube", external_id="solo", handle="solo", name="solo")
    session.add(creator)
    session.flush()
    add_post(session, creator, "a", days=2)
    session.commit()

    rank_all(session, NOW)

    # No active competitor means the post does not count at all.
    assert session.scalars(select(PostScore)).all() == []
    assert session.scalars(select(CompetitorScore)).all() == []


# --- hashtag posts: no author, so the caption's location decides ---------------------------


def add_hashtag_post(session, creator, external_id, *, status, likes=100, days=2):
    post = add_post(session, creator, external_id, days=days, likes=likes)
    post.platform = "instagram"
    post.location_status = status
    return post


def make_hashtag_creator(session):
    creator = Creator(
        platform="instagram",
        external_id="hashtag:1",
        handle="#lifeinsurance",
        name="#lifeinsurance top posts",
        kind="hashtag",
    )
    session.add(creator)
    session.flush()
    return creator


def test_only_hashtag_posts_that_look_us_based_are_ranked(session):
    tag = make_hashtag_creator(session)
    wanted = {
        "likely": add_hashtag_post(session, tag, "likely", status="likely_us"),
        "probable": add_hashtag_post(session, tag, "probable", status="probable_us"),
    }
    for name in ("unverified", "non_us", "unjudged"):
        status = None if name == "unjudged" else name
        add_hashtag_post(session, tag, name, status=status)
    session.commit()

    rank_all(session, NOW)

    ranked = {s.post_id for s in session.scalars(select(PostScore))}
    assert ranked == {p.id for p in wanted.values()}


def test_hashtag_posts_have_no_usual_and_no_competitor_score(session):
    tag = make_hashtag_creator(session)
    for index in range(4):  # enough posts for a baseline, if there were an author
        add_hashtag_post(session, tag, f"p{index}", status="likely_us", likes=50 + index * 10)
    session.commit()

    rank_all(session, NOW)

    scores = session.scalars(select(PostScore).where(PostScore.window_days == 7)).all()
    assert len(scores) == 4
    assert all(s.outperformance is None for s in scores)
    assert all("usual" not in s.reason for s in scores)
    assert session.scalars(select(CompetitorScore)).all() == []


def youtube_scores(session):
    rows = session.execute(
        select(PostScore.post_id, PostScore.score)
        .join(Post, Post.id == PostScore.post_id)
        .where(PostScore.window_days == 7, Post.platform == "youtube")
    )
    return {row.post_id: row.score for row in rows}


def test_hashtag_posts_do_not_change_the_youtube_scores(session):
    competitor, creator = add_competitor(session, "jane")
    add_post(session, creator, "a", days=2, likes=30)
    add_post(session, creator, "b", days=3, likes=60)
    session.commit()
    rank_all(session, NOW)
    before = youtube_scores(session)

    tag = make_hashtag_creator(session)
    add_hashtag_post(session, tag, "h", status="likely_us", likes=5000)
    session.commit()
    rank_all(session, NOW)

    assert before and youtube_scores(session) == before  # percentiles are per platform
    assert session.get(CompetitorScore, (competitor.id, 7)) is not None


def test_flex_posts_are_not_ranked_and_do_not_count_for_their_competitor(session):
    competitor, creator = add_competitor(session, "jane")
    flex = add_post(
        session, creator, "flex", days=2, likes=5000, topic="agent_recruiting", flex=True
    )
    useful = [
        add_post(session, creator, f"u{i}", days=2 + i, likes=20, topic="iul") for i in range(3)
    ]
    session.commit()

    rank_all(session, NOW)

    scored = set(session.scalars(select(PostScore.post_id).where(PostScore.window_days == 7)))
    assert flex.id not in scored
    assert {p.id for p in useful} <= scored
    score = session.scalars(
        select(CompetitorScore).where(
            CompetitorScore.competitor_id == competitor.id, CompetitorScore.window_days == 7
        )
    ).one()
    assert score.posts_count == 3
    assert score.best_post_id != flex.id
