"""把决策变成角色台词，唯一允许调用 LLM 的 engine 模块。"""

from __future__ import annotations

import logging

from app.config import MAX_REPLY_CHARS, MAX_REWRITE_ATTEMPTS
from app.engine.policy import Decision
from app.engine.verifier import verify_reply
from app.llm import LLMClient, LLMUnavailable, get_llm
from app.models import Fact, Role, Script

logger = logging.getLogger(__name__)


def compose(
    role: Role,
    decision: Decision,
    fact: Fact | None,
    script: Script,
    llm: LLMClient | None = None,
) -> str:
    """根据决策生成角色台词，校验失败时重写并用模板兜底。"""
    client = llm or get_llm()
    allowed_text = _allowed_text(decision, fact)
    system_prompt = build_system_prompt(role, script)
    user_prompt = build_user_prompt(decision, fact)
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
            else _action_issue(draft, decision)
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
        "因此你要提防他，但不能表现得太明显。\n"
        "必须遵守：\n"
        f"1. 用第一人称、民国口吻说话，不超过 {MAX_REPLY_CHARS} 字。\n"
        "2. 秘密只用来约束你的行为，永远不能直接说出秘密内容。\n"
        "3. 只能使用用户给出的内容，不得新增时间、地点、人名、数字。\n"
        "4. 时间保留事实中的原始写法，不要换算成中文时间或模糊说法。\n"
        "5. 不要旁白腔，不要写“根据我的记忆”，不要加引号。\n"
        "6. 只输出角色的话。"
    )


def build_user_prompt(decision: Decision, fact: Fact | None) -> str:
    """构造本次动作的用户提示，只包含 Decision 与给定事实。"""
    content = decision.content or (fact.text if fact is not None else "")
    return (
        f"{_action_text(decision)}\n"
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
    if decision.content is not None:
        return decision.content
    if fact is not None:
        return fact.text
    return ""


def _action_issue(draft: str, decision: Decision) -> str | None:
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
    return None