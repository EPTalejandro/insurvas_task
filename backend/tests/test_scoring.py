import math
from datetime import UTC, datetime, timedelta

import pytest

from app.ranking import config
from app.ranking.scoring import (
    PostInput,
    ScoredPost,
    adjusted_engagement,
    age_days,
    as_utc,
    engagements,
    is_eligible,
    make_reason,
    percentile_rank,
    score_competitor,
    score_posts,
)

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


def make_post(
    post_id,
    *,
    creator=1,
    platform="youtube",
    days=2.0,
    likes=10,
    comments=0,
    shares=None,
    views=None,
    followers=1000,
    counts=True,
    known_author=True,
) -> PostInput:
    return PostInput(
        post_id=post_id,
        creator_id=creator,
        platform=platform,
        published_at=NOW - timedelta(days=days),
        likes=likes,
        comments=comments,
        shares=shares,
        views=views,
        followers=followers,
        counts=counts,
        known_author=known_author,
    )


def results_by_id(posts, window=7):
    return {r.post_id: r for r in score_posts(posts, window, NOW)}


# --- building blocks ---------------------------------------------------------------------


def test_percentile_rank():
    values = [1, 2, 3]
    assert percentile_rank(1, values) == pytest.approx(100 * 0.5 / 3)
    assert percentile_rank(2, values) == 50
    assert percentile_rank(3, values) == pytest.approx(100 * 2.5 / 3)


def test_percentile_of_a_single_value_is_50():
    assert percentile_rank(7, [7]) == 50


def test_percentile_of_all_equal_values_is_50():
    assert percentile_rank(5, [5, 5, 5]) == 50


def test_engagements_skip_unknown_metrics():
    assert engagements(10, 5, None) == 15
    assert engagements(None, 5, None) == 5
    assert engagements(None, None, None) == 0
    assert engagements(0, 0, 0) == 0


def test_engagement_weights_are_a_knob(monkeypatch):
    monkeypatch.setitem(config.ENGAGEMENT_WEIGHTS, "comments", 5.0)
    assert engagements(10, 2, 1) == 10 + 10 + 1


def test_age_makes_the_same_engagement_count_less():
    assert adjusted_engagement(100, 0) == 100  # log2(2) = 1
    assert adjusted_engagement(100, 2) == 50  # log2(4) = 2
    assert adjusted_engagement(100, 30) < adjusted_engagement(100, 2)


def test_age_days():
    assert age_days(NOW - timedelta(hours=36), NOW) == 1.5


def test_as_utc_marks_naive_datetimes_as_utc():
    assert as_utc(datetime(2026, 1, 1)).tzinfo is UTC
    assert as_utc(datetime(2026, 1, 1, tzinfo=UTC)).tzinfo is UTC


# --- eligibility -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("changes", "eligible"),
    [
        ({}, True),
        ({"days": 5 / 24}, False),  # 5 hours old: numbers not settled
        ({"days": 7 / 24}, True),
        ({"days": 8}, False),  # outside the 7-day window
        ({"days": 6.9}, True),
        ({"counts": False}, False),  # inactive competitor or irrelevant
        ({"likes": None, "comments": None}, False),  # nothing to rank on
        ({"likes": None, "comments": 3}, True),
        ({"likes": 0, "comments": 0}, True),  # known zero is still data
    ],
)
def test_is_eligible(changes, eligible):
    assert is_eligible(make_post(1, **changes), 7, NOW) is eligible


# --- scoring posts -----------------------------------------------------------------------


def test_there_is_no_one_day_window():
    # A post under a day old has not had time to show its engagement.
    assert config.WINDOWS == (7, 30, 90)
    assert 1 not in config.MIN_POSTS_BY_WINDOW


def test_each_window_only_scores_posts_inside_it():
    posts = [make_post(1, days=3), make_post(2, days=20), make_post(3, days=60)]
    assert set(results_by_id(posts, 7)) == {1}
    assert set(results_by_id(posts, 30)) == {1, 2}
    assert set(results_by_id(posts, 90)) == {1, 2, 3}


def test_engagement_rate_needs_followers():
    posts = [make_post(1, followers=None), make_post(2, followers=0), make_post(3, followers=500)]
    results = results_by_id(posts)
    assert results[1].engagement_rate is None
    assert results[2].engagement_rate is None
    assert results[3].engagement_rate == pytest.approx(results[3].adjusted_engagement / 500)


def test_outperformance_compares_a_post_to_the_creators_usual():
    # Same age, so adjusted = likes / 2 -> 5, 10, 20; the median is 10.
    posts = [make_post(1, likes=10), make_post(2, likes=20), make_post(3, likes=40)]
    results = results_by_id(posts)
    assert results[3].outperformance == pytest.approx(2.0)
    assert results[2].outperformance == pytest.approx(1.0)
    assert results[1].outperformance == pytest.approx(0.5)


def test_outperformance_needs_three_posts():
    results = results_by_id([make_post(1, likes=10), make_post(2, likes=40)])
    assert results[1].outperformance is None
    assert results[2].outperformance is None


def test_the_usual_is_measured_over_90_days_not_just_the_window():
    # Only one post is inside the 7-day window, but three older ones give the baseline.
    posts = [
        make_post(1, days=2, likes=40),
        make_post(2, days=40, likes=10),
        make_post(3, days=50, likes=10),
        make_post(4, days=60, likes=10),
    ]
    assert results_by_id(posts, 7)[1].outperformance is not None


def test_posts_that_do_not_count_are_not_part_of_the_baseline():
    posts = [
        make_post(1, days=2, likes=40),
        make_post(2, days=40, likes=10, counts=False),
        make_post(3, days=50, likes=10, counts=False),
        make_post(4, days=60, likes=10, counts=False),
    ]
    assert results_by_id(posts, 7)[1].outperformance is None


def test_score_falls_back_to_the_percentile_of_engagement():
    # Three different creators, no followers, so no rate and no baseline.
    posts = [
        make_post(1, creator=1, likes=10, followers=None),
        make_post(2, creator=2, likes=20, followers=None),
        make_post(3, creator=3, likes=30, followers=None),
    ]
    results = results_by_id(posts)
    assert results[1].score == pytest.approx(100 * 0.5 / 3)
    assert results[2].score == 50
    assert results[3].score == pytest.approx(100 * 2.5 / 3)


def test_parts_without_data_are_left_out_not_counted_as_zero():
    # No views and one creator: impact and outperformance agree, so the score is the percentile.
    posts = [make_post(1, likes=10), make_post(2, likes=20), make_post(3, likes=40)]
    results = results_by_id(posts)
    assert results[3].score == pytest.approx(100 * 2.5 / 3)
    assert results[1].score == pytest.approx(100 * 0.5 / 3)


def test_views_add_reach_to_the_score():
    # Post 1 has more engagement, post 2 more views. Only two posts: no baseline yet.
    posts = [
        make_post(1, creator=1, likes=100, views=10),
        make_post(2, creator=2, likes=10, views=1000),
    ]
    results = results_by_id(posts)
    # impact: 75 vs 25, reach: 25 vs 75 -> (0.6*75 + 0.15*25) / 0.75 and the reverse.
    assert results[1].score == pytest.approx(65)
    assert results[2].score == pytest.approx(35)


def test_blend_weights_are_a_knob(monkeypatch):
    posts = [
        make_post(1, creator=1, likes=100, views=10),
        make_post(2, creator=2, likes=10, views=1000),
    ]
    monkeypatch.setitem(config.BLEND, "impact", 0.0)
    monkeypatch.setitem(config.BLEND, "reach", 1.0)
    results = results_by_id(posts)
    assert results[2].rank_in_platform == 1  # only views count now


def test_engagement_rate_is_shown_but_not_part_of_the_score():
    # Same engagement, very different audiences: the scores must match.
    posts = [
        make_post(1, creator=1, likes=50, followers=100),
        make_post(2, creator=2, likes=50, followers=1_000_000),
    ]
    results = results_by_id(posts)
    assert results[1].engagement_rate > results[2].engagement_rate
    assert results[1].score == results[2].score


def test_a_post_with_a_lot_of_engagement_beats_a_tiny_channel_with_a_high_rate():
    # The complaint behind this design: 5 likes on 3 subscribers is a huge "rate".
    posts = [
        make_post(1, creator=1, likes=5, followers=3, views=12),
        make_post(2, creator=2, likes=300, followers=50_000, views=9000),
    ]
    results = results_by_id(posts)
    assert results[1].engagement_rate > results[2].engagement_rate
    assert results[2].rank_in_platform == 1
    assert results[2].score > results[1].score


def test_posts_below_the_engagement_gate_are_not_ranked(monkeypatch):
    posts = [make_post(1, likes=4), make_post(2, likes=5), make_post(3, likes=2, comments=3)]
    assert set(results_by_id(posts)) == {2, 3}
    monkeypatch.setattr(config, "MIN_ENGAGEMENT_TO_RANK", 10)
    assert results_by_id(posts) == {}


def test_quiet_posts_still_count_toward_the_creators_usual():
    # Three quiet posts are gated out of the window but give the creator a baseline.
    posts = [
        make_post(1, days=2, likes=40),
        make_post(2, days=3, likes=2),
        make_post(3, days=4, likes=2),
        make_post(4, days=5, likes=2),
    ]
    results = results_by_id(posts)
    assert set(results) == {1}
    assert results[1].outperformance is not None


def test_the_creators_usual_has_a_floor():
    # The usual is about 1 (quiet posts), but it counts as 5: 20 / 5 = 4, not 20.
    posts = [
        make_post(1, days=2, likes=40),
        make_post(2, days=3, likes=2),
        make_post(3, days=4, likes=2),
        make_post(4, days=5, likes=2),
    ]
    assert results_by_id(posts)[1].outperformance == pytest.approx(4.0)


def test_views_of_zero_are_known_and_missing_views_are_not():
    posts = [make_post(1, views=0), make_post(2, views=None)]
    results = results_by_id(posts)
    assert set(results) == {1, 2}  # both are ranked; the missing part is just left out


def test_platforms_are_ranked_separately():
    posts = [
        make_post(1, platform="youtube", likes=1000, followers=None),
        make_post(2, platform="instagram", likes=10, followers=None),
    ]
    results = results_by_id(posts)
    assert results[1].rank_in_platform == 1
    assert results[2].rank_in_platform == 1
    assert results[1].score == results[2].score == 50  # each alone in its platform


def test_ranks_follow_the_score_and_ties_go_to_the_lower_id():
    posts = [
        make_post(5, likes=10, followers=None),
        make_post(3, likes=10, followers=None),
        make_post(9, likes=99, followers=None),
    ]
    ranked = sorted(score_posts(posts, 7, NOW), key=lambda r: r.rank_in_platform)
    assert [r.post_id for r in ranked] == [9, 3, 5]
    assert [r.rank_in_platform for r in ranked] == [1, 2, 3]


def test_scores_stay_between_0_and_100():
    posts = [make_post(i, likes=i * i, creator=i % 3, followers=1000 + i) for i in range(1, 30)]
    for result in score_posts(posts, 90, NOW):
        assert 0 <= result.score <= 100


def test_same_input_gives_the_same_result():
    posts = [make_post(i, likes=i * 3, creator=i % 2) for i in range(1, 10)]
    assert score_posts(posts, 7, NOW) == score_posts(posts, 7, NOW)


def test_a_later_now_ages_the_posts():
    posts = [make_post(1, likes=100, followers=1000)]
    now = score_posts(posts, 30, NOW)[0].adjusted_engagement
    later = score_posts(posts, 30, NOW + timedelta(days=10))[0].adjusted_engagement
    assert later < now


def test_nothing_eligible_gives_no_results():
    assert score_posts([], 7, NOW) == []
    assert score_posts([make_post(1, counts=False)], 7, NOW) == []


def test_adjusted_engagement_matches_the_formula():
    result = score_posts([make_post(1, likes=30, comments=6, days=2)], 7, NOW)[0]
    assert result.adjusted_engagement == pytest.approx(36 / math.log2(4))


# --- reasons -----------------------------------------------------------------------------


def test_reason_for_a_post_far_above_the_creators_usual():
    text = make_reason("instagram", 614, 4.2, 95)
    assert text == "614 engagements · 4.2× this creator's usual"


def test_reason_with_the_platform_rank_when_not_far_above_usual():
    text = make_reason("instagram", 1234, 1.0, 95)
    assert text == "1,234 engagements · top 5% on Instagram"


def test_reason_without_a_baseline():
    assert make_reason("youtube", 40, None, 70) == "40 engagements · top 30% on YouTube"


def test_reason_uses_the_singular_for_one_engagement():
    assert make_reason("youtube", 1, None, 70) == "1 engagement · top 30% on YouTube"


def test_top_percentage_is_never_below_1():
    assert make_reason("youtube", 99, None, 100) == "99 engagements · top 1% on YouTube"


def test_post_results_carry_the_reason_and_the_raw_engagement():
    result = score_posts([make_post(1, likes=30, comments=6)], 7, NOW)[0]
    assert result.engagements == 36
    assert result.reason.startswith("36 engagements")


# --- competitors -------------------------------------------------------------------------


def scored(post_id, score, topic=None, hook=None) -> ScoredPost:
    return ScoredPost(post_id=post_id, score=score, topic=topic, hook_type=hook)


def test_no_posts_gives_no_competitor_score():
    assert score_competitor([], 7) is None


def test_competitor_score_is_the_median_discounted_by_consistency():
    result = score_competitor([scored(1, 90), scored(2, 80), scored(3, 20)], 7)
    assert result.consistency == pytest.approx(2 / 3)
    assert result.score == pytest.approx(80 * (0.5 + 0.5 * 2 / 3))
    assert result.posts_count == 3
    assert result.best_post_id == 1


def test_a_score_of_exactly_50_counts_as_consistent():
    assert score_competitor([scored(1, 50), scored(2, 49.9)], 7).consistency == 0.5


def test_consistent_competitors_keep_their_full_median():
    result = score_competitor([scored(1, 60), scored(2, 70), scored(3, 80)], 7)
    assert result.consistency == 1
    assert result.score == 70


def test_inconsistent_competitors_lose_up_to_half():
    result = score_competitor([scored(1, 40), scored(2, 40)], 7)
    assert result.score == 20


@pytest.mark.parametrize(
    ("window", "posts", "low"),
    [(7, 2, True), (7, 3, False), (30, 4, True), (30, 5, False), (90, 4, True)],
)
def test_low_sample_depends_on_the_window(window, posts, low):
    result = score_competitor([scored(i, 60) for i in range(posts)], window)
    assert result.low_sample is low


def test_best_post_ties_go_to_the_lower_id():
    assert score_competitor([scored(8, 70), scored(4, 70)], 7).best_post_id == 4


def test_top_topic_is_the_most_used_ignoring_other():
    posts = [
        scored(1, 50, topic="other"),
        scored(2, 50, topic="other"),
        scored(3, 50, topic="iul"),
        scored(4, 50, topic="term_life"),
        scored(5, 90, topic="term_life"),
    ]
    assert score_competitor(posts, 7).top_topic == "term_life"


def test_top_topic_ties_go_to_the_higher_average_score():
    posts = [scored(1, 90, topic="iul"), scored(2, 40, topic="term_life")]
    assert score_competitor(posts, 7).top_topic == "iul"


def test_top_hook_ignores_none_and_missing_labels():
    posts = [scored(1, 50, hook="none"), scored(2, 50, hook=None), scored(3, 50, hook="question")]
    assert score_competitor(posts, 7).top_hook == "question"


def test_no_useful_labels_gives_no_top_topic_or_hook():
    result = score_competitor([scored(1, 50, topic="other", hook="none")], 7)
    assert (result.top_topic, result.top_hook) == (None, None)


def test_posts_without_a_known_author_have_no_usual():
    # Four posts of one placeholder "creator" would give a baseline, but the authors differ.
    posts = [make_post(i, creator=1, likes=10 * i, known_author=False) for i in range(1, 5)]
    for result in score_posts(posts, 7, NOW):
        assert result.outperformance is None
        assert "usual" not in result.reason


def test_unknown_authors_do_not_pull_a_real_creators_baseline():
    posts = [make_post(1, creator=1, likes=40, known_author=False)] + [
        make_post(i, creator=1, likes=10, known_author=True) for i in (2, 3)
    ]
    # Only two known posts: not enough for a baseline, even though three share the creator id.
    assert all(r.outperformance is None for r in score_posts(posts, 7, NOW))
