"""The `label` step: give every new or changed post its labels.

The labeler is passed in as a function, so rules and Gemini (phase 7) share this code.
"""

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import runs
from app.labeling.rules import LabelResult, content_hash, label_post
from app.labeling.taxonomy import TAXONOMY_VERSION
from app.models import Label, Post, Run, utcnow

LabelFn = Callable[[str | None, str | None], LabelResult]


@dataclass(frozen=True)
class Labeler:
    name: str  # stored in labels.labeler
    model: str | None  # stored in labels.model
    label: LabelFn


RULES = Labeler(name="rules", model=None, label=label_post)


def needs_label(post: Post, current_hash: str) -> bool:
    """Skip a post only when its words and the taxonomy are exactly what we labeled before."""
    label = post.label
    return (
        label is None
        or label.content_hash != current_hash
        or label.taxonomy_version != TAXONOMY_VERSION
    )


def label_posts(session: Session, labeler: Labeler = RULES, force: bool = False) -> Run:
    """Label new or changed posts. force=True redoes every post (after changing the rules)."""
    run = runs.start_run(session, "label")
    labeled = skipped = 0
    for post in session.scalars(select(Post)):
        current_hash = content_hash(post.title, post.text)
        if not force and not needs_label(post, current_hash):
            skipped += 1
            continue
        result = labeler.label(post.title, post.text)
        label = post.label or Label(post_id=post.id)
        label.topic = result.topic
        label.hook_type = result.hook_type
        label.hook_text = result.hook_text
        label.cta = result.cta
        label.is_relevant = result.is_relevant
        label.confidence = result.confidence
        label.labeler = labeler.name
        label.model = labeler.model
        label.content_hash = current_hash
        label.taxonomy_version = TAXONOMY_VERSION
        label.labeled_at = utcnow()
        post.label = label
        labeled += 1
    session.commit()
    return runs.finish_run(
        session,
        run,
        status=runs.OK,
        items_ok=labeled,
        message=f"{labeled} labeled with {labeler.name}, {skipped} unchanged",
    )
