"""NPC 主动插话：纯函数选人、选台词模板与结算。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from app.config import SOCIAL_DISMISS_RELIEF, SOCIAL_PRESS_PRESSURE
from app.models import Role, Script

SocialKind = Literal["approach", "demand", "whisper"]
SocialChoice = Literal["press", "dismiss"]
SOCIAL_KINDS: tuple[SocialKind, ...] = ("approach", "demand", "whisper")


@dataclass(frozen=True)
class SocialLine:
    """一条插话台词模板，按 speaker 与可选 target 渲染。"""

    kind: SocialKind
    template: str
    needs_target: bool


@dataclass(frozen=True)
class SocialChoiceOption:
    """玩家对一次插话的两种回应。"""

    id: SocialChoice
    label: str


SOCIAL_CHOICES: tuple[SocialChoiceOption, ...] = (
    SocialChoiceOption(id="press", label="追问他"),
    SocialChoiceOption(id="dismiss", label="让他走"),
)


@dataclass(frozen=True)
class SocialEvent:
    """一次待处理的主动插话。"""

    id: str
    kind: SocialKind
    speaker_id: str
    speaker_name: str
    target_id: str | None
    target_name: str | None
    line: str
    choices: tuple[SocialChoiceOption, ...]
    created_at: int = 0


SOCIAL_LINES: tuple[SocialLine, ...] = (
    SocialLine(
        kind="approach",
        template="{speaker}往前一步：“{target}今晚已经够难了，先生，您何必再逼。”",
        needs_target=True,
    ),
    SocialLine(
        kind="approach",
        template="{speaker}替{target}添了盏茶：“这事我瞧着，未必是您想的那样。”",
        needs_target=True,
    ),
    SocialLine(
        kind="approach",
        template="{speaker}拦在{target}前头：“先生，问到我这儿就成了，别为难她。”",
        needs_target=True,
    ),
    SocialLine(
        kind="approach",
        template="{speaker}凑近了些：“先生，您手里的东西，能给我瞧一眼么？”",
        needs_target=False,
    ),
    SocialLine(
        kind="approach",
        template="{speaker}在门口站住：“您查得这样细，是疑心我们哪一个？”",
        needs_target=False,
    ),
    SocialLine(
        kind="approach",
        template="{speaker}跟上来：“先生，这话您问别人了么？”",
        needs_target=False,
    ),
    SocialLine(
        kind="demand",
        template="{speaker}把门掩上：“您要查就查，别把我一家老小搭进去。”",
        needs_target=True,
    ),
    SocialLine(
        kind="demand",
        template="{speaker}压低嗓子：“先生，查到此为止吧，给我们留条活路。”",
        needs_target=True,
    ),
    SocialLine(
        kind="demand",
        template="{speaker}盯着您：“您给句准话，今晚这事会不会牵连{target}？”",
        needs_target=True,
    ),
    SocialLine(
        kind="demand",
        template="{speaker}伸手拦住：“先生，别再往下查了。”",
        needs_target=False,
    ),
    SocialLine(
        kind="demand",
        template="{speaker}把脸沉下来：“查归查，别踩到旁人头上。”",
        needs_target=False,
    ),
    SocialLine(
        kind="demand",
        template="{speaker}退到门边：“今晚就到这儿吧，先生。”",
        needs_target=False,
    ),
    SocialLine(
        kind="whisper",
        template="{speaker}从廊下过来，和{target}低声说了两句，又各自散开。",
        needs_target=True,
    ),
    SocialLine(
        kind="whisper",
        template="灯影里，{speaker}凑到{target}耳边，声音低得听不清。",
        needs_target=True,
    ),
    SocialLine(
        kind="whisper",
        template="{speaker}朝{target}递了个眼色，两人在灶间门口停了一停。",
        needs_target=True,
    ),
    SocialLine(
        kind="whisper",
        template="{speaker}独自在廊下站了一会儿，低声自语了一句。",
        needs_target=False,
    ),
    SocialLine(
        kind="whisper",
        template="廊下风冷，{speaker}裹紧衣裳，低声骂了句什么。",
        needs_target=False,
    ),
    SocialLine(
        kind="whisper",
        template="{speaker}背过身去，对着窗子低声说了两句。",
        needs_target=False,
    ),
)

PRESS_REPLIES: dict[SocialKind, str] = {
    "approach": "他顿了顿，还是开了口：“先生想问什么？”",
    "demand": "他顿了顿，还是开了口：“您非要问，我也没有别的了。”",
    "whisper": "他顿了顿，还是开了口：“您都听见了，我也不瞒了。”",
}

DISMISS_REPLIES: dict[SocialKind, str] = {
    "approach": "他退回了阴影里，脚步很轻。",
    "demand": "他退回了阴影里，门轻轻合上了。",
    "whisper": "他退回了阴影里，廊下只剩风声。",
}


def build_event(
    script: Script,
    pressure: Mapping[str, float],
    current_npc_id: str | None,
    history: Sequence[SocialEvent],
) -> SocialEvent | None:
    """按压力与历史挑出一个主动开口的人，没有候选人时返回空。"""
    speaker = _pick_speaker(script, pressure, current_npc_id, history)
    if speaker is None:
        return None
    target = _pick_target(script, speaker, current_npc_id)
    kind = _pick_kind(speaker, pressure.get(speaker.id, 0.0), history)
    line = _render_line(kind, speaker, target, pressure, history)
    return SocialEvent(
        id=f"evt-{len(history) + 1}",
        kind=kind,
        speaker_id=speaker.id,
        speaker_name=speaker.name,
        target_id=target.id if target is not None else None,
        target_name=target.name if target is not None else None,
        line=line,
        choices=SOCIAL_CHOICES,
    )


def resolve_event(
    event: SocialEvent,
    choice: str,
) -> tuple[str, float]:
    """结算玩家选择，返回回应台词与说话人的压力增量。"""
    if choice == "press":
        return PRESS_REPLIES.get(event.kind, PRESS_REPLIES["approach"]), (
            SOCIAL_PRESS_PRESSURE
        )
    if choice == "dismiss":
        return DISMISS_REPLIES.get(event.kind, DISMISS_REPLIES["approach"]), (
            -SOCIAL_DISMISS_RELIEF
        )
    return "", 0.0


def _pick_speaker(
    script: Script,
    pressure: Mapping[str, float],
    current_npc_id: str | None,
    history: Sequence[SocialEvent],
) -> Role | None:
    """排除当前 NPC 后取压力最高者，并避开上一位说话人。"""
    roles = list(script.roles)
    candidates = [role for role in roles if role.id != current_npc_id]
    if not candidates:
        candidates = roles
    if not candidates:
        return None
    order = {role.id: index for index, role in enumerate(roles)}
    candidates.sort(
        key=lambda role: (-pressure.get(role.id, 0.0), order[role.id])
    )
    last_speaker = history[-1].speaker_id if history else None
    if len(candidates) > 1 and candidates[0].id == last_speaker:
        return candidates[1]
    return candidates[0]


def _pick_target(
    script: Script,
    speaker: Role,
    current_npc_id: str | None,
) -> Role | None:
    """优先指向当前 NPC，否则取与说话人信任最高的人。"""
    roles = {role.id: role for role in script.roles}
    if current_npc_id is not None:
        current = roles.get(current_npc_id)
        if current is not None and current.id != speaker.id:
            return current
    best: Role | None = None
    best_trust = -1.0
    for role in script.roles:
        if role.id == speaker.id:
            continue
        relation = speaker.relations.get(role.id)
        if relation is None:
            continue
        if relation.trust > best_trust:
            best = role
            best_trust = relation.trust
    return best


def _pick_kind(
    speaker: Role,
    pressure: float,
    history: Sequence[SocialEvent],
) -> SocialKind:
    """按角色编号与压力档轮换事件类型，避免与上一条重复。"""
    index = (_role_number(speaker.id) + _pressure_bucket(pressure)) % (
        len(SOCIAL_KINDS)
    )
    kind = SOCIAL_KINDS[index]
    if history and history[-1].kind == kind:
        kind = SOCIAL_KINDS[(index + 1) % len(SOCIAL_KINDS)]
    return kind


def _render_line(
    kind: SocialKind,
    speaker: Role,
    target: Role | None,
    pressure: Mapping[str, float],
    history: Sequence[SocialEvent],
) -> str:
    """按说话人、压力与历史挑一条模板并填入姓名。"""
    needs_target = target is not None
    usable = [
        line
        for line in SOCIAL_LINES
        if line.kind == kind and line.needs_target is needs_target
    ]
    if not usable:
        usable = [line for line in SOCIAL_LINES if line.kind == kind]
    index = (
        _role_number(speaker.id)
        + _pressure_bucket(pressure.get(speaker.id, 0.0))
        + len(history)
    ) % len(usable)
    return usable[index].template.format(
        speaker=speaker.name,
        target=target.name if target is not None else "",
    )


def _role_number(role_id: str) -> int:
    """从角色 id 里取出数字部分，用于稳定轮换。"""
    digits = "".join(char for char in role_id if char.isdigit())
    return int(digits) if digits else 0


def _pressure_bucket(pressure: float) -> int:
    """把 0–1 的压力压成 0–10 的整数档。"""
    clamped = min(max(pressure, 0.0), 1.0)
    return int(round(clamped * 10))