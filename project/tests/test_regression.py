"""回归测试：固化已经踩过的坑。"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.engine.composer import build_user_prompt, compose
from app.engine.intent import parse_intent
from app.engine.policy import Decision, decide
from app.engine.retrieval import retrieve
from app.engine.verifier import verify_reply
from app.game import GameStore, accuse, ask, build_view, present_clue
from app.llm import LLMUnavailable
from app.main import create_app
from app.models import Fact, Role, Script
from app.script_loader import (
    ScriptValidationError,
    load_script,
    parse_script,
)

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "scripts"
    / "mistvale-inn.json"
)


class FakeLLM:
    def __init__(self, reply: str = "我只记得些片段，但说不清。") -> None:
        self.reply = reply
        self.calls = 0

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        return self.reply


class UnavailableLLM:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        raise LLMUnavailable("timeout")


@pytest.fixture(scope="module")
def script() -> Script:
    return load_script(SCRIPT_PATH)


@pytest.fixture
def store() -> GameStore:
    return GameStore()


def _role(script: Script, role_id: str) -> Role:
    return next(role for role in script.roles if role.id == role_id)


def _fact(script: Script, fact_id: str) -> Fact:
    return next(fact for fact in script.facts if fact.id == fact_id)


def _evade_decision(fact_id: str) -> Decision:
    return Decision(
        action="evade",
        fact_id=fact_id,
        content=None,
        is_lie=False,
        risk=0.6,
    )


@pytest.mark.parametrize(
    "token",
    ["书房", "从书房出来", "右袖", "沾着灰", "23:00"],
)
def test_evade_prompt_does_not_leak_observation(
    script: Script,
    token: str,
) -> None:
    fact = _fact(script, "f05")
    prompt = build_user_prompt(_evade_decision("f05"), fact)

    assert token not in prompt


def test_evade_reply_does_not_repeat_observation(
    script: Script,
    store: GameStore,
) -> None:
    fact = _fact(script, "f05")
    state = store.start(script)
    llm = FakeLLM(fact.text)
    outcome = ask(
        store,
        state.game_id,
        "r3",
        "那晚你看见什么",
        llm,
    )

    assert outcome.ok is True
    assert outcome.action == "evade"
    reply = outcome.reply or ""
    for token in ("书房", "出来", "袖", "灰", "23:00"):
        assert token not in reply
    assert llm.calls == 3


def test_zhou_belief_time_is_used_instead_of_objective_time(
    script: Script,
) -> None:
    fact = _fact(script, "f03")
    decision = decide(
        _role(script, "r2"),
        fact,
        parse_intent("争吵什么时候停的"),
        0.0,
    )

    assert decision.action == "disclose"
    assert "23:10" in (decision.content or "")
    assert "22:45" not in (decision.content or "")


def test_zhou_composer_keeps_belief_version(script: Script) -> None:
    role = _role(script, "r2")
    fact = _fact(script, "f03")
    decision = decide(
        role,
        fact,
        parse_intent("争吵什么时候停的"),
        0.0,
    )
    reply = compose(
        role,
        decision,
        fact,
        script,
        FakeLLM(decision.content or ""),
    )

    assert "23:10" in reply
    assert "22:45" not in reply


def test_same_clue_same_npc_returns_409(
    script: Script,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOCK_LLM", "1")
    client = TestClient(create_app(script, GameStore()))
    game_id = client.post("/games").json()["game_id"]
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


def test_two_clues_make_ahuang_disclose(
    script: Script,
    store: GameStore,
) -> None:
    state = store.start(script)
    ask(store, state.game_id, "r3", "壁炉边的拨火棍呢", FakeLLM())
    ask(store, state.game_id, "r2", "争吵什么时候停的", FakeLLM())
    ask(store, state.game_id, "r3", "那晚你看见什么", FakeLLM())

    first = present_clue(
        store,
        state.game_id,
        "r3",
        "c03",
        FakeLLM(),
    )
    second = present_clue(
        store,
        state.game_id,
        "r3",
        "c08",
        FakeLLM(),
    )

    assert first.action == "disclose"
    assert first.decision is not None
    assert first.decision.fact_id == "f07"
    assert first.pressure == pytest.approx(0.25)
    assert second.action == "disclose"
    assert second.decision is not None
    assert second.decision.fact_id == "f02"
    assert second.pressure == pytest.approx(0.5)
    assert second.unlocked_clue is None


def test_llm_unavailable_falls_back_after_one_call(
    script: Script,
) -> None:
    role = _role(script, "r1")
    fact = _fact(script, "f04")
    decision = Decision(
        action="disclose",
        fact_id="f04",
        content=fact.text,
        is_lie=False,
        risk=0.2,
    )
    llm = UnavailableLLM()

    reply = compose(role, decision, fact, script, llm)

    assert reply == fact.text + "。"
    assert llm.calls == 1


@pytest.mark.parametrize("npc_id", ["r2", "r4", "r5"])
def test_weapon_question_empty_for_non_holders(
    script: Script,
    npc_id: str,
) -> None:
    hits = retrieve(script, npc_id, parse_intent("凶器是什么"))

    assert hits == []


def test_r4_cannot_retrieve_ahuang_observation(script: Script) -> None:
    hits = retrieve(
        script,
        "r4",
        parse_intent("你看见沈玉兰从书房出来吗"),
    )

    assert "f05" not in {fact.id for fact in hits}
    assert all("r4" in fact.holders for fact in hits)


@pytest.mark.parametrize(
    "draft",
    [
        "我一推门就看见她出来。",
        "我一直在这儿。",
        "我们一起下的楼。",
    ],
)
def test_bare_chinese_numerals_do_not_trigger(
    script: Script,
    draft: str,
) -> None:
    result = verify_reply(
        draft,
        _fact(script, "f05").text,
        _role(script, "r3"),
    )

    assert result.ok is True


def test_chinese_time_still_rejected(script: Script) -> None:
    result = verify_reply(
        "十点半，我看见她出来。",
        _fact(script, "f05").text,
        _role(script, "r3"),
    )

    assert result.ok is False
    assert "十点半" in (result.reason or "")


def test_invalid_topic_value_is_rejected() -> None:
    raw = json.loads(SCRIPT_PATH.read_text(encoding="utf-8"))
    raw["facts"][0]["topic"] = ["time", "money"]

    with pytest.raises(ScriptValidationError) as raised:
        parse_script(raw)

    assert "facts[f01].topic[1]" in [
        issue.path for issue in raised.value.issues
    ]


def test_risk_is_independent_of_lie_propensity(script: Script) -> None:
    fact = _fact(script, "f04")
    base_role = _role(script, "r1")
    honest = base_role.model_copy(update={"lie_propensity": 0.0})
    liar = base_role.model_copy(update={"lie_propensity": 1.0})
    intent = parse_intent("凶器")

    assert decide(honest, fact, intent, 0.5).risk == decide(
        liar,
        fact,
        intent,
        0.5,
    ).risk


def test_pressure_moves_from_lie_to_disclose(script: Script) -> None:
    role = _role(script, "r1")
    fact = _fact(script, "f04")
    intent = parse_intent("凶器")

    assert decide(role, fact, intent, 0.0).action == "lie"
    assert decide(role, fact, intent, 1.0).action == "disclose"


def test_belief_is_never_recorded_as_lie(script: Script) -> None:
    fact = _fact(script, "f03").model_copy(update={"sensitivity": 1.0})
    decision = decide(
        _role(script, "r2"),
        fact,
        parse_intent("争吵什么时候停的"),
        0.0,
    )

    assert decision.action == "evade"
    assert decision.is_lie is False


def test_accuse_returns_only_missed_fact_ids(
    script: Script,
    store: GameStore,
) -> None:
    state = store.start(script)
    outcome = accuse(store, state.game_id, "r1")

    assert outcome.ok is True
    assert outcome.missed_fact_ids == tuple(script.solution_path)
    assert [fact.id for fact in outcome.timeline] == script.solution_path
    assert all(isinstance(fact_id, str) for fact_id in outcome.missed_fact_ids)


def test_state_view_has_no_secret_or_culprit(
    script: Script,
    store: GameStore,
) -> None:
    payload = asdict(build_view(store.start(script)))

    assert "culprit" not in payload
    assert "solution_path" not in payload
    assert "secret" not in str(payload)


def test_disclose_auto_unlocks_clue(
    script: Script,
    store: GameStore,
) -> None:
    state = store.start(script)
    outcome = ask(
        store,
        state.game_id,
        "r3",
        "壁炉边的拨火棍呢",
        FakeLLM(),
    )

    assert outcome.action == "disclose"
    assert outcome.unlocked_clue is not None
    assert outcome.unlocked_clue.id == "c03"


def test_observation_clue_unlocks_from_f02(
    script: Script,
    store: GameStore,
) -> None:
    state = store.start(script)
    outcome = ask(
        store,
        state.game_id,
        "r2",
        "争吵什么时候停的",
        FakeLLM(),
    )

    assert outcome.action == "disclose"
    assert outcome.unlocked_clue is not None
    assert outcome.unlocked_clue.id == "c08"


def test_unparsed_and_true_unknown_are_distinct(script: Script) -> None:
    role = _role(script, "r4")
    vague = decide(role, None, parse_intent("那根棍子呢"), 0.0)
    unknown = decide(role, None, parse_intent("凶器是什么"), 0.0)

    assert vague.action == "unparsed"
    assert unknown.action == "evade"
    assert unknown.fact_id is None


def test_unknown_game_returns_error(store: GameStore) -> None:
    outcome = ask(store, "missing", "r3", "问题", FakeLLM())

    assert outcome.error == "game_not_found"


def test_present_locked_clue_is_rejected(
    script: Script,
    store: GameStore,
) -> None:
    state = store.start(script)
    outcome = present_clue(store, state.game_id, "r3", "c01", FakeLLM())

    assert outcome.error == "clue_not_unlocked"


def test_static_frontend_is_served(script: Script) -> None:
    client = TestClient(create_app(script, GameStore()))
    response = client.get("/")

    assert response.status_code == 200
    assert "雾镇旅馆" in response.text