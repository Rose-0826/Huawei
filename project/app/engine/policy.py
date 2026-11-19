"""应答决策：说、躲、骗，或请求澄清。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.config import (
    DECISION_DISCLOSE_THRESHOLD,
    DECISION_LIE_PROPENSITY_CUTOFF,
    DECISION_LIE_THRESHOLD,
    DECISION_PRESSURE_RELIEF,

)
from app.engine.intent import Intent
from app.models import Fact, Role

DecisionAction = Literal["disclose", "evade", "lie", "unparsed"]


@dataclass(frozen=True)
class Decision:
    """一次应答的决策结果，不包含具体措辞。"""

    action: DecisionAction
    fact_id: str | None
    content: str | None
    is_lie: bool
    risk: float


def decide(
    role: Role,
    fact: Fact | None,
    intent: Intent,
    pressure: float = 0.0,
) -> Decision:
    """根据事实风险、撒谎倾向和压力决定说、躲、骗或请求澄清。"""
    if fact is None:
        if not intent.topics:
            return Decision(
                action="unparsed",
                fact_id=None,
                content=None,
                is_lie=False,
                risk=0.0,
            )
        return Decision(
            action="evade",
            fact_id=None,
            content=None,
            is_lie=False,
            risk=0.0,
        )

    if role.id not in fact.holders:
        return Decision(
            action="evade",
            fact_id=None,
            content=None,
            is_lie=False,
            risk=0.0,
        )

    risk = _risk(fact, pressure)
    belief_text = fact.belief.get(role.id)
    if belief_text is not None:
        if risk <= DECISION_DISCLOSE_THRESHOLD:
            return Decision(
                action="disclose",
                fact_id=fact.id,
                content=belief_text,
                is_lie=False,
                risk=risk,
            )
        return Decision(
            action="evade",
            fact_id=fact.id,
            content=None,
            is_lie=False,
            risk=risk,
        )

    if risk <= DECISION_DISCLOSE_THRESHOLD:
        return Decision(
            action="disclose",
            fact_id=fact.id,
            content=fact.text,
            is_lie=False,
            risk=risk,
        )
    if (
        risk >= DECISION_LIE_THRESHOLD
        and role.lie_propensity >= DECISION_LIE_PROPENSITY_CUTOFF
    ):
        return Decision(
            action="lie",
            fact_id=fact.id,
            content=None,
            is_lie=True,
            risk=risk,
        )
    return Decision(
        action="evade",
        fact_id=fact.id,
        content=None,
        is_lie=False,
        risk=risk,
    )


def _risk(fact: Fact, pressure: float) -> float:
    bounded_pressure = max(0.0, min(1.0, pressure))
    raw = fact.sensitivity - DECISION_PRESSURE_RELIEF * bounded_pressure
    return max(0.0, min(1.0, raw))