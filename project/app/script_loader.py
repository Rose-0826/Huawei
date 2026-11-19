"""剧本加载、结构校验与命令行概况输出。"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.models import TOPICS, Fact, Role, Script

DEFAULT_SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "scripts"
    / "mistvale-inn.json"
)
MIN_FACTS_PER_ROLE = 5
MIN_CULPRIT_SOLUTION_FACTS = 2


@dataclass(frozen=True)
class ScriptIssue:
    """一条可定位的剧本校验问题。"""

    path: str
    message: str


class ScriptError(ValueError):
    """剧本加载或校验失败的基类。"""


class ScriptLoadError(ScriptError):
    """剧本文件无法读取或不是合法 JSON。"""


class ScriptValidationError(ScriptError):
    """剧本字段或交叉引用不符合约束。"""

    def __init__(self, source: str, issues: list[ScriptIssue]) -> None:
        self.source = source
        self.issues = issues
        lines = [f"剧本校验失败：{source}，共 {len(issues)} 处问题"]
        for index, issue in enumerate(issues, start=1):
            lines.append(f"  {index}. {issue.path}: {issue.message}")
        super().__init__("\n".join(lines))


def load_script(path: str | Path) -> Script:
    """读取 JSON 文件并返回通过校验的剧本对象。"""
    script_path = Path(path)
    try:
        raw = script_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ScriptLoadError(f"无法读取剧本文件 {script_path}：{exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ScriptLoadError(
            f"剧本不是合法 JSON：{script_path}（第 {exc.lineno} 行，"
            f"第 {exc.colno} 列：{exc.msg}）"
        ) from exc
    return parse_script(data, source=str(script_path))


def parse_script(data: Any, source: str = "<memory>") -> Script:
    """校验已解析的 JSON 数据并返回剧本对象。"""
    if not isinstance(data, dict):
        raise ScriptValidationError(
            source, [ScriptIssue("$", "顶层必须是 JSON 对象")]
        )
    try:
        script = Script.model_validate(data)
    except ValidationError as exc:
        issues = [
            _pydantic_issue(error, data)
            for error in exc.errors(include_url=False)
        ]
        raise ScriptValidationError(source, issues) from exc

    issues = _cross_validate(script)
    if issues:
        raise ScriptValidationError(source, issues)
    return script


_PYDANTIC_MESSAGES = {
    "Field required": "缺少必填字段",
    "Extra inputs are not permitted": "不允许的字段",
    "Input should be a valid string": "必须是字符串",
    "Input should be a valid list": "必须是数组",
    "Input should be a valid dictionary": "必须是对象",
    "Input should be a valid number": "必须是数字",
    "Input should be a valid boolean": "必须是布尔值",
    "Input should be greater than or equal to 0": "必须大于等于 0",
    "Input should be less than or equal to 1": "必须小于等于 1",
    "String should have at least 1 character": "不能为空",
}


def _pydantic_issue(error: dict[str, Any], data: dict[str, Any]) -> ScriptIssue:
    path = _format_loc(tuple(error.get("loc", ())), data)
    if error.get("type") == "literal_error":
        message = "只允许 " + " / ".join(TOPICS)
    else:
        raw_message = str(error.get("msg", "字段非法"))
        message = _PYDANTIC_MESSAGES.get(raw_message, raw_message)
    return ScriptIssue(path, message)


def _format_loc(loc: tuple[Any, ...], data: Any) -> str:
    parts: list[str] = []
    current: Any = data
    for item in loc:
        if isinstance(item, int) and isinstance(current, list):
            entry = current[item] if 0 <= item < len(current) else None
            if isinstance(entry, dict) and isinstance(entry.get("id"), str):
                parts.append(f"[{entry['id']}]")
            else:
                parts.append(f"[{item}]")
            current = entry
        else:
            if parts:
                parts.append(".")
            parts.append(str(item))
            current = current.get(item) if isinstance(current, dict) else None
    return "".join(parts) or "$"


def _cross_validate(script: Script) -> list[ScriptIssue]:
    issues: list[ScriptIssue] = []
    roles = _role_index(script)
    facts = _fact_index(script)
    role_ids = [role.id for role in script.roles]
    fact_ids = [fact.id for fact in script.facts]
    clue_ids = [clue.id for clue in script.clues]

    for role_id in _duplicates(role_ids):
        issues.append(ScriptIssue(f"roles[{role_id}]", f"角色 id 重复：{role_id}"))
    for fact_id in _duplicates(fact_ids):
        issues.append(ScriptIssue(f"facts[{fact_id}]", f"事实 id 重复：{fact_id}"))
    for clue_id in _duplicates(clue_ids):
        issues.append(ScriptIssue(f"clues[{clue_id}]", f"线索 id 重复：{clue_id}"))

    if script.culprit not in roles:
        issues.append(
            ScriptIssue(
                "culprit",
                f"凶手 {script.culprit} 不是已定义的角色 id",
            )
        )

    for role in script.roles:
        for other_id in role.relations:
            if other_id not in roles:
                issues.append(
                    ScriptIssue(
                        f"roles[{role.id}].relations.{other_id}",
                        f"关系指向不存在的角色 id：{other_id}",
                    )
                )

    for fact in script.facts:
        for holder_id in fact.holders:
            if holder_id not in roles:
                issues.append(
                    ScriptIssue(
                        f"facts[{fact.id}].holders",
                        f"持有者 {holder_id} 不是已定义的角色 id",
                    )
                )
        for npc_id in fact.belief:
            if npc_id not in roles:
                issues.append(
                    ScriptIssue(
                        f"facts[{fact.id}].belief.{npc_id}",
                        f"错误版本的持有者 {npc_id} 不是已定义的角色 id",
                    )
                )
            elif npc_id not in fact.holders:
                issues.append(
                    ScriptIssue(
                        f"facts[{fact.id}].belief.{npc_id}",
                        f"{npc_id} 不在这条事实的 holders 里，"
                        "错误版本永远不会被检索到",
                    )
                )
        if fact.belief and fact.source_of_error is None:
            issues.append(
                ScriptIssue(
                    f"facts[{fact.id}].source_of_error",
                    "存在 belief 时必须填写 source_of_error",
                )
            )
        if fact.source_of_error is not None and fact.source_of_error not in roles:
            issues.append(
                ScriptIssue(
                    f"facts[{fact.id}].source_of_error",
                    f"误导者 {fact.source_of_error} 不是已定义的角色 id",
                )
            )

    for clue in script.clues:
        if clue.from_ not in facts:
            issues.append(
                ScriptIssue(
                    f"clues[{clue.id}].from",
                    f"来源事实 {clue.from_} 不存在",
                )
            )

    if not script.solution_path:
        issues.append(ScriptIssue("solution_path", "破案链不能为空"))
    for index, fact_id in enumerate(script.solution_path):
        fact = facts.get(fact_id)
        if fact is None:
            issues.append(
                ScriptIssue(
                    f"solution_path[{index}]",
                    f"破案链引用的 {fact_id} 不存在",
                )
            )
            continue
        if not fact.holders:
            issues.append(
                ScriptIssue(
                    f"facts[{fact_id}].holders",
                    "破案链上的事实必须至少有一个持有者，"
                    "否则玩家永远挖不出来",
                )
            )
    for fact_id in _duplicates(script.solution_path):
        issues.append(
            ScriptIssue("solution_path", f"破案链重复引用事实 {fact_id}")
        )

    held_counts = _held_counts(script)
    for role in script.roles:
        count = held_counts[role.id]
        if count < MIN_FACTS_PER_ROLE:
            issues.append(
                ScriptIssue(
                    f"roles[{role.id}]",
                    f"只持有 {count} 条事实，至少需要 {MIN_FACTS_PER_ROLE} 条"
                    "（否则问什么都不知道）",
                )
            )

    if script.culprit in roles:
        culprit_count = 0
        for fact_id in script.solution_path:
            fact = facts.get(fact_id)
            if fact is not None and script.culprit in fact.holders:
                culprit_count += 1
        if culprit_count < MIN_CULPRIT_SOLUTION_FACTS:
            issues.append(
                ScriptIssue(
                    f"roles[{script.culprit}]",
                    f"凶手只持有 {culprit_count} 条破案链事实，"
                    f"至少需要 {MIN_CULPRIT_SOLUTION_FACTS} 条"
                    "（否则审不出东西）",
                )
            )

    return issues


def _duplicates(items: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicated: list[str] = []
    for item in items:
        if item in seen and item not in duplicated:
            duplicated.append(item)
        seen.add(item)
    return duplicated


def _role_index(script: Script) -> dict[str, Role]:
    return {role.id: role for role in script.roles}


def _fact_index(script: Script) -> dict[str, Fact]:
    return {fact.id: fact for fact in script.facts}


def _held_counts(script: Script) -> dict[str, int]:
    counts = {role.id: 0 for role in script.roles}
    for fact in script.facts:
        for holder_id in set(fact.holders):
            if holder_id in counts:
                counts[holder_id] += 1
    return counts


def _display_width(text: str) -> int:
    return sum(
        2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
        for char in text
    )


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _display_width(text))


def _render_table(rows: list[tuple[str, ...]]) -> list[str]:
    if not rows:
        return []
    widths = [
        max(_display_width(row[index]) for row in rows)
        for index in range(len(rows[0]))
    ]
    return [
        "  ".join(
            _pad(cell, widths[index]) for index, cell in enumerate(row)
        ).rstrip()
        for row in rows
    ]


def format_overview(script: Script) -> str:
    """生成剧本概况的纯文本，用于人工检查。"""
    roles = _role_index(script)
    held_counts = _held_counts(script)
    lines: list[str] = []
    lines.append(f"{script.title}（{script.id}） v{script.version}")
    lines.append(f"年代：{script.era}")
    lines.append(
        f"死者：{script.victim.name}（{script.victim.id}）"
        f"—— {script.victim.desc}"
    )
    culprit = roles.get(script.culprit)
    culprit_text = (
        f"{culprit.name}（{culprit.id}）" if culprit else script.culprit
    )
    lines.append(f"真凶：{culprit_text}")
    lines.append("")
    lines.append("开场白")
    lines.append(f"  {script.opening}")
    lines.append("")
    lines.append(f"角色（{len(script.roles)}）")

    role_rows = [
        ("ID", "姓名", "公开身份", "持有事实", "关系数", "撒谎倾向", "凶手"),
    ]
    for role in script.roles:
        role_rows.append(
            (
                role.id,
                role.name,
                role.public,
                str(held_counts[role.id]),
                str(len(role.relations)),
                f"{role.lie_propensity:.2f}",
                "是" if role.id == script.culprit else "",
            )
        )
    lines.extend(_render_table(role_rows))
    lines.append("")
    lines.append(
        f"事实（{len(script.facts)} 条，破案链 "
        f"{len(script.solution_path)} 条）"
    )
    lines.append("破案链：" + " -> ".join(script.solution_path))
    for fact in script.facts:
        topics = ", ".join(fact.topic) if fact.topic else "无"
        holders = ", ".join(fact.holders) if fact.holders else "无"
        lines.append(f"  {fact.id} [{topics}] 持有：{holders} | {fact.text}")

    tainted = [fact for fact in script.facts if fact.belief]
    lines.append("")
    lines.append(f"记忆污染（{len(tainted)} 条）")
    for fact in tainted:
        for npc_id, belief_text in fact.belief.items():
            npc = roles.get(npc_id)
            npc_text = f"{npc.name}（{npc_id}）" if npc else npc_id
            source = (
                roles.get(fact.source_of_error)
                if fact.source_of_error
                else None
            )
            source_text = (
                f"{source.name}（{source.id}）"
                if source
                else (fact.source_of_error or "未填写")
            )
            lines.append(
                f"  {fact.id}：{npc_text} 相信「{belief_text}」，"
                f"来源 {source_text}"
            )

    lines.append("")
    lines.append("知识分布")
    for role in script.roles:
        lines.append(f"  {role.id} {role.name}：{held_counts[role.id]} 条")

    lines.append("")
    lines.append(f"线索（{len(script.clues)} 张）")
    for clue in script.clues:
        lines.append(f"  {clue.id} {clue.name} <- {clue.from_} | {clue.desc}")

    lines.append("")
    lines.append("校验：通过")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """命令行入口：加载剧本并打印概况，失败时返回非零退出码。"""
    parser = argparse.ArgumentParser(description="加载并校验剧本，打印概况")
    parser.add_argument(
        "--script",
        type=Path,
        default=DEFAULT_SCRIPT_PATH,
        help=f"剧本 JSON 路径（默认：{DEFAULT_SCRIPT_PATH}）",
    )
    args = parser.parse_args(argv)
    try:
        script = load_script(args.script)
    except ScriptError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(format_overview(script))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())