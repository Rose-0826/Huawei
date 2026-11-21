"""内存局状态机测试。"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from pathlib import Path

import pytest

from app.config import MAX_QUESTION_CHARS
from app.game import (
    REPEATED_QUESTION_REPLY,
    GameStore,
    accuse,
    ask,
    build_view,
    get_view,
    present_clue,
)
from app.models import Script
from app.script_loader import load_script

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "scripts"
    / "mistvale-inn.json"
)


class FakeLLM:
    def __init__(self, reply: str = "我记得些片段，但说不清。") -> None:
        self.reply = reply
        self.calls: list[tuple[str, str]] = []

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        return self.reply


@pytest.fixture
def script() -> Script:
    data = load_script(SCRIPT_PATH)
    facts = {fact.id: fact for fact in data.facts}
    facts["f05"].sensitivity = 0.7
    return data


@pytest.fixture
def store() -> GameStore:
    return GameStore()


def _ask_weapon(store: GameStore, game_id: str) -> None:
    outcome = ask(
        store,
        game_id,
        "r3",
        "壁炉边的拨火棍呢",
        FakeLLM(),
    )
    assert outcome.ok is True
    assert outcome.unlocked_clue is not None
    assert outcome.unlocked_clue.id == "c03"


def test_start_creates_public_game(store: GameStore, script: Script) -> None:
    state = store.start(script)
    view = build_view(state)
    payload = asdict(view)

    assert uuid.UUID(state.game_id)
    assert view.title == script.title
    assert view.opening
    assert len(view.roles) == 5
    assert view.clues == ()
    assert view.pressure["r3"] == 0.0
    assert view.ended is False
    assert "culprit" not in payload
    assert "secret" not in str(payload)
    assert set(payload["roles"][0]) == {"id", "name", "public"}


def test_ask_disclose_unlocks_clue(store: GameStore, script: Script) -> None:
    state = store.start(script)
    outcome = ask(
        store,
        state.game_id,
        "r3",
        "壁炉边的拨火棍呢",
        FakeLLM(),
    )

    assert outcome.ok is True
    assert outcome.action == "disclose"
    assert outcome.unlocked_clue is not None
    assert outcome.unlocked_clue.id == "c03"
    assert state.unlocked_clue_ids == ["c03"]
    assert state.last_questions["r3"] == "壁炉边的拨火棍呢"


def test_ask_evade_does_not_unlock(store: GameStore, script: Script) -> None:
    state = store.start(script)
    outcome = ask(
        store,
        state.game_id,
        "r3",
        "那晚你看见什么",
        FakeLLM(),
    )

    assert outcome.ok is True
    assert outcome.action == "evade"
    assert outcome.unlocked_clue is None
    assert state.unlocked_clue_ids == []


def test_present_clue_increases_pressure_and_reanswers(
    store: GameStore,
    script: Script,
) -> None:
    state = store.start(script)
    _ask_weapon(store, state.game_id)
    ask(store, state.game_id, "r3", "那晚你看见什么", FakeLLM())

    outcome = present_clue(
        store,
        state.game_id,
        "r3",
        "c03",
        FakeLLM(),
    )

    assert outcome.ok is True
    assert outcome.pressure == pytest.approx(0.25)
    assert outcome.action == "disclose"
    assert outcome.decision is not None
    assert outcome.decision.fact_id == "f07"
    assert outcome.unlocked_clue is None
    assert state.pressure["r3"] == pytest.approx(0.25)
    assert state.last_questions["r3"] == "那晚你看见什么"


def test_pressure_caps_at_one(store: GameStore, script: Script) -> None:
    state = store.start(script)
    state.unlocked_clue_ids.extend(["c01", "c03", "c04", "c07"])
    state.last_questions["r3"] = "那晚你看见什么"

    outcome = None
    for clue_id in ("c01", "c03", "c04", "c07"):
        outcome = present_clue(
            store,
            state.game_id,
            "r3",
            clue_id,
            FakeLLM(),
        )
        assert outcome.ok is True

    assert outcome is not None
    assert outcome.pressure == pytest.approx(1.0)
    assert state.pressure["r3"] == pytest.approx(1.0)


def test_same_clue_same_npc_only_once(
    store: GameStore,
    script: Script,
) -> None:
    state = store.start(script)
    _ask_weapon(store, state.game_id)
    ask(store, state.game_id, "r3", "那晚你看见什么", FakeLLM())

    first = present_clue(
        store,
        state.game_id,
        "r3",
        "c03",
        FakeLLM(),
    )
    second = present_clue(
        store,
        state.game_id,
        "r3",
        "c03",
        FakeLLM(),
    )

    assert first.ok is True
    assert first.pressure == pytest.approx(0.25)
    assert second.ok is False
    assert second.error == "clue_already_presented"
    assert state.pressure["r3"] == pytest.approx(0.25)


def test_same_clue_different_npcs_both_work(
    store: GameStore,
    script: Script,
) -> None:
    state = store.start(script)
    _ask_weapon(store, state.game_id)
    ask(store, state.game_id, "r1", "你用什么打他", FakeLLM())

    first = present_clue(
        store,
        state.game_id,
        "r3",
        "c03",
        FakeLLM(),
    )
    second = present_clue(
        store,
        state.game_id,
        "r1",
        "c03",
        FakeLLM(),
    )

    assert first.ok is True
    assert second.ok is True
    assert state.pressure["r3"] == pytest.approx(0.25)
    assert state.pressure["r1"] == pytest.approx(0.25)
    assert state.presented_clue_pairs == {
        ("c03", "r3"),
        ("c03", "r1"),
    }


def test_present_requires_unlocked_clue(
    store: GameStore,
    script: Script,
) -> None:
    state = store.start(script)

    outcome = present_clue(
        store,
        state.game_id,
        "r3",
        "c01",
        FakeLLM(),
    )

    assert outcome.ok is False
    assert outcome.error == "clue_not_unlocked"


def test_present_requires_question(store: GameStore, script: Script) -> None:
    state = store.start(script)
    _ask_weapon(store, state.game_id)

    outcome = present_clue(
        store,
        state.game_id,
        "r1",
        "c03",
        FakeLLM(),
    )

    assert outcome.ok is False
    assert outcome.error == "no_question_asked"


def test_ask_and_present_validation_errors(
    store: GameStore,
    script: Script,
) -> None:
    assert ask(store, "missing", "r3", "问题", FakeLLM()).error == "game_not_found"

    state = store.start(script)
    assert (
        ask(store, state.game_id, "r9", "问题", FakeLLM()).error
        == "npc_not_found"
    )
    assert (
        ask(store, state.game_id, "r3", "   ", FakeLLM()).error
        == "empty_question"
    )
    long_question = "问" * (MAX_QUESTION_CHARS + 1)
    assert (
        ask(store, state.game_id, "r3", long_question, FakeLLM()).error
        == "question_too_long"
    )
    assert (
        present_clue(store, state.game_id, "r3", "c99", FakeLLM()).error
        == "clue_not_found"
    )
    assert (
        present_clue(store, "missing", "r3", "c03", FakeLLM()).error
        == "game_not_found"
    )
    assert (
        present_clue(store, state.game_id, "r9", "c03", FakeLLM()).error
        == "npc_not_found"
    )


def test_accuse_returns_truth_and_missed_facts(
    store: GameStore,
    script: Script,
) -> None:
    state = store.start(script)
    _ask_weapon(store, state.game_id)
    ask(store, state.game_id, "r3", "那晚你看见什么", FakeLLM())
    present_clue(store, state.game_id, "r3", "c03", FakeLLM())

    outcome = accuse(store, state.game_id, "r1")

    assert outcome.ok is True
    assert outcome.correct is True
    assert outcome.partial is False
    assert outcome.dimensions == ()
    assert [fact.id for fact in outcome.timeline] == script.solution_path
    assert outcome.missed_fact_ids == ("f05", "f06", "f08", "f15", "f16")
    assert state.ended is True
    view = get_view(store, state.game_id)
    assert view is not None
    assert view.ended is True
    assert (
        ask(store, state.game_id, "r3", "还能问吗", FakeLLM()).error
        == "game_ended"
    )
    assert (
        present_clue(store, state.game_id, "r3", "c03", FakeLLM()).error
        == "game_ended"
    )
    assert accuse(store, state.game_id, "r1") == outcome


def test_accuse_wrong_suspect_marks_all_missed(
    store: GameStore,
    script: Script,
) -> None:
    state = store.start(script)

    outcome = accuse(store, state.game_id, "r2")

    assert outcome.ok is True
    assert outcome.correct is False
    assert outcome.partial is False
    assert outcome.dimensions == ()
    assert [fact.id for fact in outcome.timeline] == script.solution_path
    assert outcome.missed_fact_ids == tuple(script.solution_path)


def test_games_are_isolated(store: GameStore, script: Script) -> None:
    first = store.start(script)
    second = store.start(script)

    _ask_weapon(store, first.game_id)
    ask(store, first.game_id, "r3", "那晚你看见什么", FakeLLM())
    present_clue(store, first.game_id, "r3", "c03", FakeLLM())

    first_view = build_view(first)
    second_view = build_view(second)

    assert [clue.id for clue in first_view.clues] == ["c03"]
    assert first_view.pressure["r3"] == pytest.approx(0.25)
    assert second_view.clues == ()
    assert second_view.pressure["r3"] == 0.0


def test_view_excludes_secrets_and_solution(store: GameStore, script: Script) -> None:
    state = store.start(script)

    payload = asdict(build_view(state))

    assert "culprit" not in payload
    assert "solution_path" not in payload
    assert "secret" not in str(payload)
    assert "alibi" not in str(payload)
    assert set(payload["roles"][0]) == {"id", "name", "public"}

def test_r5_discloses_silver_at_zero_pressure(
    store: GameStore,
    script: Script,
) -> None:
    state = store.start(script)

    outcome = ask(
        store,
        state.game_id,
        "r5",
        "那包银元是谁给的",
        FakeLLM(),
    )

    assert outcome.ok is True
    assert outcome.action == "disclose"
    assert outcome.decision is not None
    assert outcome.decision.fact_id == "f11"
    assert outcome.unlocked_clue is not None
    assert outcome.unlocked_clue.id == "c07"


def test_r1_does_not_disclose_silver_at_zero_pressure(
    store: GameStore,
    script: Script,
) -> None:
    state = store.start(script)

    outcome = ask(
        store,
        state.game_id,
        "r1",
        "那包银元是谁给的",
        FakeLLM(),
    )

    assert outcome.ok is True
    assert outcome.action != "disclose"
    assert outcome.unlocked_clue is None
    assert "c07" not in state.unlocked_clue_ids


def test_repeated_question_does_not_call_llm_or_raise_pressure(
    store: GameStore,
    script: Script,
) -> None:
    state = store.start(script)
    llm = FakeLLM()
    question = "壁炉边的拨火棍呢"

    first = ask(store, state.game_id, "r3", question, llm)
    calls_after_first = len(llm.calls)
    second = ask(store, state.game_id, "r3", question, llm)

    assert first.ok is True
    assert second.ok is True
    assert second.reply == REPEATED_QUESTION_REPLY
    assert len(llm.calls) == calls_after_first
    assert state.pressure.get("r3", 0.0) == 0.0
    assert state.last_questions["r3"] == question


def test_present_after_repeat_still_reanswers(
    store: GameStore,
    script: Script,
) -> None:
    state = store.start(script)
    question = "那晚你看见什么"
    ask(store, state.game_id, "r3", question, FakeLLM())
    ask(store, state.game_id, "r3", question, FakeLLM())
    state.unlocked_clue_ids.append("c03")

    outcome = present_clue(
        store,
        state.game_id,
        "r3",
        "c03",
        FakeLLM(),
    )

    assert outcome.ok is True
    assert outcome.pressure == pytest.approx(0.25)
    assert outcome.reply
    assert outcome.reply != REPEATED_QUESTION_REPLY

def test_belief_disclosure_does_not_unlock_clue(
    store: GameStore,
    script: Script,
) -> None:
    fact = next(item for item in script.facts if item.id == "f14")
    state = store.start(script)

    outcome = ask(
        store,
        state.game_id,
        "r2",
        "三年前那场火到底是怎么回事",
        FakeLLM(fact.belief["r2"]),
    )

    assert outcome.ok is True
    assert outcome.action == "disclose"
    assert outcome.decision is not None
    assert outcome.decision.content == fact.belief["r2"]
    assert outcome.unlocked_clue is None
    assert "c05" not in state.unlocked_clue_ids
    assert "f14" not in state.disclosed_fact_ids


def test_true_disclosure_still_unlocks_clue(
    store: GameStore,
    script: Script,
) -> None:
    state = store.start(script)

    outcome = ask(
        store,
        state.game_id,
        "r1",
        "三年前那场火到底是怎么回事",
        FakeLLM(),
    )

    assert outcome.ok is True
    assert outcome.action == "disclose"
    assert outcome.unlocked_clue is not None
    assert outcome.unlocked_clue.id == "c05"
    assert "f14" in state.disclosed_fact_ids


def test_ask_with_new_wording_advances_to_next_fact(
    store: GameStore,
    script: Script,
) -> None:
    state = store.start(script)

    first = ask(
        store,
        state.game_id,
        "r2",
        "争吵什么时候停的",
        FakeLLM(),
    )
    second = ask(
        store,
        state.game_id,
        "r2",
        "争吵是什么时候停下的",
        FakeLLM(),
    )

    assert first.decision is not None
    assert first.decision.fact_id == "f02"
    assert second.decision is not None
    assert second.decision.fact_id == "f03"
    assert state.answered_fact_ids["r2"] == ["f02", "f03"]


def test_present_reanswer_does_not_exclude_answered_fact(
    store: GameStore,
    script: Script,
) -> None:
    state = store.start(script)
    ask(store, state.game_id, "r2", "争吵什么时候停的", FakeLLM())

    outcome = present_clue(
        store,
        state.game_id,
        "r2",
        "c08",
        FakeLLM(),
    )

    assert outcome.ok is True
    assert outcome.decision is not None
    assert outcome.decision.fact_id == "f02"


def test_answered_fact_state_defaults_to_empty(
    store: GameStore,
    script: Script,
) -> None:
    state = store.start(script)

    assert state.answered_fact_ids == {}

def test_present_c02_to_r1_answers_f06_instead_of_last_question(
    store: GameStore,
    script: Script,
) -> None:
    state = store.start(script)
    ask(store, state.game_id, "r2", "23:05 楼梯口碰见谁", FakeLLM())
    ask(store, state.game_id, "r1", "22:45 之后你在哪儿", FakeLLM())

    outcome = present_clue(
        store,
        state.game_id,
        "r1",
        "c02",
        FakeLLM(),
    )

    assert outcome.ok is True
    assert outcome.decision is not None
    assert outcome.decision.fact_id == "f06"
    assert outcome.pressure == pytest.approx(0.25)


def test_present_c03_to_r3_answers_f07(
    store: GameStore,
    script: Script,
) -> None:
    state = store.start(script)
    _ask_weapon(store, state.game_id)
    ask(store, state.game_id, "r3", "那晚你看见什么", FakeLLM())

    outcome = present_clue(
        store,
        state.game_id,
        "r3",
        "c03",
        FakeLLM(),
    )

    assert outcome.ok is True
    assert outcome.decision is not None
    assert outcome.decision.fact_id == "f07"


def test_present_clue_without_source_fact_evades(
    store: GameStore,
    script: Script,
) -> None:
    state = store.start(script)
    ask(store, state.game_id, "r2", "23:05 楼梯口碰见谁", FakeLLM())
    previous = ask(store, state.game_id, "r3", "那晚你看见什么", FakeLLM())
    assert previous.decision is not None
    previous_fact_id = previous.decision.fact_id
    assert previous_fact_id is not None
    previous_fact = next(
        fact for fact in script.facts if fact.id == previous_fact_id
    )
    llm = FakeLLM()

    outcome = present_clue(
        store,
        state.game_id,
        "r3",
        "c02",
        llm,
    )

    assert outcome.ok is True
    assert outcome.action == "evade"
    assert outcome.decision is not None
    assert outcome.decision.fact_id is None
    assert outcome.reply != previous_fact.text
    assert previous_fact.text not in (outcome.reply or "")
    assert "物证" in llm.calls[-1][1]
    assert "不认识" in llm.calls[-1][1]
    assert state.last_questions["r3"] == "那晚你看见什么"