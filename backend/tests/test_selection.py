import math

from app.discovery.selection import choose_new_active, discovery_score


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
