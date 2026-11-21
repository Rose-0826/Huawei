"""指认四要素：动机、手法、时间的选项与逐项判定。"""

from __future__ import annotations

from dataclasses import dataclass

VERDICT_DIMENSION_IDS: tuple[str, ...] = ("motive", "method", "time")


@dataclass(frozen=True)
class VerdictOption:
    """一个可选项：稳定的 id 与面向玩家的中文标签。"""

    id: str
    label: str


@dataclass(frozen=True)
class DimensionResult:
    """一个维度的判定结果，choice 保留玩家原样输入。"""

    id: str
    label: str
    choice: str
    correct: bool


VERDICT_OPTIONS: dict[str, tuple[VerdictOption, ...]] = {
    "motive": (
        VerdictOption(id="money", label="图财"),
        VerdictOption(id="cover_fire", label="掩盖旧案"),
        VerdictOption(id="quarrel", label="争执失手"),
        VerdictOption(id="love", label="私情"),
    ),
    "method": (
        VerdictOption(id="poker", label="拨火棍"),
        VerdictOption(id="paperweight", label="镇纸"),
        VerdictOption(id="poison", label="毒药"),
        VerdictOption(id="rope", label="绳索"),
    ),
    "time": (
        VerdictOption(id="t2215", label="22:15 前后"),
        VerdictOption(id="t2245", label="22:45 前后"),
        VerdictOption(id="t2250", label="22:50 前后"),
        VerdictOption(id="t2300", label="23:00 前后"),
    ),
}

VERDICT_DIMENSION_LABELS: dict[str, str] = {
    "motive": "动机",
    "method": "手法",
    "time": "时间",
}

CORRECT_CHOICES: dict[str, str] = {
    "motive": "cover_fire",
    "method": "poker",
    "time": "t2250",
}


def judge_dimensions(
    choices: dict[str, str],
) -> tuple[DimensionResult, ...]:
    """逐项比对三个维度，未知或缺省的选项一律判错而不抛异常。"""
    results: list[DimensionResult] = []
    for dimension_id in VERDICT_DIMENSION_IDS:
        choice = choices.get(dimension_id, "")
        results.append(
            DimensionResult(
                id=dimension_id,
                label=VERDICT_DIMENSION_LABELS[dimension_id],
                choice=choice,
                correct=choice == CORRECT_CHOICES[dimension_id],
            )
        )
    return tuple(results)