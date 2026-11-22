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
)# 会暴露“逐字念档案”的句式，公开发言里在它之前截断
BLOOD_MEMORY_MARKERS: Final[tuple[str, ...]] = ("我还记得", "档案里写着")
# 未登记人名过滤的通用词白名单，避免误伤“老板娘”“小声”等正常词
BLOOD_KNOWN_PERSON_TERMS: Final[tuple[str, ...]] = (
    "老板",
    "老板娘",
    "老家",
    "老人",
    "老账",
    "老规矩",
    "老天",
    "老实",
    "老早",
    "老远",
    "老半天",
    "老屋",
    "老墙",
    "老树",
    "小声",
    "小心",
    "小子",
    "小时",
    "小半",
    "小厮",
    "小伙",
    "小两口",
)
BLOOD_HEARSAY_PREFIX: Final[str] = "听旅客说，"
BLOOD_VOTE_REASON_QUOTE_CHARS: Final[int] = 12