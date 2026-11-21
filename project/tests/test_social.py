"""NPC 主动插话：纯函数、状态机与接口链路测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import MAX_SOCIAL_LINE_CHARS, SOCIAL_PRESS_PRESSURE
from app.engine.social import (
    SOCIAL_KINDS,
    SOCIAL_LINES,
    SocialEvent,
    build_event,
    resolve_event,
)
from app.game import GameStore, ask, resolve_event_choice
from app.main import create_app
from app.models import Role, Script
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

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        return self.reply


@pytest.fixture
def script() -> Script:
    data = load_script(SCRIPT_PATH)
    facts = {fact.id: fact for fact in data.facts}
    facts["f05"].sensitivity = 0.7
    return data


@pytest.fixture
def client_and_store(
    script: Script,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, GameStore]:
    monkeypatch.setenv("MOCK_LLM", "1")
    for name in ("MAAS_API_KEY", "MAAS_ENDPOINT", "MAAS_MODEL"):
        monkeypatch.delenv(name, raising=False)
    store = GameStore()
    return TestClient(create_app(script, store)), store


def _roles(script: Script) -> dict[str, Role]:
    return {role.id: role for role in script.roles}


def _start(client: TestClient) -> str:
    response = client.post("/games")
    assert response.status_code == 200
    return response.json()["game_id"]


def _ask_three(store: GameStore, game_id: str, offset: int = 0) -> None:
    questions = ("那晚你在哪", "你看见谁了", "账目对不对")
    for question in questions:
        outcome = ask(
            store,
            game_id,
            "r3",
            f"{question}（{offset}）",
            FakeLLM(),
        )
        assert outcome.ok is True


def test_templates_have_three_lines_and_fit_limit() -> None:
    for kind in SOCIAL_KINDS:
        lines = [
            line
            for line in SOCIAL_LINES
            if line.kind == kind and line.needs_target
        ]
        assert len(lines) >= 3
        for line in lines:
            text = line.template.format(
                speaker="沈玉兰",
                target="周砚青",
            )
            assert len(text) <= MAX_SOCIAL_LINE_CHARS
            assert "沈玉兰" in text


def test_every_role_can_speak(script: Script) -> None:
    for role in script.roles:
        event = build_event(
            script,
            {role.id: 1.0},
            None,
            [],
        )
        assert event is not None
        assert event.speaker_id == role.id


def test_speaker_excludes_current_npc(script: Script) -> None:
    event = build_event(
        script,
        {"r1": 1.0, "r2": 0.5},
        "r1",
        [],
    )

    assert event is not None
    assert event.speaker_id == "r2"
    assert event.target_id == "r1"
    assert event.target_name == "沈玉兰"


def test_target_falls_back_to_highest_trust(script: Script) -> None:
    event = build_event(script, {"r1": 1.0}, None, [])

    assert event is not None
    assert event.speaker_id == "r1"
    assert event.target_id == "r5"


def test_speaker_avoids_repeating_last_person(script: Script) -> None:
    first = build_event(script, {"r1": 1.0, "r2": 0.9}, None, [])
    assert first is not None
    second = build_event(script, {"r1": 1.0, "r2": 0.9}, None, [first])
    third = build_event(
        script,
        {"r1": 1.0, "r2": 0.9},
        None,
        [first, second] if second is not None else [first],
    )

    assert first.speaker_id == "r1"
    assert second is not None and second.speaker_id == "r2"
    assert third is not None and third.speaker_id == "r1"
    assert second.id == "evt-2"


def test_line_contains_speaker_name(script: Script) -> None:
    event = build_event(script, {"r5": 1.0}, None, [])

    assert event is not None
    assert event.speaker_name == "老韩"
    assert "老韩" in event.line


def test_resolve_event_press_and_dismiss(script: Script) -> None:
    event = build_event(script, {"r1": 1.0}, None, [])
    assert event is not None

    reply, delta = resolve_event(event, "press")
    assert reply
    assert delta == pytest.approx(SOCIAL_PRESS_PRESSURE)

    _, delta = resolve_event(event, "dismiss")
    assert delta == pytest.approx(-0.05)

    reply, delta = resolve_event(event, "unknown")
    assert reply == ""
    assert delta == 0.0


def test_third_action_creates_event(script: Script) -> None:
    store = GameStore()
    state = store.start(script)

    _ask_three(store, state.game_id)

    assert state.action_count == 3
    assert state.social_count == 1
    assert state.pending_event is not None
    assert state.pending_event.id == "evt-1"
    assert len(state.social_history) == 1


def test_pending_event_blocks_new_event(script: Script) -> None:
    store = GameStore()
    state = store.start(script)

    _ask_three(store, state.game_id)
    first = state.pending_event
    _ask_three(store, state.game_id, offset=1)

    assert state.action_count == 6
    assert state.social_count == 1
    assert state.pending_event is first
    assert len(state.social_history) == 1

    resolved = resolve_event_choice(store, state.game_id, "press")
    assert resolved.ok is True
    assert state.pending_event is None

    _ask_three(store, state.game_id, offset=2)
    assert state.action_count == 9
    assert state.social_count == 2
    assert state.pending_event is not None
    assert state.pending_event.id == "evt-2"
    assert first is not None
    assert state.pending_event.speaker_id != first.speaker_id


def test_social_cap_is_four(script: Script) -> None:
    store = GameStore()
    state = store.start(script)

    for round_index in range(5):
        _ask_three(store, state.game_id, offset=round_index)
        if state.pending_event is not None:
            assert resolve_event_choice(
                store,
                state.game_id,
                "dismiss",
            ).ok is True

    assert state.action_count == 15
    assert state.social_count == 4
    assert state.pending_event is None
    assert [event.id for event in state.social_history] == [
        "evt-1",
        "evt-2",
        "evt-3",
        "evt-4",
    ]


def test_dismiss_pressure_never_below_zero(script: Script) -> None:
    store = GameStore()
    state = store.start(script)
    _ask_three(store, state.game_id)
    event = state.pending_event
    assert event is not None
    assert state.pressure.get(event.speaker_id, 0.0) == 0.0

    outcome = resolve_event_choice(store, state.game_id, "dismiss")

    assert outcome.ok is True
    assert outcome.pressure[event.speaker_id] == 0.0


def test_no_pending_event_returns_409(
    client_and_store: tuple[TestClient, GameStore],
) -> None:
    client, _ = client_and_store
    game_id = _start(client)

    response = client.post(
        f"/games/{game_id}/event",
        json={"choice": "press"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "现在没有人主动开口"


def test_event_flow_through_testclient(
    client_and_store: tuple[TestClient, GameStore],
) -> None:
    client, store = client_and_store
    game_id = _start(client)

    for question in ("那晚你在哪", "你看见谁了", "账目对不对"):
        response = client.post(
            f"/games/{game_id}/ask",
            json={"npc_id": "r3", "question": question},
        )
        assert response.status_code == 200

    event_response = client.get(f"/games/{game_id}/event")
    assert event_response.status_code == 200
    event = event_response.json()["event"]
    assert event is not None
    assert event["id"] == "evt-1"
    assert event["kind"] in SOCIAL_KINDS
    assert len(event["line"]) <= MAX_SOCIAL_LINE_CHARS
    assert event["speaker"]["name"] in event["line"]
    assert [choice["id"] for choice in event["choices"]] == [
        "press",
        "dismiss",
    ]

    state = store.get(game_id)
    assert state is not None
    speaker_id = event["speaker"]["id"]
    before = state.pressure.get(speaker_id, 0.0)

    choice_response = client.post(
        f"/games/{game_id}/event",
        json={"choice": "press"},
    )
    assert choice_response.status_code == 200
    data = choice_response.json()
    assert data["reply"]
    assert data["event"] is None
    assert data["pressure"] == pytest.approx(
        {speaker_id: min(1.0, before + SOCIAL_PRESS_PRESSURE)}
    )

    assert client.get(f"/games/{game_id}/event").json()["event"] is None


def test_event_routes_error_mapping(
    client_and_store: tuple[TestClient, GameStore],
) -> None:
    client, _ = client_and_store

    assert client.get("/games/missing/event").status_code == 404
    assert (
        client.post(
            "/games/missing/event",
            json={"choice": "press"},
        ).status_code
        == 404
    )

    game_id = _start(client)
    invalid = client.post(
        f"/games/{game_id}/event",
        json={"choice": "shout"},
    )
    assert invalid.status_code == 422

    ended = client.post(
        f"/games/{game_id}/accuse",
        json={"suspect_id": "r1"},
    )
    assert ended.status_code == 200
    assert (
        client.post(
            f"/games/{game_id}/event",
            json={"choice": "press"},
        ).status_code
        == 409
    )
    assert client.get(f"/games/{game_id}/event").json()["event"] is None