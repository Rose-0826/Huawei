"""玩家问题的意图解析。"""

from __future__ import annotations

from dataclasses import dataclass

from app.models import TOPICS

TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "time": (
        "几点",
        "什么时候",
        "多久",
        "之前",
        "之后",
        "那晚",
        "当晚",
        "昨晚",
        "时间",
        "晚上",
        "夜里",
        "半夜",
        "22:",
        "23:",
    ),
    "weapon": (
        "凶器",
        "拨火棍",
        "镇纸",
        "用什么",
        "钝器",
        "受伤",
        "壁炉",
    ),
    "motive": (
        "为什么",
        "动机",
        "恨",
        "钱",
        "账",
        "账本",
        "账簿",
        "对账",
        "遗产",
        "银元",
        "赌",
        "失火",
        "火灾",
        "那场火",
        "登记簿",
    ),
    "relation": (
        "认识",
        "关系",
        "妻子",
        "前妻",
        "儿子",
        "女儿",
        "私生",
        "父女",
        "主雇",
        "同乡",
        "人情",
        "记者",
        "账本",
        "账簿",
        "对账",
    ),
    "event": (
        "发生",
        "看见",
        "听见",
        "去了",
        "做了",
        "出来",
        "上楼",
        "下楼",
        "送炭",
        "热水",
        "争吵",
        "吵架",
        "争执",
        "登记簿",
        "死了",
        "尸体",
        "发现",
        "碰见",
        "杀",
    ),
}

KEYWORD_GROUPS: tuple[tuple[str, ...], ...] = (
    ("吵架", "争吵", "争执", "吵"),
    ("钱", "银元", "大洋", "银钱", "工钱", "辛苦钱"),
    ("账", "账本", "账簿", "账目", "对账", "查账", "算账"),
    ("登记簿", "登记记录", "登记"),
)


@dataclass(frozen=True)
class Intent:
    """一次提问的意图：命中的 topic 与检索关键词。"""

    question: str
    topics: tuple[str, ...]
    keywords: tuple[str, ...]


def parse_intent(question: str) -> Intent:
    """用关键词包含匹配解析问题命中的 topic，不做分词。"""
    topics: list[str] = []
    keywords: list[str] = []
    for topic in TOPICS:
        matched = [
            keyword
            for keyword in TOPIC_KEYWORDS[topic]
            if keyword in question
        ]
        if matched:
            topics.append(topic)
            keywords.extend(matched)
    for group in KEYWORD_GROUPS:
        if any(keyword in question for keyword in group):
            keywords.extend(group)
    return Intent(
        question=question,
        topics=tuple(topics),
        keywords=tuple(dict.fromkeys(keywords)),
    )