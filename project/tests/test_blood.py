"""阵营模式「电子血染」的状态机、自辩/投票、模型兜底与接口测试。"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import blood, blood_ai
from app.blood import BloodPlayer, BloodState, BloodStore

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


def _enter_defense(
    store: BloodStore,
    state: BloodState,
    reply: blood.ReplyFn,
    target_id: str,
) -> blood.DefenseOutcome:
    outcome = blood.nominate(store, state.game_id, target_id, reply)
    assert outcome.ok is True
    assert outcome.phase == "defense"
    return outcome


@pytest.fixture
def api(
    script: Script,
) -> tuple[TestClient, BloodStore]:
    store = BloodStore(rng=random.Random(7))
    client = TestClient(
        create_app(script, blood_store=store, blood_llm=FakeLLM())
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
    assert players["p0"].name == "旅客"
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
            if player.is_you and player.role == "villager":
                assert any(
                    keyword in text for keyword in blood.YOU_WITNESS_KEYWORDS
                )


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


def test_discuss_releases_one_private_fact_per_agent(script: Script) -> None:
    """每天讨论最多公开 1 条私有信息，直到用完为止。"""
    store, state, reply = _start(script, 2)
    blood.discuss(store, state.game_id, reply)
    for agent in state.players:
        if agent.is_you:
            continue
        assert agent.released_today == 1
        assert len(agent.released) == 1
    released = [
        entry
        for entry in state.log
        if entry["type"] == "release" and entry["speaker"] == "p3"
    ]
    assert len(released) == 1


def test_accused_agent_may_release_second_fact(script: Script) -> None:
    """被点名时可再公开 1 条，但每天合计不超过 2 条。"""
    store, state, reply = _start(script, 2)
    blood.discuss(store, state.game_id, reply)
    p3 = next(p for p in state.players if p.id == "p3")
    assert len(p3.private_info) >= 2
    outcome = blood.speak(
        store, state.game_id, "阿蘅，你昨晚在哪？", reply
    )
    assert outcome.replies[0].speaker_id == "p3"
    assert p3.released_today == 2
    assert len(p3.released) == 2
    again = blood.speak(store, state.game_id, "阿蘅，再说一遍。", reply)
    assert again.ok is True
    assert p3.released_today == 2


def test_release_quota_resets_next_day(script: Script) -> None:
    store, state, reply = _start(script, 2)
    _set_murderer(state, "p5")
    blood.discuss(store, state.game_id, reply)
    assert blood.speak(store, state.game_id, "阿蘅，你答我。", reply).ok is True
    p3 = next(p for p in state.players if p.id == "p3")
    assert p3.released_today == 2
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
    _enter_defense(store, state, reply, "p1")
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
    voted = blood.vote(store, state.game_id, "p2", reply)
    assert voted.phase == "night"
    killer = next(p for p in state.players if p.id == "p5")
    killer.suspicion = {"p4": 0.9}
    night = blood.night(store, state.game_id, None)
    assert night.phase == "discussion"
    assert night.killed is not None and night.killed.id == "p4"
    blood.discuss(store, state.game_id, reply)
    assert p3.released_day == 2
    assert p3.released_today == 1
    assert len(p3.released) == 3


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


def test_nominate_enters_defense_without_execution(script: Script) -> None:
    """提名只生成自辩并进入 defense，不当场处决任何人。"""
    store, state, reply = _start(script, 3)
    _set_murderer(state, "p2")
    outcome = _enter_defense(store, state, reply, "p1")
    assert outcome.target is not None and outcome.target.id == "p1"
    assert outcome.defense is not None
    assert outcome.defense.speaker_id == "p1"
    assert outcome.defense.text
    assert state.phase == "defense"
    assert state.nominee_id == "p1"
    assert all(player.alive for player in state.players)


def test_nominate_only_once_per_day(script: Script) -> None:
    store, state, reply = _start(script, 3)
    _enter_defense(store, state, reply, "p1")
    again = blood.nominate(store, state.game_id, "p2", reply)
    assert again.ok is False
    assert again.error == "nominate_used"


def test_nominate_allowed_again_next_day(script: Script) -> None:
    """每天的提名额度在进入下一天后恢复。"""
    store, state, reply = _start(script, 3)
    _set_murderer(state, "p4")
    _enter_defense(store, state, reply, "p1")
    _force_votes(
        state,
        {
            "p1": "p2",
            "p2": "p1",
            "p3": "p2",
            "p4": "p1",
            "p5": "p2",
        },
    )
    first = blood.vote(store, state.game_id, "p1", reply)
    assert first.phase == "runoff"
    assert {item.id for item in first.runoff_candidates} == {"p1", "p2"}
    second = blood.vote(store, state.game_id, "p1", reply)
    assert second.phase == "night"
    assert second.executed is None
    killer = next(p for p in state.players if p.id == "p4")
    killer.suspicion = {"p2": 0.9}
    assert blood.night(store, state.game_id, None).phase == "discussion"
    assert state.nominated is False
    outcome = blood.nominate(store, state.game_id, "p5", reply)
    assert outcome.ok is True
    assert outcome.phase == "defense"


def test_defense_speak_prefers_named_then_nominee(script: Script) -> None:
    """质证时被点名者优先；没人被点名时由被提名者回应。"""
    store, state, reply = _start(script, 3)
    _enter_defense(store, state, reply, "p1")
    named = blood.speak(store, state.game_id, "老韩，你也说两句。", reply)
    assert named.replies[0].speaker_id == "p5"
    assert named.phase == "defense"
    nominee = blood.speak(store, state.game_id, "你还有什么话说？", reply)
    assert nominee.replies[0].speaker_id == "p1"


def test_defense_speak_limit_two_per_day(script: Script) -> None:
    store, state, reply = _start(script, 3)
    _enter_defense(store, state, reply, "p1")
    assert blood.speak(store, state.game_id, "第一问。", reply).ok is True
    assert blood.speak(store, state.game_id, "第二问。", reply).ok is True
    blocked = blood.speak(store, state.game_id, "第三问。", reply)
    assert blocked.ok is False
    assert blocked.error == "defense_speak_limit"


def test_vote_below_threshold_executes_nobody(script: Script) -> None:
    """6 人局门槛为 4 票，唯一最高只有 2 票时无人出局。"""
    store, state, reply = _start(script, 3)
    _set_murderer(state, "p2")
    _enter_defense(store, state, reply, "p1")
    _force_votes(
        state,
        {
            "p1": "p2",
            "p2": "p3",
            "p3": "p2",
            "p4": "p1",
            "p5": "p4",
        },
    )
    outcome = blood.vote(store, state.game_id, "p5", reply)
    assert outcome.ok is True
    assert outcome.threshold == 4
    assert outcome.tally == {"p2": 2, "p3": 1, "p1": 1, "p4": 1, "p5": 1}
    assert outcome.executed is None
    assert outcome.phase == "night"
    assert all(player.alive for player in state.players)


def test_vote_four_of_six_executes(script: Script) -> None:
    """6 人局 4 票正好达到严格过半，可以处决。"""
    store, state, reply = _start(script, 3)
    _set_murderer(state, "p2")
    _enter_defense(store, state, reply, "p1")
    _force_votes(
        state,
        {
            "p1": "p2",
            "p2": "p1",
            "p3": "p1",
            "p4": "p2",
            "p5": "p1",
        },
    )
    outcome = blood.vote(store, state.game_id, "p1", reply)
    assert outcome.threshold == 4
    assert outcome.tally["p1"] == 4
    assert outcome.executed is not None
    assert outcome.executed.id == "p1"
    assert outcome.phase == "night"


def test_threshold_is_strict_majority_of_alive(script: Script) -> None:
    """存活 5 人门槛 3、4 人门槛 3、3 人门槛 2。"""
    assert blood._vote_threshold(6, 0) == 4
    assert blood._vote_threshold(5, 0) == 3
    assert blood._vote_threshold(4, 0) == 3
    assert blood._vote_threshold(3, 0) == 2
    assert blood._vote_threshold(2, 0) == 2

    store, state, reply = _start(script, 3)
    _set_murderer(state, "p2")
    _kill(state, "p4")
    _enter_defense(store, state, reply, "p1")
    _force_votes(state, {"p1": "p2", "p2": "p1", "p3": "p2", "p5": "p2"})
    five = blood.vote(store, state.game_id, "p2", reply)
    assert five.threshold == 3

    store2, state2, reply2 = _start(script, 3)
    _set_murderer(state2, "p2")
    _kill(state2, "p4", "p5")
    _enter_defense(store2, state2, reply2, "p1")
    _force_votes(state2, {"p1": "p2", "p2": "p1", "p3": "p2"})
    four = blood.vote(store2, state2.game_id, "p2", reply2)
    assert four.threshold == 3


def test_vote_strict_majority_executes(script: Script) -> None:
    store, state, reply = _start(script, 3)
    _set_murderer(state, "p2")
    _enter_defense(store, state, reply, "p1")
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
    outcome = blood.vote(store, state.game_id, "p3", reply)
    assert outcome.ok is True
    assert outcome.threshold == 4
    assert outcome.tally["p3"] == 5
    assert outcome.executed is not None
    assert outcome.executed.id == "p3"
    assert outcome.phase == "night"


def test_vote_tie_executes_nobody(script: Script) -> None:
    """3:3 平票先进入重投；重投仍平票时无人被处决。"""
    store, state, reply = _start(script, 3)
    _set_murderer(state, "p2")
    _enter_defense(store, state, reply, "p1")
    _force_votes(
        state,
        {
            "p1": "p2",
            "p2": "p1",
            "p3": "p2",
            "p4": "p1",
            "p5": "p2",
        },
    )
    outcome = blood.vote(store, state.game_id, "p1", reply)
    assert outcome.tally == {"p1": 3, "p2": 3}
    assert outcome.executed is None
    assert outcome.phase == "runoff"
    assert {item.id for item in outcome.runoff_candidates} == {"p1", "p2"}

    again = blood.vote(store, state.game_id, "p1", reply)
    assert again.executed is None
    assert again.phase == "night"
    assert again.stalemate_count == 1
    assert all(player.alive for player in state.players)


def test_you_can_vote_against_the_nominee(script: Script) -> None:
    """真人投票目标可以与提名目标不同。"""
    store, state, reply = _start(script, 3)
    _set_murderer(state, "p4")
    _enter_defense(store, state, reply, "p1")
    _force_votes(
        state,
        {
            "p1": "p2",
            "p2": "p2",
            "p3": "p2",
            "p4": "p2",
            "p5": "p2",
        },
    )
    outcome = blood.vote(store, state.game_id, "p2", reply)
    you_vote = next(vote for vote in outcome.votes if vote.voter_id == "p0")
    assert you_vote.target_id == "p2"
    assert state.nominee_id == "p1"
    assert outcome.executed is not None
    assert outcome.executed.id == "p2"


def test_agent_votes_carry_public_reason(script: Script) -> None:
    store, state, reply = _start(script, 3)
    _set_murderer(state, "p2")
    _enter_defense(store, state, reply, "p1")
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
    outcome = blood.vote(store, state.game_id, "p1", reply)
    assert len(outcome.votes) == 6
    for vote in outcome.votes:
        if vote.voter_id == "p0":
            assert vote.reason == ""
        else:
            assert vote.reason
            assert len(vote.reason) <= blood.BLOOD_VOTE_REASON_MAX_CHARS


def test_agent_reason_matches_actual_target(script: Script) -> None:
    """agent 理由提到 target 以外的人名时，改写成围绕 target 的模板句。"""
    llm = FakeLLM(text="我投阿蘅，她最可疑。")
    store, state, reply = _start(script, 3, llm)
    _set_murderer(state, "p2")
    _enter_defense(store, state, reply, "p1")
    _force_votes(
        state,
        {
            "p1": "p2",
            "p2": "p1",
            "p3": "p2",
            "p4": "p2",
            "p5": "p2",
        },
    )
    outcome = blood.vote(store, state.game_id, "p2", reply)
    names = {player.id: player.name for player in state.players}
    for vote in outcome.votes:
        if vote.voter_id == "p0":
            continue
        for player_id, name in names.items():
            if player_id != vote.target_id:
                assert name not in vote.reason
    rewritten = [
        vote
        for vote in outcome.votes
        if vote.voter_id == "p1"
    ]
    assert rewritten[0].target_id == "p2"
    assert "周砚青" in rewritten[0].reason
    assert "阿蘅" not in rewritten[0].reason


def test_agent_reason_without_target_name_uses_fallback(script: Script) -> None:
    """理由不含 target 姓名时改写成带 target 的兜底句，避免空泛指代。"""
    llm = FakeLLM(text="他刚才的话前后对不上。")
    store, state, reply = _start(script, 3, llm)
    _set_murderer(state, "p2")
    _enter_defense(store, state, reply, "p1")
    _force_votes(
        state,
        {
            "p1": "p2",
            "p2": "p1",
            "p3": "p2",
            "p4": "p2",
            "p5": "p2",
        },
    )
    outcome = blood.vote(store, state.game_id, "p2", reply)
    p1_vote = next(vote for vote in outcome.votes if vote.voter_id == "p1")
    assert "周砚青" in p1_vote.reason
    assert p1_vote.reason.endswith(("。", "！", "？", "…"))
    for term in blood.VOTE_REASON_PLACEHOLDERS:
        assert term not in p1_vote.reason


def test_speak_names_two_agents_in_order(script: Script) -> None:
    """点名两人时按出现顺序各回一条，未被点名的 agent 不抢答。"""
    store, state, reply = _start(script, 3)
    _enter_defense(store, state, reply, "p1")
    outcome = blood.speak(
        store,
        state.game_id,
        "阿蘅和老韩，你们各自说清楚。",
        reply,
    )
    assert [item.speaker_id for item in outcome.replies] == ["p3", "p5"]
    assert outcome.phase == "defense"


def test_speak_names_single_agent_only(script: Script) -> None:
    """只点一个人时只由该人回应。"""
    store, state, reply = _start(script, 3)
    _enter_defense(store, state, reply, "p1")
    outcome = blood.speak(store, state.game_id, "阿蘅，你说。", reply)
    assert [item.speaker_id for item in outcome.replies] == ["p3"]


def test_speak_without_name_returns_nominee(script: Script) -> None:
    """质证未点名时由被提名者回应。"""
    store, state, reply = _start(script, 3)
    _enter_defense(store, state, reply, "p1")
    outcome = blood.speak(store, state.game_id, "你还有什么话说？", reply)
    assert [item.speaker_id for item in outcome.replies] == ["p1"]


def test_private_info_never_states_secret_identity(script: Script) -> None:
    """私有信息与公开讨论都不得直接点破私生女、记者等秘密身份。"""
    for seed in range(20):
        _, state, _ = _start(script, seed)
        for player in state.players:
            for text in player.private_info:
                assert "私生女" not in text
                assert "记者" not in text
    store, state, reply = _start(script, 2)
    blood.discuss(store, state.game_id, reply)
    public = "".join(entry.text for entry in state.public_log)
    assert "私生女" not in public
    assert "记者" not in public


def test_prompt_forbids_secret_and_hearsay(script: Script) -> None:
    """提示词约束只说亲历片段，并禁止公开秘密身份。"""
    _, state, _ = _start(script, 12)
    player = next(p for p in state.players if p.id == "p2")
    system, _ = blood_ai.build_prompt(player, state)
    assert "转述" in system
    assert "亲历" in system
    assert "私生女" in system
    assert "记者" in system


def test_you_vote_reason_enters_response_and_log(
    api: tuple[TestClient, BloodStore],
) -> None:
    """真人投票理由进入逐票响应与回看日志。"""
    client, store = api
    game_id = client.post("/blood/games").json()["game_id"]
    client.post(f"/blood/games/{game_id}/nominate", json={"target_id": "p1"})
    reason = "我投沈玉兰，她那晚最可疑。"
    response = client.post(
        f"/blood/games/{game_id}/vote",
        json={"target_id": "p1", "reason": reason},
    )
    assert response.status_code == 200
    body = response.json()
    you_vote = next(vote for vote in body["votes"] if vote["voter_id"] == "p0")
    assert you_vote["reason"] == reason
    entries = client.get(f"/blood/games/{game_id}/log").json()["entries"]
    logged = [
        vote
        for entry in entries
        if entry["type"] == "vote"
        for vote in entry["votes"]
    ]
    assert any(vote["voter_id"] == "p0" and vote["reason"] == reason for vote in logged)


def test_you_vote_reason_is_optional(api: tuple[TestClient, BloodStore]) -> None:
    """缺省 reason 时真人票理由为空串。"""
    client, store = api
    game_id = client.post("/blood/games").json()["game_id"]
    client.post(f"/blood/games/{game_id}/nominate", json={"target_id": "p1"})
    body = client.post(
        f"/blood/games/{game_id}/vote",
        json={"target_id": "p1"},
    ).json()
    you_vote = next(vote for vote in body["votes"] if vote["voter_id"] == "p0")
    assert you_vote["reason"] == ""


def test_executing_murderer_gives_good_win(script: Script) -> None:
    store, state, reply = _start(script, 4)
    _set_murderer(state, "p3")
    _enter_defense(store, state, reply, "p3")
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
    outcome = blood.vote(store, state.game_id, "p3", reply)
    assert outcome.ok is True
    assert outcome.executed is not None
    assert outcome.executed.id == "p3"
    assert outcome.winner == "good"
    assert outcome.phase == "ended"


def test_good_executed_with_six_to_five_does_not_end(script: Script) -> None:
    """好人被处决后 6→5 人，未达凶手胜利条件，继续入夜。"""
    store, state, reply = _start(script, 5)
    _set_murderer(state, "p5")
    _enter_defense(store, state, reply, "p1")
    _force_votes(
        state,
        {
            "p1": "p2",
            "p2": "p2",
            "p3": "p2",
            "p4": "p2",
            "p5": "p2",
        },
    )
    outcome = blood.vote(store, state.game_id, "p2", reply)
    assert outcome.executed is not None
    assert outcome.executed.id == "p2"
    assert outcome.winner is None
    assert outcome.phase == "night"
    assert sum(1 for p in state.players if p.alive) == 5


def test_night_after_five_to_four_does_not_end(script: Script) -> None:
    """夜晚后 5→4 人仍不结束，回到第 2 天讨论。"""
    store, state, reply = _start(script, 6)
    _set_murderer(state, "p5")
    _enter_defense(store, state, reply, "p1")
    _force_votes(
        state,
        {
            "p1": "p2",
            "p2": "p2",
            "p3": "p2",
            "p4": "p2",
            "p5": "p2",
        },
    )
    assert blood.vote(store, state.game_id, "p2", reply).phase == "night"
    killer = next(p for p in state.players if p.id == "p5")
    killer.suspicion = {"p3": 0.9}
    outcome = blood.night(store, state.game_id, None)
    assert outcome.ok is True
    assert outcome.killed is not None and outcome.killed.id == "p3"
    assert outcome.winner is None
    assert outcome.phase == "discussion"
    assert outcome.day == 2
    assert sum(1 for p in state.players if p.alive) == 4


def test_night_requires_target_when_you_are_murderer(script: Script) -> None:
    store, state, reply = _start(script, 5)
    _set_murderer(state, "p0")
    _enter_defense(store, state, reply, "p1")
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
    assert blood.vote(store, state.game_id, "p1", reply).phase == "night"
    outcome = blood.night(store, state.game_id, None)
    assert outcome.ok is False
    assert outcome.error == "night_target_required"


def test_night_kills_target_and_advances_day(script: Script) -> None:
    store, state, reply = _start(script, 5)
    _set_murderer(state, "p0")
    _enter_defense(store, state, reply, "p1")
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
    assert blood.vote(store, state.game_id, "p1", reply).phase == "night"
    outcome = blood.night(store, state.game_id, "p2")
    assert outcome.ok is True
    assert outcome.killed is not None
    assert outcome.killed.id == "p2"
    assert outcome.day == 2
    assert outcome.phase == "discussion"
    assert outcome.winner is None


def test_night_system_picks_victim_when_you_are_good(script: Script) -> None:
    store, state, reply = _start(script, 6)
    _set_murderer(state, "p3")
    _enter_defense(store, state, reply, "p1")
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
    assert blood.vote(store, state.game_id, "p1", reply).phase == "night"
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
    state.phase = "night"
    killer = next(p for p in state.players if p.id == "p5")
    killer.suspicion = {"p0": 0.9}
    outcome = blood.night(store, state.game_id, None)
    assert outcome.winner == "murderer"
    assert outcome.phase == "ended"


def test_all_good_dead_murderer_wins(script: Script) -> None:
    store, state, _ = _start(script, 8)
    _set_murderer(state, "p5")
    _kill(state, "p1", "p2", "p3", "p4")
    state.phase = "night"
    killer = next(p for p in state.players if p.id == "p5")
    killer.suspicion = {"p0": 0.9}
    outcome = blood.night(store, state.game_id, None)
    assert outcome.ok is True
    assert outcome.killed is not None
    assert outcome.killed.id == "p0"
    assert outcome.winner == "murderer"
    assert outcome.phase == "ended"


def test_you_executed_enters_spectating_then_advance_to_winner(
    script: Script,
) -> None:
    """真人被处决后进入观战，advance 跑完夜杀与下一天，亡者票只能用一次。"""
    store, state, reply = _start(script, 9)
    _set_murderer(state, "p2")
    _enter_defense(store, state, reply, "p1")
    _force_votes(
        state,
        {
            "p1": "p0",
            "p2": "p0",
            "p3": "p0",
            "p4": "p0",
            "p5": "p1",
        },
    )
    outcome = blood.vote(store, state.game_id, "p1", reply)
    assert outcome.ok is True
    assert outcome.executed is not None
    assert outcome.executed.id == "p0"
    assert outcome.phase == "spectating"
    assert outcome.winner is None
    view = blood.build_view(state)
    assert view.phase == "spectating"
    assert view.you_alive is False
    assert view.ghost_vote_available is False
    assert blood.speak(store, state.game_id, "我还想说。", reply).error == (
        "you_are_dead"
    )
    assert blood.night(store, state.game_id, None).error == "you_are_dead"
    assert blood.inspect(store, state.game_id, "p2").error == "you_are_dead"

    killer = next(player for player in state.players if player.id == "p2")
    killer.suspicion = {"p3": 0.9}
    stepped = blood.advance(store, state.game_id)
    assert stepped.ok is True
    assert stepped.phase == "defense"
    assert stepped.day == 2
    assert stepped.killed is not None
    assert stepped.ghost_vote_available is True

    ghosted = blood.vote(store, state.game_id, "p1", reply, ghost=True)
    assert ghosted.ok is True
    assert state.ghost_vote_used is True
    state.phase = "defense"
    again = blood.vote(store, state.game_id, "p1", reply, ghost=True)
    assert again.ok is False
    assert again.error == "ghost_vote_used"

    guard = 0
    while state.phase != "ended" and guard < 12:
        blood.advance(store, state.game_id)
        guard += 1
    final = blood.build_view(state)
    assert final.phase == "ended"
    assert final.winner in {"good", "murderer"}
    assert final.winner is not None


def test_you_killed_at_night_enters_spectating(script: Script) -> None:
    """真人被夜杀后进入观战，day 推进，尚不结算胜负。"""
    store, state, reply = _start(script, 10)
    _set_murderer(state, "p4")
    state.phase = "night"
    killer = next(p for p in state.players if p.id == "p4")
    killer.suspicion = {"p0": 0.9}
    outcome = blood.night(store, state.game_id, None)
    assert outcome.ok is True
    assert outcome.killed is not None and outcome.killed.id == "p0"
    assert outcome.phase == "spectating"
    assert outcome.winner is None
    assert outcome.day == 2
    view = blood.build_view(state)
    assert view.you_alive is False
    assert view.reveal is None
    assert view.ghost_vote_available is False


def test_aftermath_after_you_executed_is_day_by_day(script: Script) -> None:
    """真人被处决后，观战推进逐日记录处决与夜杀。"""
    store, state, reply = _start(script, 9)
    _set_murderer(state, "p2")
    _enter_defense(store, state, reply, "p1")
    _force_votes(
        state,
        {
            "p1": "p0",
            "p2": "p0",
            "p3": "p0",
            "p4": "p0",
            "p5": "p1",
        },
    )
    outcome = blood.vote(store, state.game_id, "p1", reply)
    assert outcome.executed is not None and outcome.executed.id == "p0"
    assert outcome.phase == "spectating"
    first = outcome.day_history[0]
    assert first["day"] == 1
    assert first["executed"] == {"id": "p0", "name": "旅客"}
    assert "第 1 天" in first["note"]
    assert "旅客" in first["note"]

    killer = next(player for player in state.players if player.id == "p2")
    killer.suspicion = {"p3": 0.9}
    blood.advance(store, state.game_id)
    assert outcome.winner is None
    days = [entry["day"] for entry in state.day_history]
    assert days == list(range(1, len(days) + 1))
    assert state.day_history[0]["killed"] is not None
    for entry in state.day_history:
        assert {"day", "executed", "killed", "note"} <= set(entry)

    guard = 0
    while state.phase != "ended" and guard < 12:
        blood.advance(store, state.game_id)
        guard += 1
    assert state.phase == "ended"
    assert state.winner in {"good", "murderer"}
    final = blood.build_view(state)
    assert final.reveal is not None
    assert final.reveal.murderer_id == "p2"


def test_aftermath_after_you_killed_starts_with_the_night(script: Script) -> None:
    """真人被夜杀后，卷宗第 1 天先记夜杀，观战再逐日推进。"""
    store, state, reply = _start(script, 10)
    _set_murderer(state, "p4")
    state.phase = "night"
    killer = next(p for p in state.players if p.id == "p4")
    killer.suspicion = {"p0": 0.9}
    outcome = blood.night(store, state.game_id, None)
    assert outcome.killed is not None and outcome.killed.id == "p0"
    first = outcome.day_history[0]
    assert first["day"] == 1
    assert first["executed"] is None
    assert first["killed"] == {"id": "p0", "name": "旅客"}
    assert "第 1 天" in first["note"]
    days = [entry["day"] for entry in outcome.day_history]
    assert days == list(range(1, len(days) + 1))

    stepped = blood.advance(store, state.game_id)
    assert stepped.phase == "defense"
    assert stepped.ghost_vote_available is True
    guard = 0
    while state.phase != "ended" and guard < 12:
        blood.advance(store, state.game_id)
        guard += 1
    assert state.winner in {"good", "murderer"}


def test_log_has_no_secret_or_culprit_fields(script: Script) -> None:
    store, state, reply = _start(script, 10)
    blood.discuss(store, state.game_id, reply)
    blood.speak(store, state.game_id, "走廊里到底有几个人？", reply)
    alive_agents = [p.id for p in state.players if p.alive and not p.is_you]
    _enter_defense(store, state, reply, alive_agents[0])
    target = next(p.id for p in state.players if p.alive and not p.is_you)
    blood.vote(store, state.game_id, target, reply)
    if state.phase == "night":
        night_target = next(
            p.id for p in state.players if p.alive and not p.is_you
        )
        blood.night(store, state.game_id, night_target)
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


def test_defense_fallback_when_llm_fails(script: Script) -> None:
    store, state, _ = _start(script, 11, FakeLLM(error=True))
    reply = blood_ai.make_reply_fn(FakeLLM(error=True))
    outcome = blood.nominate(store, state.game_id, "p1", reply)
    assert outcome.ok is True
    assert outcome.defense is not None
    assert "提名我" in outcome.defense.text


def test_ai_rejects_self_claim(script: Script) -> None:
    """自曝阵营或秘密身份时改写成不含秘密词的含糊句。"""
    for claim in ("我是凶手，别怀疑我。", "我是好人，相信我。", "我是记者，来查火灾的。"):
        rewritten = blood_ai.clean_line(claim)
        assert rewritten
        for term in blood.BLOOD_SECRET_CLAIM_TERMS:
            assert term not in rewritten
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


def test_defense_prompt_demands_answer(script: Script) -> None:
    llm = FakeLLM()
    store, state, reply = _start(script, 12, llm)
    blood.nominate(store, state.game_id, "p2", reply)
    assert any("正面自辩" in user for _, user in llm.calls)


def test_api_state_and_error_codes(api: tuple[TestClient, BloodStore]) -> None:
    client, store = api
    response = client.post("/blood/games")
    assert response.status_code == 200
    body = response.json()
    assert body["phase"] == "discussion"
    assert len(body["players"]) == 6
    assert body["you_alive"] is True
    assert body["aftermath"] == []
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
    state.phase = "defense"
    assert client.post(f"/blood/games/{game_id}/speak", json={"text": "喂"}).status_code == 409
    assert (
        client.post(
            f"/blood/games/{game_id}/nominate",
            json={"target_id": "p1"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/blood/games/{game_id}/vote",
            json={"target_id": "p1"},
        ).status_code
        == 409
    )
    response = client.get(f"/blood/games/{game_id}")
    assert response.status_code == 200
    assert response.json()["players"][0]["alive"] is False
    assert response.json()["dead"][0]["id"] == "p0"


def test_api_nominate_returns_defense(api: tuple[TestClient, BloodStore]) -> None:
    client, store = api
    game_id = client.post("/blood/games").json()["game_id"]
    response = client.post(
        f"/blood/games/{game_id}/nominate",
        json={"target_id": "p1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["phase"] == "defense"
    assert body["target"] == {"id": "p1", "name": "沈玉兰"}
    assert set(body["defense"]) == {"speaker_id", "speaker_name", "text"}
    assert body["defense"]["speaker_id"] == "p1"
    assert body["public_log"][-1]["speaker_id"] == "p1"


def test_api_vote_returns_reasons_and_threshold(
    api: tuple[TestClient, BloodStore],
) -> None:
    client, store = api
    game_id = client.post("/blood/games").json()["game_id"]
    assert (
        client.post(
            f"/blood/games/{game_id}/vote",
            json={"target_id": "p1"},
        ).status_code
        == 409
    )
    client.post(f"/blood/games/{game_id}/nominate", json={"target_id": "p1"})
    response = client.post(
        f"/blood/games/{game_id}/vote",
        json={"target_id": "p1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "votes",
        "tally",
        "threshold",
        "executed",
        "winner",
        "reveal",
        "message",
        "public_log",
        "phase",
        "aftermath",
        "runoff_candidates",
        "stalemate_count",
    }
    assert body["threshold"] == 4
    assert body["phase"] in {"night", "ended", "spectating"}
    assert len(body["votes"]) == 6
    for vote in body["votes"]:
        assert set(vote) == {
            "voter_id",
            "voter_name",
            "target_id",
            "target_name",
            "reason",
        }
    assert body["phase"] in {"night", "ended"}


def test_api_ended_returns_reveal(api: tuple[TestClient, BloodStore]) -> None:
    client, store = api
    game_id = client.post("/blood/games").json()["game_id"]
    state = store.get(game_id)
    assert state is not None
    _set_murderer(state, "p5")
    _kill(state, "p1", "p2", "p3", "p4")
    state.phase = "night"
    killer = next(p for p in state.players if p.id == "p5")
    killer.suspicion = {"p0": 0.9}
    night = client.post(f"/blood/games/{game_id}/night", json={})
    assert night.status_code == 200
    assert night.json()["phase"] == "ended"
    assert night.json()["reveal"] == {
        "murderer_id": "p5",
        "murderer_name": "老韩",
    }
    assert night.json()["winner"] == "murderer"
    view = client.get(f"/blood/games/{game_id}")
    assert view.status_code == 200
    body = view.json()
    assert body["phase"] == "ended"
    assert body["reveal"]["murderer_id"] == "p5"
    assert body["winner"] == "murderer"
    assert body["you_alive"] is False


def test_api_ended_good_win_returns_winner(
    api: tuple[TestClient, BloodStore],
) -> None:
    client, store = api
    game_id = client.post("/blood/games").json()["game_id"]
    state = store.get(game_id)
    assert state is not None
    _set_murderer(state, "p5")
    for player in state.players:
        if not player.is_you:
            player.suspicion = {"p5": 0.9}
    assert (
        client.post(
            f"/blood/games/{game_id}/nominate",
            json={"target_id": "p1"},
        ).status_code
        == 200
    )
    for player in state.players:
        if not player.is_you:
            player.suspicion = {"p5": 0.9}
    voted = client.post(
        f"/blood/games/{game_id}/vote",
        json={"target_id": "p5"},
    )
    assert voted.status_code == 200
    assert voted.json()["winner"] == "good"
    body = client.get(f"/blood/games/{game_id}").json()
    assert body["phase"] == "ended"
    assert body["winner"] == "good"
    assert body["reveal"] == {"murderer_id": "p5", "murderer_name": "老韩"}


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
    assert nominated.json()["phase"] == "defense"
    phases.append(nominated.json()["phase"])

    voted = client.post(
        f"/blood/games/{game_id}/vote",
        json={"target_id": target},
    )
    assert voted.status_code == 200
    phases.append(voted.json()["phase"])

    if phases[-1] == "night":
        state = store.get(game_id)
        assert state is not None
        you = next(p for p in state.players if p.is_you)
        payload: dict[str, str] = {}
        if you.role == "murderer":
            payload["target_id"] = next(
                p.id
                for p in state.players
                if p.alive and not p.is_you and p.role != "murderer"
            )
        night = client.post(
            f"/blood/games/{game_id}/night",
            json=payload,
        )
        assert night.status_code == 200
        phases.append(night.json()["phase"])

    print("阶段序列：", " -> ".join(phases))
    assert phases[-1] in {"discussion", "ended"}
    assert client.get(f"/blood/games/{game_id}/log").status_code == 200

def test_public_speech_strips_memory_tail_and_fact_text(
    script: Script,
) -> None:
    """公开发言出现「我还记得：X」时，X 必须被截掉，不能出现在公开频道。"""
    store, state, _ = _start(script, 2)
    p3 = next(p for p in state.players if p.id == "p3")
    fact = p3.private_info[0]
    reply = blood_ai.make_reply_fn(
        FakeLLM(text=f"我只说看见的。我还记得：{fact}")
    )
    outcome = blood.discuss(store, state.game_id, reply)
    public = "".join(entry.text for entry in state.public_log)
    assert "我还记得" not in public
    assert fact not in public
    p3_reply = next(item for item in outcome.replies if item.speaker_id == "p3")
    assert p3_reply.text


def test_public_speech_scrubs_fact_text_without_marker(script: Script) -> None:
    """即便没有「我还记得」标记，逐字复述私有信息也会被弃用并用含糊句兜底。"""
    store, state, _ = _start(script, 2)
    p3 = next(p for p in state.players if p.id == "p3")
    fact = p3.private_info[0]
    reply = blood_ai.make_reply_fn(FakeLLM(text=fact))
    outcome = blood.discuss(store, state.game_id, reply)
    public = "".join(entry.text for entry in state.public_log)
    assert fact not in public
    p3_reply = next(item for item in outcome.replies if item.speaker_id == "p3")
    assert p3_reply.text
    assert p3_reply.text == blood.VAGUE_AGENT_LINES.get(
        "p3", blood.VAGUE_AGENT_DEFAULT
    )


def test_prompt_forbids_memory_recital(script: Script) -> None:
    """提示词禁止逐字念档案，并点名两个会被后处理截断的句式。"""
    _, state, _ = _start(script, 12)
    player = next(p for p in state.players if p.id == "p2")
    system, _ = blood_ai.build_prompt(player, state)
    assert "我还记得" in system
    assert "档案里写着" in system
    assert "逐字" in system
    assert "暗示" in system


def test_prompt_forbids_upgrading_traveller_hearsay(script: Script) -> None:
    """提示词把真人的话限定为「旅客的说法」，不得升级成亲历或新增人物。"""
    _, state, _ = _start(script, 12)
    player = next(p for p in state.players if p.id == "p2")
    system, _ = blood_ai.build_prompt(player, state)
    assert "旅客" in system
    assert "转述" in system
    assert "我亲眼" in system
    assert "不得新增" in system


def test_public_speech_filters_unregistered_names(script: Script) -> None:
    """agent 自造「老周」这类未登记人名时，公开发言要过滤掉。"""
    reply = blood_ai.make_reply_fn(
        FakeLLM(text="我亲眼见的只有23:40那串钥匙往西厢去，是老周说的。")
    )
    store, state, _ = _start(script, 2)
    outcome = blood.discuss(store, state.game_id, reply)
    public = "".join(entry.text for entry in state.public_log)
    assert "老周" not in public
    assert "旁人" in public
    assert len(outcome.replies) == 5


def test_traveller_hearsay_is_prefixed_not_upgraded(script: Script) -> None:
    """agent 把旅客说过的细节说成亲历时，回复要加「听旅客说」前缀。"""
    store, state, reply = _start(script, 2, FakeLLM(text="我亲眼见的23:40那串钥匙往西厢去。"))
    blood.speak(store, state.game_id, "23:40 我看见钥匙串往西厢去了。", reply)
    p1_reply = state.public_log[-1]
    assert p1_reply.speaker_id == "p1"
    assert p1_reply.text.startswith(blood.BLOOD_HEARSAY_PREFIX)


def test_tie_vote_message_says_tie(script: Script) -> None:
    """4 人局 2-2 平票先重投；重投仍平票，文案必须写平票并入夜。"""
    store, state, reply = _start(script, 3)
    _set_murderer(state, "p3")
    _kill(state, "p4", "p5")
    _enter_defense(store, state, reply, "p1")
    _force_votes(state, {"p1": "p2", "p2": "p1", "p3": "p2"})
    outcome = blood.vote(store, state.game_id, "p1", reply)
    assert outcome.threshold == 3
    assert outcome.tally == {"p1": 2, "p2": 2}
    assert outcome.executed is None
    assert outcome.phase == "runoff"
    assert "并列" in outcome.message

    again = blood.vote(store, state.game_id, "p1", reply)
    assert again.executed is None
    assert again.phase == "night"
    assert again.message == "平票，今晚无人被处决。"


def test_below_threshold_message_says_threshold(script: Script) -> None:
    """5 人局最高 2 票、门槛 3 时，文案要写未达门槛。"""
    store, state, reply = _start(script, 3)
    _set_murderer(state, "p3")
    _kill(state, "p5")
    _enter_defense(store, state, reply, "p1")
    _force_votes(state, {"p1": "p2", "p2": "p1", "p3": "p1", "p4": "p3"})
    outcome = blood.vote(store, state.game_id, "p4", reply)
    assert outcome.threshold == 3
    assert outcome.executed is None
    assert max(outcome.tally.values()) == 2
    assert "最高 2 票，未达 3 票门槛" in outcome.message


def test_vote_at_threshold_executes(script: Script) -> None:
    """3 人局 3 张票全部落定，达到门槛 2 就处决唯一最高者。"""
    store, state, reply = _start(script, 3)
    _set_murderer(state, "p5")
    _kill(state, "p2", "p3", "p4")
    _enter_defense(store, state, reply, "p1")
    _force_votes(state, {"p1": "p5", "p5": "p1"})
    outcome = blood.vote(store, state.game_id, "p1", reply)
    assert outcome.threshold == 2
    assert outcome.executed is not None
    assert outcome.executed.id == "p1"
    assert sum(outcome.tally.values()) == 3


def _reasons_from(script: Script, seed: int) -> list[tuple[str, str, str]]:
    """跑一轮投票，返回 agent 的 (voter_id, target_id, reason)。"""
    store, state, reply = _start(
        script,
        seed,
        FakeLLM(text="我投我自己，这事没道理。"),
    )
    _set_murderer(state, "p5")
    _enter_defense(store, state, reply, "p1")
    _force_votes(
        state,
        {
            "p1": "p1",
            "p2": "p1",
            "p3": "p1",
            "p4": "p1",
            "p5": "p1",
        },
    )
    outcome = blood.vote(store, state.game_id, "p1", reply)
    return [
        (vote.voter_id, vote.target_id, vote.reason)
        for vote in outcome.votes
        if vote.voter_id != "p0"
    ]


def test_vote_reasons_are_diverse_and_target_bound(script: Script) -> None:
    """10 张 agent 票的理由去重后至少 5 种，且不含非 target 姓名与自指。"""
    collected = _reasons_from(script, 3) + _reasons_from(script, 4)
    assert len(collected) == 10
    assert len({reason for _, _, reason in collected}) >= 5
    for _, _, reason in collected:
        assert reason
        assert "我自己" not in reason
        assert "我投我自己" not in reason
    store, state, _ = _start(script, 3)
    names = {player.id: player.name for player in state.players}
    for _, target_id, reason in collected:
        for player_id, name in names.items():
            if player_id != target_id:
                assert name not in reason


def test_vote_reason_about_traveller_never_self_references(
    script: Script,
) -> None:
    """agent 投真人时，理由要写「旅客」，不能出现「我投我自己」。"""
    store, state, reply = _start(
        script,
        9,
        FakeLLM(text="我投我自己？没这道理。"),
    )
    _set_murderer(state, "p2")
    _enter_defense(store, state, reply, "p1")
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
    outcome = blood.vote(store, state.game_id, "p1", reply)
    real_votes = [
        vote
        for vote in outcome.votes
        if vote.voter_id != "p0" and vote.target_id == "p0"
    ]
    assert real_votes
    for vote in real_votes:
        assert "我自己" not in vote.reason
        assert "旅客" in vote.reason


def test_aftermath_when_you_are_murderer_executed(script: Script) -> None:
    """真人凶手被处决即终局时，卷宗仍要有当天摘要（A 号局回归）。"""
    store, state, reply = _start(script, 9)
    _set_murderer(state, "p0")
    _enter_defense(store, state, reply, "p1")
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
    outcome = blood.vote(store, state.game_id, "p1", reply)
    assert outcome.executed is not None
    assert outcome.executed.id == "p0"
    assert outcome.aftermath
    first = outcome.aftermath[0]
    assert first["day"] == 1
    assert first["executed"] == {"id": "p0", "name": "旅客"}
    assert "旅客" in first["note"]
    assert outcome.winner == "good"
    assert outcome.reveal is not None
    assert outcome.reveal.murderer_id == "p0"


class _FixedRng:
    """固定掷骰结果，用于让密谈的 accept/跟随稳定可断言。"""

    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def random(self) -> float:
        """始终返回预设值。"""
        return self.value


def _confide(
    store: BloodStore,
    state: BloodState,
    target_id: str,
    text: str,
    reply_text: str = "这话我记下了，但我不把话说死。",
) -> blood.ConfideOutcome:
    confide_fn = blood_ai.make_confide_fn(FakeLLM(text=reply_text))
    return blood.confide(store, state.game_id, target_id, text, confide_fn)


def test_confide_once_per_day_and_three_per_game(script: Script) -> None:
    """密谈每天 1 次、每局 3 次，超限返回明确错误。"""
    store, state, _ = _start(script, 3)
    state.rng = _FixedRng(0.0)  # type: ignore[assignment]
    first = _confide(store, state, "p1", "廊下风大，你怎么看今晚？")
    assert first.ok is True
    assert first.stance in {"accept", "refuse", "evade", "threaten"}
    same_day = _confide(store, state, "p2", "再问一句。")
    assert same_day.ok is False
    assert same_day.error == "confide_used_day"

    state.day = 2
    assert _confide(store, state, "p2", "第二天再问。").ok is True
    state.day = 3
    assert _confide(store, state, "p3", "第三天再问。").ok is True
    state.day = 4
    blocked = _confide(store, state, "p4", "第四天还想问。")
    assert blocked.ok is False
    assert blocked.error == "confide_limit"


def test_confide_private_log_keeps_text_public_log_does_not(
    api: tuple[TestClient, BloodStore],
) -> None:
    """密谈正文只进 private-log，公开日志只留一句旁白。"""
    client, store = api
    game_id = client.post("/blood/games").json()["game_id"]
    assert client.post(f"/blood/games/{game_id}/discuss").status_code == 200
    text = "我想提陆明川，你若肯跟我同票，明天我保你不上桌。"
    response = client.post(
        f"/blood/games/{game_id}/confide",
        json={"target_id": "p1", "text": text},
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "stance",
        "reply",
        "trust",
        "suspicion",
        "public_line",
        "betrayed",
    }
    assert body["public_line"] == "你与沈玉兰在廊下低声说了几句。"

    private = client.get(f"/blood/games/{game_id}/private-log").json()
    assert len(private["entries"]) == 1
    entry = private["entries"][0]
    assert entry["text"] == text
    assert entry["reply"]
    assert entry["target_name"] == "沈玉兰"

    state = store.get(game_id)
    assert state is not None
    public_text = "".join(item.text for item in state.public_log)
    assert "低声说了几句" in public_text
    assert text not in public_text
    assert entry["reply"] != ""

    logs = client.get(f"/blood/games/{game_id}/log").json()["entries"]
    confide_logs = [item for item in logs if item["type"] == "confide"]
    assert confide_logs
    assert "text" not in confide_logs[0]
    assert confide_logs[0]["target_id"] == "p1"


def test_confide_accept_raises_trust_and_follow(script: Script) -> None:
    """承诺保护/结盟时进入 accept，提升 trust 与 follow_prob，并在投票中跟随。"""
    store, state, reply = _start(script, 3)
    state.rng = _FixedRng(0.0)  # type: ignore[assignment]
    _set_murderer(state, "p2")
    target = next(player for player in state.players if player.id == "p1")
    before_trust = target.trust
    before_suspicion = target.suspicion.get("p0", 0.0)
    outcome = _confide(
        store,
        state,
        "p1",
        "我会保护你，我们一起投陆明川，你别把票投我。",
    )
    assert outcome.ok is True
    assert outcome.stance == "accept"
    assert outcome.trust > before_trust
    assert outcome.suspicion < int(round(before_suspicion * 100))
    assert target.follow_prob > 0.0

    _enter_defense(store, state, reply, "p1")
    _force_votes(
        state,
        {
            "p1": "p2",
            "p2": "p2",
            "p3": "p2",
            "p4": "p2",
            "p5": "p2",
        },
    )
    voted = blood.vote(store, state.game_id, "p4", reply)
    p1_vote = next(vote for vote in voted.votes if vote.voter_id == "p1")
    assert p1_vote.target_id == "p4"


def test_confide_threaten_raises_suspicion(script: Script) -> None:
    """威胁类密谈提高目标对真人的怀疑，且不提升跟随。"""
    store, state, _ = _start(script, 3)
    state.rng = _FixedRng(0.0)  # type: ignore[assignment]
    target = next(player for player in state.players if player.id == "p1")
    before = target.suspicion.get("p0", 0.0)
    outcome = _confide(
        store,
        state,
        "p1",
        "你不投我，我就把你的事捅出去，你会后悔的。",
    )
    assert outcome.ok is True
    assert outcome.stance == "threaten"
    assert target.suspicion.get("p0", 0.0) > before
    assert target.follow_prob == 0.0


def test_confide_betray_drops_trust_and_queues_retaliation(
    script: Script,
) -> None:
    """口头应下但准备背叛时，返回 betrayed，trust -15、suspicion +10，并只泄露玩家原话。"""
    class SeqRng:
        def __init__(self) -> None:
            self.values = iter([0.9, 0.0])

        def random(self) -> float:
            return next(self.values, 0.0)

    store, state, _ = _start(script, 3)
    state.rng = SeqRng()  # type: ignore[assignment]
    target = next(player for player in state.players if player.id == "p1")
    before_trust = target.trust
    before_suspicion = target.suspicion.get("p0", 0.0)
    text = "我保你不上桌，你跟我一起投陆明川。"
    outcome = _confide(store, state, "p1", text)
    assert outcome.ok is True
    assert outcome.stance == "accept"
    assert outcome.betrayed is True
    assert target.trust == blood.BETRAY_TRUST_DELTA + before_trust
    assert target.suspicion.get("p0", 0.0) > before_suspicion
    assert target.follow_prob == 0.0
    assert state.pending_leaks[target.id] == text
    assert outcome.reply == blood.CONFIDE_BETRAY_REPLY


def test_confide_leak_is_capped_and_scrubs_new_names(script: Script) -> None:
    """泄露只复述玩家原话 20 字以内，不新增未出场人物。"""
    store, state, _ = _start(script, 3)
    player = next(item for item in state.players if item.id == "p1")
    state.pending_leaks[player.id] = "老赵说那枚铜纽扣是他掉的，还提了个叫小翠的人。"
    leak = blood._consume_leak(state, player)
    assert leak
    assert "老赵" not in leak
    assert "小翠" not in leak
    quote = leak.split("「", 1)[1].split("」", 1)[0]
    assert len(quote) <= blood.LEAK_QUOTE_MAX_CHARS
    assert "铜纽扣" in quote


def test_confide_leak_reaches_public_speech_once(script: Script) -> None:
    """泄露会在目标下一次公开发言里出现一次，且不复述正文全文。"""
    store, state, reply = _start(script, 3)
    player = next(item for item in state.players if item.id == "p1")
    text = "老赵说那枚铜纽扣是他掉的，还提了个叫小翠的人。"
    state.pending_leaks[player.id] = text
    blood.discuss(store, state.game_id, reply)
    public = "".join(entry.text for entry in state.public_log)
    assert "私下说" in public
    assert "老赵" not in public
    assert "小翠" not in public
    assert text not in public


def test_vote_reason_quote_must_come_from_target_same_day(
    script: Script,
) -> None:
    """把别人的话安到 target 头上时，必须改用不含该引文的兜底理由。"""

    class VoteLLM(FakeLLM):
        def complete(self, system_prompt: str, user_prompt: str) -> str:
            if "现在投票" in user_prompt:
                return "我投沈玉兰，她说“我整晚在楼梯口，没上过二楼”。"
            return "我只说看见的，别的不好接。"

    store, state, reply = _start(script, 3, VoteLLM())
    _set_murderer(state, "p2")
    state.public_log.append(
        blood.BloodLogEntry(
            seq=len(state.public_log) + 1,
            speaker_id="p1",
            speaker_name="沈玉兰",
            text="我在后廊给过他一点钱，没人替我作证。",
            day=1,
        )
    )
    state.public_log.append(
        blood.BloodLogEntry(
            seq=len(state.public_log) + 1,
            speaker_id="p2",
            speaker_name="周砚青",
            text="我整晚在楼梯口，没上过二楼。",
            day=1,
        )
    )
    _enter_defense(store, state, reply, "p1")
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
    outcome = blood.vote(store, state.game_id, "p1", reply)
    for vote in outcome.votes:
        if vote.voter_id == "p0" or vote.target_id != "p1":
            continue
        assert "周砚青" not in vote.reason
        assert "楼梯口" not in vote.reason
        assert "沈玉兰" in vote.reason
        assert len(vote.reason) <= blood.BLOOD_VOTE_REASON_MAX_CHARS
        assert vote.reason[-1] in blood.SENTENCE_ENDS
        for term in blood.VOTE_REASON_PLACEHOLDERS:
            assert term not in vote.reason


def test_vote_reason_hard_cut_removed(script: Script) -> None:
    """超过 80 字的理由要收在句末，不留半句话，也不加占位符。"""
    long_reason = "我投周砚青，" + "他每回说到时辰就绕开，我听着实在不像实话，" * 6
    store, state, reply = _start(script, 3, FakeLLM(text=long_reason))
    _set_murderer(state, "p2")
    _enter_defense(store, state, reply, "p1")
    _force_votes(
        state,
        {
            "p1": "p2",
            "p2": "p1",
            "p3": "p2",
            "p4": "p2",
            "p5": "p2",
        },
    )
    outcome = blood.vote(store, state.game_id, "p2", reply)
    for vote in outcome.votes:
        if vote.voter_id == "p0" or vote.target_id != "p2":
            continue
        assert len(vote.reason) <= blood.BLOOD_VOTE_REASON_MAX_CHARS
        assert vote.reason[-1] in blood.SENTENCE_ENDS
        assert "某人" not in vote.reason
        assert "周砚青" in vote.reason


def test_day_history_starts_day_one_with_execution_night_and_tie(
    script: Script,
) -> None:
    """卷宗从第 1 天起记录处决与夜杀；第 2 天平票也单独成条。"""
    store, state, reply = _start(script, 3)
    _set_murderer(state, "p2")
    _enter_defense(store, state, reply, "p1")
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
    first = blood.vote(store, state.game_id, "p1", reply)
    assert first.executed is not None and first.executed.id == "p1"
    assert first.day_history[0]["day"] == 1
    assert first.day_history[0]["executed"] == {"id": "p1", "name": "沈玉兰"}

    killer = next(player for player in state.players if player.id == "p2")
    killer.suspicion = {"p3": 0.9}
    after_night = blood.night(store, state.game_id, None)
    assert after_night.killed is not None and after_night.killed.id == "p3"
    assert after_night.day_history[0]["killed"] == {"id": "p3", "name": "阿蘅"}
    assert "夜里" in after_night.day_history[0]["note"]

    _enter_defense(store, state, reply, "p4")
    _force_votes(
        state,
        {
            "p2": "p4",
            "p4": "p2",
            "p5": "p4",
        },
    )
    tie = blood.vote(store, state.game_id, "p2", reply)
    assert tie.tally == {"p2": 2, "p4": 2}
    assert tie.executed is None
    assert tie.phase == "runoff"
    assert {item.id for item in tie.runoff_candidates} == {"p2", "p4"}
    settled = blood.vote(store, state.game_id, "p2", reply)
    assert settled.executed is None
    assert settled.phase == "night"
    assert settled.day_history[1]["day"] == 2
    assert settled.day_history[1]["stalemate"] is True
    assert settled.day_history[1]["executed"] is None

    killer.suspicion = {"p4": 0.9}
    stalled = blood.night(store, state.game_id, None)
    assert stalled.killed is not None
    assert stalled.killed.id == "p4"
    assert stalled.day == 3
    assert stalled.day_history[1]["killed"] == {"id": "p4", "name": "陆明川"}
    assert "夜里" in stalled.day_history[1]["note"]
    assert state.aftermath == state.day_history


def test_tie_night_still_kills_someone(script: Script) -> None:
    """平票的当夜凶手照样杀人，天亮进入下一天。"""
    store, state, reply = _start(script, 3)
    _set_murderer(state, "p2")
    _enter_defense(store, state, reply, "p1")
    _force_votes(
        state,
        {
            "p1": "p2",
            "p2": "p1",
            "p3": "p2",
            "p4": "p1",
            "p5": "p2",
        },
    )
    outcome = blood.vote(store, state.game_id, "p1", reply)
    assert outcome.executed is None
    assert outcome.phase == "runoff"
    settled = blood.vote(store, state.game_id, "p1", reply)
    assert settled.executed is None
    assert settled.phase == "night"
    killer = next(player for player in state.players if player.id == "p2")
    killer.suspicion = {"p3": 0.9}
    night = blood.night(store, state.game_id, None)
    assert night.ok is True
    assert night.killed is not None and night.killed.id == "p3"
    assert night.day == 2
    assert night.phase == "discussion"
    assert not next(p for p in state.players if p.id == "p3").alive


def test_long_you_speech_keeps_last_sentence(script: Script) -> None:
    """真人发言超长时截到句末，并在 notice 里明确提示。"""
    store, state, reply = _start(script, 3)
    long_text = (
        "我先把话说明白。"
        + "每个人都要交代清楚自己那晚在哪里、做了什么。"
        * 10
    )
    outcome = blood.speak(store, state.game_id, long_text, reply)
    assert outcome.ok is True
    assert outcome.notice == "发言过长，已保留到最后一个句号。"
    you_entry = next(
        entry
        for entry in reversed(state.public_log)
        if entry.speaker_id == "p0"
    )
    assert len(you_entry.text) <= blood.BLOOD_MAX_LINE_CHARS
    assert you_entry.text.endswith("。")
    assert long_text.startswith(you_entry.text)


def test_api_long_speech_returns_notice(
    api: tuple[TestClient, BloodStore],
) -> None:
    """接口层也返回超长发言提示，不静默截断。"""
    client, _ = api
    game_id = client.post("/blood/games").json()["game_id"]
    body = client.post(
        f"/blood/games/{game_id}/speak",
        json={"text": "我先说。" + "这句很长的话需要被保留到句末。" * 10},
    ).json()
    assert body["notice"] == "发言过长，已保留到最后一个句号。"
    assert body["public_log"][-1]["text"].endswith("。") or any(
        entry["speaker_id"] == "p0" and entry["text"].endswith("。")
        for entry in body["public_log"]
    )


def test_last_words_once_after_you_die(
    api: tuple[TestClient, BloodStore],
) -> None:
    """真人活着不能留遗言；出局后可留 1 条，进入公开日志。"""
    client, store = api
    game_id = client.post("/blood/games").json()["game_id"]
    alive = client.post(
        f"/blood/games/{game_id}/last-words",
        json={"text": "我还没死。"},
    )
    assert alive.status_code == 409

    state = store.get(game_id)
    assert state is not None
    state.players[0].alive = False
    first = client.post(
        f"/blood/games/{game_id}/last-words",
        json={"text": "我怀疑周砚青，他一直在绕开时辰。"},
    )
    assert first.status_code == 200
    assert first.json()["text"] in first.json()["public_log"][-1]["text"]
    second = client.post(
        f"/blood/games/{game_id}/last-words",
        json={"text": "再说一句。"},
    )
    assert second.status_code == 409


def test_confide_prompt_forbids_evidence_endorsement(script: Script) -> None:
    """密谈提示词明确禁止为玩家声称的物证补充存在性。"""
    _, state, _ = _start(script, 12)
    player = next(item for item in state.players if item.id == "p2")
    system, user = blood_ai.build_confide_prompt(
        player,
        state,
        "我在门槛上捡到一枚刻着周字的铜纽扣。",
        "refuse",
    )
    assert "物证" in system
    assert "未出场" in system
    assert "不得承认它存在" in system
    assert "铜纽扣" in user


def test_confide_reply_does_not_endorse_players_evidence(
    script: Script,
) -> None:
    """agent 用自己的记忆替玩家编的物证背书时，私下回复要退回模板。"""
    store, state, _ = _start(script, 3)
    state.rng = _FixedRng(0.0)  # type: ignore[assignment]
    outcome = _confide(
        store,
        state,
        "p1",
        "我在门槛上捡到一枚铜纽扣，你认得吗？",
        reply_text="我认得那枚纽扣，周砚青衣襟上确实少过一颗。",
    )
    assert outcome.ok is True
    assert "我认得" not in outcome.reply
    assert "少过一颗" not in outcome.reply


def test_full_flow_confide_private_log_tie_stalemate(
    api: tuple[TestClient, BloodStore],
) -> None:
    """真实链路：讨论 → 密谈 → 提名 → 平票 → 僵局夜 → 逐日卷宗。"""
    client, store = api
    game_id = client.post("/blood/games").json()["game_id"]
    assert client.post(f"/blood/games/{game_id}/discuss").status_code == 200

    confided = client.post(
        f"/blood/games/{game_id}/confide",
        json={"target_id": "p1", "text": "今晚我会提沈玉兰，你怎么看？"},
    )
    assert confided.status_code == 200
    private = client.get(f"/blood/games/{game_id}/private-log").json()
    assert private["entries"][0]["text"] == "今晚我会提沈玉兰，你怎么看？"
    state = store.get(game_id)
    assert state is not None
    assert "低声说了几句" in state.public_log[-1].text

    assert (
        client.post(
            f"/blood/games/{game_id}/nominate",
            json={"target_id": "p1"},
        ).status_code
        == 200
    )
    _force_votes(
        state,
        {
            "p1": "p2",
            "p2": "p1",
            "p3": "p2",
            "p4": "p1",
            "p5": "p2",
        },
    )
    voted = client.post(
        f"/blood/games/{game_id}/vote",
        json={"target_id": "p1"},
    )
    assert voted.status_code == 200
    assert voted.json()["executed"] is None
    assert voted.json()["phase"] == "runoff"
    assert {
        item["id"] for item in voted.json()["runoff_candidates"]
    } == {"p1", "p2"}

    runoff_vote = client.post(
        f"/blood/games/{game_id}/vote",
        json={"target_id": "p1"},
    )
    assert runoff_vote.status_code == 200
    assert runoff_vote.json()["executed"] is None
    assert runoff_vote.json()["phase"] == "night"

    night = client.post(f"/blood/games/{game_id}/night", json={})
    assert night.status_code == 200
    assert night.json()["killed"] is not None
    assert night.json()["day"] == 2

    view = client.get(f"/blood/games/{game_id}").json()
    assert view["day_history"][0]["day"] == 1
    assert view["day_history"][0]["tally"] == {"p1": 3, "p2": 3}
    assert view["day_history"][0]["stalemate"] is True
    assert view["day_history"][0]["killed"] is not None
    assert view["day_history"] == view["aftermath"]


# ---- 第五轮：真人 1 次查验 ----


def test_inspect_default_hides_and_reveal_publishes(
    api: tuple[TestClient, BloodStore],
) -> None:
    """默认查验只回本人、不写公开日志；reveal=true 才宣告并推动怀疑。"""
    client, store = api
    game_id = client.post("/blood/games").json()["game_id"]
    state = store.get(game_id)
    assert state is not None
    _set_murderer(state, "p2")
    log_before = len(state.public_log)
    p1 = next(player for player in state.players if player.id == "p1")
    suspicion_before = p1.suspicion["p2"]

    hidden = client.post(
        f"/blood/games/{game_id}/inspect",
        json={"target_id": "p2"},
    )
    assert hidden.status_code == 200
    assert hidden.json() == {
        "result": "murderer",
        "public_line": "",
        "remaining": 0,
        "revealed": False,
    }
    assert len(state.public_log) == log_before
    assert p1.suspicion["p2"] == suspicion_before
    second = client.post(
        f"/blood/games/{game_id}/inspect",
        json={"target_id": "p3"},
    )
    assert second.status_code == 409

    reveal_game = client.post("/blood/games").json()["game_id"]
    reveal_state = store.get(reveal_game)
    assert reveal_state is not None
    _set_murderer(reveal_state, "p2")
    p3 = next(player for player in reveal_state.players if player.id == "p3")
    before = p3.suspicion["p2"]
    shown = client.post(
        f"/blood/games/{reveal_game}/inspect",
        json={"target_id": "p2", "reveal": True},
    )
    assert shown.status_code == 200
    assert shown.json() == {
        "result": "murderer",
        "public_line": "我查过周砚青。",
        "remaining": 0,
        "revealed": True,
    }
    view = client.get(f"/blood/games/{reveal_game}").json()
    assert view["public_log"][-1]["speaker_id"] == "p0"
    assert view["public_log"][-1]["text"] == "我查过周砚青。"
    assert p3.suspicion["p2"] == pytest.approx(
        min(1.0, before + blood.BLOOD_INSPECT_SUSPICION_MURDERER)
    )
    second_shown = client.post(
        f"/blood/games/{reveal_game}/inspect",
        json={"target_id": "p3", "reveal": True},
    )
    assert second_shown.status_code == 409


def test_inspect_blocked_for_murderer_and_moves_suspicion(
    api: tuple[TestClient, BloodStore],
) -> None:
    """真人是凶手时无查验；查验结果会改写 agent 对目标的怀疑。"""
    client, store = api
    murderer_game = client.post("/blood/games").json()["game_id"]
    murderer_state = store.get(murderer_game)
    assert murderer_state is not None
    _set_murderer(murderer_state, "p0")
    blocked = client.post(
        f"/blood/games/{murderer_game}/inspect",
        json={"target_id": "p1"},
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "你现在没有可用的查验"

    store2, state, _ = _start(load_script(SCRIPT_PATH), 3)
    _set_murderer(state, "p2")
    p1 = next(player for player in state.players if player.id == "p1")
    before = p1.suspicion["p2"]
    outcome = blood.inspect(store2, state.game_id, "p2", reveal=True)
    assert outcome.ok is True
    assert outcome.result == "murderer"
    assert outcome.revealed is True
    assert p1.suspicion["p2"] == pytest.approx(
        min(1.0, before + blood.BLOOD_INSPECT_SUSPICION_MURDERER)
    )


# ---- 第五轮：密谈数值与跟随 ----


def _stance_run(
    script: Script,
    target_id: str,
    text: str,
) -> tuple[blood.ConfideOutcome, BloodPlayer, float, float]:
    store, state, _ = _start(script, 3)
    state.rng = _FixedRng(0.0)  # type: ignore[assignment]
    target = next(player for player in state.players if player.id == target_id)
    before_trust = target.trust
    before_suspicion = target.suspicion.get("p0", 0.0)
    outcome = _confide(store, state, target_id, text)
    return outcome, target, before_trust, before_suspicion


def test_confide_stance_numbers_are_consistent(script: Script) -> None:
    """accept/refuse/evade/threaten 的姿态与 trust/suspicion/follow 数值必须一致。"""
    accepted, target, trust, susp = _stance_run(
        script,
        "p1",
        "我会保护你，我们一起投陆明川。",
    )
    assert accepted.stance == "accept"
    assert accepted.betrayed is False
    assert trust == 50.0
    assert accepted.trust == 65
    assert target.suspicion["p0"] == pytest.approx(max(0.0, susp - 0.1))
    assert target.follow_prob == pytest.approx(0.25)

    refused, target, trust, susp = _stance_run(
        script,
        "p2",
        "我亲眼看见你动过书房里的东西。",
    )
    assert refused.stance == "refuse"
    assert refused.trust == 45
    assert target.suspicion["p0"] == pytest.approx(susp + 0.08)

    evaded, target, trust, susp = _stance_run(
        script,
        "p3",
        "廊下风大，你怎么看今晚？",
    )
    assert evaded.stance == "evade"
    assert evaded.trust == 50
    assert target.suspicion["p0"] == pytest.approx(susp + 0.03)
    assert target.follow_prob == 0.0

    threatened, target, trust, susp = _stance_run(
        script,
        "p4",
        "投票跟我走，我就当没看见；不然我现在就当众说。",
    )
    assert threatened.stance == "threaten"
    assert threatened.trust == 40
    assert target.suspicion["p0"] == pytest.approx(susp + 0.12)
    assert target.follow_prob == 0.0


def test_confide_follow_changes_vote(script: Script) -> None:
    """follow_prob 命中时，agent 的票跟随真人当前投票目标而不是自己最怀疑的人。"""
    store, state, reply = _start(script, 3)
    _set_murderer(state, "p2")
    p5 = next(player for player in state.players if player.id == "p5")
    for player in state.players:
        if player.is_you:
            continue
        player.suspicion = {
            other.id: 0.9
            for other in state.players
            if other.id != player.id and other.id != "p0"
        }
    p5.suspicion = {"p2": 0.9}
    p5.follow_prob = 0.5
    state.rng = _FixedRng(0.0)  # type: ignore[assignment]
    _enter_defense(store, state, reply, "p1")
    outcome = blood.vote(store, state.game_id, "p1", reply)
    p5_vote = next(vote for vote in outcome.votes if vote.voter_id == "p5")
    assert p5_vote.target_id == "p1"


def test_confide_leak_only_quotes_player_words(script: Script) -> None:
    """泄密只引用玩家原话，绝不出现编造的「昨晚的话不算数」。"""
    store, state, reply = _start(script, 3)
    p1 = next(player for player in state.players if player.id == "p1")
    state.pending_leaks[p1.id] = "我只按证据投"
    leak = blood._consume_leak(state, p1)
    assert leak == "我听旅客私下说「我只按证据投」，我没应。"
    assert blood.CONFIDE_BETRAY_REPLY not in leak
    assert blood._consume_leak(state, p1) == ""

    class SeqRng:
        def __init__(self) -> None:
            self.values = iter([0.9, 0.0])

        def random(self) -> float:
            return next(self.values, 0.0)

    store2, state2, reply2 = _start(script, 3)
    state2.rng = SeqRng()  # type: ignore[assignment]
    betrayed = _confide(
        store2,
        state2,
        "p1",
        "我保你不上桌，你跟我一起投陆明川。",
    )
    assert betrayed.betrayed is True
    blood.discuss(store2, state2.game_id, reply2)
    public = "".join(entry.text for entry in state2.public_log)
    assert "昨晚的话不算数" not in public
    assert "我保你不上桌" in public or "我只按" in public


# ---- 第五轮：时间线与引文 ----


def test_prompt_injects_today_quotes_and_vote_quote_whitelist(
    script: Script,
) -> None:
    """prompt 注入当天原话；投票理由只允许引用 target 当天的原话。"""
    _, state, _ = _start(script, 12)
    p1 = next(player for player in state.players if player.id == "p1")
    p2 = next(player for player in state.players if player.id == "p2")
    blood._say(state, p1.id, p1.name, "昨天我在后堂对账。")
    state.day = 2
    blood._say(state, p1.id, p1.name, "今天我在楼梯口站着。")
    blood._say(state, p2.id, p2.name, "我听见书房有响动。")

    system, user = blood_ai.build_prompt(p1, state)
    assert "不得新增未发生的地点、时辰、人物或动作" in system
    today_section = user.split("你当天已经说过的原话", 1)[1]
    today_section = today_section.split("最近的公开发言", 1)[0]
    assert "今天我在楼梯口站着" in today_section
    assert "昨天我在后堂对账" not in today_section

    state.pending_hint = "vote_reason"
    state.pending_target_id = p1.id
    try:
        _, vote_user = blood_ai.build_prompt(p2, state)
    finally:
        state.pending_hint = ""
        state.pending_target_id = None
    assert "理由里若提到时辰、地点或动作" in vote_user
    assert "今天我在楼梯口站着" in vote_user


def test_vote_reason_rejects_invented_time_and_action(
    script: Script,
) -> None:
    """把不存在的时辰和动作安到 target 头上时，理由必须被替换为无出处版本。"""

    class VoteLLM(FakeLLM):
        def complete(self, system_prompt: str, user_prompt: str) -> str:
            if "现在投票" in user_prompt:
                return "我投沈玉兰，她22:30在书房翻页，前后对不上。"
            return "我只说看见的。别的不好接。"

    store, state, reply = _start(script, 3, VoteLLM())
    _set_murderer(state, "p2")
    blood._say(
        state,
        "p1",
        "沈玉兰",
        "我在后廊给过他一点钱，没人替我作证。",
    )
    _enter_defense(store, state, reply, "p1")
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
    outcome = blood.vote(store, state.game_id, "p1", reply)
    for vote in outcome.votes:
        if vote.voter_id == "p0" or vote.target_id != "p1":
            continue
        assert "22:30" not in vote.reason
        assert "翻页" not in vote.reason
        assert "沈玉兰" in vote.reason


def test_vote_reason_rejects_denying_supplied_time(
    script: Script,
) -> None:
    """target 当天给过 23:05，理由却说他没给时辰，属于时间线矛盾。"""

    class VoteLLM(FakeLLM):
        def complete(self, system_prompt: str, user_prompt: str) -> str:
            if "现在投票" in user_prompt:
                return "我投旅客，他今天这条时间线没一句落在具体时辰上。"
            return "我只说看见的。"

    store, state, reply = _start(script, 3, VoteLLM())
    _set_murderer(state, "p2")
    blood._say(
        state,
        "p0",
        "旅客",
        "二十三点零五分我在楼梯口，看见沈玉兰攥着手帕。",
    )
    _enter_defense(store, state, reply, "p1")
    for player in state.players:
        if not player.is_you:
            player.suspicion = {"p0": 0.9}
    outcome = blood.vote(store, state.game_id, "p1", reply)
    for vote in outcome.votes:
        if vote.voter_id == "p0" or vote.target_id != "p0":
            continue
        assert "没一句" not in vote.reason
        assert "时辰" not in vote.reason


def test_nominate_narration_uses_female_pronoun(script: Script) -> None:
    """女性角色的自辩旁白用「她」，不得用「他」。"""
    store, state, reply = _start(script, 3)
    _set_murderer(state, "p2")
    _enter_defense(store, state, reply, "p1")
    narration = state.public_log[-2].text
    assert "先听她自辩" in narration
    assert "先听他自辩" not in narration


def test_public_speech_respects_confide_denial(script: Script) -> None:
    """廊下否认过手帕后，公开场合不能改口说攥着手帕。"""
    store, state, _ = _start(script, 3)
    state.rng = _FixedRng(0.0)  # type: ignore[assignment]
    denied = _confide(
        store,
        state,
        "p1",
        "你见过陈守义那块手帕吗？",
        reply_text="手帕我没见过。",
    )
    assert denied.ok is True
    assert "手帕" in state.private_denials["p1"]

    p1 = next(player for player in state.players if player.id == "p1")
    sanitized = blood._sanitize_agent_line(
        state,
        p1,
        "二十三点零五分我攥着手帕在楼梯口。",
    )
    assert sanitized == ""


def test_unknown_place_is_filtered(script: Script) -> None:
    """未登记地点（西厢密室）必须替换成含糊地点。"""
    _, state, _ = _start(script, 3)
    p1 = next(player for player in state.players if player.id == "p1")
    text = blood._sanitize_agent_line(state, p1, "我在西厢密室见过他。")
    assert "密室" not in text


# ---- 第五轮：runoff 与观战日志 ----


def test_runoff_rejects_non_candidate_and_keeps_candidates(
    script: Script,
) -> None:
    """5 人局 2-2 先进入重投；重投只接受候选，非候选返回明确错误。"""
    store, state, reply = _start(script, 3)
    _set_murderer(state, "p4")
    _kill(state, "p5")
    _enter_defense(store, state, reply, "p1")
    _force_votes(
        state,
        {
            "p1": "p2",
            "p2": "p1",
            "p3": "p2",
            "p4": "p3",
        },
    )
    first = blood.vote(store, state.game_id, "p1", reply)
    assert first.tally == {"p1": 2, "p2": 2, "p3": 1}
    assert first.phase == "runoff"
    assert {item.id for item in first.runoff_candidates} == {"p1", "p2"}
    bad = blood.vote(store, state.game_id, "p3", reply)
    assert bad.ok is False
    assert bad.error == "target_invalid"


def test_spectator_log_contains_advance_events(
    api: tuple[TestClient, BloodStore],
) -> None:
    """真人出局后，观战代跑的投票、夜杀与胜负都要进入 /log。"""
    client, store = api
    game_id = client.post("/blood/games").json()["game_id"]
    state = store.get(game_id)
    assert state is not None
    _set_murderer(state, "p2")

    assert (
        client.post(
            f"/blood/games/{game_id}/nominate",
            json={"target_id": "p1"},
        ).status_code
        == 200
    )
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
    voted = client.post(
        f"/blood/games/{game_id}/vote",
        json={"target_id": "p1"},
    )
    assert voted.status_code == 200
    assert voted.json()["executed"]["id"] == "p1"

    killer = next(player for player in state.players if player.id == "p2")
    killer.suspicion = {"p0": 0.9}
    night = client.post(f"/blood/games/{game_id}/night", json={})
    assert night.status_code == 200
    assert night.json()["killed"]["id"] == "p0"
    assert night.json()["phase"] == "spectating"

    guard = 0
    while state.phase != "ended" and guard < 12:
        stepped = client.post(f"/blood/games/{game_id}/advance", json={})
        assert stepped.status_code == 200
        guard += 1
    view = client.get(f"/blood/games/{game_id}").json()
    assert view["phase"] == "ended"
    assert view["winner"] in {"good", "murderer"}

    entries = client.get(f"/blood/games/{game_id}/log").json()["entries"]
    kinds = [entry["type"] for entry in entries]
    assert "night" in kinds
    assert "win" in kinds
    assert "end" in kinds
    end = next(entry for entry in entries if entry["type"] == "end")
    assert end["winner"] in {"good", "murderer"}


def test_aftermath_log_records_execution_nightkill_and_winner(
    script: Script,
) -> None:
    """规则代跑的一天要同时把处决、夜杀与胜负写进 /log。"""
    store, state, _ = _start(script, 3)
    _set_murderer(state, "p2")
    _kill(state, "p0", "p5")
    for player in state.players:
        if not player.alive or player.is_you:
            continue
        player.suspicion = {}
    for voter_id, target_id in {
        "p1": "p2",
        "p2": "p1",
        "p3": "p1",
        "p4": "p1",
    }.items():
        voter = next(player for player in state.players if player.id == voter_id)
        voter.suspicion[target_id] = 0.9
    killer = next(player for player in state.players if player.id == "p2")
    killer.suspicion = {"p1": 0.9}

    blood._end_with_you_out(state, "测试代跑。")
    entries = state.log
    kinds = [entry["type"] for entry in entries]
    assert "aftermath_day" in kinds
    assert "win" in kinds
    assert "end" in kinds
    aftermath = next(
        entry for entry in entries if entry["type"] == "aftermath_day"
    )
    assert aftermath["executed"] == "p1"
    assert aftermath["killed"] == "p3"
    assert aftermath["winner"] == "murderer"


def test_prompt_injects_today_vote_reason(script: Script) -> None:
    """重投时 prompt 必须带上当天已经写过的投票理由，避免前后改口。"""
    _, state, _ = _start(script, 12)
    p1 = next(player for player in state.players if player.id == "p1")
    state.vote_reason_log.append(
        {
            "day": state.day,
            "voter_id": p1.id,
            "target_id": "p2",
            "reason": "我投周砚青，他的话前后对不上。",
        }
    )
    _, user = blood_ai.build_prompt(p1, state)
    assert "你当天写过的投票理由" in user
    assert "我投周砚青" in user


# ---- 第七轮：夜间必杀、8 天上限、亡者票与可选公开 ----


def test_night_murderer_dead_gives_good_win(script: Script) -> None:
    """凶手已经出局或无人可杀时，夜晚直接判好人胜。"""
    store, state, _ = _start(script, 3)
    _set_murderer(state, "p2")
    _kill(state, "p2")
    state.phase = "night"
    outcome = blood.night(store, state.game_id, None)
    assert outcome.ok is True
    assert outcome.killed is None
    assert outcome.phase == "ended"
    assert outcome.winner == "good"
    assert blood.build_view(state).winner == "good"


def test_day_eight_escape_sets_murderer_winner(script: Script) -> None:
    """第 8 天仍未分出胜负时雪停，凶手脱身并写下 reason。"""
    store, state, _ = _start(script, 3)
    _set_murderer(state, "p2")
    state.day = blood.BLOOD_MAX_DAYS
    state.phase = "night"
    killer = next(player for player in state.players if player.id == "p2")
    killer.suspicion = {"p1": 0.9}
    outcome = blood.night(store, state.game_id, None)
    assert outcome.ok is True
    assert outcome.killed is not None
    assert outcome.phase == "ended"
    assert outcome.winner == "murderer"
    assert "雪" in outcome.message and "脱身" in outcome.message
    kinds = [entry["type"] for entry in state.log]
    assert "escape" in kinds
    assert "win" in kinds
    assert "end" in kinds
    assert blood.build_view(state).winner == "murderer"


def test_advance_always_reaches_winner_within_day_limit(
    script: Script,
) -> None:
    """观战反复 advance 必在 8 天内落到终局，且 winner 非空。"""
    store, state, _ = _start(script, 3)
    guard = 0
    while state.phase != "ended" and guard < 40:
        outcome = blood.advance(store, state.game_id)
        assert outcome.ok is True
        guard += 1
    assert state.phase == "ended"
    assert state.winner in {"good", "murderer"}
    assert state.day <= blood.BLOOD_MAX_DAYS
    assert blood.build_view(state).winner is not None


def test_consecutive_stalemate_lowers_threshold(script: Script) -> None:
    """连续两次僵局后，本轮门槛由 4 降到 3，并写进公开旁白。"""
    store, state, reply = _start(script, 3)
    _set_murderer(state, "p2")
    state.stalemate_count = 2
    _enter_defense(store, state, reply, "p1")
    _force_votes(
        state,
        {
            "p1": "p2",
            "p2": "p1",
            "p3": "p2",
            "p4": "p2",
            "p5": "p2",
        },
    )
    outcome = blood.vote(store, state.game_id, "p2", reply)
    assert outcome.threshold == 3
    assert outcome.executed is not None
    assert outcome.executed.id == "p2"
    assert outcome.winner == "good"
    assert outcome.stalemate_count == 0
    assert any("门槛降低到 3 票" in entry.text for entry in state.public_log)


def test_four_player_deadlock_lowers_threshold_to_two(
    script: Script,
) -> None:
    """4 人局连续僵局后门槛降到 2，两票即可处决。"""
    store, state, reply = _start(script, 3)
    _set_murderer(state, "p2")
    _kill(state, "p4", "p5")
    state.stalemate_count = 2
    _enter_defense(store, state, reply, "p1")
    _force_votes(state, {"p1": "p2", "p2": "p3", "p3": "p2"})
    outcome = blood.vote(store, state.game_id, "p2", reply)
    assert outcome.threshold == 2
    assert outcome.executed is not None
    assert outcome.executed.id == "p2"


def test_api_advance_contract_and_ghost_vote(
    api: tuple[TestClient, BloodStore],
) -> None:
    """真实链路：处决真人→spectating→advance→亡者票→只能一次→终局。"""
    client, store = api
    game_id = client.post("/blood/games").json()["game_id"]
    state = store.get(game_id)
    assert state is not None
    _set_murderer(state, "p2")
    assert (
        client.post(
            f"/blood/games/{game_id}/nominate",
            json={"target_id": "p1"},
        ).status_code
        == 200
    )
    _force_votes(
        state,
        {
            "p1": "p0",
            "p2": "p0",
            "p3": "p0",
            "p4": "p0",
            "p5": "p1",
        },
    )
    voted = client.post(
        f"/blood/games/{game_id}/vote",
        json={"target_id": "p1"},
    )
    assert voted.status_code == 200
    assert voted.json()["phase"] == "spectating"
    assert voted.json()["winner"] is None
    spectating = client.get(f"/blood/games/{game_id}").json()
    assert spectating["you_alive"] is False
    assert spectating["ghost_vote_available"] is False
    assert (
        client.post(f"/blood/games/{game_id}/advance", json={}).status_code
        == 200
    )
    view = client.get(f"/blood/games/{game_id}").json()
    assert view["phase"] in {"defense", "runoff"}
    assert view["ghost_vote_available"] is True

    if state.phase == "runoff":
        target = state.runoff_candidates[0]
    else:
        target = next(
            player.id
            for player in state.players
            if player.alive and not player.is_you
            and player.id != state.murderer_id
        )
    ghost = client.post(
        f"/blood/games/{game_id}/vote",
        json={"target_id": target, "ghost": True},
    )
    assert ghost.status_code == 200
    assert ghost.json()["phase"] in {"discussion", "night", "runoff",
                                     "spectating", "ended"}
    again = client.post(
        f"/blood/games/{game_id}/vote",
        json={"target_id": target, "ghost": True},
    )
    assert again.status_code == 409

    guard = 0
    while state.phase != "ended" and guard < 12:
        advanced = client.post(f"/blood/games/{game_id}/advance", json={})
        assert advanced.status_code == 200
        guard += 1
    final = client.get(f"/blood/games/{game_id}").json()
    assert final["phase"] == "ended"
    assert final["winner"] in {"good", "murderer"}


def test_api_advance_response_fields(
    api: tuple[TestClient, BloodStore],
) -> None:
    """advance 响应字段与 UI 契约一致。"""
    client, store = api
    game_id = client.post("/blood/games").json()["game_id"]
    state = store.get(game_id)
    assert state is not None
    _set_murderer(state, "p2")
    state.phase = "discussion"
    body = client.post(f"/blood/games/{game_id}/advance", json={}).json()
    assert set(body) == {
        "phase",
        "day",
        "public_log",
        "votes",
        "executed",
        "killed",
        "winner",
        "reveal",
        "ghost_vote_available",
    }
    assert body["phase"] in {"defense", "runoff", "ended"}
