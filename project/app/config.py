"""全局配置与可调阈值。"""

from __future__ import annotations

from typing import Final

LLM_TIMEOUT_SECONDS: Final[float] = 30.0
LLM_MAX_TOKENS: Final[int] = 200
LLM_TEMPERATURE: Final[float] = 0.7

# 阵营模式（电子血染）
BLOOD_INITIAL_SUSPICION_BASE: Final[float] = 0.2
BLOOD_INITIAL_SUSPICION_JITTER: Final[float] = 0.2
BLOOD_SUSPICION_FACT: Final[float] = 0.2
BLOOD_SUSPICION_MURDERER: Final[float] = 0.1
BLOOD_SUSPICION_MENTION: Final[float] = 0.05
BLOOD_MAX_SUSPICION: Final[float] = 1.0
BLOOD_MAX_SPEAK_PER_DAY: Final[int] = 3
BLOOD_PRIVATE_FACTS_MIN: Final[int] = 2
BLOOD_PRIVATE_FACTS_MAX: Final[int] = 3
BLOOD_PRIVATE_MAX_SENSITIVITY: Final[float] = 0.7
BLOOD_MAX_LINE_CHARS: Final[int] = 120
BLOOD_PROMPT_CONTEXT_LINES: Final[int] = 6
BLOOD_MAX_DEFENSE_SPEAK_PER_DAY: Final[int] = 2
BLOOD_MAX_FACTS_PER_DAY: Final[int] = 2
BLOOD_VOTE_REASON_MAX_CHARS: Final[int] = 40
BLOOD_AFTERMATH_MAX_DAYS: Final[int] = 30
BLOOD_SECRET_CLAIM_TERMS: Final[tuple[str, ...]] = (
    "我是凶手",
    "我是好人",
    "我是清白的",
    "我是私生女",
    "我是记者",
    "我是真凶",
    "私生女",
    "记者",
)
BLOOD_SECRET_IDENTITY_TERMS: Final[tuple[str, ...]] = ("私生女", "记者")
BLOOD_VAGUE_REWRITE: Final[str] = (
    "这些旧事我只看见一角，说不全；你还是问那晚谁上过楼吧。"
)