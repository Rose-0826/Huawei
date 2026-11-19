"""内存局状态机：开始、提问、出示线索、查状态、指认。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.config import MAX_PRESSURE, MAX_QUESTION_CHARS, PRESSURE_PER_CLUE
from app.engine.composer import compose
from app.engine.intent import parse_intent
from app.engine.policy import DecisionAction, decide
from app.engine.retrieval import retrieve
from app.llm import LLMClient
from app.models import Clue, Fact, Role, Script


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
    ended: bool = False
    accusation: AccusationOutcome | None = None


@dataclass(frozen=True)
class AskOutcome:
    """一次提问或出示线索后的应答结果。"""

    ok: bool
    error: str | None
    reply: str | None
    pressure: float
    unlocked_clue: Clue | None
    action: DecisionAction | None


@dataclass(frozen=True)
class AccusationOutcome:
    """一次指认的结果。"""

    ok: bool
    error: str | None
    correct: bool
    timeline: tuple[Fact, ...]
    missed_fact_ids: tuple[str, ...]


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
    return _answer(state, role, text, llm)


def present_clue(
    store: GameStore,
    game_id: str,
    npc_id: str,
    clue_id: str,
    llm: LLMClient | None = None,
) -> AskOutcome:
    """出示已解锁线索，增加目标压力并立即重答上一问。"""
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
    return _answer(state, role, question, llm)


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
    )


def _answer(
    state: GameState,
    role: Role,
    question: str,
    llm: LLMClient | None,
) -> AskOutcome:
    intent = parse_intent(question)
    candidates = retrieve(state.script, role.id, intent)
    fact = candidates[0] if candidates else None
    pressure = state.pressure.get(role.id, 0.0)
    decision = decide(role, fact, intent, pressure)
    reply = compose(role, decision, fact, state.script, llm)
    state.last_questions[role.id] = question

    unlocked_clue: Clue | None = None
    if decision.action == "disclose" and fact is not None:
        if decision.content == fact.text:
            state.disclosed_fact_ids.add(fact.id)
        clue = _first_clue_for_fact(state.script, fact.id)
        if clue is not None and clue.id not in state.unlocked_clue_ids:
            state.unlocked_clue_ids.append(clue.id)
            unlocked_clue = clue
    return AskOutcome(
        ok=True,
        error=None,
        reply=reply,
        pressure=pressure,
        unlocked_clue=unlocked_clue,
        action=decision.action,
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


def _accusation_error(error: str) -> AccusationOutcome:
    return AccusationOutcome(
        ok=False,
        error=error,
        correct=False,
        timeline=(),
        missed_fact_ids=(),
    )


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