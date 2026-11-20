"""把决策变成角色台词，唯一允许调用 LLM 的 engine 模块。"""

from __future__ import annotations

import logging

from app.config import MAX_REPLY_CHARS, MAX_REWRITE_ATTEMPTS
from app.engine.policy import Decision
from app.engine.verifier import verify_reply
from app.llm import LLMClient, LLMUnavailable, get_llm
from app.models import Clue, Fact, Role, Script

logger = logging.getLogger(__name__)

TOPIC_DIRECTIONS: dict[str, str] = {
    "time": "关于那段时间你在哪里",
    "weapon": "关于那件东西",
    "motive": "关于你为什么这么做",
    "relation": "关于你和他的关系",
    "event": "关于那晚发生了什么",
}


def compose(
    role: Role,
    decision: Decision,
    fact: Fact | None,
    script: Script,
    llm: LLMClient | None = None,
    clue: Clue | None = None,
) -> str:
    """根据决策生成角色台词，校验失败时重写并用模板兜底。"""
    client = llm or get_llm()
    allowed_text = _allowed_text(decision, fact)
    if clue is not None:
        allowed_text = "\n".join(
            part for part in (allowed_text, clue.name, clue.desc) if part
        )
    system_prompt = build_system_prompt(role, script)
    user_prompt = build_user_prompt(decision, fact, clue)
    current_prompt = user_prompt

    for attempt in range(MAX_REWRITE_ATTEMPTS + 1):
        try:
            draft = client.complete(system_prompt, current_prompt)
        except LLMUnavailable as exc:
            logger.warning("模型不可用，直接模板兜底：%s", exc)
            return fallback_reply(decision, role)
        verification = verify_reply(draft, allowed_text, role)
        failure = (
            verification.reason
            if not verification.ok
            else _action_issue(draft, decision, fact)
        )
        if failure is None:
            return draft.strip()
        logger.warning(
            "第 %s 次生成未通过校验：%s",
            attempt + 1,
            failure,
        )
        current_prompt = (
            user_prompt
            + "\n\n上一次回答有问题："
            + failure
            + "。请重写，只输出角色的话，"
            "不得添加事实中没有的时间、数字或人名。"
        )
    return fallback_reply(decision, role)


def build_system_prompt(role: Role, script: Script) -> str:
    """构造注入角色设定与说话规则的 system prompt。"""
    roles = {item.id: item for item in script.roles}
    relation_lines: list[str] = []
    for target_id, relation in role.relations.items():
        target = roles.get(target_id)
        target_name = target.name if target else target_id
        relation_lines.append(
            f"- 与{target_name}（{target_id}）：{relation.type}，"
            f"信任 {relation.trust:.2f}"
        )
    relations_text = "\n".join(relation_lines) if relation_lines else "- 无"
    return (
        f"你在扮演民国悬疑推理桌游《{script.title}》中的角色。\n"
        f"姓名：{role.name}\n"
        f"公开身份：{role.public}\n"
        f"秘密：{role.secret}\n"
        f"目标：{role.goal}\n"
        f"关系：\n{relations_text}\n"
        f"情境：你正被一个人单独问话，他在查{script.victim.name}的死。"
        "你不清楚他的身份，只觉得他不像住客，"
        "因此你要提防他，但不能表现得太明显。"
        "问话的人你不认识，不要把他当成剧中的任何角色，"
        "也不要称呼他的姓名。\n"
        "必须遵守：\n"
        f"1. 用第一人称、民国口吻说话，不超过 {MAX_REPLY_CHARS} 字。\n"
        "2. 秘密只用来约束你的行为，永远不能直接说出秘密内容。\n"
        "3. 只能使用用户给出的内容，不得新增时间、地点、人名、数字。\n"
        "4. 时间保留事实中的原始写法，不要换算成中文时间或模糊说法。\n"
        "5. 不要旁白腔，不要写“根据我的记忆”，不要加引号。\n"
        "6. 编造说法时只能含糊、转移话题，"
        "不得新增具体地点/气味/物件/他人动作。\n"
        "7. 只输出角色的话。"
    )


def build_user_prompt(
    decision: Decision,
    fact: Fact | None,
    clue: Clue | None = None,
) -> str:
    """构造本次动作的用户提示，只包含 Decision、允许透露的内容与物证。"""
    clue_block = _clue_text(clue)
    if decision.action == "evade" and decision.fact_id is not None:
        return (
            "动作：你知道这件事，但不愿说。含糊其辞、转移话题或反问，"
            "不要直接说“我不知道”，也不要把这件事的具体内容说出来。\n"
            f"话题方向：{_topic_direction(fact)}\n"
            f"{clue_block}"
            "只输出角色的话。"
        )
    if decision.action == "lie":
        return (
            f"{_action_text(decision)}\n"
            f"{clue_block}"
            "只输出角色的话。"
        )
    content = decision.content or (fact.text if fact is not None else "")
    return (
        f"{_action_text(decision)}\n"
        f"{clue_block}"
        f"给定内容：{content if content else '无'}\n"
        "只输出角色的话。"
    )


def fallback_reply(decision: Decision, role: Role) -> str:
    """在校验连续失败时返回不含新事实的模板句。"""
    if decision.action == "disclose":
        content = decision.content
        if content:
            candidate = (
                content
                if content.endswith(("。", "！", "？"))
                else content + "。"
            )
            if verify_reply(candidate, content, role).ok:
                return candidate
        return "这件事我记不太清了。"
    if decision.action == "lie":
        return "那会儿我在忙自己的事，没留意别的。"
    if decision.action == "unparsed":
        return "你这话是什么意思？"
    if decision.fact_id is None:
        return "这我不知道。"
    return "有些事，你还是别问得太细。"


def _action_text(decision: Decision) -> str:
    if decision.action == "disclose":
        return "动作：把给定内容说出来，像在回忆，不要照本宣科。"
    if decision.action == "lie":
        return (
            "动作：编一个听起来可信的假说法，不要心虚，"
            "不要新增具体时间、数字、人名。"
        )
    if decision.action == "unparsed":
        return "动作：警觉地反问对方是什么意思，不要说“我不知道”。"
    if decision.fact_id is None:
        return "动作：简短地说你不知道，不要编造细节。"
    return "动作：含糊其辞、转移话题或反问，不要直接说“我不知道”。"


def _allowed_text(decision: Decision, fact: Fact | None) -> str:
    if decision.action in ("evade", "lie"):
        return ""
    if decision.content is not None:
        return decision.content
    if fact is not None:
        return fact.text
    return ""


def _clue_text(clue: Clue | None) -> str:
    if clue is None:
        return ""
    return (
        f"对方把一件物证放在你面前：{clue.name}——{clue.desc}。"
        "你必须针对这件东西作出反应，但仍受当前动作约束（说/躲/骗）。\n"
    )


def _topic_direction(fact: Fact | None) -> str:
    if fact is None:
        return "关于你被问到的那件事"
    for topic in fact.topic:
        direction = TOPIC_DIRECTIONS.get(topic)
        if direction:
            return direction
    return "关于你被问到的那件事"


def _action_issue(
    draft: str,
    decision: Decision,
    fact: Fact | None = None,
) -> str | None:
    if decision.action == "unparsed" and (
        "不知道" in draft or "没听懂" in draft
    ):
        return "问题没解析清楚时要警觉地反问，不能装不知道或没听懂"
    if (
        decision.action == "evade"
        and decision.fact_id is not None
        and "不知道" in draft
    ):
        return "知道但不愿说时不能直接说不知道，要含糊或反问"
    if (
        decision.action == "lie"
        and fact is not None
        and fact.text in draft
    ):
        return "撒谎时不能把这件事原样说出来，要编一个别的说法"
    return None