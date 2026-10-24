import pytest

from app.discovery.classify import classify_creator


def test_carrier_is_excluded():
    result = classify_creator("State Farm", "Official channel. Insurance, banking and more.")
    assert result.is_relevant is False
    assert result.reason == "insurance carrier"


def test_agent_of_a_carrier_is_not_a_carrier():
    # Must not be excluded: the name says this is a person who sells for the carrier.
    result = classify_creator("Jane Doe - State Farm Agent", "Life insurance in Austin")
    assert result.is_relevant is True
    assert result.kind == "agent"


def test_bio_mentioning_a_carrier_does_not_exclude_the_agent():
    result = classify_creator("Mike Rivera", "Life insurance agent appointed with Mutual of Omaha")
    assert result.is_relevant is True


def test_agency_word_in_name_makes_an_agency():
    result = classify_creator("Sunrise Insurance Agency", "Term and whole life")
    assert (result.kind, result.is_relevant) == ("agency", True)


def test_unrelated_channel_is_not_relevant():
    result = classify_creator("Pixel Quest", "Gaming videos every day")
    assert result.is_relevant is False
    assert result.kind is None


def test_insurance_terms_only_defaults_to_agent():
    result = classify_creator("Tom Lee", "Final expense and IUL explained")
    assert (result.kind, result.is_relevant) == ("agent", True)


@pytest.mark.parametrize("name", ["AIG", "Aflac", "Ethos", "Northwestern Mutual"])
def test_known_carriers(name):
    assert classify_creator(name, "life insurance").is_relevant is False


def test_short_carrier_names_need_whole_word_matches():
    # "aig" must not match inside another word.
    assert classify_creator("Haigh Life Insurance Tips", "life insurance").is_relevant is True
