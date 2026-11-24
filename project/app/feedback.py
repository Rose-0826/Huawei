"""玩家评分与意见收集：轻量 JSONL 持久化，线程安全。"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_FEEDBACK_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "feedback.jsonl"
)
_TZ_CN = timezone(timedelta(hours=8))
_LOCK = threading.Lock()

OUTCOME_LABELS = [
    "白天讨论",
    "提名投票",
    "自辩质证",
    "平票加赛",
    "夜晚",
    "廊下观战",
    "好人胜",
    "凶手胜",
    "结束",
]
OUTCOME_ALIASES = {
    "murderer": "凶手胜",
    "evil": "凶手胜",
    "good": "好人胜",
    "villagers": "好人胜",
}


def normalize_outcome(value: object) -> str:
    """把任意 outcome 值归一为白名单中文标签，无法识别时返回空串。"""
    text = str(value or "").strip()
    if text in OUTCOME_LABELS:
        return text
    return OUTCOME_ALIASES.get(text.lower(), "")


def resolve_feedback_path(override: Path | None = None) -> Path:
    """确定反馈存储路径：显式注入优先，其次环境变量，最后默认路径。"""
    if override is not None:
        return override
    env_path = os.environ.get("FEEDBACK_FILE", "").strip()
    if env_path:
        return Path(env_path)
    return DEFAULT_FEEDBACK_PATH


def append_feedback(
    *,
    rating: int,
    comment: str = "",
    nickname: str = "",
    game_id: str = "",
    role: str = "",
    outcome: str = "",
    day: int = 0,
    path: Path | None = None,
) -> dict[str, Any]:
    """追加一条玩家评分记录，并返回最新聚合摘要。"""
    target = resolve_feedback_path(path)
    clean_comment = " ".join(comment.strip().split())[:500]
    clean_nick = " ".join(nickname.strip().split())[:24] or "匿名旅客"
    record = {
        "created_at": datetime.now(_TZ_CN).isoformat(timespec="seconds"),
        "rating": int(rating),
        "comment": clean_comment,
        "nickname": clean_nick,
        "game_id": game_id.strip()[:64],
        "role": role.strip()[:24],
        "outcome": normalize_outcome(outcome),
        "day": max(0, min(99, int(day or 0))),
    }
    line = json.dumps(record, ensure_ascii=False)
    with _LOCK:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return _read_summary_unlocked(target, recent_limit=20)


def load_feedback_summary(
    *,
    path: Path | None = None,
    recent_limit: int = 20,
) -> dict[str, Any]:
    """读取全部反馈的统计与最近留言。"""
    target = resolve_feedback_path(path)
    with _LOCK:
        return _read_summary_unlocked(target, recent_limit=recent_limit)


def _read_summary_unlocked(
    target: Path,
    *,
    recent_limit: int,
) -> dict[str, Any]:
    distribution = {str(score): 0 for score in range(1, 6)}
    entries: list[dict[str, Any]] = []
    if target.exists():
        for raw in target.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                continue
            rating = item.get("rating")
            if not isinstance(rating, int) or not 1 <= rating <= 5:
                continue
            distribution[str(rating)] += 1
            entries.append(
                {
                    "created_at": str(item.get("created_at", "")),
                    "rating": rating,
                    "comment": str(item.get("comment", "")),
                    "nickname": str(item.get("nickname", "")) or "匿名旅客",
                    "outcome": normalize_outcome(item.get("outcome", "")),
                    "day": int(item.get("day", 0) or 0),
                }
            )
    count = len(entries)
    total = sum(int(k) * v for k, v in distribution.items())
    avg_rating = round(total / count, 2) if count else 0.0
    recent = list(reversed(entries[-max(1, recent_limit) :]))
    return {
        "count": count,
        "avg_rating": avg_rating,
        "distribution": distribution,
        "recent": recent,
    }
