import pytest

from app.discovery.linking import (
    Candidate,
    LinkDecision,
    candidates_from,
    choose_handle,
    extract_handles,
    points_back,
    resolve_conflicts,
)


@pytest.mark.parametrize(
    ("text", "handles"),
    [
        ("Follow me https://www.instagram.com/Jane.Doe/ today", {"jane.doe"}),
        ("instagram.com/janedoe", {"janedoe"}),
        ("http://instagram.com/janedoe?hl=en&x=1", {"janedoe"}),
        ("IG: INSTAGRAM.COM/JaneDoe.", {"janedoe"}),
        ("instagram.com/a_b and instagram.com/c.d", {"a_b", "c.d"}),
        ("instagram.com/p/CxYz123/ and instagram.com/reel/Abc/", set()),  # posts, not accounts
        ("instagram.com/explore/tags/insurance", set()),
        ("My instagram is @janedoe", set()),  # a bare @mention is not a link
        ("no links here", set()),
        ("", set()),
        (None, set()),
    ],
)
def test_extract_handles(text, handles):
    assert extract_handles(text) == handles


def test_a_handle_counts_once_per_description():
    texts = ["instagram.com/jane instagram.com/jane", "instagram.com/jane", "nothing"]
    assert candidates_from(texts) == [Candidate("jane", 2)]


def test_a_handle_seen_once_is_not_a_candidate():
    # Guests and partners are usually tagged once.
    assert candidates_from(["instagram.com/guest", "instagram.com/other", None]) == []


def test_candidates_are_ordered_by_mentions():
    texts = ["instagram.com/a instagram.com/b"] * 2 + ["instagram.com/b"] * 3
    assert candidates_from(texts) == [Candidate("b", 5), Candidate("a", 2)]


def test_one_clear_handle_is_chosen():
    decision = choose_handle([Candidate("jane", 6)], confirmed=set())
    assert (decision.handle, decision.confirmed) == ("jane", False)
    assert "6 descriptions" in decision.reason


def test_a_handle_mentioned_twice_as_often_as_the_next_wins():
    candidates = [Candidate("team", 12), Candidate("guest", 6)]
    assert choose_handle(candidates, set()).handle == "team"


def test_a_tie_is_not_linked():
    candidates = [Candidate("lifeinsurea", 6), Candidate("rogershort", 6)]
    decision = choose_handle(candidates, set())
    assert decision.handle is None
    assert "none clearly" in decision.reason


def test_a_close_second_is_not_linked():
    assert choose_handle([Candidate("a", 31), Candidate("b", 20)], set()).handle is None


def test_no_candidates_means_no_link():
    assert choose_handle([], set()).handle is None


def test_an_instagram_profile_that_links_back_breaks_a_tie():
    candidates = [Candidate("lifeinsurea", 6), Candidate("rogershort", 6)]
    decision = choose_handle(candidates, confirmed={"lifeinsurea"})
    assert (decision.handle, decision.confirmed) == ("lifeinsurea", True)


def test_two_profiles_linking_back_is_ambiguous():
    candidates = [Candidate("a", 3), Candidate("b", 3)]
    assert choose_handle(candidates, confirmed={"a", "b"}).handle is None


@pytest.mark.parametrize(
    ("bio", "website", "expected"),
    [
        ("Watch me on youtube.com/@janedoe", None, True),
        (None, "https://www.youtube.com/@JaneDoe", True),
        ("youtube.com/channel/UCabc123", None, True),
        ("youtube.com/@janedoe2", None, False),  # another channel starting the same way
        ("youtube.com/@someoneelse", None, False),
        ("link in bio", "https://linktr.ee/jane", False),
        (None, None, False),
    ],
)
def test_points_back(bio, website, expected):
    assert points_back(bio, website, "@janedoe", "UCabc123") is expected


def test_points_back_without_a_handle_only_uses_the_channel_id():
    assert points_back("youtube.com/@janedoe", None, None, "UCabc123") is False
    assert points_back("youtube.com/channel/UCabc123", None, "Jane Doe", "UCabc123") is True


def test_two_competitors_claiming_one_handle_both_lose_it():
    # Two channels of one team link the same Instagram account: we cannot say which one owns it.
    decisions = {
        1: LinkDecision("agentleadlab_", "linked in 37 descriptions"),
        2: LinkDecision("agentleadlab_", "linked in 50 descriptions"),
        3: LinkDecision("other", "linked in 4 descriptions"),
    }
    resolved = resolve_conflicts(decisions)
    assert resolved[1].handle is None
    assert resolved[2].handle is None
    assert "claimed by several competitors" in resolved[1].reason
    assert resolved[3].handle == "other"


def test_the_competitor_the_profile_links_back_to_keeps_a_shared_handle():
    decisions = {
        1: LinkDecision("shared", "linked in 10 descriptions"),
        2: LinkDecision("shared", "the Instagram profile links back to the channel", True),
    }
    resolved = resolve_conflicts(decisions)
    assert resolved[1].handle is None
    assert resolved[2].handle == "shared"


def test_competitors_without_a_link_are_left_alone():
    decisions = {1: LinkDecision(None, "no link"), 2: LinkDecision(None, "no link")}
    assert resolve_conflicts(decisions) == decisions
