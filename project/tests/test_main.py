"""FastAPI 五个接口测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import MAX_QUESTION_CHARS
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


@pytest.fixture
def script() -> Script:
    data = load_script(SCRIPT_PATH)
    facts = {fact.id: fact for fact in data.facts}
    facts["f05"].sensitivity = 0.7
    return data


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


def test_start_and_state_are_public(client: TestClient) -> None:
    response = client.post("/games")

    assert response.status_code == 200
    data = response.json()
    assert data["opening"]
    assert len(data["roles"]) == 5
    assert data["clues"] == []
    assert data["ended"] is False
    assert "culprit" not in data
    assert "secret" not in data
    assert "solution_path" not in data

    state = client.get(f"/games/{data['game_id']}")
    assert state.status_code == 200
    assert state.json()["game_id"] == data["game_id"]


def test_ask_returns_text_and_unlocks_clue(client: TestClient) -> None:
    game_id = _start(client)

    response = client.post(
        f"/games/{game_id}/ask",
        json={"npc_id": "r3", "question": "壁炉边的拨火棍呢"},
    )

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"reply", "pressure", "unlocked_clue"}
    assert data["reply"]
    assert data["unlocked_clue"]["id"] == "c03"
    assert "action" not in data
    assert "is_lie" not in data

    state = client.get(f"/games/{game_id}").json()
    assert [clue["id"] for clue in state["clues"]] == ["c03"]


def test_present_clue_updates_pressure_and_answers_immediately(
    client: TestClient,
) -> None:
    game_id = _start(client)
    client.post(
        f"/games/{game_id}/ask",
        json={"npc_id": "r3", "question": "壁炉边的拨火棍呢"},
    )
    client.post(
        f"/games/{game_id}/ask",
        json={"npc_id": "r3", "question": "那晚你看见什么"},
    )

    response = client.post(
        f"/games/{game_id}/clues",
        json={"npc_id": "r3", "clue_id": "c03"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["reply"]
    assert data["pressure"] == pytest.approx(0.25)
    assert data["unlocked_clue"]["id"] == "c01"

    state = client.get(f"/games/{game_id}").json()
    assert state["pressure"]["r3"] == pytest.approx(0.25)
    assert [clue["id"] for clue in state["clues"]] == ["c03", "c01"]


def test_duplicate_clue_to_same_npc_returns_409(
    client: TestClient,
) -> None:
    game_id = _start(client)
    client.post(
        f"/games/{game_id}/ask",
        json={"npc_id": "r3", "question": "壁炉边的拨火棍呢"},
    )

    first = client.post(
        f"/games/{game_id}/clues",
        json={"npc_id": "r3", "clue_id": "c03"},
    )
    second = client.post(
        f"/games/{game_id}/clues",
        json={"npc_id": "r3", "clue_id": "c03"},
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"] == "这张线索你已经给他看过了"

    state = client.get(f"/games/{game_id}").json()
    assert state["pressure"]["r3"] == pytest.approx(0.25)


def test_same_clue_different_npcs_both_work(
    client: TestClient,
) -> None:
    game_id = _start(client)
    client.post(
        f"/games/{game_id}/ask",
        json={"npc_id": "r3", "question": "壁炉边的拨火棍呢"},
    )
    client.post(
        f"/games/{game_id}/ask",
        json={"npc_id": "r1", "question": "你用什么打他"},
    )

    first = client.post(
        f"/games/{game_id}/clues",
        json={"npc_id": "r3", "clue_id": "c03"},
    )
    second = client.post(
        f"/games/{game_id}/clues",
        json={"npc_id": "r1", "clue_id": "c03"},
    )

    assert first.status_code == 200
    assert second.status_code == 200

    state = client.get(f"/games/{game_id}").json()
    assert state["pressure"]["r3"] == pytest.approx(0.25)
    assert state["pressure"]["r1"] == pytest.approx(0.25)


def test_present_locked_clue_returns_409(client: TestClient) -> None:
    game_id = _start(client)

    response = client.post(
        f"/games/{game_id}/clues",
        json={"npc_id": "r3", "clue_id": "c01"},
    )

    assert response.status_code == 409
    assert "还没有解锁" in response.json()["detail"]


def test_present_without_question_returns_409(client: TestClient) -> None:
    game_id = _start(client)
    client.post(
        f"/games/{game_id}/ask",
        json={"npc_id": "r3", "question": "壁炉边的拨火棍呢"},
    )

    response = client.post(
        f"/games/{game_id}/clues",
        json={"npc_id": "r1", "clue_id": "c03"},
    )

    assert response.status_code == 409
    assert "还没有向这个角色提问" in response.json()["detail"]


def test_empty_and_long_questions_return_422(client: TestClient) -> None:
    game_id = _start(client)

    empty = client.post(
        f"/games/{game_id}/ask",
        json={"npc_id": "r3", "question": "   "},
    )
    assert empty.status_code == 422
    assert empty.json()["detail"] == "问题不能为空"

    long_question = "问" * (MAX_QUESTION_CHARS + 1)
    too_long = client.post(
        f"/games/{game_id}/ask",
        json={"npc_id": "r3", "question": long_question},
    )
    assert too_long.status_code == 422
    assert "问题不能超过" in too_long.json()["detail"]


def test_unknown_game_and_npc_return_404(client: TestClient) -> None:
    assert (
        client.post(
            "/games/missing/ask",
            json={"npc_id": "r3", "question": "问题"},
        ).status_code
        == 404
    )
    assert client.get("/games/missing").status_code == 404
    assert (
        client.post(
            "/games/missing/accuse",
            json={"suspect_id": "r1"},
        ).status_code
        == 404
    )

    game_id = _start(client)
    response = client.post(
        f"/games/{game_id}/ask",
        json={"npc_id": "r9", "question": "问题"},
    )
    assert response.status_code == 404
    assert "找不到这个角色" in response.json()["detail"]


def test_accuse_returns_timeline_and_missed_ids(client: TestClient) -> None:
    game_id = _start(client)
    client.post(
        f"/games/{game_id}/ask",
        json={"npc_id": "r3", "question": "壁炉边的拨火棍呢"},
    )
    client.post(
        f"/games/{game_id}/ask",
        json={"npc_id": "r3", "question": "那晚你看见什么"},
    )
    client.post(
        f"/games/{game_id}/clues",
        json={"npc_id": "r3", "clue_id": "c03"},
    )

    response = client.post(
        f"/games/{game_id}/accuse",
        json={"suspect_id": "r1"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["correct"] is True
    assert [fact["fact_id"] for fact in data["timeline"]] == [
        "f05",
        "f06",
        "f08",
        "f15",
        "f16",
    ]
    assert set(data["missed_fact_ids"]) == {"f06", "f08", "f15", "f16"}
    assert "culprit" not in data
    assert "secret" not in response.text

    state = client.get(f"/games/{game_id}").json()
    assert state["ended"] is True

    after = client.post(
        f"/games/{game_id}/ask",
        json={"npc_id": "r3", "question": "还能问吗"},
    )
    assert after.status_code == 409
    assert "本局已经结束" in after.json()["detail"]


def test_accuse_wrong_suspect(client: TestClient, script: Script) -> None:
    game_id = _start(client)

    response = client.post(
        f"/games/{game_id}/accuse",
        json={"suspect_id": "r2"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["correct"] is False
    assert [fact["fact_id"] for fact in data["timeline"]] == script.solution_path
    assert set(data["missed_fact_ids"]) == set(script.solution_path)

def test_frontend_is_served(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "雾镇旅馆" in response.text
    assert "./app.js" in response.text
    assert client.get("/app.js").status_code == 200
    assert client.get("/styles.css").status_code == 200