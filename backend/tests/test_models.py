import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import Competitor, Creator, Label, Post, PostScore


def make_post(session, creator: Creator, external_id: str = "vid1") -> Post:
    post = Post(
        creator=creator,
        platform=creator.platform,
        external_id=external_id,
        url=f"https://example.com/{external_id}",
        views=None,  # unknown, not zero
        likes=120,
    )
    session.add(post)
    session.commit()
    return post


def test_post_with_label_and_score_round_trip(session):
    competitor = Competitor(name="Jane Agent", kind="agent", status="active")
    creator = Creator(
        competitor=competitor,
        platform="youtube",
        external_id="UC123",
        handle="@jane",
        name="Jane",
    )
    session.add(creator)
    post = make_post(session, creator)
    post.label = Label(topic="term_life", labeler="rules", taxonomy_version=1)
    post.scores.append(PostScore(window_days=7, score=85.0, rank_in_platform=1))
    session.commit()

    saved = session.scalars(select(Post)).one()
    assert saved.creator.competitor.name == "Jane Agent"
    assert saved.label.topic == "term_life"
    assert saved.scores[0].window_days == 7
    assert saved.views is None


def test_creator_can_exist_before_being_linked_to_a_competitor(session):
    creator = Creator(platform="youtube", external_id="UC9", handle="@new", name="New")
    session.add(creator)
    session.commit()
    assert creator.competitor_id is None


def test_same_platform_and_external_id_is_rejected(session):
    creator = Creator(platform="youtube", external_id="UC1", handle="@a", name="a")
    session.add(creator)
    make_post(session, creator, external_id="dup")
    session.add(Post(creator=creator, platform="youtube", external_id="dup", url="u"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
