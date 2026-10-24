import pytest

from app.labeling.rules import (
    TOPIC_KEYWORDS,
    content_hash,
    detect_cta,
    detect_hook,
    detect_topic,
    label_post,
    opening_line,
)
from app.labeling.taxonomy import CTAS, HOOKS, TOPICS


def test_every_rule_uses_a_value_from_the_taxonomy():
    assert set(TOPIC_KEYWORDS) <= set(TOPICS)


@pytest.mark.parametrize(
    ("title", "text", "topic"),
    [
        ("Final expense explained", None, "final_expense"),
        ("Is burial insurance worth it?", "funeral costs", "final_expense"),
        ("Don't buy term life until you watch this", None, "term_life"),
        ("Why your IUL is underperforming", None, "iul"),
        ("Mortgage protection for new homeowners", None, "mortgage_protection"),
        ("Roth vs annuity for retirement income", None, "annuities_retirement"),
        ("Join my team and become an agent", None, "agent_recruiting"),
        ("Cold call script that books appointments", None, "sales_training"),
        ("Infinite banking: be your own bank", None, "infinite_banking"),
        ("What living benefits cover", "chronic illness rider", "living_benefits"),
        ("Texas Life Exam Quiz: Lesson 8 #Shorts", None, "sales_training"),
        ("How to avoid chargebacks and grow your book of business", None, "sales_training"),
        ("Client Testimonial | Chris Thomas", None, "client_story"),
        ("No medical exam life insurance", None, "other"),  # "exam" alone must not match
        ("A good day", "nothing about the topic", "other"),
        (None, None, "other"),
    ],
)
def test_topic(title, text, topic):
    assert detect_topic(title, text)[0] == topic


def test_a_title_keyword_counts_more_than_a_description_keyword():
    # One "whole life" in the title (2) beats one "term life" in the text (1).
    assert detect_topic("Whole life", "term life")[0] == "whole_life"


def test_keywords_match_whole_words_only():
    # "description" contains "script" and "trusted" contains "trust".
    assert detect_topic("See the description", "a trusted friend")[0] == "other"


@pytest.mark.parametrize(
    ("hook_text", "hook"),
    [
        ("5 ways to sell final expense", "how_to_list"),
        ("How to get your first client", "how_to_list"),
        ("$28K in sales, $0 profit", "statistic"),
        ("97% of agents quit", "statistic"),
        ("Is whole life a scam?", "question"),
        ("Is IUL worth it?", "question"),
        ("The myth about term life", "contrarian"),
        ("Nobody tells you this about IUL", "contrarian"),
        ("Don't buy term life until you watch this", "warning"),
        ("Avoid this mistake with annuities", "warning"),
        ("I made my first sale today", "personal_story"),
        ("My client lost her husband", "personal_story"),
        ("5 star review from a happy family", "social_proof"),
        ("Made $5,000 in a week", "statistic"),
        ("Honest review from a client", "social_proof"),
        ("The secret agents hide", "curiosity_gap"),
        ("Get a free quote in minutes", "direct_offer"),
        ("Good morning everyone", "none"),
        (None, "none"),
        ("", "none"),
    ],
)
def test_hook(hook_text, hook):
    assert detect_hook(hook_text) == hook


def test_first_matching_hook_rule_wins():
    # A list and a question: the list rule is checked first.
    assert detect_hook("How to pick term life, and why?") == "how_to_list"


@pytest.mark.parametrize(
    ("title", "text", "cta"),
    [
        (None, "Call or text me today", "call_or_text"),
        (None, "Reach me at 512-555-0142", "call_or_text"),
        (None, "Comment QUOTE and I will send it", "comment_or_dm_keyword"),
        (None, "DM me the word LIFE", "comment_or_dm_keyword"),
        (None, "Link in bio for details", "link_in_bio"),
        (None, "Book a call at calendly.com/x", "book_call"),
        (None, "Join my team today", "join_team"),
        (None, "Subscribe for more videos", "follow_subscribe"),
        ("Plain title", "Plain text", "none"),
        (None, None, "none"),
    ],
)
def test_cta(title, text, cta):
    assert detect_cta(title, text) == cta


def test_more_commercial_cta_wins_over_subscribe():
    assert detect_cta(None, "Join my team! Also subscribe.") == "join_team"


def test_cta_far_down_a_long_description_is_ignored():
    assert detect_cta(None, "x " * 400 + "book a call") == "none"


def test_opening_line_uses_the_title_first():
    assert opening_line("My title", "First line\nSecond") == "My title"


def test_opening_line_falls_back_to_first_non_empty_line():
    assert opening_line(None, "\n\n  Why   IUL?  \nmore") == "Why IUL?"


def test_opening_line_is_cut_at_150_characters():
    assert len(opening_line("x" * 400, None)) == 150
    assert opening_line(None, None) is None


def test_content_hash_changes_only_with_the_words():
    assert content_hash("a", "b") == content_hash("a", "b")
    assert content_hash("a", "b") != content_hash("a", "c")
    assert content_hash("ab", None) != content_hash("a", "b")


@pytest.mark.parametrize(
    ("title", "text"),
    [
        ("Don't buy term life until you watch this", "Call or text 512-555-0142"),
        (None, "Why is your IUL underperforming?\nComment QUOTE"),
        ("", ""),
        (None, None),
    ],
)
def test_label_post_only_returns_values_from_the_taxonomy(title, text):
    result = label_post(title, text)
    assert result.topic in TOPICS
    assert result.hook_type in HOOKS
    assert result.cta in CTAS
    assert 0 <= result.confidence <= 1
    assert result.is_relevant is True


def test_confidence_is_low_without_keywords_and_grows_with_hits():
    none = label_post("Good morning", None).confidence
    one = label_post("Final expense", None).confidence
    assert none < one
