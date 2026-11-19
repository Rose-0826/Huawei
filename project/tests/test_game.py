"""内存局状态机测试。"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from pathlib import Path

import pytest

from app.config import MAX_QUESTION_CHARS
from app.game import (
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
    assert outcome.unlocked_clue is not None
    assert outcome.unlocked_clue.id == "c01"
    assert state.pressure["r3"] == pytest.approx(0.25)
    assert state.last_questions["r3"] == "那晚你看见什么"


def test_pressure_caps_at_one(store: GameStore, script: Script) -> None:
    state = store.start(script)
    _ask_weapon(store, state.game_id)
    ask(store, state.game_id, "r3", "那晚你看见什么", FakeLLM())

    outcome = None
    for _ in range(4):
        outcome = present_clue(
            store,
            state.game_id,
            "r3",
            "c03",
            FakeLLM(),
        )
        assert outcome.ok is True

    assert outcome is not None
    assert outcome.pressure == pytest.approx(1.0)
    assert state.pressure["r3"] == pytest.approx(1.0)


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
    assert [fact.id for fact in outcome.timeline] == script.solution_path
    assert outcome.missed_fact_ids == ("f06", "f08", "f15", "f16")
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

    assert [clue.id for clue in first_view.clues] == ["c03", "c01"]
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