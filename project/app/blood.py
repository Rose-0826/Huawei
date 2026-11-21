"""阵营模式「电子血染」的状态机：只做状态转移，不调用模型。"""

from __future__ import annotations

import logging
import random
import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Literal

from app.config import (
    BLOOD_AFTERMATH_MAX_DAYS,
    BLOOD_INITIAL_SUSPICION_BASE,
    BLOOD_INITIAL_SUSPICION_JITTER,
    BLOOD_MAX_DEFENSE_SPEAK_PER_DAY,
    BLOOD_MAX_FACTS_PER_DAY,
    BLOOD_MAX_LINE_CHARS,
    BLOOD_MAX_SPEAK_PER_DAY,
    BLOOD_MAX_SUSPICION,
    BLOOD_PRIVATE_FACTS_MAX,
    BLOOD_PRIVATE_FACTS_MIN,
    BLOOD_PRIVATE_MAX_SENSITIVITY,
    BLOOD_SECRET_CLAIM_TERMS,
    BLOOD_SECRET_IDENTITY_TERMS,
    BLOOD_SUSPICION_FACT,
    BLOOD_SUSPICION_MENTION,
    BLOOD_SUSPICION_MURDERER,
    BLOOD_VAGUE_REWRITE,
    BLOOD_VOTE_REASON_MAX_CHARS,
)
from app.models import Script

logger = logging.getLogger(__name__)

RoleKind = Literal["villager", "murderer"]
Phase = Literal["discussion", "defense", "night", "ended"]
Winner = Literal["good", "murderer"]

YOU_ID = "p0"
YOU_NAME = "你"
YOU_PUBLIC = "旅客"
AGENT_ROLE_IDS: tuple[tuple[str, str], ...] = (
    ("p1", "r1"),
    ("p2", "r2"),
    ("p3", "r3"),
    ("p4", "r4"),
    ("p5", "r5"),
)
FALLBACK_NAMES: dict[str, str] = {
    "p1": "沈玉兰",
    "p2": "周砚青",
    "p3": "阿蘅",
    "p4": "陆明川",
    "p5": "老韩",
}
FALLBACK_PUBLICS: dict[str, str] = {
    "p1": "老板娘",
    "p2": "账房先生",
    "p3": "女佣",
    "p4": "旅客",
    "p5": "马夫",
}
AGENT_ADDRESS_ALIASES: dict[str, tuple[str, ...]] = {
    "p1": ("沈玉兰", "沈老板娘", "沈老板", "老板娘"),
    "p2": ("周砚青", "周先生", "账房"),
    "p3": ("阿蘅",),
    "p4": ("陆明川", "陆先生", "陆老板"),
    "p5": ("老韩",),
}
YOU_WITNESS_KEYWORDS: tuple[str, ...] = ("书房", "楼梯口", "拨火棍")
YOU_WITNESS_FALLBACK: str = "你记得楼上书房里闹过一阵响动，像是桌椅被撞了一下。"
FORBIDDEN_AGENT_CLAIMS: tuple[str, ...] = ("我是凶手", "我是好人", "我是清白的")
DEFENSE_FALLBACKS: dict[str, str] = {
    "p1": "你提名我，我认一句：那晚我进过二楼，是点灯油查账，没进书房。要查就查谁在我之后下了楼。",
    "p2": "你提名我，这笔账我不认。那晚我在楼梯口听见书房吵得凶，就没敢往前——听见和动手是两回事。",
    "p3": "你提名我，我把话说明白：我上楼送过炭，灯太暗，书房门是掩着的，我没进去。谁最后出来，你们该问。",
    "p4": "你提名我，我认我去过二楼。我是听见闷响才探头，没敢声张。可要说动手，我连拨火棍都没碰过。",
    "p5": "你提名我，我认我没说全。那晚我在马厩添草，后来端热水进去，人已经没了。我瞒的是别的，不是人命。",
}
DEFENSE_FALLBACK_DEFAULT: str = (
    "你提名我，我不能不答。那晚我在哪儿、做过什么，我都说了，没进过书房。"
)
VOTE_REASON_FALLBACKS: tuple[str, ...] = (
    "我投{name}，他刚才的话前后对不上。",
    "我投{name}，那一晚他一直没交代清楚。",
    "我投{name}，这屋里数他的说法最含糊。",
)
VOTE_REASON_TARGET_TEMPLATE: str = "我投{name}，因为今晚他的说法最对不上。"
AFTERMATH_DEATH_PLACE: str = "走廊"


@dataclass
class BloodPlayer:
    """一名玩家：公开信息、阵营、私有信息与怀疑值。"""

    id: str
    name: str
    public: str
    role: RoleKind
    is_you: bool
    role_id: str | None = None
    private_info: list[str] = field(default_factory=list)
    suspicion: dict[str, float] = field(default_factory=dict)
    alive: bool = True
    released: set[int] = field(default_factory=set)
    released_day: int = 0
    released_today: int = 0


@dataclass(frozen=True)
class BloodLogEntry:
    """公开频道里的一条发言。"""

    seq: int
    speaker_id: str
    speaker_name: str
    text: str


@dataclass
class BloodState:
    """一局阵营模式的内存状态。"""

    game_id: str
    script: Script
    day: int = 1
    phase: Phase = "discussion"
    players: list[BloodPlayer] = field(default_factory=list)
    murderer_id: str = ""
    public_log: list[BloodLogEntry] = field(default_factory=list)
    log: list[dict[str, object]] = field(default_factory=list)
    discussed: bool = False
    speak_count: int = 0
    nominated: bool = False
    nominee_id: str | None = None
    defense_speak_count: int = 0
    speak_cursor: int = 0
    winner: Winner | None = None
    message: str = ""
    aftermath: list[dict[str, object]] = field(default_factory=list)
    pending_hint: str = ""
    pending_target_id: str | None = None
    pending_fact: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PlayerView:
    """玩家可见的玩家信息。"""

    id: str
    name: str
    public: str
    alive: bool
    is_you: bool


@dataclass(frozen=True)
class DeadView:
    """已出局玩家。"""

    id: str
    name: str


@dataclass(frozen=True)
class YouView:
    """只返回给真人的身份信息。"""

    id: str
    name: str
    role: RoleKind
    private_info: tuple[str, ...]
    teammates: tuple[str, ...]


@dataclass(frozen=True)
class RevealView:
    """终局揭晓的凶手身份。"""

    murderer_id: str
    murderer_name: str


@dataclass(frozen=True)
class BloodView:
    """一局的公开视图。"""

    game_id: str
    day: int
    phase: Phase
    players: tuple[PlayerView, ...]
    you: YouView
    public_log: tuple[BloodLogEntry, ...]
    dead: tuple[DeadView, ...]
    message: str
    winner: Winner | None = None
    reveal: RevealView | None = None
    aftermath: tuple[dict[str, object], ...] = ()
    you_alive: bool = True


@dataclass(frozen=True)
class TalkReply:
    """一次 agent 回应。"""

    speaker_id: str
    speaker_name: str
    text: str


@dataclass(frozen=True)
class TalkOutcome:
    """讨论或发言的结果。"""

    ok: bool
    error: str | None
    replies: tuple[TalkReply, ...] = ()
    phase: Phase = "discussion"


@dataclass(frozen=True)
class VoteResult:
    """一名玩家的投票，agent 附带一句公开理由。"""

    voter_id: str
    voter_name: str
    target_id: str
    target_name: str
    reason: str = ""


@dataclass(frozen=True)
class DefenseOutcome:
    """提名后进入自辩阶段的结果。"""

    ok: bool
    error: str | None
    target: BloodPlayer | None = None
    defense: TalkReply | None = None
    message: str = ""
    phase: Phase = "discussion"


@dataclass(frozen=True)
class VoteOutcome:
    """投票与处决结算的结果。"""

    ok: bool
    error: str | None
    votes: tuple[VoteResult, ...] = ()
    tally: dict[str, int] = field(default_factory=dict)
    threshold: int = 0
    executed: BloodPlayer | None = None
    winner: Winner | None = None
    reveal: RevealView | None = None
    message: str = ""
    phase: Phase = "discussion"
    aftermath: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True)
class NightOutcome:
    """夜晚结算的结果。"""

    ok: bool
    error: str | None
    killed: BloodPlayer | None = None
    day: int = 1
    phase: Phase = "discussion"
    winner: Winner | None = None
    reveal: RevealView | None = None
    message: str = ""
    aftermath: tuple[dict[str, object], ...] = ()


ReplyFn = Callable[[BloodState, BloodPlayer], str]


class BloodStore:
    """内存对局存储，进程重启即清空。"""

    def __init__(self, rng: random.Random | None = None) -> None:
        self._games: dict[str, BloodState] = {}
        self._rng = rng or random.Random()

    def start(self, script: Script) -> BloodState:
        """创建一局随机阵营并返回初始状态。"""
        state = _create_state(str(uuid.uuid4()), script, self._rng)
        self._games[state.game_id] = state
        return state

    def get(self, game_id: str) -> BloodState | None:
        """按 id 取局，不存在时返回空。"""
        return self._games.get(game_id)


def _create_state(
    game_id: str,
    script: Script,
    rng: random.Random,
) -> BloodState:
    roles = {role.id: role for role in script.roles}
    players: list[BloodPlayer] = [
        BloodPlayer(
            id=YOU_ID,
            name=YOU_NAME,
            public=YOU_PUBLIC,
            role="villager",
            is_you=True,
        )
    ]
    for player_id, role_id in AGENT_ROLE_IDS:
        role = roles.get(role_id)
        players.append(
            BloodPlayer(
                id=player_id,
                name=role.name if role is not None else FALLBACK_NAMES[player_id],
                public=(
                    role.public
                    if role is not None
                    else FALLBACK_PUBLICS[player_id]
                ),
                role="villager",
                is_you=False,
                role_id=role_id,
            )
        )
    murderer = players[rng.randrange(len(players))]
    murderer.role = "murderer"
    state = BloodState(
        game_id=game_id,
        script=script,
        players=players,
        murderer_id=murderer.id,
    )
    for player in players:
        player.private_info = _private_info(script, player, rng)
    _init_suspicion(state, rng)
    state.message = "风雪封路，六个人围坐在灯下。昨夜有人动了手。"
    _log(state, {"type": "start", "day": 1, "players": len(players)})
    _say(
        state,
        "system",
        "旁白",
        f"第一夜过去，{script.victim.name} 死了。六个人里有一个凶手。",
    )
    return state


def _leaks_secret_identity(text: str) -> bool:
    """判断一段私有信息是否直接点破秘密身份。"""
    return any(term in text for term in BLOOD_SECRET_IDENTITY_TERMS)


def _private_info(
    script: Script,
    player: BloodPlayer,
    rng: random.Random,
) -> list[str]:
    if player.is_you:
        if player.role == "murderer":
            return [
                "只有你知道：昨夜动手的人是你，得把话头引开。",
                "没人看见你离开房间，但你要给出说得通的说法。",
            ]
        return [
            "你只是个路过的旅客，这里的旧事你一概不知。",
            "暴雪封路，天亮前谁也走不了。",
            _you_witness_line(script, rng),
        ]
    facts = [
        fact
        for fact in script.facts
        if player.role_id is not None and player.role_id in fact.holders
    ]
    facts = [fact for fact in facts if not _leaks_secret_identity(fact.text)]
    safe = [
        fact
        for fact in facts
        if fact.sensitivity <= BLOOD_PRIVATE_MAX_SENSITIVITY
    ]
    pool = safe or facts
    if not pool:
        return ["你什么也没看见，只记得那晚风很大。"]
    count = min(
        len(pool),
        rng.randint(BLOOD_PRIVATE_FACTS_MIN, BLOOD_PRIVATE_FACTS_MAX),
    )
    return [fact.text for fact in rng.sample(pool, count)]


def _you_witness_line(script: Script, rng: random.Random) -> str:
    """给真人一条与命案现场相关、且来自剧本事实的私密见闻。"""
    pool = [
        fact
        for fact in script.facts
        if fact.sensitivity <= BLOOD_PRIVATE_MAX_SENSITIVITY
        and any(keyword in fact.text for keyword in YOU_WITNESS_KEYWORDS)
        and not _leaks_secret_identity(fact.text)
    ]
    if not pool:
        return YOU_WITNESS_FALLBACK
    return f"你记得那晚的一条：{rng.choice(pool).text}"


def _init_suspicion(state: BloodState, rng: random.Random) -> None:
    for player in state.players:
        if player.is_you:
            continue
        for other in state.players:
            if other.id == player.id:
                continue
            value = BLOOD_INITIAL_SUSPICION_BASE + rng.uniform(
                0.0,
                BLOOD_INITIAL_SUSPICION_JITTER,
            )
            if _mentioned_in_private(player, other):
                value += BLOOD_SUSPICION_FACT
            if player.role == "murderer" and other.role == "villager":
                value += BLOOD_SUSPICION_MURDERER
            player.suspicion[other.id] = _clip(value)


def _mentioned_in_private(player: BloodPlayer, other: BloodPlayer) -> bool:
    if other.is_you:
        return False
    return any(other.name in text for text in player.private_info)


def _clip(value: float) -> float:
    return min(BLOOD_MAX_SUSPICION, max(0.0, value))


def _player(state: BloodState, player_id: str | None) -> BloodPlayer | None:
    if player_id is None:
        return None
    for player in state.players:
        if player.id == player_id:
            return player
    return None


def _you(state: BloodState) -> BloodPlayer:
    return _player(state, YOU_ID)  # type: ignore[return-value]


def _alive_agents(state: BloodState) -> list[BloodPlayer]:
    return [p for p in state.players if p.alive and not p.is_you]


def _name_of(state: BloodState, player_id: str | None) -> str:
    player = _player(state, player_id)
    return player.name if player is not None else "有人"


def _release_fact(
    state: BloodState,
    player: BloodPlayer,
    allow: int,
) -> str | None:
    """按当天的条数上限，取一条尚未公开的私密信息备说。"""
    if player.is_you:
        return None
    if player.released_day != state.day:
        player.released_day = state.day
        player.released_today = 0
    if player.released_today >= allow:
        return None
    for index, text in enumerate(player.private_info):
        if index in player.released:
            continue
        player.released.add(index)
        player.released_today += 1
        _log(
            state,
            {
                "type": "release",
                "day": state.day,
                "speaker": player.id,
                "index": index,
            },
        )
        return text
    return None


def _mentioned_agents(
    state: BloodState,
    text: str,
    limit: int = 2,
) -> list[BloodPlayer]:
    """按出现顺序取最多 limit 名被点到的在场 agent；被提名者优先入选。"""
    found: list[tuple[int, BloodPlayer]] = []
    for player in _alive_agents(state):
        aliases = AGENT_ADDRESS_ALIASES.get(player.id, (player.name,))
        positions = [text.find(alias) for alias in aliases if alias in text]
        if positions:
            found.append((min(positions), player))
    found.sort(key=lambda item: (item[0], item[1].id))
    mentioned = [player for _, player in found]
    limited = mentioned[:limit]
    nominee = _player(state, state.nominee_id)
    if (
        state.phase == "defense"
        and nominee is not None
        and nominee.alive
        and any(player.id == nominee.id for player in mentioned)
        and all(player.id != nominee.id for player in limited)
    ):
        limited = [nominee, *limited[: limit - 1]]
    return limited


def _top_suspicion_target(
    state: BloodState,
    player: BloodPlayer,
) -> str | None:
    candidates = [
        other for other in state.players if other.alive and other.id != player.id
    ]
    if not candidates:
        return None
    best = max(candidates, key=lambda p: player.suspicion.get(p.id, 0.0))
    return best.id


def _bump(state: BloodState, target_id: str, amount: float) -> None:
    for player in state.players:
        if not player.alive or player.is_you or player.id == target_id:
            continue
        current = player.suspicion.get(target_id, 0.0)
        player.suspicion[target_id] = _clip(current + amount)


def _apply_public_text(state: BloodState, speaker_id: str, text: str) -> None:
    speaker = _player(state, speaker_id)
    if speaker is None:
        return
    mentioned = [
        player.id
        for player in state.players
        if player.id != speaker_id and player.name in text
    ]
    for target_id in mentioned:
        _bump(state, target_id, BLOOD_SUSPICION_MENTION)
    if "可疑" in text and speaker_id not in mentioned:
        _bump(state, speaker_id, BLOOD_SUSPICION_MENTION)


def _say(
    state: BloodState,
    speaker_id: str,
    speaker_name: str,
    text: str,
) -> BloodLogEntry:
    entry = BloodLogEntry(
        seq=len(state.public_log) + 1,
        speaker_id=speaker_id,
        speaker_name=speaker_name,
        text=text,
    )
    state.public_log.append(entry)
    return entry


def _log(state: BloodState, entry: dict[str, object]) -> None:
    state.log.append({"step": len(state.log) + 1, **entry})


def _clip_line(text: str, limit: int = BLOOD_MAX_LINE_CHARS) -> str:
    flat = " ".join(part.strip() for part in text.splitlines() if part.strip())
    return flat.replace("\u3000", " ").strip()[:limit]


def _sanitize_agent_line(text: str) -> str:
    """压行限长；自曝阵营则弃用，泄露秘密身份则改为含糊句。"""
    flat = _clip_line(text)
    if any(claim in flat for claim in FORBIDDEN_AGENT_CLAIMS):
        return ""
    if any(term in flat for term in BLOOD_SECRET_CLAIM_TERMS):
        return BLOOD_VAGUE_REWRITE
    return flat


def _fallback_line(
    state: BloodState,
    player: BloodPlayer,
    hint: str = "",
) -> str:
    if hint in {"defense", "accused"}:
        return DEFENSE_FALLBACKS.get(player.id, DEFENSE_FALLBACK_DEFAULT)
    target = _name_of(state, _top_suspicion_target(state, player))
    template = FALLBACK_PUBLICS.get(player.id, "我也说不清。")
    if player.id == "p1":
        return f"我一个开店的，只盼着天亮雪停。{target}那时候在哪儿，我说不清。"
    if player.id == "p2":
        return f"账我记得清，别的不好说。{target}那晚走得急，我总觉得不对劲。"
    if player.id == "p3":
        return f"我上楼送过炭，灯太暗。{target}的话我信一半。"
    if player.id == "p4":
        return f"二楼有响动，我不敢乱指。{target}倒是没解释清楚。"
    if player.id == "p5":
        return f"马棚里我守了一夜。{target}那话说得不太顺。"
    return f"我把知道的都说了。{target}那晚的行踪还得再问。{template}"


def _agent_speak(
    state: BloodState,
    player: BloodPlayer,
    reply_fn: ReplyFn,
    hint: str = "",
    target_id: str | None = None,
    allow_fact: int = 1,
) -> TalkReply:
    state.pending_hint = hint
    state.pending_target_id = target_id
    fact = _release_fact(state, player, allow_fact)
    state.pending_fact[player.id] = fact or ""
    text = ""
    try:
        text = _sanitize_agent_line(reply_fn(state, player))
    except Exception:  # 模型故障不打断回合，退回角色模板
        logger.warning("agent 发言生成失败：%s", player.id, exc_info=True)
    finally:
        state.pending_hint = ""
        state.pending_target_id = None
        state.pending_fact.pop(player.id, None)
    if not text:
        text = _fallback_line(state, player, hint)
    elif fact:
        text = f"{text} 我还记得：{fact}"
    text = _clip_line(text)
    _say(state, player.id, player.name, text)
    _apply_public_text(state, player.id, text)
    return TalkReply(speaker_id=player.id, speaker_name=player.name, text=text)


def _next_agent(state: BloodState) -> BloodPlayer | None:
    agents = [p for p in state.players if not p.is_you]
    if not agents:
        return None
    total = len(agents)
    for offset in range(total):
        index = (state.speak_cursor + offset) % total
        if agents[index].alive:
            state.speak_cursor = (index + 1) % total
            return agents[index]
    return None


def _talk_precheck(state: BloodState) -> str | None:
    if state.phase == "ended":
        return "game_ended"
    if state.phase not in ("discussion", "defense"):
        return "wrong_phase"
    if not _you(state).alive:
        return "you_are_dead"
    return None


def discuss(
    store: BloodStore,
    game_id: str,
    reply_fn: ReplyFn,
) -> TalkOutcome:
    """白天讨论：每个存活 agent 各公开发言一句，并各放出一条私密信息。"""
    state = store.get(game_id)
    if state is None:
        return TalkOutcome(ok=False, error="game_not_found")
    error = _talk_precheck(state)
    if error is not None:
        return TalkOutcome(ok=False, error=error, phase=state.phase)
    if state.phase != "discussion":
        return TalkOutcome(ok=False, error="wrong_phase", phase=state.phase)
    if state.discussed:
        return TalkOutcome(ok=False, error="discuss_used", phase=state.phase)
    state.discussed = True
    replies = tuple(
        _agent_speak(state, player, reply_fn) for player in _alive_agents(state)
    )
    _log(
        state,
        {
            "type": "discuss",
            "day": state.day,
            "speakers": [reply.speaker_id for reply in replies],
        },
    )
    state.message = f"第 {state.day} 天，众人各自说了一句话。"
    return TalkOutcome(ok=True, error=None, replies=replies, phase=state.phase)


def speak(
    store: BloodStore,
    game_id: str,
    text: str,
    reply_fn: ReplyFn,
) -> TalkOutcome:
    """真人公开发言一次，被点名者优先回应，自辩阶段被提名者优先。"""
    state = store.get(game_id)
    if state is None:
        return TalkOutcome(ok=False, error="game_not_found")
    error = _talk_precheck(state)
    if error is not None:
        return TalkOutcome(ok=False, error=error, phase=state.phase)
    if state.phase == "defense":
        if state.defense_speak_count >= BLOOD_MAX_DEFENSE_SPEAK_PER_DAY:
            return TalkOutcome(
                ok=False, error="defense_speak_limit", phase=state.phase
            )
    elif state.speak_count >= BLOOD_MAX_SPEAK_PER_DAY:
        return TalkOutcome(ok=False, error="speak_limit", phase=state.phase)
    clean = _clip_line(text)
    if not clean:
        return TalkOutcome(ok=False, error="target_invalid", phase=state.phase)
    if state.phase == "defense":
        state.defense_speak_count += 1
    else:
        state.speak_count += 1
    you = _you(state)
    _say(state, you.id, you.name, clean)
    _apply_public_text(state, you.id, clean)
    replies: list[TalkReply] = []
    mentioned = _mentioned_agents(state, clean)
    agents: list[BloodPlayer] = list(mentioned)
    if not agents and state.phase == "defense":
        nominee = _player(state, state.nominee_id)
        if nominee is not None and nominee.alive:
            agents.append(nominee)
    if not agents:
        rotated = _next_agent(state)
        if rotated is not None:
            agents.append(rotated)
    for agent in agents:
        if mentioned:
            hint = "accused"
        elif state.phase == "defense":
            hint = "defense"
        else:
            hint = ""
        replies.append(
            _agent_speak(
                state,
                agent,
                reply_fn,
                hint=hint,
                target_id=state.nominee_id,
                allow_fact=BLOOD_MAX_FACTS_PER_DAY if hint else 1,
            )
        )
    _log(
        state,
        {
            "type": "speak",
            "day": state.day,
            "phase": state.phase,
            "text": clean,
            "replied_by": [reply.speaker_id for reply in replies],
        },
    )
    if state.phase == "defense":
        state.message = "质证还在继续。"
    else:
        state.message = "话头被抛了出去，有人接了一句。"
    return TalkOutcome(
        ok=True,
        error=None,
        replies=tuple(replies),
        phase=state.phase,
    )


def _judge_alive_ids(
    roles: dict[str, RoleKind],
    alive_ids: set[str],
    murderer_id: str,
) -> Winner | None:
    """按存活集合判定胜负：凶手出局好人胜，只剩两人或凶手独存则凶手胜。"""
    if murderer_id not in alive_ids:
        return "good"
    if all(roles.get(player_id) != "villager" for player_id in alive_ids):
        return "murderer"
    if len(alive_ids) <= 2:
        return "murderer"
    return None


def _judge(state: BloodState) -> Winner | None:
    """按当前存活玩家判定胜负。"""
    return _judge_alive_ids(
        {player.id: player.role for player in state.players},
        {player.id for player in state.players if player.alive},
        state.murderer_id,
    )


def _win_text(winner: Winner) -> str:
    if winner == "good":
        return "凶手伏法，剩下的人熬到了天亮。好人胜。"
    return "天亮时，凶手还站着。凶手胜。"


def _declare_winner(state: BloodState, winner: Winner, reason: str) -> None:
    state.winner = winner
    state.phase = "ended"
    state.message = reason
    _log(state, {"type": "win", "day": state.day, "winner": winner})
    _say(state, "system", "旁白", reason)


def _aftermath_entry(
    state: BloodState,
    day: int,
    executed: BloodPlayer | None,
    killed: BloodPlayer | None,
) -> dict[str, object] | None:
    """生成一条卷宗摘要：当天的处决与夜杀。"""
    if executed is None and killed is None:
        return None
    parts: list[str] = []
    if executed is not None:
        parts.append(f"{executed.name}被处决")
    if killed is not None:
        parts.append(f"夜里，{killed.name}死在{AFTERMATH_DEATH_PLACE}")
    return {
        "day": day,
        "executed": (
            {"id": executed.id, "name": executed.name}
            if executed is not None
            else None
        ),
        "killed": (
            {"id": killed.id, "name": killed.name}
            if killed is not None
            else None
        ),
        "note": f"第 {day} 天，" + "；".join(parts) + "。",
    }


def _sim_vote(
    state: BloodState,
    alive_ids: set[str],
) -> BloodPlayer | None:
    """模拟一轮 agent 投票：各投最怀疑的存活者，达标才处决。"""
    voters = [
        player
        for player in state.players
        if player.alive and not player.is_you and player.id in alive_ids
    ]
    tally: Counter[str] = Counter()
    for voter in voters:
        candidates = [
            player
            for player in state.players
            if player.alive
            and player.id in alive_ids
            and player.id != voter.id
        ]
        if not candidates:
            continue
        target = max(
            candidates,
            key=lambda player: voter.suspicion.get(player.id, 0.0),
        )
        tally[target.id] += 1
    threshold = (len(voters) + 1) // 2
    if not tally:
        return None
    top = max(tally.values())
    leaders = [target_id for target_id, count in tally.items() if count == top]
    if len(leaders) != 1 or top < threshold:
        return None
    return _player(state, leaders[0])


def _sim_kill(
    state: BloodState,
    alive_ids: set[str],
) -> BloodPlayer | None:
    """模拟凶手夜杀：挑对其威胁最高、且仍存活的 agent。"""
    murderer = _player(state, state.murderer_id)
    if murderer is None or murderer.id not in alive_ids:
        return None
    candidates = [
        player
        for player in state.players
        if player.alive and player.id in alive_ids and player.id != murderer.id
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda player: murderer.suspicion.get(player.id, 0.0),
    )


def _simulate_aftermath(
    state: BloodState,
) -> tuple[list[dict[str, object]], Winner | None]:
    """真人出局后，用纯规则推演剩余处决与夜杀，直到分出胜负。"""
    roles = {player.id: player.role for player in state.players}
    alive_ids = {player.id for player in state.players if player.alive}
    winner = _judge_alive_ids(roles, alive_ids, state.murderer_id)
    entries: list[dict[str, object]] = []
    day = state.day
    if winner is None and state.phase in ("discussion", "defense"):
        killed = _sim_kill(state, alive_ids)
        if killed is not None:
            alive_ids.discard(killed.id)
            winner = _judge_alive_ids(roles, alive_ids, state.murderer_id)
        entry = _aftermath_entry(state, day, None, killed)
        if entry is not None:
            entries.append(entry)
        day += 1
    elif winner is None:
        day += 1
    while winner is None and day <= state.day + BLOOD_AFTERMATH_MAX_DAYS:
        executed = _sim_vote(state, alive_ids)
        if executed is not None:
            alive_ids.discard(executed.id)
        winner = _judge_alive_ids(roles, alive_ids, state.murderer_id)
        killed = None
        if winner is None:
            killed = _sim_kill(state, alive_ids)
            if killed is not None:
                alive_ids.discard(killed.id)
                winner = _judge_alive_ids(roles, alive_ids, state.murderer_id)
        entry = _aftermath_entry(state, day, executed, killed)
        if entry is not None:
            entries.append(entry)
        day += 1
    return entries, winner


def _end_with_you_out(state: BloodState, reason: str) -> None:
    """真人出局后进入终局，并用纯规则补全卷宗摘要与最终胜负。"""
    aftermath, winner = _simulate_aftermath(state)
    state.aftermath = aftermath
    if winner is not None:
        state.winner = winner
        suffix = (
            "余下的人把凶手揪了出来。"
            if winner == "good"
            else "剩下的日子里，凶手笑到了最后。"
        )
        reason = f"{reason}{suffix}"
    state.phase = "ended"
    state.message = reason
    _log(
        state,
        {
            "type": "end",
            "day": state.day,
            "reason": "you_out",
            "winner": state.winner,
        },
    )
    _say(state, "system", "旁白", reason)


def _system_kill_target(state: BloodState) -> BloodPlayer | None:
    murderer = _player(state, state.murderer_id)
    if murderer is None:
        return None
    candidates = [
        player
        for player in state.players
        if player.alive and player.id != murderer.id
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: murderer.suspicion.get(p.id, 0.0))



def _fallback_reason(
    state: BloodState,
    voter: BloodPlayer,
    target: BloodPlayer,
) -> str:
    index = int(voter.id[1:]) % len(VOTE_REASON_FALLBACKS)
    return VOTE_REASON_FALLBACKS[index].format(name=target.name)


def _reason_names_other(
    state: BloodState,
    reason: str,
    target: BloodPlayer,
) -> bool:
    """判断理由里是否出现了 target 以外的玩家姓名或称呼。"""
    for player in state.players:
        if player.id == target.id:
            continue
        aliases = AGENT_ADDRESS_ALIASES.get(player.id, (player.name,))
        if any(alias and alias in reason for alias in (*aliases, player.name)):
            return True
    return False


def _aligned_reason(
    state: BloodState,
    voter: BloodPlayer,
    target: BloodPlayer,
    raw: str,
) -> str:
    """把理由绑定到实际投票目标；提到他人或泄露秘密时改用模板句。"""
    reason = _clip_line(raw, BLOOD_VOTE_REASON_MAX_CHARS)
    if not reason:
        return _fallback_reason(state, voter, target)
    if any(claim in reason for claim in FORBIDDEN_AGENT_CLAIMS):
        return VOTE_REASON_TARGET_TEMPLATE.format(name=target.name)
    if any(term in reason for term in BLOOD_SECRET_CLAIM_TERMS):
        return VOTE_REASON_TARGET_TEMPLATE.format(name=target.name)
    if _reason_names_other(state, reason, target):
        return VOTE_REASON_TARGET_TEMPLATE.format(name=target.name)
    return reason


def _agent_vote(
    state: BloodState,
    agent: BloodPlayer,
    reply_fn: ReplyFn,
) -> VoteResult | None:
    """agent 投给最怀疑的人，并附一句可撒谎的公开理由。"""
    target = _player(state, _top_suspicion_target(state, agent))
    if target is None:
        return None
    state.pending_hint = "vote_reason"
    state.pending_target_id = target.id
    reason = ""
    try:
        raw = reply_fn(state, agent)
        reason = _clip_line(raw, BLOOD_VOTE_REASON_MAX_CHARS)
    except Exception:
        logger.warning("投票理由生成失败：%s", agent.id, exc_info=True)
    finally:
        state.pending_hint = ""
        state.pending_target_id = None
    reason = _aligned_reason(state, agent, target, reason)
    return VoteResult(agent.id, agent.name, target.id, target.name, reason)


def _resolve_votes(
    state: BloodState,
    votes: list[VoteResult],
) -> tuple[dict[str, int], int, BloodPlayer | None]:
    """按向上取整半数处决：票数达到 ceil(存活/2) 且唯一最高。"""
    alive_count = sum(1 for player in state.players if player.alive)
    threshold = (alive_count + 1) // 2
    tally = Counter(vote.target_id for vote in votes)
    if not tally:
        return {}, threshold, None
    top = max(tally.values())
    leaders = [target_id for target_id, count in tally.items() if count == top]
    if len(leaders) != 1 or top < threshold:
        return dict(tally), threshold, None
    return dict(tally), threshold, _player(state, leaders[0])


def _vote_log_entry(state: BloodState, votes: list[VoteResult]) -> dict[str, object]:
    return {
        "type": "vote",
        "day": state.day,
        "votes": [
            {
                "voter_id": vote.voter_id,
                "target_id": vote.target_id,
                "reason": vote.reason,
            }
            for vote in votes
        ],
    }


def nominate(
    store: BloodStore,
    game_id: str,
    target_id: str,
    reply_fn: ReplyFn,
) -> DefenseOutcome:
    """提名进入自辩阶段，由被提名者先回应，不立即结算处决。"""
    state = store.get(game_id)
    if state is None:
        return DefenseOutcome(ok=False, error="game_not_found")
    error = _talk_precheck(state)
    if error is not None:
        return DefenseOutcome(ok=False, error=error, phase=state.phase)
    if state.nominated:
        return DefenseOutcome(ok=False, error="nominate_used", phase=state.phase)
    if state.phase != "discussion":
        return DefenseOutcome(ok=False, error="wrong_phase", phase=state.phase)
    target = _player(state, target_id)
    if target is None:
        return DefenseOutcome(
            ok=False, error="target_not_found", phase=state.phase
        )
    if not target.alive:
        return DefenseOutcome(ok=False, error="target_dead", phase=state.phase)
    if target.is_you:
        return DefenseOutcome(
            ok=False, error="target_invalid", phase=state.phase
        )
    state.nominated = True
    state.phase = "defense"
    state.nominee_id = target.id
    state.defense_speak_count = 0
    _say(state, "system", "旁白", f"{target.name} 被提名。先听他自辩。")
    defense = _agent_speak(
        state,
        target,
        reply_fn,
        hint="defense",
        allow_fact=BLOOD_MAX_FACTS_PER_DAY,
    )
    state.message = f"{target.name} 被提名，先自辩，随后投票。"
    _log(
        state,
        {
            "type": "nominate",
            "day": state.day,
            "target": target.id,
            "defense_by": defense.speaker_id,
        },
    )
    return DefenseOutcome(
        ok=True,
        error=None,
        target=target,
        defense=defense,
        message=state.message,
        phase=state.phase,
    )


def vote(
    store: BloodStore,
    game_id: str,
    target_id: str,
    reply_fn: ReplyFn,
    reason: str = "",
) -> VoteOutcome:
    """全体存活玩家投票，得票达到 ceil(存活/2) 才处决；真人可附一句理由。"""
    state = store.get(game_id)
    if state is None:
        return VoteOutcome(ok=False, error="game_not_found")
    if state.phase == "ended":
        return VoteOutcome(ok=False, error="game_ended", phase=state.phase)
    if state.phase != "defense":
        return VoteOutcome(ok=False, error="wrong_phase", phase=state.phase)
    you = _you(state)
    if not you.alive:
        return VoteOutcome(ok=False, error="you_are_dead", phase=state.phase)
    target = _player(state, target_id)
    if target is None:
        return VoteOutcome(
            ok=False, error="target_not_found", phase=state.phase
        )
    if not target.alive:
        return VoteOutcome(ok=False, error="target_dead", phase=state.phase)
    if target.is_you:
        return VoteOutcome(ok=False, error="target_invalid", phase=state.phase)
    votes: list[VoteResult] = [
        VoteResult(
            you.id,
            you.name,
            target.id,
            target.name,
            _clip_line(reason),
        )
    ]
    for agent in _alive_agents(state):
        agent_vote = _agent_vote(state, agent, reply_fn)
        if agent_vote is not None:
            votes.append(agent_vote)
    tally, threshold, executed = _resolve_votes(state, votes)
    if executed is not None:
        executed.alive = False
        _say(state, "system", "旁白", f"{executed.name} 被投票处决。")
        state.message = f"{executed.name} 被处决，天黑了。"
    else:
        top = max(tally.values(), default=0)
        state.message = (
            f"最高 {top} 票，没过 {threshold} 票门槛，没有人被处决。"
        )
    _log(state, _vote_log_entry(state, votes))
    winner = _judge(state)
    if winner is not None:
        _declare_winner(state, winner, _win_text(winner))
    elif not you.alive:
        _end_with_you_out(state, f"{you.name} 出局了，本局到此为止。")
    else:
        state.phase = "night"
    return VoteOutcome(
        ok=True,
        error=None,
        votes=tuple(votes),
        tally=dict(tally),
        threshold=threshold,
        executed=executed,
        winner=state.winner,
        reveal=_reveal_of(state),
        message=state.message,
        phase=state.phase,
        aftermath=tuple(state.aftermath),
    )


def night(
    store: BloodStore,
    game_id: str,
    target_id: str | None = None,
) -> NightOutcome:
    """夜晚结算：凶手杀一人，天亮后进入下一天或结束。"""
    state = store.get(game_id)
    if state is None:
        return NightOutcome(ok=False, error="game_not_found", day=1)
    if state.phase == "ended":
        return NightOutcome(
            ok=False, error="game_ended", day=state.day, phase=state.phase
        )
    if state.phase != "night":
        return NightOutcome(
            ok=False, error="wrong_phase", day=state.day, phase=state.phase
        )
    you = _you(state)
    if not you.alive:
        return NightOutcome(
            ok=False, error="you_are_dead", day=state.day, phase=state.phase
        )
    if you.role == "murderer":
        if target_id is None:
            return NightOutcome(
                ok=False,
                error="night_target_required",
                day=state.day,
                phase=state.phase,
            )
        victim = _player(state, target_id)
        if victim is None:
            return NightOutcome(
                ok=False, error="target_not_found", day=state.day,
                phase=state.phase,
            )
        if not victim.alive:
            return NightOutcome(
                ok=False, error="target_dead", day=state.day,
                phase=state.phase,
            )
        if victim.is_you or victim.role == "murderer":
            return NightOutcome(
                ok=False, error="target_invalid", day=state.day,
                phase=state.phase,
            )
    else:
        victim = _system_kill_target(state)
    if victim is not None:
        victim.alive = False
        _say(state, "system", "旁白", f"夜里，{victim.name} 没能等到天亮。")
    _log(
        state,
        {
            "type": "night",
            "day": state.day,
            "killed": victim.id if victim is not None else None,
        },
    )
    winner = _judge(state)
    if winner is not None:
        _declare_winner(state, winner, _win_text(winner))
        return NightOutcome(
            ok=True,
            error=None,
            killed=victim,
            day=state.day,
            phase=state.phase,
            winner=state.winner,
            reveal=_reveal_of(state),
            message=state.message,
            aftermath=tuple(state.aftermath),
        )
    if not you.alive:
        _end_with_you_out(state, f"{you.name} 没能等到天亮，本局到此为止。")
        return NightOutcome(
            ok=True,
            error=None,
            killed=victim,
            day=state.day,
            phase=state.phase,
            winner=state.winner,
            reveal=_reveal_of(state),
            message=state.message,
            aftermath=tuple(state.aftermath),
        )
    _reset_day(state)
    state.message = f"第 {state.day} 天，天亮了。"
    return NightOutcome(
        ok=True,
        error=None,
        killed=victim,
        day=state.day,
        phase=state.phase,
        winner=state.winner,
        reveal=_reveal_of(state),
        message=state.message,
        aftermath=tuple(state.aftermath),
    )


def _reset_day(state: BloodState) -> None:
    state.day += 1
    state.phase = "discussion"
    state.discussed = False
    state.speak_count = 0
    state.nominated = False
    state.nominee_id = None
    state.defense_speak_count = 0
    state.speak_cursor = 0
    _log(state, {"type": "phase", "day": state.day, "phase": "discussion"})


def _reveal_of(state: BloodState) -> RevealView | None:
    """终局时返回凶手揭晓，未结束时返回空。"""
    if state.phase != "ended":
        return None
    murderer = _player(state, state.murderer_id)
    if murderer is None:
        return None
    return RevealView(
        murderer_id=murderer.id,
        murderer_name=murderer.name,
    )


def build_view(state: BloodState) -> BloodView:
    """生成公开视图，终局时附上凶手揭晓与卷宗摘要。"""
    you = _you(state)
    return BloodView(
        game_id=state.game_id,
        day=state.day,
        phase=state.phase,
        players=tuple(
            PlayerView(
                id=player.id,
                name=player.name,
                public=player.public,
                alive=player.alive,
                is_you=player.is_you,
            )
            for player in state.players
        ),
        you=YouView(
            id=you.id,
            name=you.name,
            role=you.role,
            private_info=tuple(you.private_info),
            teammates=(),
        ),
        public_log=tuple(state.public_log),
        dead=tuple(
            DeadView(id=player.id, name=player.name)
            for player in state.players
            if not player.alive
        ),
        message=state.message,
        winner=state.winner,
        reveal=_reveal_of(state),
        aftermath=tuple(state.aftermath),
        you_alive=you.alive,
    )


def build_log(state: BloodState) -> list[dict[str, object]]:
    """返回不含秘密字段的回看日志。"""
    return [dict(entry) for entry in state.log]