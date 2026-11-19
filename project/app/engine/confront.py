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
        return "conflicting"
    if left.action == "disclose" and right.action == "disclose":
        if left.fact_id is None or left.fact_id != right.fact_id:
            return "conflicting"
        if left.content is not None and left.content == right.content:
            return "aligned"
        return "conflicting"
    return "conflicting"