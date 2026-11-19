"""知识边界检索测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import RETRIEVAL_MAX_RESULTS
from app.engine.intent import parse_intent
from app.engine.retrieval import retrieve
from app.models import Fact, Script
from app.script_loader import load_script

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "scripts"
    / "mistvale-inn.json"
)


@pytest.fixture(scope="module")
def script() -> Script:
    return load_script(SCRIPT_PATH)


def _ids(facts: list[Fact]) -> list[str]:
    return [fact.id for fact in facts]


@pytest.mark.parametrize("npc_id", ["r2", "r4", "r5"])
def test_weapon_question_returns_empty_without_weapon_knowledge(
    script: Script,
    npc_id: str,
) -> None:
    hits = retrieve(script, npc_id, parse_intent("凶器是什么"))

    assert hits == []


def test_weapon_question_returns_only_held_weapon_facts(
    script: Script,
) -> None:
    intent = parse_intent("凶器是什么")

    assert _ids(retrieve(script, "r1", intent)) == ["f04", "f08"]
    assert _ids(retrieve(script, "r3", intent)) == ["f07"]


def test_retrieval_never_returns_facts_outside_holders(
    script: Script,
) -> None:
    intent = parse_intent("你看见沈玉兰从书房出来吗")
    hits = retrieve(script, "r4", intent)

    assert "f05" not in _ids(hits)
    assert all("r4" in fact.holders for fact in hits)


@pytest.mark.parametrize("npc_id", ["r1", "r2", "r3", "r4", "r5"])
def test_every_hit_is_held_by_npc(
    script: Script,
    npc_id: str,
) -> None:
    hits = retrieve(script, npc_id, parse_intent("那晚发生了什么"))

    assert all(npc_id in fact.holders for fact in hits)


def test_unknown_question_returns_empty(script: Script) -> None:
    intent = parse_intent("今天天气不错")

    assert intent.topics == ()
    assert retrieve(script, "r1", intent) == []


def test_empty_question_returns_empty(script: Script) -> None:
    assert retrieve(script, "r1", parse_intent("")) == []


def test_unknown_npc_returns_empty(script: Script) -> None:
    assert retrieve(script, "r9", parse_intent("凶器是什么")) == []


def test_keyword_match_ranks_first(script: Script) -> None:
    hits = retrieve(script, "r2", parse_intent("你听见争吵了吗"))

    assert hits[0].id == "f02"


def test_only_matching_topics_are_returned(script: Script) -> None:
    hits = retrieve(script, "r1", parse_intent("凶器是什么"))

    assert all("weapon" in fact.topic for fact in hits)


def test_results_are_limited(script: Script) -> None:
    hits = retrieve(script, "r1", parse_intent("那晚发生了什么"))

    assert len(hits) <= RETRIEVAL_MAX_RESULTS


def test_retrieval_is_deterministic(script: Script) -> None:
    intent = parse_intent("你听见争吵了吗")
    first = _ids(retrieve(script, "r2", intent))
    second = _ids(retrieve(script, "r2", intent))

    assert first == second