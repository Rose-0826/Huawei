"""pytest 全局配置：真模型用例默认跳过。"""

from __future__ import annotations

import os

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """注册真模型标记，避免 pytest 把它当成未知标记。"""
    config.addinivalue_line(
        "markers",
        "real_model: 需要真实 MaaS 模型与网络，默认跳过",
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """未显式开启真模型时，跳过带 real_model 标记的用例。"""
    if os.environ.get("RUN_REAL_MODEL") == "1":
        return
    skip = pytest.mark.skip(
        reason="需要真实模型：设置 RUN_REAL_MODEL=1 并配置 MAAS_* 后运行",
    )
    for item in items:
        if "real_model" in item.keywords:
            item.add_marker(skip)