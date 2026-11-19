#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MaaS 连通性自检（只依赖标准库，不需要装 openai）

用法：
    1. 在 project/.env 里填好三个变量，或者直接 export
    2. python tools/check_maas.py
    3. 加 --say "你好" 可以看模型的实际回复

.env 内容：
    MAAS_API_KEY=你的key
    MAAS_ENDPOINT=https://api.modelarts-maas.com/v1
    MAAS_MODEL=你在控制台看到的模型名称
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def load_env(path: Path) -> None:
    """把 .env 读进 os.environ，已存在的变量不覆盖。"""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def explain(status: int, body: str) -> str:
    """把常见错误翻译成人话。"""
    body = body[:400]
    if status == 401 or status == 403:
        return (
            f"鉴权失败（{status}）。API Key 不对、或者复制时少了字符。\n"
            "  → 去 MaaS 控制台「API Key 管理」重新创建一个，注意只在创建时显示一次。"
        )
    if status == 404:
        return (
            f"找不到模型或接口（{status}）。多半是模型名称写错了。\n"
            "  → 在「调用说明 → OpenAI SDK」页签里复制原始 model 值，别自己猜。"
        )
    if status == 429:
        return (
            f"配额或限流（{status}）。免费额度按 token 计，可能已经用完。\n"
            "  → 控制台看额度余量；调试时把 max_tokens 调小。"
        )
    if status >= 500:
        return f"服务端错误（{status}），稍等重试。响应：{body}"
    return f"请求失败（{status}）。响应：{body}"


def main() -> int:
    ap = argparse.ArgumentParser(description="MaaS 接口连通性自检")
    ap.add_argument("--say", default=None, help="给模型发一句话，看真实回复")
    args = ap.parse_args()

    load_env(ENV_FILE)

    key = os.environ.get("MAAS_API_KEY")
    endpoint = os.environ.get(
        "MAAS_ENDPOINT", "https://api.modelarts-maas.com/v1"
    ).rstrip("/")
    model = os.environ.get("MAAS_MODEL")

    missing = [
        name
        for name, value in (
            ("MAAS_API_KEY", key),
            ("MAAS_MODEL", model),
        )
        if not value
    ]
    if missing:
        print("缺少环境变量：" + "、".join(missing))
        print(f"把它们写进 {ENV_FILE}，然后重跑。模板见 .env.example")
        return 2

    url = f"{endpoint}/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是一个简洁的助手，回答不超过 20 字。"},
            {"role": "user", "content": args.say or "回复两个字：收到"},
        ],
        "max_tokens": 64,
        "temperature": 0.3,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )

    print(f"endpoint : {url}")
    print(f"model    : {model}")
    print("请求中……")

    try:
        with urllib.request.urlopen(request, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print("✗ " + explain(exc.code, exc.read().decode("utf-8", "ignore")))
        return 1
    except urllib.error.URLError as exc:
        print(f"✗ 网络不通：{exc.reason}")
        print("  → 检查代理设置，或者换一个网络环境再试。")
        return 1
    except TimeoutError:
        print("✗ 超时。可能是网络，也可能是免费额度排队。")
        return 1

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        print("✗ 返回结构和预期不符：")
        print(json.dumps(data, ensure_ascii=False, indent=2)[:800])
        return 1

    usage = data.get("usage", {})
    print("✓ 连通")
    print(f"  回复：{content}")
    print(
        "  用量：prompt {p} / completion {c} / total {t} tokens".format(
            p=usage.get("prompt_tokens", "?"),
            c=usage.get("completion_tokens", "?"),
            t=usage.get("total_tokens", "?"),
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
