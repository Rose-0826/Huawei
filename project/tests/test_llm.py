"""模型客户端测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from urllib.error import HTTPError, URLError
from urllib.request import Request

from app.llm import LLMUnavailable, MaaSLLM, MOCK_REPLY, MockLLM, get_llm


def test_mock_llm_returns_fixed_reply() -> None:
    assert MockLLM().complete("system", "user") == MOCK_REPLY


def test_get_llm_uses_mock_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_LLM", "1")
    monkeypatch.delenv("MAAS_API_KEY", raising=False)
    monkeypatch.delenv("MAAS_ENDPOINT", raising=False)
    monkeypatch.delenv("MAAS_MODEL", raising=False)

    assert isinstance(get_llm(), MockLLM)


def test_get_llm_reports_missing_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("app.llm.ENV_FILE", tmp_path / "missing.env")
    monkeypatch.delenv("MOCK_LLM", raising=False)
    for name in ("MAAS_API_KEY", "MAAS_ENDPOINT", "MAAS_MODEL"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(RuntimeError) as raised:
        get_llm()

    message = str(raised.value)
    assert "MAAS_API_KEY" in message
    assert "MOCK_LLM=1" in message


def test_get_llm_reads_env_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "MAAS_API_KEY=file-key\n"
        "MAAS_ENDPOINT=https://maas.example.com/v1\n"
        "MAAS_MODEL=file-model\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("app.llm.ENV_FILE", env_file)
    for name in ("MOCK_LLM", "MAAS_API_KEY", "MAAS_ENDPOINT", "MAAS_MODEL"):
        monkeypatch.delenv(name, raising=False)

    client = get_llm()

    assert isinstance(client, MaaSLLM)
    assert client.model == "file-model"
    assert client._url == "https://maas.example.com/v1/chat/completions"


def test_maas_client_posts_openai_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def read(self) -> bytes:
            return json.dumps(
                {"choices": [{"message": {"content": "  台词  "}}]},
                ensure_ascii=False,
            ).encode("utf-8")

    def fake_urlopen(request: Request, timeout: float) -> FakeResponse:
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["headers"] = dict(request.header_items())
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("app.llm.urlopen", fake_urlopen)
    client = MaaSLLM("test-key", "https://maas.example.com/v1", "deepseek")
    result = client.complete("系统提示", "用户提示")

    body = captured["body"]
    headers = captured["headers"]
    assert isinstance(body, dict)
    assert isinstance(headers, dict)
    assert result == "台词"
    assert captured["url"] == "https://maas.example.com/v1/chat/completions"
    assert body["model"] == "deepseek"
    assert body["messages"][0]["content"] == "系统提示"
    assert body["messages"][1]["content"] == "用户提示"
    assert headers["Authorization"] == "Bearer test-key"
    assert captured["timeout"] == client.timeout


def test_maas_client_raises_on_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request: Request, timeout: float) -> object:
        raise URLError("boom")

    monkeypatch.setattr("app.llm.urlopen", fake_urlopen)
    client = MaaSLLM("test-key", "https://maas.example.com", "deepseek")

    with pytest.raises(LLMUnavailable):
        client.complete("系统提示", "用户提示")


def test_maas_client_raises_on_auth_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request: Request, timeout: float) -> object:
        raise HTTPError(
            "https://maas.example.com",
            401,
            "Unauthorized",
            None,
            None,
        )

    monkeypatch.setattr("app.llm.urlopen", fake_urlopen)
    client = MaaSLLM("bad-key", "https://maas.example.com", "deepseek")

    with pytest.raises(LLMUnavailable):
        client.complete("系统提示", "用户提示")


def test_maas_client_raises_on_bad_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def read(self) -> bytes:
            return b"not json"

    def fake_urlopen(request: Request, timeout: float) -> FakeResponse:
        return FakeResponse()

    monkeypatch.setattr("app.llm.urlopen", fake_urlopen)
    client = MaaSLLM("test-key", "https://maas.example.com", "deepseek")

    with pytest.raises(LLMUnavailable):
        client.complete("系统提示", "用户提示")


def test_maas_client_raises_on_missing_choices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def read(self) -> bytes:
            return b'{"choices": []}'

    def fake_urlopen(request: Request, timeout: float) -> FakeResponse:
        return FakeResponse()

    monkeypatch.setattr("app.llm.urlopen", fake_urlopen)
    client = MaaSLLM("test-key", "https://maas.example.com", "deepseek")

    with pytest.raises(LLMUnavailable):
        client.complete("系统提示", "用户提示")