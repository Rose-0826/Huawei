"""全局配置与可调阈值。"""

from __future__ import annotations

from typing import Final

RETRIEVAL_MAX_RESULTS: Final[int] = 3
RETRIEVAL_TOPIC_WEIGHT: Final[int] = 2
RETRIEVAL_KEYWORD_WEIGHT: Final[int] = 1

DECISION_PRESSURE_RELIEF: Final[float] = 0.60
DECISION_DISCLOSE_THRESHOLD: Final[float] = 0.55
DECISION_LIE_THRESHOLD: Final[float] = 0.75
DECISION_LIE_PROPENSITY_CUTOFF: Final[float] = 0.50
LLM_TIMEOUT_SECONDS: Final[float] = 30.0
LLM_MAX_TOKENS: Final[int] = 200
LLM_TEMPERATURE: Final[float] = 0.7

MAX_REPLY_CHARS: Final[int] = 80
MAX_REWRITE_ATTEMPTS: Final[int] = 2
SECRET_FRAGMENT_LENGTH: Final[int] = 8
PRESSURE_PER_CLUE: Final[float] = 0.25
CONFRONT_PRESSURE: Final[float] = 0.10
MAX_PRESSURE: Final[float] = 1.0
MAX_QUESTION_CHARS: Final[int] = 200