import pytest
from sqlalchemy import select

from app.labeling.rules import LabelResult, label_post
from app.labeling.service import BatchResult, Labeler, label_posts
from app.labeling.taxonomy import TAXONOMY_VERSION
from app.models import Creator, Label, Post


def add_post(
    session, external_id="p1", title="Final expense explained", text=None, likes=None, comments=None
) -> Post:
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
        likes=likes,
        comments=comments,
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


# --- batch labelers (Gemini) ---------------------------------------------------------------


def batch_labeler(answer, *, batch_size=2, name="gemini"):
    """A labeler that answers in batches. `answer(items)` returns {post_id: LabelResult | None}."""
    calls = []

    def label_batch(items):
        calls.append([item.post_id for item in items])
        return BatchResult(
            answer(items),
            model="model-x",
            error="a problem" if None in answer(items).values() else None,
        )

    labeler = Labeler(
        name=name, model="alias", label=label_post, label_batch=label_batch, batch_size=batch_size
    )
    return labeler, calls


def label_result(topic="iul", relevant=True, flex=False):
    return LabelResult(topic, "question", "hook", "none", relevant, 0.9, is_flex=flex)


def add_posts(session, count, **fields):
    return [add_post(session, f"p{i}", title=f"Title {i}", **fields) for i in range(count)]


def test_posts_are_sent_in_batches(session):
    add_posts(session, 5)
    labeler, calls = batch_labeler(lambda items: {i.post_id: label_result() for i in items})

    run = label_posts(session, labeler)

    assert [len(chunk) for chunk in calls] == [2, 2, 1]
    assert run.items_ok == 5
    assert run.message.startswith("5 labeled with gemini")
    labels = session.scalars(select(Label)).all()
    assert {(lab.labeler, lab.model, lab.topic) for lab in labels} == {("gemini", "model-x", "iul")}


def test_posts_the_batch_labeler_cannot_label_fall_back_to_the_rules(session):
    posts = add_posts(session, 2)
    only_first = lambda items: {items[0].post_id: label_result("iul"), items[1].post_id: None}  # noqa: E731
    labeler, _ = batch_labeler(only_first)

    run = label_posts(session, labeler)

    first, second = (session.get(Label, p.id) for p in posts)
    assert (first.labeler, first.model) == ("gemini", "model-x")
    assert (second.labeler, second.model) == ("rules", None)
    assert second.topic == "other"  # what the rules say about "Title 1"
    assert "1 fell back to rules" in run.message
    assert "last error: a problem" in run.message


def test_a_rules_label_is_upgraded_when_gemini_is_available(session):
    post = add_post(session)
    label_posts(session)  # labeled by the rules
    assert session.get(Label, post.id).labeler == "rules"
    labeler, _ = batch_labeler(lambda items: {i.post_id: label_result("whole_life") for i in items})

    run = label_posts(session, labeler)

    assert run.items_ok == 1
    label = session.get(Label, post.id)
    assert (label.labeler, label.topic) == ("gemini", "whole_life")


def test_a_gemini_label_is_not_replaced_by_the_rules(session):
    post = add_post(session)
    labeler, _ = batch_labeler(lambda items: {i.post_id: label_result() for i in items})
    label_posts(session, labeler)

    run = label_posts(session)  # the rules labeler

    assert run.items_ok == 0
    assert session.get(Label, post.id).labeler == "gemini"


def test_gemini_labels_are_not_asked_for_again(session):
    add_posts(session, 3)
    labeler, calls = batch_labeler(lambda items: {i.post_id: label_result() for i in items})
    label_posts(session, labeler)
    calls.clear()

    run = label_posts(session, labeler)

    assert calls == []
    assert run.items_ok == 0
    assert "3 unchanged" in run.message


def test_posts_that_fell_back_are_tried_again_on_the_next_run(session):
    add_posts(session, 2)
    failing, _ = batch_labeler(lambda items: {i.post_id: None for i in items})
    label_posts(session, failing)

    working, calls = batch_labeler(lambda items: {i.post_id: label_result() for i in items})
    run = label_posts(session, working)

    assert run.items_ok == 2
    assert {lab.labeler for lab in session.scalars(select(Label))} == {"gemini"}


def test_the_limit_labels_the_most_engaging_posts_first(session):
    quiet = add_post(session, "quiet", title="Quiet", likes=1)
    loud = add_post(session, "loud", title="Loud", likes=500, comments=40)
    medium = add_post(session, "medium", title="Medium", likes=50)
    labeler, calls = batch_labeler(
        lambda items: {i.post_id: label_result() for i in items}, batch_size=1
    )

    run = label_posts(session, labeler, limit=2)

    assert calls == [[loud.id], [medium.id]]
    assert session.get(Label, quiet.id) is None
    assert "1 left for a later run" in run.message


def test_progress_is_reported_after_each_batch(session):
    add_posts(session, 5)
    labeler, _ = batch_labeler(lambda items: {i.post_id: label_result() for i in items})
    seen = []

    label_posts(session, labeler, progress=lambda done, total: seen.append((done, total)))

    assert seen == [(2, 5), (4, 5), (5, 5)]


def test_work_is_saved_after_every_batch(session):
    add_posts(session, 4)
    calls = []

    def label_batch(items):
        calls.append(len(items))
        if len(calls) == 2:
            raise KeyboardInterrupt  # the run is stopped in the middle
        return BatchResult({i.post_id: label_result() for i in items})

    labeler = Labeler("gemini", "m", label_post, label_batch, batch_size=2)

    with pytest.raises(KeyboardInterrupt):
        label_posts(session, labeler)

    assert len(session.scalars(select(Label)).all()) == 2


def test_the_flex_flag_is_stored_and_counted_in_the_run(session):
    posts = add_posts(session, 3)
    flexes = {posts[0].id}
    labeler, _ = batch_labeler(
        lambda items: {i.post_id: label_result(flex=i.post_id in flexes) for i in items}
    )

    run = label_posts(session, labeler)

    assert [session.get(Label, p.id).is_flex for p in posts] == [True, False, False]
    assert "1 flagged as flex" in run.message
