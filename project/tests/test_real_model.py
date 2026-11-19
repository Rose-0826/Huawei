"""真实模型冒烟测试，默认跳过。"""

from __future__ import annotations

import os

import pytest

from app.llm import MaaSLLM, MockLLM, get_llm


@pytest.mark.real_model
def test_maas_chat_completion_smoke() -> None:
    """真实 MaaS 模型可返回非空文本，默认不在 pytest 中执行。"""
    if os.environ.get("MOCK_LLM") == "1":
        pytest.skip("MOCK_LLM=1，没有启用真实模型")
    try:
        client = get_llm()
    except RuntimeError as exc:
        pytest.skip(str(exc))
    if isinstance(client, MockLLM):
        pytest.skip("当前是模拟模型")
    assert isinstance(client, MaaSLLM)

    reply = client.complete(
        "你是一个简洁的助手。",
        "只回复四个字：连接成功",
    )

    assert reply