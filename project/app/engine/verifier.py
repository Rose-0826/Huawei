"""草稿一致性校验：时间、数字、秘密与长度。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import MAX_REPLY_CHARS, SECRET_FRAGMENT_LENGTH
from app.models import Role

TIME_PATTERN = re.compile(r"\d{1,2}[:：]\d{2}")
ARABIC_PATTERN = re.compile(r"\d+(?:\.\d+)?")
CHINESE_NUMBER_PATTERN = re.compile(
    r"[零一二两三四五六七八九十百千万]+"
    r"(?:点[零一二两三四五六七八九十半]+)?"
)


@dataclass(frozen=True)
class Verification:
    """一次草稿校验的结果。"""

    ok: bool
    reason: str | None


def verify_reply(
    draft: str,
    allowed_text: str | None,
    role: Role,
) -> Verification:
    """校验草稿的时间数字、秘密泄露与长度，返回可读原因。"""
    text = draft.strip()
    if not text:
        return Verification(False, "回答为空")
    if len(text) > MAX_REPLY_CHARS:
        return Verification(False, f"回答超过 {MAX_REPLY_CHARS} 字")

    if leaks_secret(text, role.secret, allowed_text):
        return Verification(
            False,
            "你刚才差点直接说出了自己的秘密，必须收回去",
        )

    allowed_tokens = set(_extract_number_tokens(allowed_text or ""))
    unexpected = [
        token
        for token in _extract_number_tokens(text)
        if token not in allowed_tokens
    ]
    if unexpected:
        return Verification(
            False,
            "你刚才说的时间和事实不符："
            + "、".join(unexpected)
            + " 不在给定事实里",
        )
    return Verification(True, None)


def leaks_secret(
    draft: str,
    secret: str,
    allowed_text: str | None = None,
) -> bool:
    """判断草稿是否说出了 allowed 文本之外的秘密片段。"""
    normalized_secret = _normalize_text(secret)
    normalized_draft = _normalize_text(draft)
    normalized_allowed = _normalize_text(allowed_text or "")
    if not normalized_secret:
        return False
    if (
        normalized_secret in normalized_draft
        and normalized_secret not in normalized_allowed
    ):
        return True
    window = SECRET_FRAGMENT_LENGTH
    if len(normalized_secret) <= window:
        return False
    for start in range(len(normalized_secret) - window + 1):
        fragment = normalized_secret[start : start + window]
        if fragment in normalized_allowed:
            continue
        if fragment in normalized_draft:
            return True
    return False


def _normalize_text(text: str) -> str:
    return "".join(char for char in text if char.isalnum())


def _normalize_token(token: str) -> str:
    return token.replace("：", ":").strip()


def _extract_number_tokens(text: str) -> tuple[str, ...]:
    spans: list[tuple[int, int, str]] = []
    for pattern in (TIME_PATTERN, ARABIC_PATTERN, CHINESE_NUMBER_PATTERN):
        for match in pattern.finditer(text):
            if any(start <= match.start() < end for start, end, _ in spans):
                continue
            token = _normalize_token(match.group(0))
            spans.append((match.start(), match.end(), token))
    spans.sort(key=lambda item: item[0])
    return tuple(dict.fromkeys(token for _, _, token in spans))