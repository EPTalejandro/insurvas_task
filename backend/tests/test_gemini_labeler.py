import pytest

from app.gemini_client import GeminiJson
from app.labeling.gemini import BATCH_SIZE, TEXT_CHARS, GeminiLabel, GeminiLabeler, build_prompt
from app.labeling.service import PostText
from app.labeling.taxonomy import CTAS, HOOKS, TOPICS
from tests.gemini_fake import RESOLVED_MODEL, SECRET, Clock, FakeGemini, ids_in, label_for


def items(*ids):
    return [PostText(i, "youtube", f"Title {i}", f"Text of post {i}") for i in ids]


def labeler(fake):
    clock = Clock()
    gemini = GeminiJson(
        fake, "gemini-flash-lite-latest", 10, secret=SECRET, sleep=clock.sleep, clock=clock.clock
    )
    return GeminiLabeler(gemini)


def test_the_schema_only_allows_ids_from_the_taxonomy():
    properties = GeminiLabel.model_json_schema()["properties"]
    assert properties["topic"]["enum"] == list(TOPICS)
    assert properties["hook_type"]["enum"] == list(HOOKS)
    assert properties["cta"]["enum"] == list(CTAS)


def test_the_prompt_explains_the_taxonomy_and_lists_the_posts():
    prompt = build_prompt(items(7, 8))

    for ids in (TOPICS, HOOKS, CTAS):
        for key, description in ids.items():
            assert f"- {key}: {description}" in prompt
    assert ids_in(prompt) == [7, 8]
    assert "Title 7" in prompt
    assert "Medicare" in prompt  # the relevance rule is spelled out


def test_long_texts_are_cut_in_the_prompt():
    long_post = PostText(1, "instagram", None, "x" * (TEXT_CHARS * 3))
    prompt = build_prompt([long_post])
    assert "x" * TEXT_CHARS in prompt
    assert "x" * (TEXT_CHARS + 1) not in prompt


def test_valid_answers_become_labels_and_remember_the_model():
    result = labeler(FakeGemini()).label_batch(items(1, 2))

    assert result.model == RESOLVED_MODEL
    first = result.labels[1]
    assert (first.topic, first.hook_type, first.cta, first.is_relevant) == (
        "iul",
        "question",
        "book_call",
        True,
    )
    assert first.confidence == 0.9
    assert set(result.labels) == {1, 2}


def test_the_hook_text_is_the_real_opening_line_not_geminis_paraphrase():
    result = labeler(FakeGemini()).label_batch(items(1))
    assert result.labels[1].hook_text == "Title 1"


def test_an_invalid_label_only_affects_its_own_post():
    def answer(prompt):
        return [label_for(1), label_for(2, topic="made_up_topic"), label_for(3, hook_type=None)]

    result = labeler(FakeGemini(answer)).label_batch(items(1, 2, 3))

    assert result.labels[1] is not None
    assert result.labels[2] is None
    assert result.labels[3] is None


def test_a_post_missing_from_the_answer_gets_none():
    result = labeler(FakeGemini(lambda prompt: [label_for(1)])).label_batch(items(1, 2))
    assert result.labels[1] is not None
    assert result.labels[2] is None


def test_confidence_is_kept_between_0_and_1():
    answer = lambda prompt: [label_for(1, confidence=7.5), label_for(2, confidence=-3)]  # noqa: E731
    result = labeler(FakeGemini(answer)).label_batch(items(1, 2))
    assert (result.labels[1].confidence, result.labels[2].confidence) == (1.0, 0.0)


def test_when_gemini_fails_every_post_gets_none_and_the_error_is_reported():
    fake = FakeGemini(lambda prompt: RuntimeError(f"boom with {SECRET}"))

    result = labeler(fake).label_batch(items(1, 2))

    assert result.labels == {1: None, 2: None}
    assert "boom" in result.error
    assert SECRET not in result.error


def test_it_plugs_into_the_label_step_as_a_batch_labeler():
    plugged = labeler(FakeGemini()).as_labeler()
    assert plugged.name == "gemini"
    assert plugged.batch_size == BATCH_SIZE == 10
    assert plugged.label_batch is not None


@pytest.mark.parametrize("text", [None, ""])
def test_posts_without_text_can_be_labeled_too(text):
    post = PostText(1, "youtube", "Only a title", text)
    result = labeler(FakeGemini()).label_batch([post])
    assert result.labels[1] is not None
