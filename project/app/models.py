"""剧本数据模型。"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

NonEmptyStr = Annotated[str, Field(min_length=1)]
UnitFloat = Annotated[float, Field(ge=0.0, le=1.0)]
Topic = Literal["time", "weapon", "motive", "relation", "event"]
TOPICS: tuple[Topic, ...] = (
    "time",
    "weapon",
    "motive",
    "relation",
    "event",
)


class ScriptModel(BaseModel):
    """剧本模型基类：拒绝未知字段，避免字段拼写错误被静默忽略。"""

    model_config = ConfigDict(extra="forbid")


class Victim(ScriptModel):
    id: NonEmptyStr
    name: NonEmptyStr
    desc: NonEmptyStr


class Relation(ScriptModel):
    type: NonEmptyStr
    trust: UnitFloat


class Role(ScriptModel):
    id: NonEmptyStr
    name: NonEmptyStr
    public: NonEmptyStr
    secret: NonEmptyStr
    goal: NonEmptyStr
    lie_propensity: UnitFloat
    alibi: NonEmptyStr
    relations: dict[NonEmptyStr, Relation]


class Fact(ScriptModel):
    id: NonEmptyStr
    text: NonEmptyStr
    topic: list[Topic]
    holders: list[NonEmptyStr]
    sensitivity: UnitFloat
    risk_by_holder: dict[NonEmptyStr, UnitFloat] = Field(default_factory=dict)
    belief: dict[NonEmptyStr, NonEmptyStr] = Field(default_factory=dict)
    source_of_error: NonEmptyStr | None = None


class Clue(ScriptModel):
    id: NonEmptyStr
    from_: NonEmptyStr = Field(alias="from")
    name: NonEmptyStr
    desc: NonEmptyStr


class Script(ScriptModel):
    id: NonEmptyStr
    title: NonEmptyStr
    version: NonEmptyStr
    era: NonEmptyStr
    opening: NonEmptyStr
    victim: Victim
    culprit: NonEmptyStr
    solution_path: list[NonEmptyStr]
    roles: list[Role]
    facts: list[Fact]
    clues: list[Clue]