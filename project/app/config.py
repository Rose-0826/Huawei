"""全局配置与可调阈值。"""

from __future__ import annotations

from typing import Final

RETRIEVAL_MAX_RESULTS: Final[int] = 3
RETRIEVAL_TOPIC_WEIGHT: Final[int] = 2
RETRIEVAL_KEYWORD_WEIGHT: Final[int] = 1
DECISION_RISK_BASE: Final[float] = 0.50
DECISION_RISK_LIE_FACTOR: Final[float] = 0.50
DECISION_PRESSURE_RELIEF: Final[float] = 0.60
DECISION_DISCLOSE_THRESHOLD: Final[float] = 0.55
DECISION_LIE_THRESHOLD: Final[float] = 0.75
DECISION_LIE_PROPENSITY_CUTOFF: Final[float] = 0.50