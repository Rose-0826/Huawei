"""意图解析测试。"""

from __future__ import annotations

import pytest

from app.engine.intent import parse_intent


@pytest.mark.parametrize(
    ("question", "topics"),
    [
        ("凶器是什么", ("weapon",)),
        ("你昨晚几点看见他", ("time", "event")),
        ("你为什么要杀他", ("motive", "event")),
        ("你和他是什么关系", ("relation",)),
        ("昨晚发生了什么", ("time", "event")),
        ("今天天气不错", ()),
        ("", ()),
    ],
)
def test_parse_intent_topics(
    question: str,
    topics: tuple[str, ...],
) -> None:
    assert parse_intent(question).topics == topics


def test_parse_intent_keeps_matched_keywords() -> None:
    intent = parse_intent("你昨晚几点看见谁")

    assert intent.topics == ("time", "relation", "event")
    assert "几点" in intent.keywords
    assert "昨晚" in intent.keywords
    assert "看见" in intent.keywords
    assert "谁" in intent.keywords


def test_parse_intent_deduplicates_keywords() -> None:
    intent = parse_intent("你看见谁，谁看见你")

    assert intent.keywords.count("看见") == 1
    assert intent.keywords.count("谁") == 1