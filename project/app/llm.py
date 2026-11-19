"""模型调用封装，唯一允许发网络请求的地方。"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import (
    LLM_MAX_TOKENS,
    LLM_TEMPERATURE,
    LLM_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
MOCK_REPLY = "（模拟回复）我记得那会儿的事，但不敢乱说细节。"


class LLMUnavailable(RuntimeError):
    """模型网络、鉴权、超时或响应结构异常。"""


class LLMClient(Protocol):
    """模型客户端的最小接口。"""

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """返回模型生成的文本，模型不可用时抛出 LLMUnavailable。"""
        ...


class MockLLM:
    """无密钥时返回固定文案的模拟客户端。"""

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """返回固定模拟文案，用于在无密钥时跑通链路。"""
        return MOCK_REPLY


class MaaSLLM:
    """华为云 MaaS 的 OpenAI 兼容客户端。"""

    def __init__(
        self,
        api_key: str,
        endpoint: str,
        model: str,
        timeout: float = LLM_TIMEOUT_SECONDS,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._url = _resolve_endpoint(endpoint)

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """调用模型并返回文本，不可用时抛出 LLMUnavailable。"""
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": LLM_TEMPERATURE,
            "max_tokens": LLM_MAX_TOKENS,
        }
        try:
            request = Request(
                self._url,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except (
            HTTPError,
            URLError,
            TimeoutError,
            OSError,
            ValueError,
        ) as exc:
            logger.warning("模型请求失败：%s", exc)
            raise LLMUnavailable(f"模型请求失败：{exc}") from exc

        try:
            body = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("模型返回不是合法 JSON：%s", exc)
            raise LLMUnavailable("模型返回不是合法 JSON") from exc

        content = _extract_content(body)
        if not content:
            logger.warning("模型返回没有可用文本")
            raise LLMUnavailable("模型返回没有可用文本")
        return content


def get_llm() -> LLMClient:
    """按环境变量或 project/.env 返回模型客户端，MOCK_LLM=1 时返回模拟客户端。"""
    if os.environ.get("MOCK_LLM") == "1":
        logger.info("使用模拟模型")
        return MockLLM()

    file_values = _read_env_file()
    api_key = os.environ.get("MAAS_API_KEY") or file_values.get("MAAS_API_KEY")
    endpoint = (
        os.environ.get("MAAS_ENDPOINT")
        or file_values.get("MAAS_ENDPOINT")
    )
    model = os.environ.get("MAAS_MODEL") or file_values.get("MAAS_MODEL")
    missing = [
        name
        for name, value in (
            ("MAAS_API_KEY", api_key),
            ("MAAS_ENDPOINT", endpoint),
            ("MAAS_MODEL", model),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            "缺少模型环境变量："
            + "、".join(missing)
            + "；可设置 MOCK_LLM=1 先跑通链路"
        )
    logger.info("使用 MaaS 模型 %s", model)
    return MaaSLLM(api_key, endpoint, model)


def _read_env_file() -> dict[str, str]:
    if not ENV_FILE.exists():
        return {}
    values: dict[str, str] = {}
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            values[key] = value
    return values


def _resolve_endpoint(endpoint: str) -> str:
    normalized = endpoint.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    if normalized.endswith("/v1"):
        return normalized + "/chat/completions"
    return normalized + "/v1/chat/completions"


def _extract_content(body: Any) -> str:
    if not isinstance(body, dict):
        return ""
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if not isinstance(content, str):
        return ""
    return content.strip()