"""线索对撞规则表与状态机测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import MAX_COMBINE_PER_GAME, MAX_COMBO_TEXT_CHARS, MAX_PRESSURE
from app.engine.combine import COMBO_RULES, find_rule
from app.game import GameState, GameStore, accuse, combine
from app.models import Script
from app.script_loader import load_script

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "scripts"
    / "mistvale-inn.json"
)


@pytest.fixture
def script() -> Script:
    return load_script(SCRIPT_PATH)


@pytest.fixture
def store() -> GameStore:
    return GameStore()


def _unlock(state: GameState, *clue_ids: str) -> None:
    state.unlocked_clue_ids.extend(clue_ids)


def test_rules_cover_known_clues_without_duplicates(script: Script) -> None:
    clue_ids = {clue.id for clue in script.clues}
    role_ids = {role.id for role in script.roles}
    seen: set[frozenset[str]] = set()

    assert len(COMBO_RULES) >= 6
    for rule in COMBO_RULES:
        assert len(rule.clue_ids) == 2
        assert rule.clue_ids[0] != rule.clue_ids[1]
        assert set(rule.clue_ids) <= clue_ids
        assert rule.title
        assert 0 < len(rule.text) <= MAX_COMBO_TEXT_CHARS
        assert rule.pressure_npc is None or rule.pressure_npc in role_ids
        assert 0.0 <= rule.pressure_delta <= 1.0
        key = frozenset(rule.clue_ids)
        assert key not in seen
        seen.add(key)


def test_find_rule_matches_both_orders() -> None:
    forward = find_rule(("c01", "c02"))
    backward = find_rule(("c02", "c01"))

    assert forward is not None
    assert forward == backward
    assert forward.title == "时间线钉板"


def test_find_rule_returns_none_for_unknown_pairs() -> None:
    assert find_rule(("c01", "c03")) is None
    assert find_rule(("c01",)) is None
    assert find_rule(("c01", "c01")) is None
    assert find_rule(("c99", "c01")) is None


def test_combine_hits_rule_and_raises_pressure(
    store: GameStore,
    script: Script,
) -> None:
    state = store.start(script)
    _unlock(state, "c01", "c02")

    outcome = combine(store, state.game_id, ("c01", "c02"))

    assert outcome.ok is True
    assert outcome.error is None
    assert outcome.title == "时间线钉板"
    assert "23:00" in outcome.text
    assert "23:05" in outcome.text
    assert outcome.pressure == {"r1": pytest.approx(0.10)}
    assert outcome.remaining == MAX_COMBINE_PER_GAME - 1
    assert state.pressure["r1"] == pytest.approx(0.10)
    assert state.combine_count == 1
    assert state.combine_pairs == {("c01", "c02")}


def test_combine_does_not_unlock_new_clue(
    store: GameStore,
    script: Script,
) -> None:
    state = store.start(script)
    _unlock(state, "c01", "c02")

    outcome = combine(store, state.game_id, ("c02", "c01"))

    assert outcome.ok is True
    assert state.unlocked_clue_ids == ["c01", "c02"]


def test_combine_reverses_order_and_rejects_duplicate_pair(
    store: GameStore,
    script: Script,
) -> None:
    state = store.start(script)
    _unlock(state, "c01", "c02")

    first = combine(store, state.game_id, ("c02", "c01"))
    second = combine(store, state.game_id, ("c01", "c02"))

    assert first.ok is True
    assert second.ok is False
    assert second.error == "combine_already_used"
    assert state.combine_count == 1


def test_combine_limit_blocks_fourth_pair(
    store: GameStore,
    script: Script,
) -> None:
    state = store.start(script)
    _unlock(state, "c01", "c02", "c03", "c04", "c05", "c06", "c08")

    for pair in (("c01", "c02"), ("c03", "c04"), ("c05", "c06")):
        outcome = combine(store, state.game_id, pair)
        assert outcome.ok is True

    fourth = combine(store, state.game_id, ("c08", "c04"))

    assert fourth.ok is False
    assert fourth.error == "combine_limit_reached"
    assert fourth.remaining == 0
    assert state.combine_count == MAX_COMBINE_PER_GAME


def test_combine_requires_two_distinct_clues(
    store: GameStore,
    script: Script,
) -> None:
    state = store.start(script)
    _unlock(state, "c01", "c02")

    assert combine(store, state.game_id, ("c01",)).error == "combine_needs_two"
    assert combine(store, state.game_id, ("c01", "c01")).error == (
        "combine_needs_two"
    )
    assert combine(store, state.game_id, ("c01", "c02", "c03")).error == (
        "combine_needs_two"
    )


def test_combine_rejects_unknown_clue(
    store: GameStore,
    script: Script,
) -> None:
    state = store.start(script)
    _unlock(state, "c01")

    outcome = combine(store, state.game_id, ("c01", "c99"))

    assert outcome.ok is False
    assert outcome.error == "clue_not_found"


def test_combine_rejects_locked_clue(
    store: GameStore,
    script: Script,
) -> None:
    state = store.start(script)
    _unlock(state, "c02")

    outcome = combine(store, state.game_id, ("c01", "c02"))

    assert outcome.ok is False
    assert outcome.error == "clue_not_unlocked"
    assert state.combine_count == 0


def test_combine_rejects_pair_without_rule(
    store: GameStore,
    script: Script,
) -> None:
    state = store.start(script)
    _unlock(state, "c01", "c03")

    outcome = combine(store, state.game_id, ("c01", "c03"))

    assert outcome.ok is False
    assert outcome.error == "combine_not_found"
    assert state.combine_count == 0
    assert state.pressure.get("r1", 0.0) == 0.0


def test_combine_caps_pressure_at_one(
    store: GameStore,
    script: Script,
) -> None:
    state = store.start(script)
    _unlock(state, "c01", "c02")
    state.pressure["r1"] = 0.95

    outcome = combine(store, state.game_id, ("c01", "c02"))

    assert outcome.pressure == {"r1": pytest.approx(MAX_PRESSURE)}
    assert state.pressure["r1"] == pytest.approx(MAX_PRESSURE)


def test_combine_pressure_targets_rule_npc(
    store: GameStore,
    script: Script,
) -> None:
    state = store.start(script)
    _unlock(state, "c02", "c07")

    outcome = combine(store, state.game_id, ("c07", "c02"))

    assert outcome.ok is True
    assert set(outcome.pressure) == {"r5"}
    assert state.pressure["r5"] == pytest.approx(0.10)


def test_combine_rejects_missing_or_ended_game(
    store: GameStore,
    script: Script,
) -> None:
    assert combine(store, "missing", ("c01", "c02")).error == "game_not_found"

    state = store.start(script)
    _unlock(state, "c01", "c02")
    accuse(store, state.game_id, "r1")

    assert combine(store, state.game_id, ("c01", "c02")).error == "game_ended"