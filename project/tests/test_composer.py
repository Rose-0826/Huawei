"""composer 措辞生成测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.engine.composer import (
    _allowed_text,
    build_system_prompt,
    build_user_prompt,
    compose,
    fallback_reply,
)
from app.engine.policy import Decision
from app.llm import LLMUnavailable
from app.models import Clue, Fact, Role, Script
from app.script_loader import load_script

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "scripts"
    / "mistvale-inn.json"
)


class FakeLLM:
    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.calls: list[tuple[str, str]] = []

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        index = min(len(self.calls) - 1, len(self.replies) - 1)
        return self.replies[index]


class UnavailableLLM:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        raise LLMUnavailable("timeout")


@pytest.fixture(scope="module")
def script() -> Script:
    return load_script(SCRIPT_PATH)


def _role(script: Script, role_id: str) -> Role:
    return next(role for role in script.roles if role.id == role_id)


def _fact(script: Script, fact_id: str) -> Fact:
    return next(fact for fact in script.facts if fact.id == fact_id)


def _disclose(fact: Fact) -> Decision:
    return Decision(
        action="disclose",
        fact_id=fact.id,
        content=fact.text,
        is_lie=False,
        risk=0.2,
    )


def _clue(script: Script, clue_id: str) -> Clue:
    return next(clue for clue in script.clues if clue.id == clue_id)


def test_disclose_returns_valid_draft(script: Script) -> None:
    fact = _fact(script, "f05")
    role = _role(script, "r3")
    llm = FakeLLM(["23:00，我上楼送炭，看见她出来。"])

    result = compose(role, _disclose(fact), fact, script, llm)

    assert result == "23:00，我上楼送炭，看见她出来。"


def test_bad_time_triggers_rewrite_with_reason(script: Script) -> None:
    fact = _fact(script, "f05")
    role = _role(script, "r3")
    llm = FakeLLM(
        [
            "十一点多吧，我看见她出来。",
            "23:00，我上楼送炭，看见她出来。",
        ]
    )

    result = compose(role, _disclose(fact), fact, script, llm)

    assert result == "23:00，我上楼送炭，看见她出来。"
    assert len(llm.calls) == 2
    assert "时间和事实不符" in llm.calls[1][1]


def test_two_bad_attempts_fall_back_to_template(script: Script) -> None:
    fact = _fact(script, "f05")
    role = _role(script, "r3")
    llm = FakeLLM(
        [
            "快十二点吧。",
            "快十二点吧。",
            "快十二点吧。",
        ]
    )

    result = compose(role, _disclose(fact), fact, script, llm)

    assert len(llm.calls) == 3
    assert result == fact.text + "。"


def test_mock_llm_runs_without_key(
    script: Script,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOCK_LLM", "1")
    for name in ("MAAS_API_KEY", "MAAS_ENDPOINT", "MAAS_MODEL"):
        monkeypatch.delenv(name, raising=False)

    fact = _fact(script, "f05")
    role = _role(script, "r3")
    result = compose(role, _disclose(fact), fact, script)

    assert result
    assert "23:00" not in result


def test_system_prompt_contains_role_settings(script: Script) -> None:
    role = _role(script, "r1")

    prompt = build_system_prompt(role, script)

    assert "沈玉兰" in prompt
    assert "老板娘" in prompt
    assert role.secret in prompt
    assert role.goal in prompt
    assert "周砚青" in prompt


def test_system_prompt_contains_interrogator_context(
    script: Script,
) -> None:
    prompt = build_system_prompt(_role(script, "r3"), script)

    assert "单独问话" in prompt
    assert "陈守义" in prompt
    assert "不像住客" in prompt
    assert "提防" in prompt


def test_system_prompt_forbids_naming_interviewer(script: Script) -> None:
    prompt = build_system_prompt(_role(script, "r1"), script)

    assert "问话的人你不认识" in prompt
    assert "不要把他当成剧中的任何角色" in prompt
    assert "不要称呼他的姓名" in prompt


def test_user_prompt_distinguishes_evade_states(script: Script) -> None:
    fact = _fact(script, "f09")
    unknown = Decision(
        action="evade",
        fact_id=None,
        content=None,
        is_lie=False,
        risk=0.0,
    )
    withhold = Decision(
        action="evade",
        fact_id="f09",
        content=None,
        is_lie=False,
        risk=0.6,
    )

    unknown_prompt = build_user_prompt(unknown, None)
    withhold_prompt = build_user_prompt(withhold, fact)

    assert "简短地说你不知道" in unknown_prompt
    assert "含糊" in withhold_prompt


def test_evade_prompt_does_not_leak_fact_text(script: Script) -> None:
    fact = _fact(script, "f05")
    decision = Decision(
        action="evade",
        fact_id="f05",
        content=None,
        is_lie=False,
        risk=0.6,
    )

    prompt = build_user_prompt(decision, fact)

    assert fact.text not in prompt
    assert "23:00" not in prompt
    assert "送炭" not in prompt
    assert "右袖沾着灰" not in prompt
    assert "你知道这件事，但不愿说" in prompt
    assert "关于那段时间你在哪里" in prompt


def test_unparsed_prompt_asks_back(script: Script) -> None:
    decision = Decision(
        action="unparsed",
        fact_id=None,
        content=None,
        is_lie=False,
        risk=0.0,
    )

    prompt = build_user_prompt(decision, None)

    assert "反问" in prompt


def test_belief_disclose_uses_belief_content(script: Script) -> None:
    fact = _fact(script, "f03")
    role = _role(script, "r2")
    decision = Decision(
        action="disclose",
        fact_id="f03",
        content=fact.belief["r2"],
        is_lie=False,
        risk=0.2,
    )
    llm = FakeLLM([fact.belief["r2"]])

    result = compose(role, decision, fact, script, llm)

    assert result == fact.belief["r2"]
    prompt = llm.calls[0][1]
    assert fact.belief["r2"] in prompt
    assert fact.text not in prompt


def test_secret_leak_rewrites_then_falls_back(script: Script) -> None:
    role = _role(script, "r1")
    fact = _fact(script, "f04")
    llm = FakeLLM([role.secret, role.secret, role.secret])

    result = compose(role, _disclose(fact), fact, script, llm)

    assert result == fact.text + "。"
    assert "秘密" in llm.calls[1][1]


def test_fallback_replies_avoid_new_information(script: Script) -> None:
    role = _role(script, "r1")
    decisions = [
        Decision(
            action="lie",
            fact_id="f04",
            content=None,
            is_lie=True,
            risk=0.9,
        ),
        Decision(
            action="evade",
            fact_id="f04",
            content=None,
            is_lie=False,
            risk=0.6,
        ),
        Decision(
            action="evade",
            fact_id=None,
            content=None,
            is_lie=False,
            risk=0.0,
        ),
        Decision(
            action="unparsed",
            fact_id=None,
            content=None,
            is_lie=False,
            risk=0.0,
        ),
    ]

    for decision in decisions:
        reply = fallback_reply(decision, role)
        assert reply
        assert "23:" not in reply
        assert "十" not in reply


def test_empty_draft_triggers_rewrite_and_fallback(script: Script) -> None:
    fact = _fact(script, "f05")
    role = _role(script, "r3")
    llm = FakeLLM(["", "", ""])

    result = compose(role, _disclose(fact), fact, script, llm)

    assert result == fact.text + "。"
    assert len(llm.calls) == 3
    assert "回答为空" in llm.calls[1][1]

def test_unparsed_cannot_answer_unknown(script: Script) -> None:
    role = _role(script, "r3")
    decision = Decision(
        action="unparsed",
        fact_id=None,
        content=None,
        is_lie=False,
        risk=0.0,
    )
    llm = FakeLLM(["我不知道。", "你这话是什么意思？"])

    result = compose(role, decision, None, script, llm)

    assert result == "你这话是什么意思？"
    assert len(llm.calls) == 2
    assert "反问" in llm.calls[1][1]


def test_known_evade_cannot_answer_unknown(script: Script) -> None:
    role = _role(script, "r1")
    fact = _fact(script, "f04")
    decision = Decision(
        action="evade",
        fact_id="f04",
        content=None,
        is_lie=False,
        risk=0.6,
    )
    llm = FakeLLM(["我不知道。", "有些事，你还是别问得太细。"])

    result = compose(role, decision, fact, script, llm)

    assert result == "有些事，你还是别问得太细。"
    assert len(llm.calls) == 2
    assert "含糊" in llm.calls[1][1]


def test_evade_cannot_repeat_fact_details(script: Script) -> None:
    fact = _fact(script, "f05")
    role = _role(script, "r3")
    decision = Decision(
        action="evade",
        fact_id="f05",
        content=None,
        is_lie=False,
        risk=0.6,
    )
    llm = FakeLLM([fact.text, "有些事，你还是别问得太细。"])

    result = compose(role, decision, fact, script, llm)

    assert result == "有些事，你还是别问得太细。"
    assert len(llm.calls) == 2
    assert fact.text not in llm.calls[0][1]
    assert "时间和事实不符" in llm.calls[1][1]

def test_llm_unavailable_falls_back_without_retry(
    script: Script,
) -> None:
    fact = _fact(script, "f05")
    role = _role(script, "r3")
    llm = UnavailableLLM()

    result = compose(role, _disclose(fact), fact, script, llm)

    assert result == fact.text + "。"
    assert llm.calls == 1

def test_clue_prompt_contains_evidence(script: Script) -> None:
    fact = _fact(script, "f02")
    role = _role(script, "r3")
    clue = _clue(script, "c08")
    llm = FakeLLM(["我瞧见这东西，心里咯噔一下。"])

    result = compose(role, _disclose(fact), fact, script, llm, clue=clue)

    prompt = llm.calls[0][1]
    assert result == "我瞧见这东西，心里咯噔一下。"
    assert clue.name in prompt
    assert clue.desc in prompt
    assert "物证" in prompt
    assert "仍受当前动作约束" in prompt


def test_plain_prompt_has_no_evidence(script: Script) -> None:
    fact = _fact(script, "f02")
    role = _role(script, "r3")
    llm = FakeLLM(["那会儿我在楼下听见吵声。"])

    compose(role, _disclose(fact), fact, script, llm)

    assert "物证" not in llm.calls[0][1]


def test_lie_prompt_omits_fact_text_and_allowed_text(script: Script) -> None:
    fact = _fact(script, "f11")
    decision = Decision(
        action="lie",
        fact_id="f11",
        content=None,
        is_lie=True,
        risk=0.9,
    )

    prompt = build_user_prompt(decision, fact)

    assert fact.text not in prompt
    assert "银元" not in prompt
    assert _allowed_text(decision, fact) == ""


def test_lie_system_prompt_forbids_new_concrete_details(
    script: Script,
) -> None:
    fact = _fact(script, "f11")
    role = _role(script, "r1")
    decision = Decision(
        action="lie",
        fact_id="f11",
        content=None,
        is_lie=True,
        risk=0.9,
    )
    llm = FakeLLM(["那会儿我在忙自己的事，没留意别的。"])

    compose(role, decision, fact, script, llm)

    system_prompt, user_prompt = llm.calls[0]
    assert fact.text not in user_prompt
    assert "不得新增具体地点/气味/物件" in system_prompt
    assert _allowed_text(decision, fact) == ""


def test_lie_cannot_copy_fact_verbatim(script: Script) -> None:
    fact = _fact(script, "f07")
    role = _role(script, "r3")
    decision = Decision(
        action="lie",
        fact_id="f07",
        content=None,
        is_lie=True,
        risk=0.9,
    )
    llm = FakeLLM([fact.text, fact.text, fact.text])

    result = compose(role, decision, fact, script, llm)

    assert result == "那会儿我在忙自己的事，没留意别的。"
    assert "撒谎" in llm.calls[1][1]