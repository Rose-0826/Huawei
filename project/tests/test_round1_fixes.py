"""第一轮试玩修补的接口级回归：物证、假记忆、检索、谎言。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.game import GameStore
from app.main import create_app
from app.models import Script
from app.script_loader import load_script

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "scripts"
    / "mistvale-inn.json"
)


class CapturingLLM:
    """返回固定台词并记录提示词，便于断言物证是否进入对话。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.reply = "我瞧见这东西，心里咯噔一下。"

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        return self.reply


@pytest.fixture
def script() -> Script:
    return load_script(SCRIPT_PATH)


@pytest.fixture
def client(
    script: Script,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    monkeypatch.setenv("MOCK_LLM", "1")
    for name in ("MAAS_API_KEY", "MAAS_ENDPOINT", "MAAS_MODEL"):
        monkeypatch.delenv(name, raising=False)
    return TestClient(create_app(script, GameStore()))


def _start(client: TestClient) -> str:
    response = client.post("/games")
    assert response.status_code == 200
    return response.json()["game_id"]


def _ask(client: TestClient, game_id: str, npc_id: str, question: str) -> dict:
    response = client.post(
        f"/games/{game_id}/ask",
        json={"npc_id": npc_id, "question": question},
    )
    assert response.status_code == 200
    return response.json()


def test_present_clue_prompt_carries_evidence(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = CapturingLLM()
    monkeypatch.setattr("app.engine.composer.get_llm", lambda: llm)
    game_id = _start(client)

    plain = _ask(client, game_id, "r3", "书房壁炉边有几根拨火棍？")
    plain_prompt = llm.calls[-1][1]
    response = client.post(
        f"/games/{game_id}/clues",
        json={"npc_id": "r3", "clue_id": "c03"},
    )

    assert plain["unlocked_clue"]["id"] == "c03"
    assert response.status_code == 200
    clue_prompt = llm.calls[-1][1]
    assert "物证" not in plain_prompt
    assert "少了一根拨火棍" in clue_prompt
    assert "书房壁炉边只有一根拨火棍" in clue_prompt
    assert "仍受当前动作约束" in clue_prompt


def test_r2_fire_belief_does_not_unlock_c05(client: TestClient) -> None:
    game_id = _start(client)

    data = _ask(client, game_id, "r2", "三年前那场火到底是怎么回事")

    assert data["unlocked_clue"] is None
    state = client.get(f"/games/{game_id}").json()
    assert "c05" not in [clue["id"] for clue in state["clues"]]


def test_r1_fire_truth_unlocks_c05(client: TestClient) -> None:
    game_id = _start(client)

    data = _ask(client, game_id, "r1", "三年前那场火到底是怎么回事")

    assert data["unlocked_clue"]["id"] == "c05"


def test_c08_quarrel_question_hits(client: TestClient) -> None:
    game_id = _start(client)

    data = _ask(client, game_id, "r3", "22:30 前后是不是在吵架？")

    assert data["unlocked_clue"]["id"] == "c08"


def test_c07_money_question_hits(client: TestClient) -> None:
    game_id = _start(client)

    data = _ask(
        client,
        game_id,
        "r5",
        "案发之后，沈玉兰有没有给过你钱？",
    )

    assert data["unlocked_clue"]["id"] == "c07"


def test_lie_reply_does_not_expose_fact_via_api(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = CapturingLLM()
    llm.reply = (
        "23:35，沈玉兰塞给老韩一包银元，"
        "让他咬死说整晚没上过二楼。"
    )
    monkeypatch.setattr("app.engine.composer.get_llm", lambda: llm)
    game_id = _start(client)

    data = _ask(client, game_id, "r1", "那包银元是谁给的")

    assert "银元" not in data["reply"]
    assert "23:35" not in data["reply"]
    assert len(llm.calls) == 3
    assert "撒谎" not in llm.calls[0][1]