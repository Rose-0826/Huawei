"""对局日志：条目顺序、可见字段与接口链路测试。"""

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

FORBIDDEN_KEYS = ("is_lie", "action", "fact_id")


@pytest.fixture
def script() -> Script:
    data = load_script(SCRIPT_PATH)
    facts = {fact.id: fact for fact in data.facts}
    facts["f05"].sensitivity = 0.7
    return data


@pytest.fixture
def client_with_store(
    script: Script,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, GameStore]:
    monkeypatch.setenv("MOCK_LLM", "1")
    for name in ("MAAS_API_KEY", "MAAS_ENDPOINT", "MAAS_MODEL"):
        monkeypatch.delenv(name, raising=False)
    store = GameStore()
    return TestClient(create_app(script, store)), store


def _start(client: TestClient) -> str:
    response = client.post("/games")
    assert response.status_code == 200
    return response.json()["game_id"]


def _unlock(store: GameStore, game_id: str, *clue_ids: str) -> None:
    state = store.get(game_id)
    assert state is not None
    state.unlocked_clue_ids.extend(clue_ids)


def _play_full_game(
    client: TestClient,
    store: GameStore,
) -> str:
    game_id = _start(client)
    _unlock(store, game_id, "c01", "c02")

    assert (
        client.post(
            f"/games/{game_id}/ask",
            json={"npc_id": "r3", "question": "壁炉边的拨火棍呢"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/games/{game_id}/clues",
            json={"npc_id": "r3", "clue_id": "c03"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/games/{game_id}/confront",
            json={"npc_ids": ["r1", "r3"], "question": "那晚你在哪"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/games/{game_id}/combine",
            json={"clue_ids": ["c01", "c02"]},
        ).status_code
        == 200
    )
    event = client.get(f"/games/{game_id}/event").json()["event"]
    assert event is not None
    assert (
        client.post(
            f"/games/{game_id}/event",
            json={"choice": "press"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/games/{game_id}/accuse",
            json={"suspect_id": "r1"},
        ).status_code
        == 200
    )
    return game_id


def test_log_sequence_and_types(
    client_with_store: tuple[TestClient, GameStore],
) -> None:
    client, store = client_with_store
    game_id = _play_full_game(client, store)

    response = client.get(f"/games/{game_id}/log")

    assert response.status_code == 200
    data = response.json()
    assert data["game_id"] == game_id
    entries = data["entries"]
    assert [entry["type"] for entry in entries] == [
        "start",
        "ask",
        "present",
        "confront",
        "combine",
        "event",
        "accuse",
    ]
    assert [entry["seq"] for entry in entries] == list(
        range(1, len(entries) + 1)
    )
    assert entries[0]["opening"]
    present = entries[2]
    assert present["clue_id"] == "c03"
    assert present["pressure"] == pytest.approx(0.25)
    combine = entries[4]
    assert combine["title"] == "时间线钉板"
    assert combine["pressure"]["r1"] == pytest.approx(0.2)
    accuse = entries[6]
    assert accuse["suspect_id"] == "r1"
    assert accuse["correct"] is True


def test_ask_entry_has_public_fields_only(
    client_with_store: tuple[TestClient, GameStore],
) -> None:
    client, store = client_with_store
    game_id = _start(client)
    client.post(
        f"/games/{game_id}/ask",
        json={"npc_id": "r3", "question": "壁炉边的拨火棍呢"},
    )

    entries = client.get(f"/games/{game_id}/log").json()["entries"]
    ask = entries[1]

    assert ask["type"] == "ask"
    assert ask["npc_id"] == "r3"
    assert ask["npc_name"]
    assert ask["question"] == "壁炉边的拨火棍呢"
    assert ask["reply"]
    assert ask["unlocked_clue"] == {"id": "c03", "name": ask["unlocked_clue"]["name"]}
    for key in FORBIDDEN_KEYS:
        assert key not in ask


def test_log_for_missing_game_returns_404(
    client_with_store: tuple[TestClient, GameStore],
) -> None:
    client, _ = client_with_store

    response = client.get("/games/missing/log")

    assert response.status_code == 404
    assert response.json()["detail"] == "找不到这一局"


def test_failed_actions_do_not_break_log(
    client_with_store: tuple[TestClient, GameStore],
) -> None:
    client, store = client_with_store
    game_id = _start(client)

    failed = client.post(
        f"/games/{game_id}/ask",
        json={"npc_id": "r9", "question": "问题"},
    )
    assert failed.status_code == 404
    locked = client.post(
        f"/games/{game_id}/clues",
        json={"npc_id": "r3", "clue_id": "c01"},
    )
    assert locked.status_code == 409

    entries = client.get(f"/games/{game_id}/log").json()["entries"]
    assert [entry["type"] for entry in entries] == ["start"]

    assert (
        client.post(
            f"/games/{game_id}/ask",
            json={"npc_id": "r3", "question": "那晚你看见什么"},
        ).status_code
        == 200
    )
    entries = client.get(f"/games/{game_id}/log").json()["entries"]
    assert [entry["type"] for entry in entries] == ["start", "ask"]
    assert [entry["seq"] for entry in entries] == [1, 2]


def test_log_response_has_no_internal_fields(
    client_with_store: tuple[TestClient, GameStore],
) -> None:
    client, store = client_with_store
    game_id = _play_full_game(client, store)

    response = client.get(f"/games/{game_id}/log")

    for forbidden in ("secret", "culprit", "is_lie"):
        assert forbidden not in response.text
    for entry in response.json()["entries"]:
        for key in FORBIDDEN_KEYS:
            assert key not in entry