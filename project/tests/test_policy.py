"""应答决策测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.engine.intent import parse_intent
from app.engine.policy import decide
from app.models import Fact, Role, Script
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


def _role(script: Script, role_id: str) -> Role:
    return next(role for role in script.roles if role.id == role_id)


def _fact(script: Script, fact_id: str) -> Fact:
    return next(fact for fact in script.facts if fact.id == fact_id)


def test_culprit_lies_under_no_pressure(script: Script) -> None:
    decision = decide(
        _role(script, "r1"),
        _fact(script, "f04"),
        parse_intent("你用什么打他"),
        0.0,
    )

    assert decision.action == "lie"
    assert decision.fact_id == "f04"
    assert decision.is_lie is True
    assert decision.content is None


def test_pressure_moves_culprit_from_lie_to_evade_to_disclose(
    script: Script,
) -> None:
    role = _role(script, "r1")
    fact = _fact(script, "f04")
    intent = parse_intent("你用什么打他")

    actions = [
        decide(role, fact, intent, pressure).action
        for pressure in (0.0, 0.5, 1.0)
    ]

    assert actions == ["lie", "evade", "disclose"]


def test_disclose_content_is_fact_text(script: Script) -> None:
    fact = _fact(script, "f04")
    decision = decide(
        _role(script, "r1"),
        fact,
        parse_intent("你用什么打他"),
        1.0,
    )

    assert decision.action == "disclose"
    assert decision.content == fact.text
    assert decision.is_lie is False


def test_belief_is_disclosed_as_truth_not_lie(script: Script) -> None:
    fact = _fact(script, "f03")
    decision = decide(
        _role(script, "r2"),
        fact,
        parse_intent("争吵什么时候停的"),
        0.0,
    )

    assert decision.action == "disclose"
    assert decision.content == fact.belief["r2"]
    assert decision.content != fact.text
    assert decision.is_lie is False


def test_high_risk_belief_is_not_recorded_as_lie(script: Script) -> None:
    fact = _fact(script, "f03").model_copy(update={"sensitivity": 1.0})
    decision = decide(
        _role(script, "r2"),
        fact,
        parse_intent("争吵什么时候停的"),
        0.0,
    )

    assert decision.action == "evade"
    assert decision.fact_id == "f03"
    assert decision.is_lie is False


def test_no_knowledge_evades_without_fact(script: Script) -> None:
    decision = decide(
        _role(script, "r4"),
        None,
        parse_intent("凶器是什么"),
        0.0,
    )

    assert decision.action == "evade"
    assert decision.fact_id is None
    assert decision.content is None


def test_unparsed_question_requests_clarification(script: Script) -> None:
    decision = decide(
        _role(script, "r1"),
        None,
        parse_intent("那根棍子呢"),
        0.0,
    )

    assert decision.action == "unparsed"
    assert decision.fact_id is None
    assert decision.content is None


def test_unparsed_differs_from_no_knowledge(script: Script) -> None:
    role = _role(script, "r4")

    no_knowledge = decide(role, None, parse_intent("凶器是什么"), 0.0)
    unparsed = decide(role, None, parse_intent("那根棍子呢"), 0.0)

    assert no_knowledge.action == "evade"
    assert unparsed.action == "unparsed"


def test_non_holder_fact_is_treated_as_no_knowledge(
    script: Script,
) -> None:
    decision = decide(
        _role(script, "r4"),
        _fact(script, "f05"),
        parse_intent("你看见沈玉兰从书房出来吗"),
        0.0,
    )

    assert decision.action == "evade"
    assert decision.fact_id is None


def test_low_propensity_npc_evades_instead_of_lying(
    script: Script,
) -> None:
    fact = _fact(script, "f05").model_copy(update={"sensitivity": 1.0})
    decision = decide(
        _role(script, "r3"),
        fact,
        parse_intent("你看见什么"),
        0.0,
    )

    assert decision.action == "evade"
    assert decision.fact_id == "f05"
    assert decision.is_lie is False


@pytest.mark.parametrize("pressure", [-1.0, 2.0])
def test_pressure_is_bounded(script: Script, pressure: float) -> None:
    decision = decide(
        _role(script, "r1"),
        _fact(script, "f04"),
        parse_intent("凶器"),
        pressure,
    )

    assert 0.0 <= decision.risk <= 1.0


def test_decisions_cover_all_four_actions(script: Script) -> None:
    role = _role(script, "r1")
    fact = _fact(script, "f04")
    intent = parse_intent("凶器")
    decisions = [
        decide(role, fact, intent, 0.0),
        decide(role, fact, intent, 0.5),
        decide(role, fact, intent, 1.0),
        decide(role, None, parse_intent("那根棍子呢"), 0.0),
    ]

    assert {decision.action for decision in decisions} == {
        "disclose",
        "evade",
        "lie",
        "unparsed",
    }

def test_risk_is_independent_of_lie_propensity(script: Script) -> None:
    fact = _fact(script, "f04")
    base_role = _role(script, "r1")
    honest = base_role.model_copy(update={"lie_propensity": 0.0})
    liar = base_role.model_copy(update={"lie_propensity": 1.0})
    intent = parse_intent("凶器")
    pressure = 0.5

    honest_decision = decide(honest, fact, intent, pressure)
    liar_decision = decide(liar, fact, intent, pressure)

    assert honest_decision.risk == liar_decision.risk


def test_lie_propensity_only_changes_protection_style(
    script: Script,
) -> None:
    fact = _fact(script, "f05").model_copy(update={"sensitivity": 1.0})
    base_role = _role(script, "r3")
    liar = base_role.model_copy(update={"lie_propensity": 0.9})
    honest = base_role.model_copy(update={"lie_propensity": 0.3})
    intent = parse_intent("你看见什么")
    pressure = 0.3

    liar_decision = decide(liar, fact, intent, pressure)
    honest_decision = decide(honest, fact, intent, pressure)

    assert liar_decision.risk == honest_decision.risk
    assert liar_decision.action == "lie"
    assert honest_decision.action == "evade"

def test_risk_by_holder_overrides_base_sensitivity(script: Script) -> None:
    """f11 对收钱的老韩是低风险，对给钱的沈玉兰是高风险的。"""
    fact = _fact(script, "f11")
    intent = parse_intent("那包银元是谁给的")

    paid = decide(_role(script, "r5"), fact, intent, 0.0)
    payer = decide(_role(script, "r1"), fact, intent, 0.0)

    assert paid.action == "disclose"
    assert paid.content == fact.text
    assert payer.action != "disclose"
    assert payer.fact_id == "f11"
    assert payer.risk == pytest.approx(0.9)


def test_risk_by_holder_falls_back_to_sensitivity(script: Script) -> None:
    fact = _fact(script, "f11")
    other = _role(script, "r3")

    decision = decide(other, fact, parse_intent("银元"), 0.0)

    assert decision.fact_id is None
    assert decision.action == "evade"