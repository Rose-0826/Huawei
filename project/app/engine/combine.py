"""线索对撞规则表：两张物证组合成一条新推断。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.config import COMBINE_PRESSURE


@dataclass(frozen=True)
class ComboRule:
    """一条对撞规则：两张物证、一条推断与受压角色。"""

    clue_ids: tuple[str, str]
    title: str
    text: str
    pressure_npc: str | None
    pressure_delta: float


COMBO_RULES: tuple[ComboRule, ...] = (
    ComboRule(
        clue_ids=("c01", "c02"),
        title="时间线钉板",
        text="23:00 她离开书房，23:05 还在楼梯口——所谓早早回房不成立。",
        pressure_npc="r1",
        pressure_delta=COMBINE_PRESSURE,
    ),
    ComboRule(
        clue_ids=("c03", "c04"),
        title="凶器确认",
        text="壁炉边少的那根拨火棍，正是雪堆里带血的那根，凶器对上了。",
        pressure_npc="r1",
        pressure_delta=COMBINE_PRESSURE,
    ),
    ComboRule(
        clue_ids=("c05", "c06"),
        title="旧案重开",
        text="登记簿的日期与油灯对得上，三年前那场火不是意外。",
        pressure_npc="r1",
        pressure_delta=COMBINE_PRESSURE,
    ),
    ComboRule(
        clue_ids=("c08", "c04"),
        title="争吵后的凶器",
        text="22:30 争吵后，凶器在 23:20 前后进了雪堆，动手就在争吵之后。",
        pressure_npc="r1",
        pressure_delta=COMBINE_PRESSURE,
    ),
    ComboRule(
        clue_ids=("c02", "c07"),
        title="封口动机",
        text="老韩在楼梯口看见了她，随后就收下了那包银元，封口不是巧合。",
        pressure_npc="r5",
        pressure_delta=COMBINE_PRESSURE,
    ),
    ComboRule(
        clue_ids=("c01", "c07"),
        title="目击与封口",
        text="阿蘅看见她出书房，她又塞钱给老韩，看见的人都被买住了。",
        pressure_npc="r1",
        pressure_delta=COMBINE_PRESSURE,
    ),
)


def find_rule(clue_ids: Iterable[str]) -> ComboRule | None:
    """按两张物证的集合匹配规则，正反顺序都算，找不到返回空。"""
    wanted = frozenset(clue_ids)
    if len(wanted) != 2:
        return None
    for rule in COMBO_RULES:
        if frozenset(rule.clue_ids) == wanted:
            return rule
    return None