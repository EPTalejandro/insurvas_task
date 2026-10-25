"""A small, ranked dataset for the API tests. Dates are relative to the real clock because the
API itself uses it (to find posts that are too new)."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import select

from app.models import Competitor, Creator, Label, Post
from app.ranking.service import rank_all


def add_post(
    session,
    creator,
    external_id,
    *,
    likes,
    days=None,
    hours=None,
    comments=0,
    format="long_video",
    topic=None,
    hook=None,
    platform="youtube",
    location_status=None,
    location_evidence=None,
):
    age = timedelta(days=days or 0, hours=hours or 0)
    post = Post(
        creator_id=creator.id,
        platform=platform,
        external_id=external_id,
        url=f"https://example.com/{external_id}",
        title=f"Title {external_id}",
        text=f"Caption of {external_id}",
        # SQLite stores datetimes without a timezone; they are UTC.
        published_at=(datetime.now(UTC) - age).replace(tzinfo=None),
        format=format,
        likes=likes,
        comments=comments,
        location_status=location_status,
        location_evidence=location_evidence,
    )
    session.add(post)
    session.flush()
    if topic or hook:
        session.add(
            Label(
                post_id=post.id,
                topic=topic,
                hook_type=hook,
                hook_text=f"Hook of {external_id}",
                cta="none",
                confidence=0.6,
                labeler="rules",
                taxonomy_version=1,
            )
        )
    return post


def add_competitor(session, name, *, kind="agent", status="active", followers=1000):
    competitor = Competitor(name=name, kind=kind, status=status, website=f"https://{name}.test")
    creator = Creator(
        competitor=competitor,
        platform="youtube",
        external_id=f"UC-{name}",
        handle=f"@{name}",
        name=name,
        url=f"https://youtube.com/@{name}",
        followers=followers,
        kind=kind,
        country="US",
        location_status="us",
        location_evidence="channel country: US",
    )
    session.add(creator)
    session.flush()
    return competitor, creator


def build_dataset(session) -> SimpleNamespace:
    """Two active competitors, one candidate, one hashtag, all ranked at the real time."""
    alpha, alpha_yt = add_competitor(session, "alpha", kind="agency", followers=50000)
    alpha_ig = Creator(
        competitor=alpha,
        platform="instagram",
        external_id="ig-alpha",
        handle="alpha_ig",
        name="Alpha on Instagram",
        followers=900,
        kind="agency",
        location_status="likely_us",
        location_evidence="US phone number 512-555-0142",
    )
    session.add(alpha_ig)
    bravo, bravo_yt = add_competitor(session, "bravo", followers=2000)
    candidate, candidate_yt = add_competitor(session, "candidate", status="candidate")
    tag = Creator(
        platform="instagram",
        external_id="hashtag:1",
        handle="#lifeinsurance",
        name="#lifeinsurance top posts",
        kind="hashtag",
    )
    session.add(tag)
    session.flush()

    # alpha: 4 posts in the last 7 days, 1 older, 1 posted an hour ago (too new to rank)
    add_post(session, alpha_yt, "a1", days=1, likes=100, topic="final_expense", hook="question",
             format="short_video")  # fmt: skip
    add_post(session, alpha_yt, "a2", days=2, likes=80, topic="final_expense", hook="statistic",
             format="video")  # fmt: skip
    add_post(session, alpha_yt, "a3", days=3, likes=60, topic="iul", hook="question",
             format="reel")  # fmt: skip
    add_post(session, alpha_yt, "a4", days=4, likes=40, topic="iul", hook="none")
    add_post(session, alpha_yt, "a-old", days=20, likes=70, topic="iul", hook="question")
    add_post(session, alpha_yt, "a-new", hours=1, likes=50, topic="iul", hook="question")
    # bravo: only 2 posts, so a "low sample" competitor in the 7-day window
    add_post(session, bravo_yt, "b1", days=1, likes=30, topic="term_life", hook="warning")
    add_post(session, bravo_yt, "b2", days=5, likes=20, topic="term_life", hook="warning")
    # the candidate is not an active competitor: its posts are never ranked
    add_post(session, candidate_yt, "c1", days=1, likes=999, topic="iul", hook="question")

    # hashtag posts: only the ones that look US-based are ranked
    def hashtag_post(name, likes, status, evidence, **age):
        add_post(
            session, tag, name, likes=likes, platform="instagram", format="image",
            location_status=status, location_evidence=evidence, **age,
        )  # fmt: skip

    hashtag_post("h1", 500, "likely_us", "US phone number 615-905-6050", days=2)
    hashtag_post("h2", 300, "probable_us", "English caption with US cues: iul", days=3)
    h2 = session.scalars(select(Post).where(Post.external_id == "h2")).one()
    h2.format = "carousel"  # an image group member, like "image"
    hashtag_post("h3", 900, "non_us", "caption is not in English", days=2)
    hashtag_post("h-new", 40, "probable_us", "English caption with US cues: iul", hours=2)
    session.commit()
    rank_all(session)
    return SimpleNamespace(
        alpha=alpha, bravo=bravo, candidate=candidate, alpha_yt=alpha_yt, alpha_ig=alpha_ig, tag=tag
    )
