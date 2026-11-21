"""阵营模式「电子血染」的状态机、模型兜底与接口测试。"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import blood, blood_ai
from app.blood import BloodPlayer, BloodState, BloodStore
from app.game import GameStore
from app.llm import LLMUnavailable
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
    """返回固定台词或抛出不可用异常的测试客户端。"""

    def __init__(self, text: str = "我觉得有人还没说真话。", error: bool = False) -> None:
        self.text = text
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """记录提示词并返回固定文本。"""
        self.calls.append((system_prompt, user_prompt))
        if self.error:
            raise LLMUnavailable("测试注入失败")
        return self.text


@pytest.fixture
def script() -> Script:
    return load_script(SCRIPT_PATH)


def _start(
    script: Script,
    seed: int = 0,
    llm: FakeLLM | None = None,
) -> tuple[BloodStore, BloodState, blood.ReplyFn]:
    store = BloodStore(rng=random.Random(seed))
    state = store.start(script)
    reply = blood_ai.make_reply_fn(llm or FakeLLM())
    return store, state, reply


def _set_murderer(state: BloodState, player_id: str) -> None:
    for player in state.players:
        player.role = "murderer" if player.id == player_id else "villager"
    state.murderer_id = player_id
    for player in state.players:
        if not player.is_you:
            player.suspicion = {
                other.id: 0.4
                for other in state.players
                if other.id != player.id
            }


def _force_votes(state: BloodState, mapping: dict[str, str]) -> None:
    for player in state.players:
        if player.is_you:
            continue
        player.suspicion = {}
    for voter_id, target_id in mapping.items():
        voter = next(p for p in state.players if p.id == voter_id)
        voter.suspicion[target_id] = 0.9


def _kill(state: BloodState, *player_ids: str) -> None:
    for player_id in player_ids:
        player = next(p for p in state.players if p.id == player_id)
        player.alive = False


@pytest.fixture
def api(
    script: Script,
) -> tuple[TestClient, BloodStore]:
    store = BloodStore(rng=random.Random(7))
    client = TestClient(
        create_app(script, GameStore(), blood_store=store, blood_llm=FakeLLM())
    )
    return client, store


def test_roster_and_one_murderer_per_game(script: Script) -> None:
    seen: set[str] = set()
    for seed in range(80):
        _, state, _ = _start(script, seed)
        assert [p.id for p in state.players] == [
            "p0",
            "p1",
            "p2",
            "p3",
            "p4",
            "p5",
        ]
        murderers = [p for p in state.players if p.role == "murderer"]
        assert len(murderers) == 1
        assert state.murderer_id == murderers[0].id
        seen.add(state.murderer_id)
    assert seen == {"p0", "p1", "p2", "p3", "p4", "p5"}


def test_you_murderer_ratio_is_one_in_six(script: Script) -> None:
    total = 600
    hits = sum(
        1
        for seed in range(total)
        if _start(script, seed)[1].murderer_id == blood.YOU_ID
    )
    assert 50 <= hits <= 150


def test_player_public_contract(script: Script) -> None:
    _, state, _ = _start(script, 1)
    players = {p.id: p for p in state.players}
    assert players["p0"].name == "你"
    assert players["p0"].public == "旅客"
    assert players["p0"].is_you is True
    assert players["p1"].name == "沈玉兰"
    assert players["p2"].name == "周砚青"
    assert players["p3"].name == "阿蘅"
    assert players["p4"].name == "陆明川"
    assert players["p5"].name == "老韩"
    assert all(p.alive for p in state.players)


def test_private_info_from_facts_without_secret(script: Script) -> None:
    secrets = "".join(role.secret for role in script.roles)
    for seed in range(30):
        _, state, _ = _start(script, seed)
        for player in state.players:
            assert 2 <= len(player.private_info) <= 3
            text = "".join(player.private_info)
            assert "secret" not in text
            assert "culprit" not in text
            assert text not in secrets


def test_suspicion_range_and_murderer_bias(script: Script) -> None:
    _, state, _ = _start(script, 1)
    murderer = next(p for p in state.players if p.role == "murderer")
    assert murderer.id == "p1"
    for other in state.players:
        if other.is_you or other.id == murderer.id:
            continue
        assert murderer.suspicion[other.id] >= 0.3
    for player in state.players:
        if player.is_you:
            continue
        for value in player.suspicion.values():
            assert 0.0 <= value <= 1.0


def test_discuss_makes_every_agent_speak(script: Script) -> None:
    store, state, reply = _start(script, 2)
    outcome = blood.discuss(store, state.game_id, reply)
    assert outcome.ok is True
    assert outcome.phase == "discussion"
    assert [r.speaker_id for r in outcome.replies] == [
        "p1",
        "p2",
        "p3",
        "p4",
        "p5",
    ]
    assert len(state.public_log) == 1 + 5
    assert state.log[-1]["type"] == "discuss"


def test_discuss_only_once_per_day(script: Script) -> None:
    store, state, reply = _start(script, 2)
    assert blood.discuss(store, state.game_id, reply).ok is True
    second = blood.discuss(store, state.game_id, reply)
    assert second.ok is False
    assert second.error == "discuss_used"


def test_speak_triggers_agents_in_rotation(script: Script) -> None:
    store, state, reply = _start(script, 2)
    first = blood.speak(store, state.game_id, "我在走廊里听见了响动。", reply)
    second = blood.speak(store, state.game_id, "谁都不许回房。", reply)
    assert [r.speaker_id for r in first.replies] == ["p1"]
    assert [r.speaker_id for r in second.replies] == ["p2"]
    assert state.speak_count == 2
    assert state.public_log[-2].speaker_id == "p0"


def test_speak_limit_three_per_day(script: Script) -> None:
    store, state, reply = _start(script, 2)
    for index in range(3):
        assert blood.speak(
            store, state.game_id, f"第{index}句。", reply
        ).ok is True
    blocked = blood.speak(store, state.game_id, "还有一句。", reply)
    assert blocked.ok is False
    assert blocked.error == "speak_limit"


def test_public_mention_raises_suspicion(script: Script) -> None:
    llm = FakeLLM(text="我觉得沈玉兰很可疑。")
    store, state, reply = _start(script, 3, llm)
    watcher = next(p for p in state.players if p.id == "p2")
    before = watcher.suspicion["p1"]
    blood.discuss(store, state.game_id, reply)
    assert watcher.suspicion["p1"] > before


def test_nominate_tie_leaves_nobody_executed(script: Script) -> None:
    store, state, _ = _start(script, 3)
    _set_murderer(state, "p2")
    _force_votes(
        state,
        {
            "p1": "p2",
            "p2": "p1",
            "p3": "p1",
            "p4": "p2",
            "p5": "p2",
        },
    )
    outcome = blood.nominate(store, state.game_id, "p1")
    assert outcome.ok is True
    assert outcome.executed is None
    assert outcome.tally == {"p1": 3, "p2": 3}
    assert outcome.phase == "night"
    assert all(p.alive for p in state.players)


def test_nominate_plurality_executes(script: Script) -> None:
    store, state, _ = _start(script, 3)
    _set_murderer(state, "p2")
    _force_votes(
        state,
        {
            "p1": "p3",
            "p2": "p3",
            "p3": "p1",
            "p4": "p3",
            "p5": "p3",
        },
    )
    outcome = blood.nominate(store, state.game_id, "p3")
    assert outcome.ok is True
    assert outcome.executed is not None
    assert outcome.executed.id == "p3"
    assert outcome.tally["p3"] == 5
    assert outcome.phase == "night"


def test_executing_murderer_gives_good_win(script: Script) -> None:
    store, state, _ = _start(script, 4)
    _set_murderer(state, "p3")
    _force_votes(
        state,
        {
            "p1": "p3",
            "p2": "p3",
            "p3": "p1",
            "p4": "p3",
            "p5": "p3",
        },
    )
    outcome = blood.nominate(store, state.game_id, "p3")
    assert outcome.ok is True
    assert outcome.executed is not None
    assert outcome.executed.id == "p3"
    assert outcome.winner == "good"
    assert outcome.phase == "ended"


def test_night_requires_target_when_you_are_murderer(script: Script) -> None:
    store, state, _ = _start(script, 5)
    _set_murderer(state, "p0")
    _force_votes(
        state,
        {
            "p1": "p2",
            "p2": "p1",
            "p3": "p1",
            "p4": "p1",
            "p5": "p1",
        },
    )
    assert blood.nominate(store, state.game_id, "p1").phase == "night"
    outcome = blood.night(store, state.game_id, None)
    assert outcome.ok is False
    assert outcome.error == "night_target_required"


def test_night_kills_target_and_advances_day(script: Script) -> None:
    store, state, _ = _start(script, 5)
    _set_murderer(state, "p0")
    _force_votes(
        state,
        {
            "p1": "p2",
            "p2": "p1",
            "p3": "p1",
            "p4": "p1",
            "p5": "p1",
        },
    )
    assert blood.nominate(store, state.game_id, "p1").phase == "night"
    outcome = blood.night(store, state.game_id, "p2")
    assert outcome.ok is True
    assert outcome.killed is not None
    assert outcome.killed.id == "p2"
    assert outcome.day == 2
    assert outcome.phase == "discussion"
    assert outcome.winner is None


def test_night_system_picks_victim_when_you_are_good(script: Script) -> None:
    store, state, _ = _start(script, 6)
    _set_murderer(state, "p3")
    _force_votes(
        state,
        {
            "p1": "p2",
            "p2": "p1",
            "p3": "p2",
            "p4": "p1",
            "p5": "p1",
        },
    )
    assert blood.nominate(store, state.game_id, "p1").phase == "night"
    killer = next(p for p in state.players if p.id == "p3")
    killer.suspicion = {"p5": 0.9, "p0": 0.1}
    outcome = blood.night(store, state.game_id, None)
    assert outcome.ok is True
    assert outcome.killed is not None
    assert outcome.killed.id == "p5"
    assert outcome.phase == "discussion"


def test_two_alive_murderer_wins(script: Script) -> None:
    store, state, _ = _start(script, 7)
    _set_murderer(state, "p5")
    _kill(state, "p1", "p2", "p3", "p4")
    outcome = blood.nominate(store, state.game_id, "p5")
    assert outcome.ok is True
    assert outcome.executed is None
    assert outcome.winner == "murderer"
    assert outcome.phase == "ended"


def test_all_good_dead_murderer_wins(script: Script) -> None:
    store, state, _ = _start(script, 8)
    _set_murderer(state, "p5")
    _kill(state, "p1", "p2", "p3", "p4")
    state.phase = "night"
    outcome = blood.night(store, state.game_id, None)
    assert outcome.ok is True
    assert outcome.killed is not None
    assert outcome.killed.id == "p0"
    assert outcome.winner == "murderer"
    assert outcome.phase == "ended"


def test_you_dead_becomes_spectator(script: Script) -> None:
    store, state, reply = _start(script, 9)
    _set_murderer(state, "p2")
    _force_votes(
        state,
        {
            "p1": "p0",
            "p2": "p0",
            "p3": "p0",
            "p4": "p0",
            "p5": "p0",
        },
    )
    outcome = blood.nominate(store, state.game_id, "p1")
    assert outcome.ok is True
    assert outcome.executed is not None
    assert outcome.executed.id == "p0"
    assert outcome.phase == "ended"
    assert outcome.winner in {"good", "murderer"}
    assert blood.speak(store, state.game_id, "我还想说。", reply).error in {
        "you_are_dead",
        "game_ended",
    }
    assert blood.night(store, state.game_id, None).error in {
        "you_are_dead",
        "game_ended",
    }
    assert blood.build_view(state).you.id == "p0"


def test_log_has_no_secret_or_culprit_fields(script: Script) -> None:
    store, state, reply = _start(script, 10)
    blood.discuss(store, state.game_id, reply)
    blood.speak(store, state.game_id, "走廊里到底有几个人？", reply)
    alive_agents = [p.id for p in state.players if p.alive and not p.is_you]
    blood.nominate(store, state.game_id, alive_agents[0])
    if state.phase == "night":
        target = next(p.id for p in state.players if p.alive and not p.is_you)
        blood.night(store, state.game_id, target)
    payload = json.dumps(blood.build_log(state), ensure_ascii=False)
    assert '"secret"' not in payload
    assert '"culprit"' not in payload
    assert '"is_lie"' not in payload
    assert "murderer_id" not in payload
    public = json.dumps(
        [entry.text for entry in state.public_log],
        ensure_ascii=False,
    )
    for role in script.roles:
        assert role.secret not in public


def test_ai_fallback_on_llm_failure(script: Script) -> None:
    store, state, _ = _start(script, 11, FakeLLM(error=True))
    reply = blood_ai.make_reply_fn(FakeLLM(error=True))
    outcome = blood.discuss(store, state.game_id, reply)
    assert outcome.ok is True
    assert len(outcome.replies) == 5
    for item in outcome.replies:
        assert item.text
        assert "我是凶手" not in item.text


def test_ai_rejects_self_claim(script: Script) -> None:
    assert blood_ai.clean_line("我是凶手，别怀疑我。") == ""
    assert blood_ai.clean_line("我是好人，相信我。") == ""
    _, state, _ = _start(script, 11)
    reply = blood_ai.make_reply_fn(FakeLLM(text="我是凶手，别怀疑我。"))
    text = reply(state, state.players[1])
    assert text
    assert "我是凶手" not in text


def test_prompt_contains_identity_and_rule(script: Script) -> None:
    _, state, _ = _start(script, 12)
    player = next(p for p in state.players if p.id == "p2")
    system, user = blood_ai.build_prompt(player, state)
    assert player.name in user
    assert "公开身份" in user
    assert "不能" in system
    assert "凶手" in system


def test_api_state_and_error_codes(api: tuple[TestClient, BloodStore]) -> None:
    client, store = api
    response = client.post("/blood/games")
    assert response.status_code == 200
    body = response.json()
    assert body["phase"] == "discussion"
    assert len(body["players"]) == 6
    assert set(body["you"]) == {"id", "name", "role", "private_info", "teammates"}
    assert body["you"]["role"] in {"villager", "murderer"}
    game_id = body["game_id"]

    assert client.post("/blood/games/nope/discuss").status_code == 404
    assert client.get("/blood/games/nope").status_code == 404
    assert (
        client.post(
            f"/blood/games/{game_id}/nominate",
            json={"target_id": "p9"},
        ).status_code
        == 404
    )
    assert (
        client.post(f"/blood/games/{game_id}/speak", json={"text": ""}).status_code
        == 422
    )
    assert (
        client.post(
            f"/blood/games/{game_id}/nominate",
            json={"target_id": ""},
        ).status_code
        == 422
    )
    assert client.post(f"/blood/games/{game_id}/discuss").status_code == 200
    assert client.post(f"/blood/games/{game_id}/discuss").status_code == 409

    state = store.get(game_id)
    assert state is not None
    state.phase = "night"
    assert client.post(f"/blood/games/{game_id}/night", json={}).status_code in {
        200,
        409,
        422,
    }
    response = client.get(f"/blood/games/{game_id}/log")
    assert response.status_code == 200
    assert response.json()["game_id"] == game_id


def test_api_you_dead_only_spectates(api: tuple[TestClient, BloodStore]) -> None:
    client, store = api
    game_id = client.post("/blood/games").json()["game_id"]
    state = store.get(game_id)
    assert state is not None
    state.players[0].alive = False
    assert client.post(f"/blood/games/{game_id}/speak", json={"text": "喂"}).status_code == 409
    assert (
        client.post(
            f"/blood/games/{game_id}/nominate",
            json={"target_id": "p1"},
        ).status_code
        == 409
    )
    response = client.get(f"/blood/games/{game_id}")
    assert response.status_code == 200
    assert response.json()["players"][0]["alive"] is False
    assert response.json()["dead"][0]["id"] == "p0"


def test_full_flow_with_testclient(api: tuple[TestClient, BloodStore]) -> None:
    client, store = api
    body = client.post("/blood/games").json()
    game_id = body["game_id"]
    phases = [body["phase"]]

    discussed = client.post(f"/blood/games/{game_id}/discuss")
    assert discussed.status_code == 200
    phases.append(discussed.json()["phase"])

    spoke = client.post(
        f"/blood/games/{game_id}/speak",
        json={"text": "昨晚谁上过二楼？"},
    )
    assert spoke.status_code == 200
    assert len(spoke.json()["replies"]) == 1
    phases.append(spoke.json()["phase"])

    state = store.get(game_id)
    assert state is not None
    target = next(p.id for p in state.players if p.alive and not p.is_you)
    nominated = client.post(
        f"/blood/games/{game_id}/nominate",
        json={"target_id": target},
    )
    assert nominated.status_code == 200
    phases.append(nominated.json()["phase"])

    if phases[-1] == "night":
        state = store.get(game_id)
        assert state is not None
        night_target = next(
            p.id
            for p in state.players
            if p.alive and not p.is_you and p.role != "murderer"
        )
        night = client.post(
            f"/blood/games/{game_id}/night",
            json={"target_id": night_target},
        )
        assert night.status_code == 200
        phases.append(night.json()["phase"])

    print("阶段序列：", " -> ".join(phases))
    assert phases[-1] in {"discussion", "ended"}
    assert client.get(f"/blood/games/{game_id}/log").status_code == 200