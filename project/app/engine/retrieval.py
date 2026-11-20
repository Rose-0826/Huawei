"""在 NPC 的知识边界内检索相关事实。"""

from __future__ import annotations

from collections.abc import Collection

from app.config import (
    RETRIEVAL_KEYWORD_WEIGHT,
    RETRIEVAL_MAX_RESULTS,
    RETRIEVAL_TOPIC_WEIGHT,
)
from app.engine.intent import Intent
from app.models import Fact, Script


def retrieve(
    script: Script,
    npc_id: str,
    intent: Intent,
    exclude_ids: Collection[str] = (),
) -> list[Fact]:
    """只在 NPC 持有的事实中检索，按相关度返回候选，已答事实整体后排。"""
    if not intent.topics:
        return []
    wanted = set(intent.topics)
    excluded = set(exclude_ids)
    candidates: list[tuple[int, int, Fact]] = []
    for order, fact in enumerate(script.facts):
        if npc_id not in fact.holders:
            continue
        topic_score = len(wanted.intersection(fact.topic))
        if topic_score == 0:
            continue
        keyword_score = sum(
            1 for keyword in intent.keywords if keyword in fact.text
        )
        score = (
            topic_score * RETRIEVAL_TOPIC_WEIGHT
            + keyword_score * RETRIEVAL_KEYWORD_WEIGHT
        )
        candidates.append((score, order, fact))
    candidates.sort(
        key=lambda item: (
            item[2].id in excluded,
            -item[0],
            item[1],
        )
    )
    return [fact for _, _, fact in candidates[:RETRIEVAL_MAX_RESULTS]]