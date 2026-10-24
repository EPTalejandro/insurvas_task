from sqlalchemy import select

from app.labeling.rules import LabelResult
from app.labeling.service import Labeler, label_posts
from app.labeling.taxonomy import TAXONOMY_VERSION
from app.models import Creator, Label, Post


def add_post(session, external_id="p1", title="Final expense explained", text=None) -> Post:
    creator = session.scalars(select(Creator)).first()
    if creator is None:
        creator = Creator(platform="youtube", external_id="UC1", handle="@a", name="A")
        session.add(creator)
        session.flush()
    post = Post(
        creator_id=creator.id,
        platform="youtube",
        external_id=external_id,
        url=f"https://example.com/{external_id}",
        title=title,
        text=text,
    )
    session.add(post)
    session.commit()
    return post


def test_new_posts_get_labels_and_the_run_is_recorded(session):
    post = add_post(session)

    run = label_posts(session)

    label = session.get(Label, post.id)
    assert label.topic == "final_expense"
    assert label.hook_text == "Final expense explained"
    assert label.labeler == "rules"
    assert label.taxonomy_version == TAXONOMY_VERSION
    assert label.content_hash
    assert (run.kind, run.status, run.items_ok) == ("label", "ok", 1)


def test_unchanged_posts_are_skipped(session):
    add_post(session)
    label_posts(session)

    run = label_posts(session)

    assert run.items_ok == 0
    assert "1 unchanged" in run.message


def test_changed_text_is_labeled_again_without_duplicating(session):
    post = add_post(session)
    label_posts(session)

    post.title = "Whole life explained"
    session.commit()
    label_posts(session)

    labels = session.scalars(select(Label)).all()
    assert len(labels) == 1
    assert labels[0].topic == "whole_life"


def test_force_labels_unchanged_posts_again(session):
    add_post(session)
    label_posts(session)

    run = label_posts(session, force=True)

    assert run.items_ok == 1
    assert len(session.scalars(select(Label)).all()) == 1


def test_an_old_taxonomy_version_is_labeled_again(session):
    post = add_post(session)
    label_posts(session)
    session.get(Label, post.id).taxonomy_version = TAXONOMY_VERSION - 1
    session.commit()

    run = label_posts(session)

    assert run.items_ok == 1
    assert session.get(Label, post.id).taxonomy_version == TAXONOMY_VERSION


def test_another_labeler_can_be_plugged_in(session):
    post = add_post(session)

    def fake(title, text):
        return LabelResult("iul", "question", "hook", "none", False, 0.9)

    label_posts(session, Labeler(name="fake", model="m-1", label=fake))

    label = session.get(Label, post.id)
    assert (label.labeler, label.model, label.topic, label.is_relevant) == (
        "fake",
        "m-1",
        "iul",
        False,
    )
