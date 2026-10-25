"""The `label` step: give every new or changed post its labels.

The labeler is passed in, so rules and Gemini share this code. A labeler may answer one post at
a time (rules) or in batches (Gemini); anything it cannot label falls back to the rules.
"""

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import batched

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import runs
from app.labeling.rules import LabelResult, content_hash, label_post
from app.labeling.taxonomy import TAXONOMY_VERSION
from app.models import Label, Post, Run, utcnow

LabelFn = Callable[[str | None, str | None], LabelResult]


@dataclass(frozen=True)
class PostText:
    """What a labeler gets to read about a post."""

    post_id: int
    platform: str
    title: str | None
    text: str | None


@dataclass(frozen=True)
class BatchResult:
    labels: dict[int, LabelResult | None]  # None: this post could not be labeled
    model: str | None = None  # the model that really answered
    error: str | None = None


BatchFn = Callable[[list[PostText]], BatchResult]


@dataclass(frozen=True)
class Labeler:
    name: str  # stored in labels.labeler
    model: str | None  # stored in labels.model
    label: LabelFn
    label_batch: BatchFn | None = None
    batch_size: int = 1


RULES = Labeler(name="rules", model=None, label=label_post)


@dataclass
class _Progress:
    used: Counter[str] = field(default_factory=Counter)  # labeler name -> posts
    error: str | None = None


def needs_label(post: Post, current_hash: str, labeler_name: str = RULES.name) -> bool:
    """Skip a post only when its words and the taxonomy are what we labeled before.

    A label made by the rules is redone when a better labeler is available (and again on every
    run if that labeler keeps failing). The other way round never happens.
    """
    label = post.label
    if (
        label is None
        or label.content_hash != current_hash
        or label.taxonomy_version != TAXONOMY_VERSION
    ):
        return True
    return labeler_name != RULES.name and label.labeler == RULES.name


def _engagement(post: Post) -> int:
    return (post.likes or 0) + (post.comments or 0)


def _label_chunk(
    labeler: Labeler, chunk: tuple[tuple[Post, str], ...], progress: _Progress
) -> dict[int, tuple[LabelResult, Labeler]]:
    """Labels for one chunk of posts, with the labeler that made each one."""
    items = [PostText(p.id, p.platform, p.title, p.text) for p, _ in chunk]
    model = labeler.model
    if labeler.label_batch is not None:
        batch = labeler.label_batch(items)
        answers = batch.labels
        model = batch.model or labeler.model
        progress.error = batch.error or progress.error
    else:
        answers = {item.post_id: labeler.label(item.title, item.text) for item in items}

    made_by = Labeler(labeler.name, model, labeler.label)
    results: dict[int, tuple[LabelResult, Labeler]] = {}
    for item in items:
        answer = answers.get(item.post_id)
        if answer is not None:
            results[item.post_id] = (answer, made_by)
        else:  # the labeler had no answer: the rules always do
            results[item.post_id] = (RULES.label(item.title, item.text), RULES)
    return results


def label_posts(
    session: Session,
    labeler: Labeler = RULES,
    force: bool = False,
    limit: int | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> Run:
    """Label new or changed posts. force=True redoes every post (after changing the rules)."""
    run = runs.start_run(session, "label")
    todo: list[tuple[Post, str]] = []
    skipped = 0
    for post in session.scalars(select(Post)):
        current_hash = content_hash(post.title, post.text)
        if force or needs_label(post, current_hash, labeler.name):
            todo.append((post, current_hash))
        else:
            skipped += 1
    # Most engaging first: if a limit or the daily quota stops us, the posts that matter are done.
    todo.sort(key=lambda item: -_engagement(item[0]))
    deferred = max(len(todo) - limit, 0) if limit is not None else 0
    if limit is not None:
        todo = todo[:limit]

    state = _Progress()
    done = 0
    for chunk in batched(todo, labeler.batch_size, strict=False):  # the last chunk may be short
        results = _label_chunk(labeler, chunk, state)
        for post, current_hash in chunk:
            result, made_by = results[post.id]
            label = post.label or Label(post_id=post.id)
            label.topic = result.topic
            label.hook_type = result.hook_type
            label.hook_text = result.hook_text
            label.cta = result.cta
            label.is_relevant = result.is_relevant
            label.confidence = result.confidence
            label.labeler = made_by.name
            label.model = made_by.model
            label.content_hash = current_hash
            label.taxonomy_version = TAXONOMY_VERSION
            label.labeled_at = utcnow()
            post.label = label
            state.used[made_by.name] += 1
        session.commit()  # after each chunk, so an interrupted run keeps its work
        done += len(chunk)
        if progress:
            progress(done, len(todo))

    message = f"{len(todo)} labeled with {labeler.name}"
    fallbacks = state.used[RULES.name] if labeler.name != RULES.name else 0
    if fallbacks:
        message += f" ({fallbacks} fell back to rules)"
    message += f", {skipped} unchanged"
    if deferred:
        message += f", {deferred} left for a later run"
    if state.error:
        message += f"; last error: {state.error}"
    return runs.finish_run(session, run, status=runs.OK, items_ok=len(todo), message=message)
