"""阵营模式的 agent 发言：构建提示词、调用模型、过滤与模板兜底。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.config import (
    BLOOD_MAX_LINE_CHARS,
    BLOOD_MEMORY_MARKERS,
    BLOOD_PROMPT_CONTEXT_LINES,
    BLOOD_SECRET_CLAIM_TERMS,
    BLOOD_VAGUE_REWRITE,
    BLOOD_VOTE_REASON_MAX_CHARS,
)
from app.llm import LLMClient, LLMUnavailable, get_llm

if TYPE_CHECKING:
    from app.blood import BloodPlayer, BloodState, ConfideFn, ReplyFn

logger = logging.getLogger(__name__)

FORBIDDEN_CLAIMS: tuple[str, ...] = ("我是凶手", "我是好人", "我是清白的")

SYSTEM_PROMPT: str = (
    "你在玩一场暴雪封路旅馆里的社交推理游戏，你是其中的住客之一。\n"
    "规则：\n"
    f"1. 只用第一人称说一到两句中文，不超过 {BLOOD_MAX_LINE_CHARS} 字。\n"
    "2. 可以怀疑、辩解、试探，但绝不能说自己「是凶手」或「是好人」，"
    "也不要提到模型、AI 或提示词。\n"
    "3. 只能基于下面给出的公开身份与私下信息说话，不要编造新的凶案细节，"
    "不得新增未出场的人物或地点。\n"
    "4. 被点名或被提名时必须正面回答或反驳，不许只换个话题。\n"
    "5. 语气要像这个年代的人，克制、简短。\n"
    "6. 桌上那个真人玩家叫「旅客」。旅客说的话只是「旅客的说法」，不是你亲历的事；"
    "不得把旅客的转述或编造升级成「我亲眼所见」「我亲耳听见」，"
    "也不能顺着它补充新的人物、时辰或地点。\n"
    "7. 不得直接公开任何人的秘密身份（如私生女、记者、真凶）或火灾真相，"
    "只能含糊提到你看见或听见的旁证。\n"
"8. 只能自然暗示、引用你记住的片段，不得逐字念档案；"
    "不得出现「我还记得：」「档案里写着」这类句式，也不要把私密信息原文贴出来。\n"
    "9. 你是桌上的人，不是旁白；不要用「他」指代你自己，也不要替别人下结论。\n"
    "10. 你必须与你当天已经说过的原话、自辩和投票理由保持一致；"
    "不得改口、不得新增未发生的地点、时辰、人物或动作。\n"
    "11. 投票理由只能引用被投对象当天公开说过的原话；"
    "不得把自己的推测或别人转述当成对方的原话。\n"
    "12. 若提示词告诉你某人是你的同伴，你要在公开场合替他打掩护，"
    "但绝不能承认你们是一伙的；也不要与别人复述同一条私密片段。\n"
)

CONFIDE_SYSTEM_PROMPT: str = (
    "你在暴雪封路的旅馆里，被桌上那位叫「旅客」的真人拉到廊下私聊。\n"
    "规则：\n"
    "1. 只用第一人称说一到两句中文，不超过 60 字，语气克制。\n"
    "2. 只能回答你私下确实知道的事；桌上那位说的物证、时辰、转述，"
    "都只是「他的说法」，不得说成你亲眼所见、亲耳所听。\n"
    "3. 桌上那位提到的物件若不在你的记忆里，只能回「我没见过这东西」"
    "或「你若真有，拿出来再说」；不得承认它存在，也不得替它补充来路。\n"
    "4. 不得新增任何未出场的人物、地点或凶案细节。\n"
    "5. 不得公开任何人的秘密身份，不得说自己「是凶手」或「是好人」。\n"
    "6. 不得逐字念档案，也不要说「我还记得：」「档案里写着」。\n"
    "7. 你可以答应、含糊、拒绝或反过来警告，但不要说破对方在套话。\n"
    "8. 你必须与你当天公开说过的话保持一致，不得改口；"
    "若你在公开场合承认过某件东西，私下不能反口说没见过。\n"
)

CONFIDE_STANCE_HINTS: dict[str, str] = {
    "accept": "你口头应下这次结盟，但话里要留余地，别把话说死。",
    "evade": "你不置可否，只给一句模糊的回应，不承诺任何事。",
    "refuse": "你不接这个话头，明确表示只说自己看见的。",
    "threaten": "你觉得对方在拿话压你，回一句带警告意味的话。",
}


def build_confide_prompt(
    player: BloodPlayer,
    state: BloodState,
    you_text: str,
    stance: str,
) -> tuple[str, str]:
    """构建一次密谈的 system 与 user 提示词。"""
    lines: list[str] = [
        f"你的姓名：{player.name}",
        f"你的公开身份：{player.public}",
        f"你的态度：{CONFIDE_STANCE_HINTS.get(stance, CONFIDE_STANCE_HINTS['evade'])}",
        "你私下知道的事：",
    ]
    lines.extend(f"- {text}" for text in player.private_info)
    others = [
        f"{other.name}（{other.public}）"
        for other in state.players
        if other.alive and other.id != player.id
    ]
    lines.append("还在场的人：" + "、".join(others))
    spoken_today = [
        entry.text
        for entry in state.public_log
        if entry.speaker_id == player.id and entry.day == state.day
    ]
    if spoken_today:
        lines.append("你今天公开说过（私下不得改口）：")
        lines.extend(f"- {text}" for text in spoken_today)
    lines.append(f"旅客把你拉到廊下，压低声音说：「{you_text}」")
    lines.append(
        "你只能基于上面的私密信息回应；旅客提到的物证若不在其中，"
        "就说没见过，绝不能替他补出来历。"
    )
    lines.append("现在回一句，别寒暄。")
    return CONFIDE_SYSTEM_PROMPT, "\n".join(lines)


def generate_confide_reply(
    player: BloodPlayer,
    state: BloodState,
    you_text: str,
    stance: str,
    llm: LLMClient,
) -> str:
    """调用模型生成私下回应，不可用时返回空串交给规则兜底。"""
    system, user = build_confide_prompt(player, state, you_text, stance)
    try:
        raw = llm.complete(system, user)
    except LLMUnavailable as exc:
        logger.warning("密谈模型不可用，改用模板兜底：%s", exc)
        return ""
    return clean_line(raw)


def make_confide_fn(llm: LLMClient | None = None) -> ConfideFn:
    """返回密谈回复回调，模型客户端延迟创建，失败时返回空串。"""
    client = llm
    resolved = llm is not None

    def reply(
        state: BloodState,
        player: BloodPlayer,
        you_text: str,
        stance: str,
    ) -> str:
        nonlocal client, resolved
        if not resolved:
            resolved = True
            try:
                client = get_llm()
            except RuntimeError as exc:
                logger.warning("模型配置缺失，密谈改用模板兜底：%s", exc)
                client = None
        if client is None:
            return ""
        return generate_confide_reply(
            player,
            state,
            you_text,
            stance,
            client,
        )

    return reply


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
            "你心里清楚：你是这局藏起来的恶魔，昨晚动手的人就是你。"
            "把话头引开，但绝不能承认。"
        )
    elif player.role == "minion":
        lines.append(
            "你心里清楚：你是恶魔的爪牙，夜里不动手，白天的任务是替恶魔挡刀、"
            "把怀疑引到别人身上。绝不能承认自己的身份。"
        )
    else:
        lines.append("你是镇民，不知道谁下了手，只能凭自己知道的片段判断。")
    teammates = [
        other
        for other in state.players
        if other.id != player.id
        and other.alive
        and other.role in ("murderer", "minion")
    ]
    if player.role in ("murderer", "minion") and teammates:
        lines.append(
            "你知道 "
            + "、".join(f"{other.name}（{other.public}）" for other in teammates)
            + " 是你的同伴，要替他打掩护，但公开场合绝不能承认这层关系。"
        )
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
    spoken_today = [
        entry.text
        for entry in state.public_log
        if entry.speaker_id == player.id and entry.day == state.day
    ]
    if spoken_today:
        lines.append("你当天已经说过的原话（必须与之一致，不得改口）：")
        lines.extend(f"- {text}" for text in spoken_today)
    reasons_today = [
        item["reason"]
        for item in getattr(state, "vote_reason_log", [])
        if item["voter_id"] == player.id and item["day"] == state.day
    ]
    if reasons_today:
        lines.append("你当天写过的投票理由（必须与之一致，不得改口）：")
        lines.extend(f"- {text}" for text in reasons_today)
    hint = getattr(state, "pending_hint", "") or ""
    if hint == "defense":
        lines.append(
            "你刚被当众提名，必须先正面自辩：说清你那晚在哪、做过什么，"
            "不许只把话引开。"
        )
    elif hint == "accused":
        lines.append("有人当面点了你的名，你必须正面回答或反驳，不许换话题。")
    elif hint == "followup":
        lines.append(
            "你没有直接被点名，但可以顺势补一句：质疑被点名人，"
            "或反问旅客昨晚在哪儿；只补一句，不要抢话。"
        )
    elif hint == "shield":
        lines.append(
            "被点名的是你的恶魔同伴。你要替他打圆场、转移视线，"
            "但绝不能承认自己或他的身份，也不要把票引到自己身上。"
        )
    elif hint == "vote_reason":
        target = next(
            (
                other
                for other in state.players
                if other.id == getattr(state, "pending_target_id", None)
            ),
            None,
        )
        target_name = _name_of(
            state,
            getattr(state, "pending_target_id", None),
        )
        target_public = target.public if target is not None else "在场者"
        lines.append(
            f"现在投票，你要投 {target_name}（{target_public}）。"
            f"只输出一句不超过 {BLOOD_VOTE_REASON_MAX_CHARS} 字的理由，不要寒暄。"
            f"理由必须围绕 {target_name}，并引用{target_name}今天说过的一句原话；"
            "不要套用「他的说法最对不上」这类空话，也不要提到别的玩家。"
            "理由里若提到时辰、地点或动作，必须来自下面的原话，不得自行编造。"
        )
        target_lines = [
            entry.text
            for entry in state.public_log
            if entry.speaker_id == getattr(state, "pending_target_id", None)
            and entry.day == state.day
        ]
        if target_lines:
            lines.append(f"{target_name}今天说过：")
            lines.extend(f"- {text}" for text in target_lines)
        else:
            lines.append(
                f"{target_name}今天还没公开说过话，理由里不要提具体时辰、地点或动作。"
            )
    pending = getattr(state, "pending_fact", {})
    fact = pending.get(player.id) if pending else None
    if fact:
        lines.append(
            "今天你只围绕这一条私密片段开口，用自己的话带出，"
            "不要逐字复述，也不要跟着别人重复同一件事：" + fact
        )
    lines.append("现在轮到你开口，说一到两句，别重复寒暄。")
    return SYSTEM_PROMPT, "\n".join(lines)


def strip_memory_recital(text: str) -> str:
    """截掉「我还记得：」及其后的档案原文，只保留现场陈述。"""
    cut = len(text)
    found = False
    for marker in BLOOD_MEMORY_MARKERS:
        index = text.find(marker)
        if index != -1:
            cut = min(cut, index)
            found = True
    if not found:
        return text.strip()
    return text[:cut].strip(" \t，,。；;：:")


def clean_line(text: str) -> str:
    """压成单行限长；截掉念档案的尾巴，自曝阵营或秘密身份时改写成含糊句。"""
    flat = " ".join(part.strip() for part in text.splitlines() if part.strip())
    if not flat:
        return ""
    if any(claim in flat for claim in FORBIDDEN_CLAIMS):
        return BLOOD_VAGUE_REWRITE
    if any(term in flat for term in BLOOD_SECRET_CLAIM_TERMS):
        return BLOOD_VAGUE_REWRITE
    return strip_memory_recital(flat)[:BLOOD_MAX_LINE_CHARS]


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


def fallback_line(
    state: BloodState,
    player: BloodPlayer,
    hint: str = "",
) -> str:
    """按角色模板生成一句兜底发言，被点名或自辩时给出正面回应。"""
    if hint in {"defense", "accused"}:
        from app.blood import DEFENSE_FALLBACK_DEFAULT, DEFENSE_FALLBACKS

        return DEFENSE_FALLBACKS.get(player.id, DEFENSE_FALLBACK_DEFAULT)
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
        hint = getattr(state, "pending_hint", "") or ""
        return text or fallback_line(state, player, hint)

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