from sqlalchemy import select

from app.discovery.keywords import DEFAULT_HASHTAGS, DEFAULT_KEYWORDS, seed_keywords
from app.models import Keyword


def test_seed_adds_defaults_once(session):
    assert seed_keywords(session) == len(DEFAULT_KEYWORDS) + len(DEFAULT_HASHTAGS)
    assert seed_keywords(session) == 0  # second run adds nothing

    terms = list(session.scalars(select(Keyword.term).where(Keyword.platform.is_(None))))
    assert sorted(terms) == sorted(DEFAULT_KEYWORDS)


def test_seed_adds_the_instagram_hashtags(session):
    seed_keywords(session)

    tags = session.scalars(select(Keyword).where(Keyword.platform == "instagram")).all()
    assert [k.term for k in tags] == list(DEFAULT_HASHTAGS)
    assert all(k.active for k in tags)


def test_seed_keeps_existing_custom_keyword(session):
    session.add(Keyword(term="custom term", platform="youtube", active=False))
    session.commit()

    seed_keywords(session)

    custom = session.scalars(select(Keyword).where(Keyword.term == "custom term")).one()
    assert custom.active is False
