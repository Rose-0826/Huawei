"""线索对撞规则表：两张物证组合成一条新推断。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.config import COMBINE_PRESSURE, COMBINE_REACTION_TEMPLATE


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
        text="周砚青在楼梯口看见她攥着手帕，老韩随后收下银元——封口不是巧合。",
        pressure_npc="r5",
        pressure_delta=COMBINE_PRESSURE,
    ),
    ComboRule(
        clue_ids=("c01", "c07"),
        title="目击与封口",
        text="阿蘅看见她袖口带灰出了书房，转头又拿银元堵住老韩的嘴。",
        pressure_npc="r1",
        pressure_delta=COMBINE_PRESSURE,
    ),
    ComboRule(
        clue_ids=("c02", "c08"),
        title="时间线钉板",
        text="22:30 书房还在争吵，23:05 周砚青在楼梯口碰见她，她没回房，早睡之说站不住。",
        pressure_npc="r1",
        pressure_delta=COMBINE_PRESSURE,
    ),
    ComboRule(
        clue_ids=("c03", "c08"),
        title="争吵与凶器",
        text="22:30 的争吵就在书房，壁炉边又少了一根拨火棍，凶器正是从这儿出去的。",
        pressure_npc="r1",
        pressure_delta=COMBINE_PRESSURE,
    ),
    ComboRule(
        clue_ids=("c02", "c03"),
        title="楼梯口与凶器",
        text="23:05 她在楼梯口攥着手帕，书房壁炉边少了一根拨火棍，两样都对上。",
        pressure_npc="r1",
        pressure_delta=COMBINE_PRESSURE,
    ),
    ComboRule(
        clue_ids=("c05", "c08"),
        title="旧账新账",
        text="今晚书房吵得那样凶，三年前的登记簿又翻了出来——旧账新账，一块儿要算。",
        pressure_npc="r1",
        pressure_delta=COMBINE_PRESSURE,
    ),
    ComboRule(
        clue_ids=("c05", "c07"),
        title="封口与旧案",
        text="一包银元堵住老韩的嘴，三年前的登记簿却还在——她怕的不只是今晚。",
        pressure_npc="r1",
        pressure_delta=COMBINE_PRESSURE,
    ),
    ComboRule(
        clue_ids=("c03", "c07"),
        title="先动手再封口",
        text="一根拨火棍先动了手，一包银元随后堵上嘴，两件事的顺序对得严丝合缝。",
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


def reaction_line(name: str) -> str:
    """按目标角色姓名生成一句对撞后的模板反应。"""
    return COMBINE_REACTION_TEMPLATE.format(name=name)