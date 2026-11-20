"""对质判定：比较两人对同一问题的口径。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.engine.policy import DecisionAction

Alignment = Literal["aligned", "conflicting", "unclear"]

_QUIET: tuple[DecisionAction, ...] = ("evade", "unparsed")


@dataclass(frozen=True)
class Statement:
    """一条可供比对的口径：动作、事实与最终说出的内容。"""

    action: DecisionAction
    fact_id: str | None
    content: str | None


def compare_testimony(left: Statement, right: Statement) -> Alignment:
    """比较两份口径，只判断一致与否，不判断谁说谎。"""
    if left.action in _QUIET and right.action in _QUIET:
        return "unclear"
    if left.action == "lie" and right.action == "lie":
        return _same_fact(left, right)
    if left.action == "disclose" and right.action == "disclose":
        return _compare_disclosures(left, right)
    if "disclose" in (left.action, right.action):
        other = right if left.action == "disclose" else left
        if other.action == "lie":
            return _same_fact(left, right)
        return "unclear"
    return "unclear"


def _same_fact(left: Statement, right: Statement) -> Alignment:
    """两条口径指向同一条事实才算对不上，否则只是说不清。"""
    if left.fact_id is None or left.fact_id != right.fact_id:
        return "unclear"
    return "conflicting"


def _compare_disclosures(left: Statement, right: Statement) -> Alignment:
    """比较两份如实披露：topic 不同只算说不清，同一条事实才看措辞。"""
    if left.fact_id is None or left.fact_id != right.fact_id:
        return "unclear"
    if left.content == right.content:
        return "aligned"
    return "conflicting"