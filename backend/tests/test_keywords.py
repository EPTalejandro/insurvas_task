import pytest

from app.discovery.keywords import normalize_keyword


@pytest.mark.parametrize(
    ("term", "platform", "stored"),
    [
        ("  whole   life agent ", None, "whole life agent"),
        ("#FinalExpense", "instagram", "finalexpense"),
        ("iul_tips", "instagram", "iul_tips"),
    ],
)
def test_normalize_keyword(term, platform, stored):
    assert normalize_keyword(term, platform) == stored


@pytest.mark.parametrize(
    ("term", "platform"),
    [
        ("a", None),  # too short
        ("x" * 81, None),  # too long
        ("life insurance", "instagram"),  # a hashtag has no spaces
        ("#", "instagram"),
        ("life-insurance", "instagram"),
        ("agent", "tiktok"),
    ],
)
def test_normalize_keyword_rejects_bad_terms(term, platform):
    with pytest.raises(ValueError):
        normalize_keyword(term, platform)
