from datetime import UTC, datetime, timedelta

from app.budget import INSTAGRAM_HASHTAG_LIMIT, hashtag_budget, searches_from_runs

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)


def days_ago(days: float) -> datetime:
    return NOW - timedelta(days=days)


def test_no_searches_means_every_slot_is_free():
    budget = hashtag_budget([], NOW)
    assert (budget.used, budget.free, budget.next_free_at) == (0, INSTAGRAM_HASHTAG_LIMIT, None)


def test_a_hashtag_searched_twice_takes_one_slot_until_7_days_after_its_last_search():
    budget = hashtag_budget([("iul", days_ago(5)), ("iul", days_ago(1))], NOW)

    assert (budget.used, budget.free) == (1, INSTAGRAM_HASHTAG_LIMIT - 1)
    assert budget.slots == {"iul": days_ago(1) + timedelta(days=7)}


def test_a_hashtag_searched_more_than_7_days_ago_is_free_again():
    budget = hashtag_budget([("old", days_ago(8)), ("new", days_ago(2))], NOW)

    assert set(budget.slots) == {"new"}
    assert budget.next_free_at == days_ago(2) + timedelta(days=7)


def test_the_next_free_slot_is_the_one_searched_longest_ago():
    budget = hashtag_budget([("a", days_ago(1)), ("b", days_ago(6)), ("c", days_ago(3))], NOW)
    assert budget.next_free_at == days_ago(6) + timedelta(days=7)


def test_free_never_goes_below_zero():
    searches = [(f"tag{i}", days_ago(1)) for i in range(INSTAGRAM_HASHTAG_LIMIT + 2)]
    budget = hashtag_budget(searches, NOW)
    assert (budget.used, budget.free) == (INSTAGRAM_HASHTAG_LIMIT + 2, 0)


def test_searches_from_runs_splits_the_list_and_skips_runs_without_hashtags():
    naive = datetime(2026, 10, 29, 8, 0)  # SQLite gives naive UTC datetimes back
    rows = [("iul,lifeinsurance", naive), (None, naive), ("", naive)]

    assert searches_from_runs(rows) == [
        ("iul", naive.replace(tzinfo=UTC)),
        ("lifeinsurance", naive.replace(tzinfo=UTC)),
    ]
