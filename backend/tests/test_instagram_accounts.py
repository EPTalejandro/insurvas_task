from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.collectors.instagram_accounts import collect_instagram_accounts, link_instagram_accounts
from app.models import Competitor, Creator, Post
from tests.instagram_fake import FakeInstagram, make_settings, media

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


def add_competitor(session, name="jane", *, texts=(), bio=None, status="active"):
    competitor = Competitor(name=name, kind="agent", status=status)
    channel = Creator(
        competitor=competitor,
        platform="youtube",
        external_id=f"UC{name}",
        handle=f"@{name}",
        name=name,
        bio=bio,
        followers=5000,
        kind="agent",
    )
    session.add(channel)
    session.flush()
    for index, text in enumerate(texts):
        session.add(
            Post(
                creator_id=channel.id,
                platform="youtube",
                external_id=f"{name}-{index}",
                url="https://youtu.be/x",
                text=text,
            )
        )
    session.commit()
    return competitor, channel


def link(session, fake, **settings):
    return link_instagram_accounts(session, fake.client(), make_settings(**settings))


def instagram_creators(session):
    return session.scalars(select(Creator).where(Creator.platform == "instagram")).all()


def follow(handle, times=3):
    return [f"Follow me: https://www.instagram.com/{handle}/" for _ in range(times)]


# --- linking -------------------------------------------------------------------------------


def test_a_handle_linked_in_several_videos_becomes_the_competitors_account(session):
    competitor, _ = add_competitor(session, texts=follow("jane_ig"))
    fake = FakeInstagram()
    fake.add_account("jane_ig", name="Jane Insurance", bio="Life insurance agent", followers=4200)

    run = link(session, fake)

    (account,) = instagram_creators(session)
    assert (account.external_id, account.handle, account.name) == (
        "jane_ig",
        "jane_ig",
        "Jane Insurance",
    )
    assert account.competitor_id == competitor.id
    assert (account.followers, account.kind, account.is_relevant) == (4200, "agent", True)
    assert account.url == "https://www.instagram.com/jane_ig/"
    assert account.discovered_via.startswith("YouTube links:")
    assert (run.kind, run.platform, run.status, run.items_ok) == ("link", "instagram", "ok", 1)
    assert run.message.startswith("1 linked of 1 competitors (@jane_ig)")


def test_guests_tagged_once_are_never_linked(session):
    add_competitor(session, texts=["with instagram.com/guest_a", "and instagram.com/guest_b"])
    fake = FakeInstagram()
    fake.add_account("guest_a")

    run = link(session, fake)

    assert instagram_creators(session) == []
    assert fake.account_calls() == []  # not even looked up
    assert "0 linked of 1" in run.message
    assert "not linked: 1" in run.message


def test_a_tie_is_settled_by_the_profile_that_links_back(session):
    add_competitor(session, texts=follow("official") + follow("partner"))
    fake = FakeInstagram()
    fake.add_account("official", bio="Watch us on youtube.com/@jane")
    fake.add_account("partner", bio="Another team")

    link(session, fake)

    assert [c.handle for c in instagram_creators(session)] == ["official"]
    assert "links back" in instagram_creators(session)[0].discovered_via


def test_an_unproven_tie_links_nothing(session):
    add_competitor(session, texts=follow("official") + follow("partner"))
    fake = FakeInstagram()
    fake.add_account("official", bio="Life insurance")
    fake.add_account("partner", bio="Life insurance")

    run = link(session, fake)

    assert instagram_creators(session) == []
    assert "not linked: 1" in run.message


def test_two_competitors_sharing_a_handle_both_lose_it(session):
    add_competitor(session, "arnold", texts=follow("agentleadlab_", 5))
    add_competitor(session, "lab", texts=follow("agentleadlab_", 8))
    fake = FakeInstagram()
    fake.add_account("agentleadlab_", bio="Leads for agents")

    run = link(session, fake)

    assert instagram_creators(session) == []
    assert len(fake.account_calls()) == 1  # the profile was fetched once and reused
    assert "not linked: 2" in run.message


def test_the_competitor_the_profile_links_back_to_keeps_a_shared_handle(session):
    add_competitor(session, "arnold", texts=follow("shared", 5))
    mine, _ = add_competitor(session, "jane", texts=follow("shared", 5))
    fake = FakeInstagram()
    fake.add_account("shared", bio="youtube.com/@jane")

    link(session, fake)

    (account,) = instagram_creators(session)
    assert account.competitor_id == mine.id


def test_an_unreadable_front_runner_is_not_replaced_by_a_weaker_account(session):
    # A tie where one side cannot be read stays a tie: the readable one may be a guest.
    add_competitor(session, texts=follow("personal_account") + follow("business_account"))
    fake = FakeInstagram()
    fake.add_account("business_account", bio="Life insurance")  # the other one does not exist

    run = link(session, fake)

    assert instagram_creators(session) == []
    assert "not linked: 1" in run.message


def test_a_readable_account_clearly_ahead_of_an_unreadable_one_is_linked(session):
    add_competitor(session, texts=follow("business_account", 9) + follow("personal_account", 3))
    fake = FakeInstagram()
    fake.add_account("business_account", bio="Life insurance")

    link(session, fake)

    assert [c.handle for c in instagram_creators(session)] == ["business_account"]


def test_an_unreadable_main_account_means_no_link(session):
    add_competitor(session, texts=follow("personal_account", 9) + follow("business_account", 3))
    fake = FakeInstagram()
    fake.add_account("business_account", bio="Life insurance")

    run = link(session, fake)

    assert instagram_creators(session) == []
    assert "not linked: 1" in run.message


def test_an_insurance_carrier_is_not_linked(session):
    add_competitor(session, texts=follow("statefarm"))
    fake = FakeInstagram()
    fake.add_account("statefarm", name="State Farm", bio="Official account")

    run = link(session, fake)

    assert instagram_creators(session) == []
    assert "not linked: 1" in run.message


def test_a_handle_already_linked_to_another_competitor_is_not_taken(session):
    other, _ = add_competitor(session, "other", texts=follow("taken"))
    add_competitor(session, "jane", texts=follow("taken", 6))
    session.add(
        Creator(
            competitor_id=other.id,
            platform="instagram",
            external_id="taken",
            handle="taken",
            name="taken",
            kind="agent",
        )
    )
    session.commit()
    fake = FakeInstagram()
    fake.add_account("taken", bio="x")

    link(session, fake)

    assert len(instagram_creators(session)) == 1  # still only the original one
    assert instagram_creators(session)[0].competitor_id == other.id


def test_competitors_that_already_have_an_account_are_not_looked_at(session):
    competitor, _ = add_competitor(session, texts=follow("jane_ig"))
    session.add(
        Creator(
            competitor_id=competitor.id,
            platform="instagram",
            external_id="old_handle",
            handle="old_handle",
            name="old",
            kind="agent",
        )
    )
    session.commit()
    fake = FakeInstagram()

    link(session, fake)

    assert fake.calls == []


def test_inactive_competitors_are_not_linked(session):
    add_competitor(session, status="candidate", texts=follow("jane_ig"))
    fake = FakeInstagram()
    fake.add_account("jane_ig")

    link(session, fake)

    assert fake.calls == []


def test_at_most_three_candidates_are_looked_up(session):
    add_competitor(session, texts=sum((follow(f"handle{i}") for i in range(5)), []))
    fake = FakeInstagram()
    for i in range(5):
        fake.add_account(f"handle{i}", bio="x")

    link(session, fake)

    assert len(fake.account_calls()) == 3
    assert instagram_creators(session) == []  # all tied


def test_a_failed_lookup_means_no_decision_for_that_competitor(session):
    add_competitor(session, texts=follow("jane_ig"))
    fake = FakeInstagram()
    fake.account_failure = (500, {"error": {"message": "temporary problem", "code": 2}})

    run = link(session, fake)

    assert instagram_creators(session) == []
    assert (run.status, run.items_failed) == ("error", 1)
    assert "temporary problem" in run.message


def test_an_expired_token_stops_linking(session):
    add_competitor(session, "a", texts=follow("a_ig"))
    add_competitor(session, "b", texts=follow("b_ig"))
    fake = FakeInstagram()
    fake.token_expired = True

    run = link(session, fake)

    assert len(fake.account_calls()) == 1
    assert run.status == "error"
    assert "token expired" in run.message


# --- collecting ----------------------------------------------------------------------------


def add_account_creator(session, competitor, handle="jane_ig", **extra):
    creator = Creator(
        competitor_id=competitor.id,
        platform="instagram",
        external_id=handle,
        handle=handle,
        name=handle,
        followers=100,
        kind="agent",
        **extra,
    )
    session.add(creator)
    session.commit()
    return creator


def collect(session, fake, **settings):
    return collect_instagram_accounts(session, fake.client(), make_settings(**settings), now=NOW)


def test_posts_of_a_linked_account_are_collected_with_reel_views(session):
    competitor, _ = add_competitor(session)
    account = add_account_creator(session, competitor)
    fake = FakeInstagram()
    fake.add_account(
        "jane_ig",
        name="Jane Insurance",
        bio="New bio",
        followers=4200,
        pages=[
            [
                media("m1", days=1, likes=120, comments=7),
                media("m2", days=2, likes=300, kind="VIDEO", product="REELS", views=5000),
            ]
        ],
    )

    run = collect(session, fake)

    posts = {
        p.external_id: p for p in session.scalars(select(Post).where(Post.platform == "instagram"))
    }
    assert set(posts) == {"m1", "m2"}
    assert (posts["m1"].format, posts["m1"].views, posts["m1"].likes) == ("image", None, 120)
    assert (posts["m2"].format, posts["m2"].views) == ("reel", 5000)
    assert all(p.creator_id == account.id for p in posts.values())
    assert (account.followers, account.bio, account.name) == (4200, "New bio", "Jane Insurance")
    assert (run.kind, run.platform, run.status, run.items_ok) == ("collect", "instagram", "ok", 1)
    assert run.message == "accounts: 2 posts from 1 accounts"


def test_old_posts_are_dropped_and_paging_stops_when_they_begin(session):
    competitor, _ = add_competitor(session)
    add_account_creator(session, competitor)
    fake = FakeInstagram()
    fake.add_account(
        "jane_ig",
        pages=[[media("new", days=1), media("old", days=120)], [media("older", days=200)]],
    )

    collect(session, fake)

    assert {p.external_id for p in session.scalars(select(Post))} == {"new"}
    assert len(fake.account_calls()) == 1  # page 2 would only hold older posts


def test_paging_stops_at_the_post_limit(session):
    competitor, _ = add_competitor(session)
    add_account_creator(session, competitor)
    fake = FakeInstagram()
    pages = [[media(f"p{i}a", days=1), media(f"p{i}b", days=2)] for i in range(4)]
    fake.add_account("jane_ig", pages=pages)

    collect(session, fake, max_posts_per_account=3)

    assert len(fake.account_calls()) == 2
    assert len(session.scalars(select(Post)).all()) == 3


def test_a_page_that_is_too_big_steps_the_size_down(session):
    competitor, _ = add_competitor(session)
    add_account_creator(session, competitor)
    fake = FakeInstagram()
    fake.add_account("jane_ig", pages=[[media("m1")]])
    fake.max_account_page_size = 10

    run = collect(session, fake)

    assert fake.account_page_sizes() == [25, 10]
    assert run.status == "ok"
    assert len(session.scalars(select(Post)).all()) == 1


def test_collecting_again_refreshes_metrics_without_duplicates(session):
    competitor, _ = add_competitor(session)
    add_account_creator(session, competitor)
    fake = FakeInstagram()
    fake.add_account("jane_ig", pages=[[media("m1", likes=10)]])
    collect(session, fake)

    fake.accounts["jane_ig"]["pages"][0][0]["like_count"] = 999
    collect(session, fake)

    (post,) = session.scalars(select(Post)).all()
    assert post.likes == 999


def test_an_account_that_cannot_be_read_is_switched_off(session):
    competitor, _ = add_competitor(session)
    account = add_account_creator(session, competitor)
    fake = FakeInstagram()  # the account does not exist for Business Discovery

    run = collect(session, fake)

    assert account.is_relevant is False
    assert (run.status, run.items_failed) == ("error", 1)
    assert "not a professional account" in run.message
    calls = len(fake.account_calls())
    collect(session, fake)
    assert len(fake.account_calls()) == calls  # no longer asked about


def test_one_bad_account_does_not_stop_the_others(session):
    one, _ = add_competitor(session, "one")
    two, _ = add_competitor(session, "two")
    add_account_creator(session, one, "missing_ig")
    add_account_creator(session, two, "good_ig")
    fake = FakeInstagram()
    fake.add_account("good_ig", pages=[[media("g1")]])

    run = collect(session, fake)

    assert run.status == "partial"
    assert [p.external_id for p in session.scalars(select(Post))] == ["g1"]


def test_an_expired_token_stops_collecting(session):
    one, _ = add_competitor(session, "one")
    two, _ = add_competitor(session, "two")
    add_account_creator(session, one, "a_ig")
    add_account_creator(session, two, "b_ig")
    fake = FakeInstagram()
    fake.token_expired = True

    run = collect(session, fake)

    assert len(fake.account_calls()) == 1
    assert run.status == "error"
    assert "token expired" in run.message


def test_only_active_competitors_and_real_accounts_are_collected(session):
    candidate, _ = add_competitor(session, "cand", status="candidate")
    add_account_creator(session, candidate, "cand_ig")
    placeholder = Creator(
        platform="instagram", external_id="hashtag:1", handle="#x", name="x", kind="hashtag"
    )
    session.add(placeholder)
    session.commit()
    fake = FakeInstagram()
    fake.add_account("cand_ig", pages=[[media("c1")]])

    run = collect(session, fake)

    assert fake.calls == []
    assert run.message == "accounts: none linked yet"


@pytest.mark.parametrize("field", ["biography", "website"])
def test_profiles_may_have_empty_bio_and_website(session, field):
    competitor, _ = add_competitor(session)
    add_account_creator(session, competitor)
    fake = FakeInstagram()
    fake.add_account("jane_ig", pages=[[media("m1")]])
    fake.accounts["jane_ig"][field] = None

    assert collect(session, fake).status == "ok"


def test_account_posts_get_image_links_and_reels_use_their_preview(session):
    competitor, _ = add_competitor(session)
    add_account_creator(session, competitor)
    fake = FakeInstagram()
    fake.add_account(
        "jane_ig",
        pages=[
            [
                media("photo", kind="IMAGE"),
                media("reel", kind="VIDEO", product="REELS", views=900),
                media("bare", images=False),  # the API gave no link
            ]
        ],
    )

    collect(session, fake)

    posts = {p.external_id: p for p in session.scalars(select(Post))}
    assert posts["photo"].thumbnail_url == "https://cdn.test/photo.jpg"
    assert posts["reel"].thumbnail_url == "https://cdn.test/reel-thumb.jpg"  # not the .mp4
    assert posts["bare"].thumbnail_url is None


def test_collecting_again_renews_expired_image_links(session):
    competitor, _ = add_competitor(session)
    add_account_creator(session, competitor)
    fake = FakeInstagram()
    fake.add_account("jane_ig", pages=[[media("m1")]])
    collect(session, fake)

    fake.accounts["jane_ig"]["pages"][0][0]["media_url"] = "https://cdn.test/m1-new.jpg"
    collect(session, fake)

    (post,) = session.scalars(select(Post)).all()
    assert post.thumbnail_url == "https://cdn.test/m1-new.jpg"


def test_account_requests_ask_for_both_image_fields(session):
    competitor, _ = add_competitor(session)
    add_account_creator(session, competitor)
    fake = FakeInstagram()
    fake.add_account("jane_ig", pages=[[media("m1")]])

    collect(session, fake)

    assert "media_url" in fake.account_calls()[0]["fields"]
    assert "thumbnail_url" in fake.account_calls()[0]["fields"]
