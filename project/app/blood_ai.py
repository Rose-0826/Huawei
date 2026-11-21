"""阵营模式的 agent 发言：构建提示词、调用模型、过滤与模板兜底。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.config import BLOOD_MAX_LINE_CHARS, BLOOD_PROMPT_CONTEXT_LINES
from app.llm import LLMClient, LLMUnavailable, get_llm

if TYPE_CHECKING:
    from app.blood import BloodPlayer, BloodState, ReplyFn

logger = logging.getLogger(__name__)

FORBIDDEN_CLAIMS: tuple[str, ...] = ("我是凶手", "我是好人", "我是清白的")

SYSTEM_PROMPT: str = (
    "你在玩一场暴雪封路旅馆里的社交推理游戏，你是其中的住客之一。\n"
    "规则：\n"
    f"1. 只用第一人称说一到两句中文，不超过 {BLOOD_MAX_LINE_CHARS} 字。\n"
    "2. 可以怀疑、辩解、试探，但绝不能说自己「是凶手」或「是好人」，"
    "也不要提到模型、AI 或提示词。\n"
    "3. 只能基于下面给出的公开身份与私下信息说话，不要编造新的凶案细节。\n"
    "4. 语气要像这个年代的人，克制、简短。"
)

FALLBACK_LINES: dict[str, str] = {
    "p1": "我一个开店的，只盼着天亮雪停。{name}那时候在哪儿，我说不清。",
    "p2": "账我记得清，别的不好说。{name}那晚走得急，我总觉得不对劲。",
    "p3": "我上楼送过炭，灯太暗。{name}的话我信一半。",
    "p4": "二楼有响动，我不敢乱指。{name}倒是没解释清楚。",
    "p5": "马棚里我守了一夜。{name}那话说得不太顺。",
}
DEFAULT_FALLBACK: str = "我把知道的都说了。{name}那晚的行踪还得再问。"


def build_prompt(
    player: BloodPlayer,
    state: BloodState,
) -> tuple[str, str]:
    """构建一次 agent 发言的 system 与 user 提示词。"""
    lines: list[str] = [
        f"你的姓名：{player.name}",
        f"你的公开身份：{player.public}",
    ]
    if player.role == "murderer":
        lines.append(
            "你心里清楚：昨晚动手的人就是你。把话头引开，但绝不能承认。"
        )
    else:
        lines.append("你不是凶手，但你也不知道是谁。")
    lines.append("你私下知道的事：")
    lines.extend(f"- {text}" for text in player.private_info)
    others = [
        f"{other.name}（{other.public}）"
        for other in state.players
        if other.alive and other.id != player.id
    ]
    lines.append("还在场的人：" + "、".join(others))
    recent = state.public_log[-BLOOD_PROMPT_CONTEXT_LINES:]
    if recent:
        lines.append("最近的公开发言：")
        lines.extend(
            f"- {entry.speaker_name}：{entry.text}" for entry in recent
        )
    suspects = sorted(
        player.suspicion.items(),
        key=lambda item: item[1],
        reverse=True,
    )[:2]
    names = [
        _name_of(state, player_id)
        for player_id, _ in suspects
        if _is_alive(state, player_id)
    ]
    if names:
        lines.append("你现在最怀疑：" + "、".join(names))
    lines.append("现在轮到你开口，说一到两句，别重复寒暄。")
    return SYSTEM_PROMPT, "\n".join(lines)


def clean_line(text: str) -> str:
    """压成单行、限长并剔除违规自曝，违规时返回空串。"""
    flat = " ".join(part.strip() for part in text.splitlines() if part.strip())
    if not flat:
        return ""
    if any(claim in flat for claim in FORBIDDEN_CLAIMS):
        return ""
    return flat[:BLOOD_MAX_LINE_CHARS]


def generate_line(
    player: BloodPlayer,
    state: BloodState,
    llm: LLMClient,
) -> str:
    """调用模型生成一句发言，模型不可用或内容违规时返回空串。"""
    system, user = build_prompt(player, state)
    try:
        raw = llm.complete(system, user)
    except LLMUnavailable as exc:
        logger.warning("模型不可用，改用模板兜底：%s", exc)
        return ""
    return clean_line(raw)


def fallback_line(state: BloodState, player: BloodPlayer) -> str:
    """按角色模板生成一句兜底发言。"""
    target_id = _top_target(state, player)
    name = _name_of(state, target_id)
    template = FALLBACK_LINES.get(player.id, DEFAULT_FALLBACK)
    return template.format(name=name)


def make_reply_fn(llm: LLMClient | None = None) -> ReplyFn:
    """返回发言回调，模型客户端延迟创建，失败时用模板兜底。"""
    client = llm
    resolved = llm is not None

    def reply(state: BloodState, player: BloodPlayer) -> str:
        nonlocal client, resolved
        if not resolved:
            resolved = True
            try:
                client = get_llm()
            except RuntimeError as exc:
                logger.warning("模型配置缺失，改用模板兜底：%s", exc)
                client = None
        text = ""
        if client is not None:
            text = generate_line(player, state, client)
        return text or fallback_line(state, player)

    return reply


def _is_alive(state: BloodState, player_id: str) -> bool:
    return any(p.id == player_id and p.alive for p in state.players)


def _name_of(state: BloodState, player_id: str | None) -> str:
    for player in state.players:
        if player.id == player_id:
            return player.name
    return "有人"


def _top_target(state: BloodState, player: BloodPlayer) -> str | None:
    candidates = [
        other for other in state.players if other.alive and other.id != player.id
    ]
    if not candidates:
        return None
    best = max(candidates, key=lambda p: player.suspicion.get(p.id, 0.0))
    return best.id