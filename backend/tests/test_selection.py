import math
from datetime import UTC, datetime

from app.discovery.selection import choose_new_active, discovery_score, stale_competitors


def test_score_grows_with_followers_and_platforms():
    assert discovery_score(None, 1) == 0
    assert discovery_score(999, 1) == 3  # log10(1000)
    assert discovery_score(999, 2) == 3.5
    assert math.isclose(discovery_score(9, 1), 1)


def test_choose_new_active_takes_best_scores_up_to_slots():
    candidates = [(1, 2.0), (2, 4.0), (3, 3.0)]
    assert choose_new_active(candidates, 2) == [2, 3]


def test_no_slots_means_no_new_active():
    assert choose_new_active([(1, 5.0)], 0) == []
    assert choose_new_active([(1, 5.0)], -3) == []


def test_ties_go_to_the_lower_id():
    assert choose_new_active([(7, 1.0), (3, 1.0)], 1) == [3]


# --- stale competitors ---------------------------------------------------------------------

JUDGED = datetime(2026, 10, 20, tzinfo=UTC)  # when the posts behind the latest scores came in
BEFORE = datetime(2026, 9, 1, tzinfo=UTC)
AFTER = datetime(2026, 10, 25, tzinfo=UTC)


def test_a_judged_competitor_without_ranked_posts_is_stale():
    assert stale_competitors([(1, BEFORE), (2, BEFORE)], {2}, JUDGED) == [1]


def test_a_competitor_activated_after_the_last_collect_is_not_judged_yet():
    assert stale_competitors([(1, AFTER)], set(), JUDGED) == []


def test_nobody_is_stale_before_any_collect_and_rank():
    assert stale_competitors([(1, BEFORE)], set(), None) == []


def test_a_competitor_without_an_activation_time_is_kept():
    assert stale_competitors([(1, None)], set(), JUDGED) == []


def test_naive_times_from_sqlite_compare_as_utc():
    assert stale_competitors([(1, BEFORE.replace(tzinfo=None))], set(), JUDGED) == [1]
