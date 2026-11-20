"""对质判定、状态机与接口测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import MAX_QUESTION_CHARS
from app.engine.confront import Statement, compare_testimony
from app.game import GameStore, accuse, ask, confront
from app.main import create_app
from app.models import Script
from app.script_loader import load_script

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "scripts"
    / "mistvale-inn.json"
)


class FakeLLM:
    def __init__(self, reply: str = "我记得些片段，但说不清。") -> None:
        self.reply = reply
        self.calls: list[tuple[str, str]] = []

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        return self.reply


@pytest.fixture
def script() -> Script:
    data = load_script(SCRIPT_PATH)
    facts = {fact.id: fact for fact in data.facts}
    facts["f05"].sensitivity = 0.7
    return data


@pytest.fixture
def store() -> GameStore:
    return GameStore()


@pytest.fixture
def client(
    script: Script,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    monkeypatch.setenv("MOCK_LLM", "1")
    for name in ("MAAS_API_KEY", "MAAS_ENDPOINT", "MAAS_MODEL"):
        monkeypatch.delenv(name, raising=False)
    return TestClient(create_app(script, GameStore()))


def test_same_fact_same_wording_is_aligned() -> None:
    left = Statement("disclose", "f02", "22:30 前后有争吵")
    right = Statement("disclose", "f02", "22:30 前后有争吵")

    assert compare_testimony(left, right) == "aligned"


def test_same_fact_different_memory_conflicts() -> None:
    left = Statement("disclose", "f02", "22:30 前后有争吵")
    right = Statement("disclose", "f02", "22:45 前后有争吵")

    assert compare_testimony(left, right) == "conflicting"


def test_different_facts_is_unclear() -> None:
    left = Statement("disclose", "f02", "甲")
    right = Statement("disclose", "f05", "乙")

    assert compare_testimony(left, right) == "unclear"


def test_one_speaks_one_stays_quiet_is_unclear() -> None:
    """需求变更：只说一方无法构成矛盾，降级为说不清。"""
    left = Statement("disclose", "f02", "甲")
    right = Statement("evade", "f02", None)

    assert compare_testimony(left, right) == "unclear"


def test_both_quiet_is_unclear() -> None:
    left = Statement("evade", None, None)
    right = Statement("unparsed", None, None)

    assert compare_testimony(left, right) == "unclear"


def test_both_lie_conflicts() -> None:
    left = Statement("lie", "f02", None)
    right = Statement("lie", "f02", None)

    assert compare_testimony(left, right) == "conflicting"


def test_both_lie_different_facts_is_unclear() -> None:
    left = Statement("lie", "f11", None)
    right = Statement("lie", "f12", None)

    assert compare_testimony(left, right) == "unclear"


def test_lie_against_disclose_conflicts() -> None:
    left = Statement("lie", "f02", None)
    right = Statement("disclose", "f02", "甲")

    assert compare_testimony(left, right) == "conflicting"


def test_lie_against_disclose_different_facts_is_unclear() -> None:
    left = Statement("lie", "f11", None)
    right = Statement("disclose", "f14", "甲")

    assert compare_testimony(left, right) == "unclear"


def test_lie_against_quiet_is_unclear() -> None:
    left = Statement("lie", "f02", None)
    right = Statement("evade", "f02", None)

    assert compare_testimony(left, right) == "unclear"


def test_c2_one_deflects_one_answers_is_unclear(
    store: GameStore,
    script: Script,
) -> None:
    """C2：r2 手里没有拨火棍的知识，r3 如实回答，只算说不清。"""
    state = store.start(script)

    outcome = confront(
        store,
        state.game_id,
        ("r2", "r3"),
        "壁炉边的拨火棍呢",
        FakeLLM(),
    )

    assert outcome.ok is True
    assert outcome.alignment == "unclear"
    assert all(reply.reply for reply in outcome.replies)


def test_c3_both_evade_is_unclear(
    store: GameStore,
    script: Script,
) -> None:
    """C3：两人都不知道凶器，谁也没给出可比口径。"""
    state = store.start(script)

    outcome = confront(
        store,
        state.game_id,
        ("r2", "r5"),
        "凶器是什么",
        FakeLLM(),
    )

    assert outcome.ok is True
    assert outcome.alignment == "unclear"


def test_confront_returns_two_replies_without_pressure(
    store: GameStore,
    script: Script,
) -> None:
    state = store.start(script)

    outcome = confront(
        store,
        state.game_id,
        ("r2", "r3"),
        "22:30 前后书房里的争吵",
        FakeLLM(),
    )

    assert outcome.ok is True
    assert outcome.alignment in {"aligned", "conflicting", "unclear"}
    assert [reply.npc_id for reply in outcome.replies] == ["r2", "r3"]
    assert all(reply.reply for reply in outcome.replies)
    assert state.pressure.get("r2", 0.0) == 0.0
    assert state.pressure.get("r3", 0.0) == 0.0
    assert state.last_questions["r2"] == "22:30 前后书房里的争吵"
    assert state.last_questions["r3"] == "22:30 前后书房里的争吵"


def test_confront_validation(
    store: GameStore,
    script: Script,
) -> None:
    state = store.start(script)
    long_question = "问" * (MAX_QUESTION_CHARS + 1)

    assert confront(
        store, "missing", ("r2", "r3"), "问题", FakeLLM()
    ).error == "game_not_found"
    assert confront(
        store, state.game_id, ("r2", "r2"), "问题", FakeLLM()
    ).error == "confront_needs_two"
    assert confront(
        store, state.game_id, ("r2",), "问题", FakeLLM()
    ).error == "confront_needs_two"
    assert confront(
        store, state.game_id, ("r2", "r9"), "问题", FakeLLM()
    ).error == "npc_not_found"
    assert confront(
        store, state.game_id, ("r2", "r3"), "   ", FakeLLM()
    ).error == "empty_question"
    assert confront(
        store, state.game_id, ("r2", "r3"), long_question, FakeLLM()
    ).error == "question_too_long"
    assert confront(
        store, state.game_id, ("r2", "r3"), "问题", FakeLLM()
    ).ok is True


def test_confront_after_accusation_is_rejected(
    store: GameStore,
    script: Script,
) -> None:
    state = store.start(script)
    accuse(store, state.game_id, "r2")

    outcome = confront(
        store,
        state.game_id,
        ("r2", "r3"),
        "问题",
        FakeLLM(),
    )

    assert outcome.ok is False
    assert outcome.error == "game_ended"


def test_confront_endpoint_returns_alignment(client: TestClient) -> None:
    game_id = client.post("/games").json()["game_id"]

    response = client.post(
        f"/games/{game_id}/confront",
        json={
            "npc_ids": ["r2", "r3"],
            "question": "22:30 前后书房里的争吵",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"alignment", "replies", "unlocked_clues"}
    assert data["alignment"] in {"aligned", "conflicting", "unclear"}
    assert [reply["npc_id"] for reply in data["replies"]] == ["r2", "r3"]
    assert all(reply["reply"] for reply in data["replies"])
    assert "is_lie" not in response.text
    assert "action" not in response.text

    state = client.get(f"/games/{game_id}").json()
    assert state["pressure"]["r2"] == 0.0
    assert state["pressure"]["r3"] == 0.0


def test_confront_endpoint_rejects_same_person(client: TestClient) -> None:
    game_id = client.post("/games").json()["game_id"]

    response = client.post(
        f"/games/{game_id}/confront",
        json={"npc_ids": ["r2", "r2"], "question": "问题"},
    )

    assert response.status_code == 422
    assert "两个不同的人" in response.json()["detail"]


def test_confront_endpoint_requires_two_ids(client: TestClient) -> None:
    game_id = client.post("/games").json()["game_id"]

    response = client.post(
        f"/games/{game_id}/confront",
        json={"npc_ids": ["r2"], "question": "问题"},
    )

    assert response.status_code == 422

def test_confront_rejects_repeated_question(
    store: GameStore,
    script: Script,
) -> None:
    state = store.start(script)
    question = "争吵什么时候停的"
    ask(store, state.game_id, "r2", question, FakeLLM())

    outcome = confront(
        store,
        state.game_id,
        ("r2", "r3"),
        question,
        FakeLLM(),
    )

    assert outcome.ok is False
    assert outcome.error == "confront_repeated_question"
    assert outcome.alignment is None


def test_confront_repeat_endpoint_returns_409(
    client: TestClient,
) -> None:
    game_id = client.post("/games").json()["game_id"]
    question = "争吵什么时候停的"
    client.post(
        f"/games/{game_id}/ask",
        json={"npc_id": "r2", "question": question},
    )

    response = client.post(
        f"/games/{game_id}/confront",
        json={"npc_ids": ["r2", "r3"], "question": question},
    )

    assert response.status_code == 409
    assert "换个问法" in response.json()["detail"]


def test_k6_different_facts_both_lie_is_unclear(
    client: TestClient,
) -> None:
    game_id = client.post("/games").json()["game_id"]

    response = client.post(
        f"/games/{game_id}/confront",
        json={
            "npc_ids": ["r1", "r2"],
            "question": "老板娘是不是塞给你一包银元，让你别说她上过二楼？",
        },
    )

    assert response.status_code == 200
    assert response.json()["alignment"] == "unclear"


def test_k5_same_fact_conflict_still_conflicting(
    client: TestClient,
) -> None:
    game_id = client.post("/games").json()["game_id"]

    response = client.post(
        f"/games/{game_id}/confront",
        json={
            "npc_ids": ["r1", "r5"],
            "question": "老板娘是不是塞给你一包银元，让你别说她上过二楼？",
        },
    )

    assert response.status_code == 200
    assert response.json()["alignment"] == "conflicting"