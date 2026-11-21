"""内存局状态机：开始、提问、出示线索、查状态、指认。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.config import (
    CONFRONT_PRESSURE,
    MAX_COMBINE_PER_GAME,
    MAX_PRESSURE,
    MAX_QUESTION_CHARS,
    PRESSURE_PER_CLUE,
)
from app.engine.combine import find_rule, reaction_line
from app.engine.composer import compose
from app.engine.confront import Alignment, Statement, compare_testimony
from app.engine.intent import parse_intent
from app.engine.policy import Decision, DecisionAction, decide
from app.engine.retrieval import retrieve
from app.llm import LLMClient
from app.models import Clue, Fact, Role, Script

REPEATED_QUESTION_REPLY = "这个他刚说过了。"


@dataclass
class GameState:
    """一局的内存状态。"""

    game_id: str
    script: Script
    pressure: dict[str, float] = field(default_factory=dict)
    last_questions: dict[str, str] = field(default_factory=dict)
    unlocked_clue_ids: list[str] = field(default_factory=list)
    presented_clue_pairs: set[tuple[str, str]] = field(default_factory=set)
    disclosed_fact_ids: set[str] = field(default_factory=set)
    answered_fact_ids: dict[str, list[str]] = field(default_factory=dict)
    ended: bool = False
    accusation: AccusationOutcome | None = None
    combine_pairs: set[tuple[str, str]] = field(default_factory=set)
    combine_count: int = 0


@dataclass(frozen=True)
class AskOutcome:
    """一次提问或出示线索后的应答结果。"""

    ok: bool
    error: str | None
    reply: str | None
    pressure: float
    unlocked_clue: Clue | None
    action: DecisionAction | None
    decision: Decision | None = None


@dataclass(frozen=True)
class ConfrontReply:
    """对质中一个角色的回答。"""

    npc_id: str
    name: str
    reply: str


@dataclass(frozen=True)
class ConfrontOutcome:
    """一次对质的结果：两人原话与口径判定。"""

    ok: bool
    error: str | None
    replies: tuple[ConfrontReply, ...]
    alignment: Alignment | None
    unlocked_clues: tuple[Clue, ...]
    pressure: dict[str, float]


@dataclass(frozen=True)
class AccusationOutcome:
    """一次指认的结果。"""

    ok: bool
    error: str | None
    correct: bool
    timeline: tuple[Fact, ...]
    missed_fact_ids: tuple[str, ...]


@dataclass(frozen=True)
class CombineReaction:
    """对撞命中后相关角色的一句模板反应。"""

    npc_id: str
    name: str
    line: str


@dataclass(frozen=True)
class CombineOutcome:
    """一次线索对撞的结果：新推断、受压角色、反应与剩余次数。"""

    ok: bool
    error: str | None
    title: str | None
    text: str | None
    pressure: dict[str, float] = field(default_factory=dict)
    remaining: int = MAX_COMBINE_PER_GAME
    reaction: CombineReaction | None = None
    target_npc_id: str | None = None


@dataclass(frozen=True)
class RoleView:
    """玩家可见的角色信息。"""

    id: str
    name: str
    public: str


@dataclass(frozen=True)
class ClueView:
    """玩家可见的线索信息。"""

    id: str
    name: str
    desc: str


@dataclass(frozen=True)
class VictimView:
    """玩家可见的死者信息。"""

    id: str
    name: str
    desc: str


@dataclass(frozen=True)
class GameView:
    """玩家可见的局状态，不含秘密与真凶。"""

    game_id: str
    title: str
    era: str
    opening: str
    victim: VictimView
    roles: tuple[RoleView, ...]
    clues: tuple[ClueView, ...]
    pressure: dict[str, float]
    ended: bool
    combine_remaining: int
    combine_max: int


class GameStore:
    """内存局存储，进程重启即清空。"""

    def __init__(self) -> None:
        self._games: dict[str, GameState] = {}

    def start(self, script: Script) -> GameState:
        """创建一局并返回初始状态。"""
        game_id = str(uuid.uuid4())
        state = GameState(game_id=game_id, script=script)
        self._games[game_id] = state
        return state

    def get(self, game_id: str) -> GameState | None:
        """按 id 取局，不存在时返回空。"""
        return self._games.get(game_id)


def ask(
    store: GameStore,
    game_id: str,
    npc_id: str,
    question: str,
    llm: LLMClient | None = None,
) -> AskOutcome:
    """向指定角色提问，检索第一条事实并完成决策与生成。"""
    state = store.get(game_id)
    if state is None:
        return _ask_error("game_not_found")
    if state.ended:
        return _ask_error("game_ended")
    role = _role_index(state.script).get(npc_id)
    if role is None:
        return _ask_error("npc_not_found")
    text = question.strip()
    if not text:
        return _ask_error("empty_question")
    if len(text) > MAX_QUESTION_CHARS:
        return _ask_error("question_too_long")
    if state.last_questions.get(npc_id) == text:
        return AskOutcome(
            ok=True,
            error=None,
            reply=REPEATED_QUESTION_REPLY,
            pressure=state.pressure.get(npc_id, 0.0),
            unlocked_clue=None,
            action=None,
        )
    return _answer(state, role, text, llm)


def present_clue(
    store: GameStore,
    game_id: str,
    npc_id: str,
    clue_id: str,
    llm: LLMClient | None = None,
) -> AskOutcome:
    """出示已解锁线索：持有来源事实时重答，否则只针对物证回避。"""
    state = store.get(game_id)
    if state is None:
        return _ask_error("game_not_found")
    if state.ended:
        return _ask_error("game_ended")
    role = _role_index(state.script).get(npc_id)
    if role is None:
        return _ask_error("npc_not_found")
    clue = _clue_index(state.script).get(clue_id)
    if clue is None:
        return _ask_error("clue_not_found")
    if clue_id not in state.unlocked_clue_ids:
        return _ask_error("clue_not_unlocked")
    pair = (clue_id, npc_id)
    if pair in state.presented_clue_pairs:
        return _ask_error("clue_already_presented")
    question = state.last_questions.get(npc_id)
    if question is None:
        return _ask_error("no_question_asked")
    state.presented_clue_pairs.add(pair)
    state.pressure[npc_id] = min(
        MAX_PRESSURE,
        state.pressure.get(npc_id, 0.0) + PRESSURE_PER_CLUE,
    )
    source_fact = _fact_index(state.script).get(clue.from_)
    fact_override = (
        source_fact
        if source_fact is not None and npc_id in source_fact.holders
        else None
    )
    return _answer(
        state,
        role,
        question,
        llm,
        clue=clue,
        exclude_answered=False,
        fact_override=fact_override,
        clue_only=fact_override is None,
    )


def combine(
    store: GameStore,
    game_id: str,
    clue_ids: tuple[str, ...],
) -> CombineOutcome:
    """把两张已解锁物证对撞成一条新推断，并提升相关角色压力。"""
    state = store.get(game_id)
    if state is None:
        return _combine_error("game_not_found")
    if state.ended:
        return _combine_error("game_ended", _remaining(state))
    if len(clue_ids) != 2 or clue_ids[0] == clue_ids[1]:
        return _combine_error("combine_needs_two", _remaining(state))
    first_id, second_id = clue_ids
    clues = _clue_index(state.script)
    if first_id not in clues or second_id not in clues:
        return _combine_error("clue_not_found", _remaining(state))
    for clue_id in (first_id, second_id):
        if clue_id not in state.unlocked_clue_ids:
            return _combine_error("clue_not_unlocked", _remaining(state))
    if state.combine_count >= MAX_COMBINE_PER_GAME:
        return _combine_error(
            "combine_limit_reached",
            _remaining(state),
        )
    pair = (first_id, second_id) if first_id < second_id else (
        second_id,
        first_id,
    )
    if pair in state.combine_pairs:
        return _combine_error("combine_already_used", _remaining(state))
    rule = find_rule((first_id, second_id))
    if rule is None:
        return _combine_error("combine_not_found", _remaining(state))

    state.combine_pairs.add(pair)
    state.combine_count += 1
    pressure: dict[str, float] = {}
    reaction: CombineReaction | None = None
    target_npc_id: str | None = rule.pressure_npc
    if rule.pressure_npc is not None:
        current = state.pressure.get(rule.pressure_npc, 0.0)
        state.pressure[rule.pressure_npc] = min(
            MAX_PRESSURE,
            current + rule.pressure_delta,
        )
        pressure[rule.pressure_npc] = state.pressure[rule.pressure_npc]
        target = _role_index(state.script).get(rule.pressure_npc)
        if target is None:
            target_npc_id = None
        else:
            reaction = CombineReaction(
                npc_id=target.id,
                name=target.name,
                line=reaction_line(target.name),
            )
    return CombineOutcome(
        ok=True,
        error=None,
        title=rule.title,
        text=rule.text,
        pressure=pressure,
        remaining=_remaining(state),
        reaction=reaction,
        target_npc_id=target_npc_id,
    )


def confront(
    store: GameStore,
    game_id: str,
    npc_ids: tuple[str, ...],
    question: str,
    llm: LLMClient | None = None,
) -> ConfrontOutcome:
    """让两个角色回答同一问题，只比较口径是否一致。"""
    state = store.get(game_id)
    if state is None:
        return _confront_error("game_not_found")
    if state.ended:
        return _confront_error("game_ended")
    if len(npc_ids) != 2 or npc_ids[0] == npc_ids[1]:
        return _confront_error("confront_needs_two")
    roles = _role_index(state.script)
    left = roles.get(npc_ids[0])
    right = roles.get(npc_ids[1])
    if left is None or right is None:
        return _confront_error("npc_not_found")
    text = question.strip()
    if not text:
        return _confront_error("empty_question")
    if len(text) > MAX_QUESTION_CHARS:
        return _confront_error("question_too_long")
    for role in (left, right):
        state.pressure[role.id] = min(
            MAX_PRESSURE,
            state.pressure.get(role.id, 0.0) + CONFRONT_PRESSURE,
        )

    outcomes = [
        _answer(state, role, text, llm, exclude_answered=True)
        for role in (left, right)
    ]
    left_decision = outcomes[0].decision
    right_decision = outcomes[1].decision
    if left_decision is None or right_decision is None:
        return _confront_error("confront_failed")
    alignment = compare_testimony(
        Statement(
            action=left_decision.action,
            fact_id=left_decision.fact_id,
            content=left_decision.content,
        ),
        Statement(
            action=right_decision.action,
            fact_id=right_decision.fact_id,
            content=right_decision.content,
        ),
    )
    replies = tuple(
        ConfrontReply(
            npc_id=role.id,
            name=role.name,
            reply=outcome.reply or "",
        )
        for role, outcome in zip((left, right), outcomes)
    )
    unlocked = tuple(
        outcome.unlocked_clue
        for outcome in outcomes
        if outcome.unlocked_clue is not None
    )
    return ConfrontOutcome(
        ok=True,
        error=None,
        replies=replies,
        alignment=alignment,
        unlocked_clues=unlocked,
        pressure={
            role.id: state.pressure.get(role.id, 0.0)
            for role in (left, right)
        },
    )


def get_view(store: GameStore, game_id: str) -> GameView | None:
    """返回玩家可见状态，局不存在时返回空。"""

    state = store.get(game_id)
    if state is None:
        return None
    return build_view(state)


def accuse(
    store: GameStore,
    game_id: str,
    suspect_id: str,
) -> AccusationOutcome:
    """指认凶手，返回命中结果、真相时间线和漏掉的破案链事实。"""
    state = store.get(game_id)
    if state is None:
        return _accusation_error("game_not_found")
    if state.ended:
        if state.accusation is not None:
            return state.accusation
        return _accusation_error("game_ended")
    if _role_index(state.script).get(suspect_id) is None:
        return _accusation_error("npc_not_found")

    facts = _fact_index(state.script)
    timeline = tuple(
        facts[fact_id]
        for fact_id in state.script.solution_path
        if fact_id in facts
    )
    missed = tuple(
        fact_id
        for fact_id in state.script.solution_path
        if fact_id not in state.disclosed_fact_ids
    )
    outcome = AccusationOutcome(
        ok=True,
        error=None,
        correct=suspect_id == state.script.culprit,
        timeline=timeline,
        missed_fact_ids=missed,
    )
    state.ended = True
    state.accusation = outcome
    return outcome


def build_view(state: GameState) -> GameView:
    """构造玩家可见状态，过滤秘密、真凶与事实原文。"""
    clues = _clue_index(state.script)
    unlocked: list[ClueView] = []
    for clue_id in state.unlocked_clue_ids:
        clue = clues.get(clue_id)
        if clue is None:
            continue
        unlocked.append(
            ClueView(id=clue.id, name=clue.name, desc=clue.desc)
        )
    roles = tuple(
        RoleView(id=role.id, name=role.name, public=role.public)
        for role in state.script.roles
    )
    return GameView(
        game_id=state.game_id,
        title=state.script.title,
        era=state.script.era,
        opening=state.script.opening,
        victim=VictimView(
            id=state.script.victim.id,
            name=state.script.victim.name,
            desc=state.script.victim.desc,
        ),
        roles=roles,
        clues=tuple(unlocked),
        pressure={
            role.id: state.pressure.get(role.id, 0.0)
            for role in state.script.roles
        },
        ended=state.ended,
        combine_remaining=_remaining(state),
        combine_max=MAX_COMBINE_PER_GAME,
    )


def _answer(
    state: GameState,
    role: Role,
    question: str,
    llm: LLMClient | None,
    clue: Clue | None = None,
    exclude_answered: bool = True,
    fact_override: Fact | None = None,
    clue_only: bool = False,
) -> AskOutcome:
    intent = parse_intent(question)
    if clue_only:
        fact = None
    elif fact_override is not None:
        fact = fact_override
    else:
        exclude_ids = (
            state.answered_fact_ids.get(role.id, [])
            if exclude_answered
            else []
        )
        candidates = retrieve(
            state.script,
            role.id,
            intent,
            exclude_ids=exclude_ids,
        )
        fact = candidates[0] if candidates else None
    pressure = state.pressure.get(role.id, 0.0)
    if clue_only:
        decision = Decision(
            action="evade",
            fact_id=None,
            content=None,
            is_lie=False,
            risk=0.0,
        )
    else:
        decision = decide(role, fact, intent, pressure)
    reply = compose(
        role,
        decision,
        fact,
        state.script,
        llm,
        clue=clue,
    )
    state.last_questions[role.id] = question
    if fact is not None:
        answered = state.answered_fact_ids.setdefault(role.id, [])
        if fact.id not in answered:
            answered.append(fact.id)

    unlocked_clue: Clue | None = None
    if (
        decision.action == "disclose"
        and fact is not None
        and decision.content == fact.text
    ):
        state.disclosed_fact_ids.add(fact.id)
        first_clue = _first_clue_for_fact(state.script, fact.id)
        if (
            first_clue is not None
            and first_clue.id not in state.unlocked_clue_ids
        ):
            state.unlocked_clue_ids.append(first_clue.id)
            unlocked_clue = first_clue
    return AskOutcome(
        ok=True,
        error=None,
        reply=reply,
        pressure=pressure,
        unlocked_clue=unlocked_clue,
        action=decision.action,
        decision=decision,
    )


def _ask_error(error: str) -> AskOutcome:
    return AskOutcome(
        ok=False,
        error=error,
        reply=None,
        pressure=0.0,
        unlocked_clue=None,
        action=None,
    )


def _confront_error(error: str) -> ConfrontOutcome:
    return ConfrontOutcome(
        ok=False,
        error=error,
        replies=(),
        alignment=None,
        unlocked_clues=(),
        pressure={},
    )


def _accusation_error(error: str) -> AccusationOutcome:
    return AccusationOutcome(
        ok=False,
        error=error,
        correct=False,
        timeline=(),
        missed_fact_ids=(),
    )


def _combine_error(
    error: str,
    remaining: int = MAX_COMBINE_PER_GAME,
) -> CombineOutcome:
    return CombineOutcome(
        ok=False,
        error=error,
        title=None,
        text=None,
        remaining=remaining,
    )


def _remaining(state: GameState) -> int:
    """返回本局剩余的对撞次数。"""
    return max(0, MAX_COMBINE_PER_GAME - state.combine_count)


def _role_index(script: Script) -> dict[str, Role]:
    return {role.id: role for role in script.roles}


def _fact_index(script: Script) -> dict[str, Fact]:
    return {fact.id: fact for fact in script.facts}


def _clue_index(script: Script) -> dict[str, Clue]:
    return {clue.id: clue for clue in script.clues}


def _first_clue_for_fact(script: Script, fact_id: str) -> Clue | None:
    for clue in script.clues:
        if clue.from_ == fact_id:
            return clue
    return None