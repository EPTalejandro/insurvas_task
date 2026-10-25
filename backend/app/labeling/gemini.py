"""The Gemini labeler: reads posts in batches and labels them with the closed taxonomy.

Gemini is better than the rules with nuance (sarcasm, mixed topics, off-topic posts), but it can
fail or answer badly. Every post it does not label cleanly gets None here, and the label step
falls back to the rules for exactly those posts.
"""

import json
from typing import Literal

from pydantic import BaseModel, ValidationError

from app.gemini_client import GeminiJson
from app.labeling.rules import HOOK_MAX_CHARS, LabelResult, opening_line
from app.labeling.service import BatchResult, Labeler, PostText, label_post
from app.labeling.taxonomy import CTAS, HOOKS, TOPICS

BATCH_SIZE = 10  # posts per request: keeps us inside the free-tier request limits
TEXT_CHARS = 600


def _one_of(options: dict[str, str]):
    """A type that only accepts the taxonomy's ids, so Gemini cannot invent a label."""
    return Literal[tuple(options)]


class GeminiLabel(BaseModel):
    """One post's labels, as Gemini must return them."""

    post_id: int
    topic: _one_of(TOPICS)
    hook_type: _one_of(HOOKS)
    hook_text: str
    cta: _one_of(CTAS)
    is_relevant: bool
    confidence: float


def _describe(options: dict[str, str]) -> str:
    return "\n".join(f"- {key}: {text}" for key, text in options.items())


def build_prompt(items: list[PostText]) -> str:
    posts = "\n".join(
        json.dumps(
            {
                "post_id": item.post_id,
                "platform": item.platform,
                "title": item.title,
                "text": (item.text or "")[:TEXT_CHARS],
            },
            ensure_ascii=False,
        )
        for item in items
    )
    return f"""You label social media posts from US life insurance agents and agencies.
Return a JSON list with exactly one object per post, using the post_id given.

topic: what the post is mostly about. One of:
{_describe(TOPICS)}
Topic rules:
- Use a product topic (term_life, iul, final_expense...) only when the post is about that product.
- agent_recruiting is only for posts that invite agents to join a team or agency, or are about
  recruiting. Sales skills, leadership and business advice for agents are sales_training.
- Use "other" when no topic clearly fits. Do not force a topic onto a post.

hook_type: how the post opens (judge the title, or the first sentence of the text). One of:
{_describe(HOOKS)}

cta: the call to action, if any. One of:
{_describe(CTAS)}

hook_text: the opening line, copied exactly (the title, or the first sentence),
at most {HOOK_MAX_CHARS} characters.
is_relevant: true if the post is about life insurance or annuities, or about the work of
insurance agents and agencies (selling, leads, recruiting, training), even when no product is
named. False for posts that have nothing to do with selling insurance (personal life, lifestyle,
beauty, parenting, memes, motivation), and for content only about health, Medicare, auto or
home insurance.
confidence: how sure you are, from 0 to 1.

Posts, one JSON object per line:
{posts}
"""


def _to_result(label: GeminiLabel, item: PostText) -> LabelResult:
    return LabelResult(
        topic=label.topic,
        hook_type=label.hook_type,
        # Gemini sometimes paraphrases; the opening line is cheap to get exactly right.
        hook_text=opening_line(item.title, item.text) or label.hook_text[:HOOK_MAX_CHARS] or None,
        cta=label.cta,
        is_relevant=label.is_relevant,
        confidence=min(1.0, max(0.0, label.confidence)),
    )


class GeminiLabeler:
    def __init__(self, gemini: GeminiJson) -> None:
        self._gemini = gemini

    def label_batch(self, items: list[PostText]) -> BatchResult:
        answers = self._gemini.ask(build_prompt(items), list[GeminiLabel])
        if answers is None:
            return BatchResult(
                {item.post_id: None for item in items}, error=self._gemini.last_error
            )

        valid: dict[int, GeminiLabel] = {}
        for answer in answers:
            try:
                label = GeminiLabel.model_validate(answer)
            except ValidationError:
                continue  # an invalid label for one post must not spoil the others
            valid[label.post_id] = label
        labels = {
            item.post_id: _to_result(valid[item.post_id], item) if item.post_id in valid else None
            for item in items
        }
        return BatchResult(labels, model=self._gemini.model_used, error=self._gemini.last_error)

    def as_labeler(self) -> Labeler:
        return Labeler(
            name="gemini",
            model=self._gemini.model,
            label=label_post,  # unused: this labeler works in batches
            label_batch=self.label_batch,
            batch_size=BATCH_SIZE,
        )
