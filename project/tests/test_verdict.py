"""指认四要素：纯函数判定、状态机与 HTTP 契约测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.engine.verdict import (
    CORRECT_CHOICES,
    VERDICT_OPTIONS,
    judge_dimensions,
)
from app.game import GameStore, accuse, build_view
from app.main import create_app
from app.models import Script
from app.script_loader import load_script

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "scripts"
    / "mistvale-inn.json"
)

FULL_CHOICES = {
    "motive": "cover_fire",
    "method": "poker",
    "time": "t2250",
}


@pytest.fixture
def script() -> Script:
    return load_script(SCRIPT_PATH)


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


def _start(client: TestClient) -> str:
    response = client.post("/games")
    assert response.status_code == 200
    return response.json()["game_id"]


def test_options_have_four_entries_and_known_answers() -> None:
    assert set(VERDICT_OPTIONS) == {"motive", "method", "time"}
    assert CORRECT_CHOICES == {
        "motive": "cover_fire",
        "method": "poker",
        "time": "t2250",
    }
    for dimension, options in VERDICT_OPTIONS.items():
        assert len(options) == 4
        assert len({option.id for option in options}) == 4
        assert all(option.label for option in options)
        assert CORRECT_CHOICES[dimension] in {
            option.id for option in options
        }


def test_all_dimensions_correct() -> None:
    dimensions = judge_dimensions(FULL_CHOICES)

    assert [item.id for item in dimensions] == ["motive", "method", "time"]
    assert [item.label for item in dimensions] == ["动机", "手法", "时间"]
    assert all(item.correct for item in dimensions)
    assert [item.choice for item in dimensions] == [
        "cover_fire",
        "poker",
        "t2250",
    ]


def test_wrong_method_is_judged_per_dimension() -> None:
    dimensions = judge_dimensions({**FULL_CHOICES, "method": "paperweight"})
    by_id = {item.id: item for item in dimensions}

    assert by_id["motive"].correct is True
    assert by_id["method"].correct is False
    assert by_id["method"].choice == "paperweight"
    assert by_id["time"].correct is True


def test_unknown_ids_are_judged_wrong_without_raising() -> None:
    dimensions = judge_dimensions(
        {"motive": "money", "method": "hammer", "time": "t2300"}
    )
    by_id = {item.id: item for item in dimensions}

    assert by_id["motive"].correct is False
    assert by_id["method"].correct is False
    assert by_id["method"].choice == "hammer"
    assert by_id["time"].correct is False


def test_missing_dimensions_are_judged_wrong() -> None:
    dimensions = judge_dimensions({})

    assert len(dimensions) == 3
    assert all(item.correct is False for item in dimensions)
    assert all(item.choice == "" for item in dimensions)


def test_accuse_with_full_choices_sets_correct(
    store: GameStore,
    script: Script,
) -> None:
    state = store.start(script)

    outcome = accuse(store, state.game_id, "r1", **FULL_CHOICES)

    assert outcome.ok is True
    assert outcome.correct is True
    assert len(outcome.dimensions) == 3
    assert all(item.correct for item in outcome.dimensions)


def test_accuse_with_wrong_method_is_partial(
    store: GameStore,
    script: Script,
) -> None:
    state = store.start(script)

    outcome = accuse(
        store,
        state.game_id,
        "r1",
        motive="cover_fire",
        method="paperweight",
        time="t2250",
    )

    assert outcome.correct is False
    assert outcome.partial is True
    by_id = {item.id: item.correct for item in outcome.dimensions}
    assert by_id == {"motive": True, "method": False, "time": True}


def test_accuse_without_dimensions_keeps_old_behavior(
    store: GameStore,
    script: Script,
) -> None:
    state = store.start(script)

    outcome = accuse(store, state.game_id, "r1")

    assert outcome.correct is True
    assert outcome.partial is False
    assert outcome.dimensions == ()


def test_wrong_suspect_with_correct_choices_is_not_partial(
    store: GameStore,
    script: Script,
) -> None:
    state = store.start(script)

    outcome = accuse(store, state.game_id, "r2", **FULL_CHOICES)

    assert outcome.correct is False
    assert outcome.partial is False
    assert all(item.correct for item in outcome.dimensions)


def test_view_exposes_verdict_options(
    store: GameStore,
    script: Script,
) -> None:
    view = build_view(store.start(script))

    assert set(view.verdict_options) == {"motive", "method", "time"}
    assert [option.id for option in view.verdict_options["method"]] == [
        "poker",
        "paperweight",
        "poison",
        "rope",
    ]


def test_get_game_returns_verdict_options(client: TestClient) -> None:
    game_id = _start(client)

    response = client.get(f"/games/{game_id}")

    assert response.status_code == 200
    options = response.json()["verdict_options"]
    assert set(options) == {"motive", "method", "time"}
    assert options["motive"] == [
        {"id": "money", "label": "图财"},
        {"id": "cover_fire", "label": "掩盖旧案"},
        {"id": "quarrel", "label": "争执失手"},
        {"id": "love", "label": "私情"},
    ]
    assert options["method"][0] == {"id": "poker", "label": "拨火棍"}
    assert options["time"][2] == {"id": "t2250", "label": "22:50 前后"}


def test_http_accuse_full_choices(client: TestClient) -> None:
    game_id = _start(client)

    response = client.post(
        f"/games/{game_id}/accuse",
        json={"suspect_id": "r1", **FULL_CHOICES},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["correct"] is True
    assert data["partial"] is True
    assert [item["id"] for item in data["dimensions"]] == [
        "motive",
        "method",
        "time",
    ]
    assert all(item["correct"] for item in data["dimensions"])
    assert data["dimensions"][0] == {
        "id": "motive",
        "label": "动机",
        "choice": "cover_fire",
        "correct": True,
    }


def test_http_accuse_wrong_method_is_partial(client: TestClient) -> None:
    game_id = _start(client)

    response = client.post(
        f"/games/{game_id}/accuse",
        json={
            "suspect_id": "r1",
            "motive": "cover_fire",
            "method": "paperweight",
            "time": "t2250",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["correct"] is False
    assert data["partial"] is True
    by_id = {item["id"]: item["correct"] for item in data["dimensions"]}
    assert by_id == {"motive": True, "method": False, "time": True}


def test_http_accuse_legacy_request_only_judges_suspect(
    client: TestClient,
) -> None:
    game_id = _start(client)

    response = client.post(
        f"/games/{game_id}/accuse",
        json={"suspect_id": "r1"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["correct"] is True
    assert data["partial"] is False
    assert data["dimensions"] == []


def test_http_accuse_unknown_choice_is_wrong(client: TestClient) -> None:
    game_id = _start(client)

    response = client.post(
        f"/games/{game_id}/accuse",
        json={"suspect_id": "r1", **FULL_CHOICES, "method": "hammer"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["correct"] is False
    assert data["partial"] is True
    method = next(
        item for item in data["dimensions"] if item["id"] == "method"
    )
    assert method["choice"] == "hammer"
    assert method["correct"] is False


def test_http_accuse_rejects_empty_dimension_value(
    client: TestClient,
) -> None:
    game_id = _start(client)

    response = client.post(
        f"/games/{game_id}/accuse",
        json={"suspect_id": "r1", "motive": ""},
    )

    assert response.status_code == 422