"""FastAPI 五个接口测试。"""

from __future__ import annotations

import json
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
    assert data["unlocked_clue"] is None

    state = client.get(f"/games/{game_id}").json()
    assert state["pressure"]["r3"] == pytest.approx(0.25)
    assert [clue["id"] for clue in state["clues"]] == ["c03"]


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
    assert set(data["missed_fact_ids"]) == {
        "f05",
        "f06",
        "f08",
        "f15",
        "f16",
    }
    assert all(fact["text"] == "" for fact in data["timeline"])
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
    assert all(fact["text"] == "" for fact in data["timeline"])

def test_frontend_is_served(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "雾镇旅馆" in response.text
    assert "./app.js" in response.text
    assert client.get("/app.js").status_code == 200
    assert client.get("/styles.css").status_code == 200

def test_script_path_env_selects_script(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    data = json.loads(SCRIPT_PATH.read_text(encoding="utf-8"))
    data["title"] = "雾镇旅馆·副本"
    target = tmp_path / "copy.json"
    target.write_text(
        json.dumps(data, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setenv("SCRIPT_PATH", str(target))

    client = TestClient(create_app())
    response = client.post("/games")

    assert response.status_code == 200
    assert response.json()["title"] == "雾镇旅馆·副本"

def test_combine_returns_inference_and_pressure(
    client_with_store: tuple[TestClient, GameStore],
) -> None:
    client, store = client_with_store
    game_id = _start(client)
    _unlock(store, game_id, "c01", "c02")

    response = client.post(
        f"/games/{game_id}/combine",
        json={"clue_ids": ["c01", "c02"]},
    )

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {
        "title",
        "text",
        "pressure",
        "remaining",
        "reaction",
        "target_npc_id",
    }
    assert data["title"] == "时间线钉板"
    assert "23:00" in data["text"]
    assert "23:05" in data["text"]
    assert data["pressure"]["r1"] == pytest.approx(0.1)
    assert data["remaining"] == 2
    assert data["target_npc_id"] == "r1"
    assert data["reaction"]["npc_id"] == "r1"
    assert data["reaction"]["name"] == "沈玉兰"
    assert "沈玉兰" in data["reaction"]["line"]

    state = client.get(f"/games/{game_id}").json()
    assert state["pressure"]["r1"] == pytest.approx(0.1)
    assert [clue["id"] for clue in state["clues"]] == ["c01", "c02"]
    assert state["combine_remaining"] == 2
    assert state["combine_max"] == 3


def test_combine_reverse_order_and_duplicate_pair(
    client_with_store: tuple[TestClient, GameStore],
) -> None:
    client, store = client_with_store
    game_id = _start(client)
    _unlock(store, game_id, "c01", "c02")

    first = client.post(
        f"/games/{game_id}/combine",
        json={"clue_ids": ["c02", "c01"]},
    )
    second = client.post(
        f"/games/{game_id}/combine",
        json={"clue_ids": ["c01", "c02"]},
    )

    assert first.status_code == 200
    assert second.status_code == 409
    detail = second.json()["detail"]
    assert "这两张物证已经对撞过了" in detail
    assert "本局还剩 2 次" in detail


def test_combine_limit_blocks_fourth_pair(
    client_with_store: tuple[TestClient, GameStore],
) -> None:
    client, store = client_with_store
    game_id = _start(client)
    _unlock(
        store,
        game_id,
        "c01",
        "c02",
        "c03",
        "c04",
        "c05",
        "c06",
        "c07",
        "c08",
    )

    for pair in (["c01", "c02"], ["c03", "c04"], ["c05", "c06"]):
        assert (
            client.post(
                f"/games/{game_id}/combine",
                json={"clue_ids": pair},
            ).status_code
            == 200
        )

    fourth = client.post(
        f"/games/{game_id}/combine",
        json={"clue_ids": ["c04", "c08"]},
    )

    assert fourth.status_code == 409
    detail = fourth.json()["detail"]
    assert "本局的对撞次数已经用完" in detail
    assert "本局还剩 0 次" in detail


def test_combine_locked_clue_returns_409(
    client_with_store: tuple[TestClient, GameStore],
) -> None:
    client, store = client_with_store
    game_id = _start(client)
    _unlock(store, game_id, "c02")

    response = client.post(
        f"/games/{game_id}/combine",
        json={"clue_ids": ["c01", "c02"]},
    )

    assert response.status_code == 409
    assert "还没有解锁" in response.json()["detail"]


def test_combine_pair_without_rule_returns_422(
    client_with_store: tuple[TestClient, GameStore],
) -> None:
    client, store = client_with_store
    game_id = _start(client)
    _unlock(store, game_id, "c01", "c03")

    response = client.post(
        f"/games/{game_id}/combine",
        json={"clue_ids": ["c01", "c03"]},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "这两张物证对不上" in detail
    assert "试试有共同人物或时间的物证" in detail
    assert "本局还剩 3 次" in detail


def test_combine_input_errors(
    client_with_store: tuple[TestClient, GameStore],
) -> None:
    client, store = client_with_store
    game_id = _start(client)
    _unlock(store, game_id, "c01")

    one = client.post(
        f"/games/{game_id}/combine",
        json={"clue_ids": ["c01"]},
    )
    same = client.post(
        f"/games/{game_id}/combine",
        json={"clue_ids": ["c01", "c01"]},
    )
    unknown = client.post(
        f"/games/{game_id}/combine",
        json={"clue_ids": ["c01", "c99"]},
    )
    missing = client.post(
        "/games/missing/combine",
        json={"clue_ids": ["c01", "c02"]},
    )

    assert one.status_code == 422
    assert "对撞需要两张不同的物证" in one.json()["detail"]
    assert "本局还剩 3 次" in one.json()["detail"]
    assert same.status_code == 422
    assert same.json()["detail"] == one.json()["detail"]
    assert unknown.status_code == 404
    assert unknown.json()["detail"] == "找不到这张线索"
    assert missing.status_code == 404
    assert missing.json()["detail"] == "找不到这一局"


def test_combine_after_accuse_returns_409(
    client_with_store: tuple[TestClient, GameStore],
) -> None:
    client, store = client_with_store
    game_id = _start(client)
    _unlock(store, game_id, "c01", "c02")
    client.post(f"/games/{game_id}/accuse", json={"suspect_id": "r1"})

    response = client.post(
        f"/games/{game_id}/combine",
        json={"clue_ids": ["c01", "c02"]},
    )

    assert response.status_code == 409
    assert "本局已经结束" in response.json()["detail"]


def test_present_clue_to_uninformed_npc_does_not_repeat_last_answer(
    client_with_store: tuple[TestClient, GameStore],
    script: Script,
) -> None:
    client, store = client_with_store
    game_id = _start(client)
    client.post(
        f"/games/{game_id}/ask",
        json={"npc_id": "r1", "question": "23:05 楼梯口碰见谁"},
    )
    client.post(
        f"/games/{game_id}/ask",
        json={"npc_id": "r3", "question": "那晚你看见什么"},
    )
    previous = next(fact for fact in script.facts if fact.id == "f05")

    response = client.post(
        f"/games/{game_id}/clues",
        json={"npc_id": "r3", "clue_id": "c02"},
    )

    assert response.status_code == 200
    reply = response.json()["reply"]
    assert reply
    assert reply != previous.text
    assert "23:00" not in reply
    state = store.get(game_id)
    assert state is not None
    assert state.pressure["r3"] == pytest.approx(0.25)


def test_accuse_masks_undisclosed_timeline_text(
    client_with_store: tuple[TestClient, GameStore],
) -> None:
    client, store = client_with_store
    game_id = _start(client)
    client.post(
        f"/games/{game_id}/ask",
        json={"npc_id": "r1", "question": "23:05 楼梯口碰见谁"},
    )
    state = store.get(game_id)
    assert state is not None
    assert "f06" in state.disclosed_fact_ids

    response = client.post(
        f"/games/{game_id}/accuse",
        json={"suspect_id": "r1"},
    )

    assert response.status_code == 200
    texts = {
        fact["fact_id"]: fact["text"]
        for fact in response.json()["timeline"]
    }
    assert texts["f06"]
    for fact_id in ("f05", "f08", "f15", "f16"):
        assert texts[fact_id] == ""
