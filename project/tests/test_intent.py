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
    intent = parse_intent("你昨晚几点看见他")

    assert intent.topics == ("time", "event")
    assert "几点" in intent.keywords
    assert "昨晚" in intent.keywords
    assert "看见" in intent.keywords


def test_parse_intent_deduplicates_keywords() -> None:
    intent = parse_intent("你看见我看见你")

    assert intent.keywords.count("看见") == 1


@pytest.mark.parametrize(
    "question",
    [
        "你打算怎么办",
        "那根棍子呢",
        "你休息得如何",
        "今天天气不错",
    ],
)
def test_ambiguous_questions_have_no_topic(question: str) -> None:
    assert parse_intent(question).topics == ()


@pytest.mark.parametrize(
    ("question", "topics"),
    [
        ("他哪里受伤了", ("weapon",)),
        ("那场火是谁放的", ("motive",)),
        ("你妻子认识他吗", ("relation",)),
        ("你们吵架了吗", ("event",)),
        ("账本拿来我看看", ("motive", "relation")),
        ("把那本登记簿给我看看", ("motive", "event")),
    ],
)
def test_replacement_double_char_keywords_still_match(
    question: str,
    topics: tuple[str, ...],
) -> None:
    assert parse_intent(question).topics == topics


@pytest.mark.parametrize(
    ("question", "keyword"),
    [
        ("22:30 前后是不是在吵架？", "争吵"),
        ("案发之后他给过你钱吗", "银元"),
        ("账本上记了什么", "对账"),
        ("登记簿还在不在", "登记记录"),
    ],
)
def test_synonym_groups_expand_keywords(
    question: str,
    keyword: str,
) -> None:
    assert keyword in parse_intent(question).keywords