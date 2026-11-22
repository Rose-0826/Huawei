"""阵营模式「电子血染」的状态机：只做状态转移，不调用模型。"""

from __future__ import annotations

import logging
import random
import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Literal

from app.config import (
    BETRAY_SUSPICION_DELTA,
    BETRAY_TRUST_DELTA,
    BLOOD_AFTERMATH_MAX_DAYS,
    BLOOD_HEARSAY_PREFIX,
    BLOOD_INITIAL_SUSPICION_BASE,
    BLOOD_INITIAL_SUSPICION_JITTER,
    BLOOD_KNOWN_PERSON_TERMS,
    BLOOD_LAST_WORDS_MAX_CHARS,
    BLOOD_MAX_DEFENSE_SPEAK_PER_DAY,
    BLOOD_MAX_FACTS_PER_DAY,
    BLOOD_MAX_LINE_CHARS,
    BLOOD_MAX_SPEAK_PER_DAY,
    BLOOD_MAX_SUSPICION,
    BLOOD_MEMORY_MARKERS,
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
    BLOOD_VOTE_REASON_MIN_QUOTE_CHARS,
    BLOOD_VOTE_REASON_QUOTE_CHARS,
    CONFIDE_REPLY_MAX_CHARS,
    CONFIDE_SUSPICION_ACCEPT,
    CONFIDE_SUSPICION_REFUSE,
    CONFIDE_SUSPICION_THREATEN,
    CONFIDE_TEXT_MAX_CHARS,
    CONFIDE_TRUST_ACCEPT,
    CONFIDE_TRUST_REFUSE,
    CONFIDE_TRUST_START,
    CONFIDE_TRUST_THREATEN,
    FOLLOW_ACCEPT_DELTA,
    FOLLOW_MAX,
    LEAK_QUOTE_MAX_CHARS,
    LEAK_RATE_MURDERER,
    LEAK_RATE_NORMAL,
    LIMIT_PER_DAY,
    LIMIT_PER_GAME,
)
from app.models import Script

logger = logging.getLogger(__name__)

RoleKind = Literal["villager", "murderer"]
Phase = Literal["discussion", "defense", "night", "ended"]
Winner = Literal["good", "murderer"]

YOU_ID = "p0"
YOU_NAME = "旅客"
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
    "p0": ("旅客",),
    "p1": ("沈玉兰", "沈老板娘", "沈老板", "老板娘"),
    "p2": ("周砚青", "周先生", "账房"),
    "p3": ("阿蘅",),
    "p4": ("陆明川", "陆先生", "陆老板"),
    "p5": ("老韩",),
}
YOU_WITNESS_KEYWORDS: tuple[str, ...] = ("书房", "楼梯口", "拨火棍")
YOU_WITNESS_FALLBACK: str = "你记得楼上书房里闹过一阵响动，像是桌椅被撞了一下。"
FORBIDDEN_AGENT_CLAIMS: tuple[str, ...] = ("我是凶手", "我是好人", "我是清白的")
VAGUE_AGENT_LINES: dict[str, str] = {
    "p1": "我一个开店的，那晚楼道上脚步不干净，可我只看清一角。",
    "p2": "账我不想乱认，那晚的动静我听见了，细节说不圆。",
    "p3": "我送完炭就回下房了，灯太暗，谁在楼里走动我没看真。",
    "p4": "二楼有响动，我没敢声张，只记得不像一个人。",
    "p5": "马棚里我守到后半夜，走廊那头有人影，我没看清脸。",
}
VAGUE_AGENT_DEFAULT: str = "那晚的事我只看见一角，说不全，别逼我认没看见的。"
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
    "我投{name}，他方才说“{quote}”，这话绕开了时辰。",
    "我投{name}。“{quote}”这一句，他自己没法圆回来。",
    "我投{name}，{quote}——说了一遍，还是没讲清那晚在哪。",
    "我投{name}，他那句“{quote}”和前面的说法接不上。",
    "我投{name}，今天他一直含糊，尤其“{quote}”那一句。",
    "我投{name}，从“{quote}”到现在，他都没把自己摘清。",
    "我投{name}，他拿“{quote}”搪塞，却没回答自己在哪儿。",
    "我投{name}，对照他今天说的“{quote}”，前后对不上。",
)
VOTE_REASON_NO_QUOTE_FALLBACKS: tuple[str, ...] = (
    "我投{name}，他今天说的那几句，没一句落在自己那晚的行踪上。",
    "我投{name}，别人问他的时候，他总把话头推到旁人身上。",
    "我投{name}，他从白天到刚才都含糊，没法让人信。",
    "我投{name}，他那套说法我越听越不对。",
    "我投{name}，白天他答得最虚，也没补上一句实话。",
    "我投{name}，他说来说去，始终没交代清楚那段时间。",
    "我投{name}，他避开了最要紧的一句，我只好投他。",
    "我投{name}，桌上数他前后说法最不齐整。",
)
VOTE_REASON_PLACEHOLDERS: tuple[str, ...] = ("某人", "某先生", "某某", "XXX", "该玩家")
CONFIDE_THREAT_TERMS: tuple[str, ...] = (
    "威胁",
    "不投我",
    "你会后悔",
    "弄死",
    "揭穿",
    "曝光",
    "对你不利",
    "小心点",
    "同归于尽",
    "我保证你出局",
)
CONFIDE_EVIDENCE_TERMS: tuple[str, ...] = (
    "我有证据",
    "证据在我",
    "我亲眼看见你",
    "我看见你",
    "我手里有",
    "我知道你是",
    "你动的手",
    "你杀了",
    "指纹",
    "你袖口",
)
CONFIDE_PROMISE_TERMS: tuple[str, ...] = (
    "保护",
    "保你",
    "结盟",
    "同盟",
    "联手",
    "合作",
    "一起",
    "同票",
    "跟我投",
    "跟你投",
    "替你挡",
    "不提名",
    "不投你",
    "信任我",
    "我帮你",
    "帮我",
)
CONFIDE_STANCE_FALLBACKS: dict[str, str] = {
    "accept": "这话我记下了。你要提谁，别把我摆上桌。",
    "evade": "廊下风大，我没什么可跟你交底的。",
    "refuse": "我不应这种话。你要提谁，是你的事；我只说我看见的。",
    "threaten": "你拿话压我，我也记着。明天桌上见。",
}
CONFIDE_BETRAY_LINE: str = "昨晚的话不算数，我只按证据投。"
CONFIDE_PLAYER_EVIDENCE_TERMS: tuple[str, ...] = (
    "我捡到",
    "我找到",
    "地上有",
    "门槛上",
    "一枚",
    "一件",
    "我亲眼",
    "我有证据",
)
CONFIDE_ENDORSE_TERMS: tuple[str, ...] = (
    "我认得",
    "我见过这东西",
    "确实有",
    "少过一颗",
    "少了一颗",
    "崩了线",
    "是我掉的",
    "我承认这物证",
)
AFTERMATH_DEATH_PLACE: str = "走廊"
UNKNOWN_NAME_PATTERN = re.compile(r"[老小][\u4e00-\u9fa5]")


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
    trust: float = CONFIDE_TRUST_START
    follow_prob: float = 0.0


@dataclass(frozen=True)
class BloodLogEntry:
    """公开频道里的一条发言。"""

    seq: int
    speaker_id: str
    speaker_name: str
    text: str
    day: int = 1


@dataclass(frozen=True)
class ConfideEntry:
    """一条只给真人看的密谈记录，含正文。"""

    seq: int
    day: int
    target_id: str
    target_name: str
    text: str
    stance: str
    reply: str


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
    day_history: list[dict[str, object]] = field(default_factory=list)
    pending_hint: str = ""
    pending_target_id: str | None = None
    pending_fact: dict[str, str] = field(default_factory=dict)
    night_blocked: bool = False
    confide_day: int = 0
    confide_count: int = 0
    private_log: list[ConfideEntry] = field(default_factory=list)
    confide_intents: dict[str, str] = field(default_factory=dict)
    pending_leaks: dict[str, str] = field(default_factory=dict)
    last_words_used: bool = False
    rng: random.Random = field(default_factory=random.Random, repr=False)


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
    day_history: tuple[dict[str, object], ...] = ()
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
    notice: str = ""


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
    day_history: tuple[dict[str, object], ...] = ()


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
    day_history: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True)
class ConfideOutcome:
    """一次密谈的结果，正文只回给真人。"""

    ok: bool
    error: str | None
    target: BloodPlayer | None = None
    stance: str = "evade"
    reply: str = ""
    trust: int = 50
    suspicion: int = 0
    follow_prob: float = 0.0
    public_line: str = ""
    remaining: int = 0
    entry: ConfideEntry | None = None


@dataclass(frozen=True)
class LastWordsOutcome:
    """真人出局后留遗言的结果。"""

    ok: bool
    error: str | None
    text: str = ""
    message: str = ""


ReplyFn = Callable[[BloodState, BloodPlayer], str]
ConfideFn = Callable[[BloodState, BloodPlayer, str, str], str]


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
        rng=rng,
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
    day: int | None = None,
) -> BloodLogEntry:
    entry = BloodLogEntry(
        seq=len(state.public_log) + 1,
        speaker_id=speaker_id,
        speaker_name=speaker_name,
        text=text,
        day=state.day if day is None else day,
    )
    state.public_log.append(entry)
    return entry


def _log(state: BloodState, entry: dict[str, object]) -> None:
    state.log.append({"step": len(state.log) + 1, **entry})


def _flat_line(text: str) -> str:
    """压成单行并去掉全角缩进，不做长度截断。"""
    flat = " ".join(part.strip() for part in text.splitlines() if part.strip())
    return flat.replace("\u3000", " ").strip()


def _clip_line(text: str, limit: int = BLOOD_MAX_LINE_CHARS) -> str:
    return _flat_line(text)[:limit]


SENTENCE_ENDS: tuple[str, ...] = ("。", "！", "？", "!", "?", "…")
CLAUSE_ENDS: tuple[str, ...] = ("；", ";", "，", ",", "、")


def _clip_sentence(text: str, limit: int) -> str:
    """限长时截到最后一个完整标点，绝不把半句话留在末尾。"""
    flat = _flat_line(text)
    if len(flat) <= limit:
        return flat
    head = flat[:limit]
    cut = _last_index(head, SENTENCE_ENDS)
    if cut < 0:
        cut = _last_index(head, CLAUSE_ENDS)
    if cut < 0:
        return head.rstrip(" \t") + "。"
    return head[: cut + 1].rstrip()


def _last_index(text: str, marks: tuple[str, ...]) -> int:
    return max((text.rfind(mark) for mark in marks), default=-1)


def _clip_you_line(text: str) -> tuple[str, bool]:
    """真人发言超长时截到句末，并告知已经保留到最后一个句号。"""
    flat = _flat_line(text)
    if len(flat) <= BLOOD_MAX_LINE_CHARS:
        return flat, False
    return _clip_sentence(flat, BLOOD_MAX_LINE_CHARS), True


def _clip_leak_quote(text: str) -> str:
    """泄露引用最多 20 字，优先收在完整分句上。"""
    flat = _flat_line(text)
    if len(flat) <= LEAK_QUOTE_MAX_CHARS:
        return flat
    head = flat[:LEAK_QUOTE_MAX_CHARS]
    cut = _last_index(head, SENTENCE_ENDS + CLAUSE_ENDS)
    if cut >= 0:
        return head[: cut + 1].strip()
    return head.strip()


def _sanitize_agent_line(
    state: BloodState,
    player: BloodPlayer,
    text: str,
) -> str:
    """压行限长；去念档案尾巴、秘密身份与新编人名，自曝阵营则弃用。"""
    flat = _clip_line(text)
    if any(claim in flat for claim in FORBIDDEN_AGENT_CLAIMS):
        return ""
    if any(term in flat for term in BLOOD_SECRET_CLAIM_TERMS):
        return BLOOD_VAGUE_REWRITE
    flat = _strip_memory_tail(flat)
    flat = _scrub_private_fact_text(state, player, flat)
    if not flat:
        return ""
    flat = _filter_unknown_names(state, flat)
    flat = _prefix_hearsay(state, flat)
    return _clip_line(flat)


def _strip_memory_tail(text: str) -> str:
    """截掉「我还记得」「档案里写着」及其后的原文。"""
    cut = len(text)
    found = False
    for marker in BLOOD_MEMORY_MARKERS:
        index = text.find(marker)
        if index != -1:
            cut = min(cut, index)
            found = True
    if not found:
        return text
    return text[:cut].strip(" \t，,。；;：:")


def _scrub_private_fact_text(
    state: BloodState,
    player: BloodPlayer,
    text: str,
) -> str:
    """公开发言若逐字出现任一档案事实原文，整句弃用，交给角色化兜底。"""
    cores = [fact.text for fact in state.script.facts]
    for other in state.players:
        cores.extend(other.private_info)
    for core in cores:
        core = core.strip()
        if len(core) >= 6 and core in text:
            return ""
    return text


def _known_person_terms(state: BloodState) -> set[str]:
    """收集本局已登记的人名、称呼与通用词，供未登记人名过滤使用。"""
    terms: set[str] = set(BLOOD_KNOWN_PERSON_TERMS)
    for player in state.players:
        terms.add(player.name)
        terms.add(player.public)
        terms.update(AGENT_ADDRESS_ALIASES.get(player.id, ()))
    terms.add(state.script.victim.name)
    return {term for term in terms if term}


def _filter_unknown_names(state: BloodState, text: str) -> str:
    """把「老X」「小X」这类未登记的人名替换成含糊称呼。"""
    terms = _known_person_terms(state)

    def _replace(match: re.Match[str]) -> str:
        token = match.group(0)
        if any(token == term or term.startswith(token) for term in terms):
            return token
        return "旁人"

    return UNKNOWN_NAME_PATTERN.sub(_replace, text)


def _prefix_hearsay(state: BloodState, text: str) -> str:
    """agent 把旅客转述说成亲历时，补上「听旅客说」前缀。"""
    if "我亲眼" not in text and "我亲耳" not in text:
        return text
    if text.startswith(BLOOD_HEARSAY_PREFIX):
        return text
    you_lines = [
        entry.text for entry in state.public_log if entry.speaker_id == YOU_ID
    ]
    if not you_lines:
        return text
    last = you_lines[-1]
    if any(last[index : index + 3] in text for index in range(len(last) - 2)):
        return BLOOD_HEARSAY_PREFIX + text
    return text


def _vague_agent_line(player: BloodPlayer) -> str:
    """截断后为空时，用角色化的含糊句兜底。"""
    return VAGUE_AGENT_LINES.get(player.id, VAGUE_AGENT_DEFAULT)


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


def _consume_leak(state: BloodState, player: BloodPlayer) -> str:
    """目标 agent 决定泄露时，只复述玩家原话的 20 字以内，绝不加码。"""
    raw = state.pending_leaks.pop(player.id, None)
    if not raw:
        return ""
    quote = _clip_leak_quote(raw)
    quote = quote.strip(" \t，,。；;：:\"'“”")
    quote = _filter_unknown_names(state, quote)
    if not quote:
        return ""
    return f"我听{YOU_NAME}私下说「{quote}」，我没应。"


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
        text = _sanitize_agent_line(state, player, reply_fn(state, player))
    except Exception:  # 模型故障不打断回合，退回角色模板
        logger.warning("agent 发言生成失败：%s", player.id, exc_info=True)
    finally:
        state.pending_hint = ""
        state.pending_target_id = None
        state.pending_fact.pop(player.id, None)
    if not text:
        text = _vague_agent_line(player)
    text = _clip_sentence(text, BLOOD_MAX_LINE_CHARS)
    leak = _consume_leak(state, player)
    if leak:
        text = _clip_sentence(
            f"{text}{leak}",
            BLOOD_MAX_LINE_CHARS + LEAK_QUOTE_MAX_CHARS + 40,
        )
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
    clean, truncated = _clip_you_line(text)
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
            "truncated": truncated,
            "replied_by": [reply.speaker_id for reply in replies],
        },
    )
    notice = ""
    if truncated:
        notice = "发言过长，已保留到最后一个句号。"
        state.message = notice
    elif state.phase == "defense":
        state.message = "质证还在继续。"
    else:
        state.message = "话头被抛了出去，有人接了一句。"
    return TalkOutcome(
        ok=True,
        error=None,
        replies=tuple(replies),
        phase=state.phase,
        notice=notice,
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


def _player_ref(player: BloodPlayer | None) -> dict[str, object] | None:
    if player is None:
        return None
    return {"id": player.id, "name": player.name}


def _vote_note(
    day: int,
    executed: BloodPlayer | None,
    stalemate: bool,
    tally: dict[str, int],
    threshold: int,
) -> str:
    """生成当天投票摘要，平票与未达门槛都明确写无人被处决。"""
    if executed is not None:
        return f"第 {day} 天，{executed.name}被处决。"
    if stalemate:
        return f"第 {day} 天，平票或未达 {threshold} 票门槛，无人被处决。"
    return f"第 {day} 天，无人被处决。"


def _push_history(state: BloodState, entry: dict[str, object]) -> None:
    state.day_history.append(entry)
    state.aftermath.append(dict(entry))


def _record_vote_day(
    state: BloodState,
    executed: BloodPlayer | None,
    tally: dict[str, int],
    threshold: int,
    votes: list[VoteResult],
    stalemate: bool,
) -> None:
    """投票结算后，先把当天条目写进逐日卷宗；夜杀稍后再补。"""
    entry: dict[str, object] = {
        "day": state.day,
        "executed": _player_ref(executed),
        "killed": None,
        "tally": dict(tally),
        "threshold": threshold,
        "stalemate": stalemate,
        "note": _vote_note(state.day, executed, stalemate, tally, threshold),
        "votes": [
            {
                "voter_id": vote.voter_id,
                "voter_name": vote.voter_name,
                "target_id": vote.target_id,
                "target_name": vote.target_name,
                "reason": vote.reason,
            }
            for vote in votes
        ],
    }
    _push_history(state, entry)


def _record_night(
    state: BloodState,
    killed: BloodPlayer | None,
    stalemate: bool,
) -> None:
    """把夜杀补进当天卷宗；若当天还没有条目则补一条完整的天。"""
    if not state.day_history or state.day_history[-1].get("day") != state.day:
        _push_history(
            state,
            {
                "day": state.day,
                "executed": None,
                "killed": None,
                "tally": {},
                "threshold": 0,
                "stalemate": False,
                "note": f"第 {state.day} 天，天亮前没有再处决谁。",
                "votes": [],
            },
        )
    entry = state.day_history[-1]
    entry["killed"] = _player_ref(killed)
    entry["phase"] = "night"
    note = str(entry.get("note", "")).rstrip("。")
    if killed is not None:
        entry["note"] = f"{note}；夜里，{killed.name}死在{AFTERMATH_DEATH_PLACE}。"
    elif stalemate:
        entry["note"] = f"{note}；凶手也没敢动手。"
    state.aftermath[-1] = dict(entry)


def _sim_day_entry(
    day: int,
    executed: BloodPlayer | None,
    killed: BloodPlayer | None,
    tally: dict[str, int],
    threshold: int,
    stalemate: bool,
) -> dict[str, object]:
    """构造真人出局后由系统推演出来的一天。"""
    note = _vote_note(day, executed, stalemate, tally, threshold)
    if killed is not None:
        note = note.rstrip("。") + f"；夜里，{killed.name}死在{AFTERMATH_DEATH_PLACE}。"
    elif stalemate:
        note = note.rstrip("。") + "；凶手也没敢动手。"
    return {
        "day": day,
        "executed": _player_ref(executed),
        "killed": _player_ref(killed),
        "tally": dict(tally),
        "threshold": threshold,
        "stalemate": stalemate,
        "note": note,
        "votes": [],
    }


def _sim_tally(
    state: BloodState,
    alive_ids: set[str],
) -> Counter[str]:
    """模拟一轮 agent 投票的票型，供卷宗记录。"""
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
    return tally


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


def _simulate_aftermath(state: BloodState) -> Winner | None:
    """真人出局后，用纯规则推演剩余处决与夜杀，逐日补进卷宗。"""
    roles = {player.id: player.role for player in state.players}
    alive_ids = {player.id for player in state.players if player.alive}
    winner = _judge_alive_ids(roles, alive_ids, state.murderer_id)
    day = state.day + 1
    while winner is None and day <= state.day + BLOOD_AFTERMATH_MAX_DAYS:
        tally = _sim_tally(state, alive_ids)
        voter_count = sum(
            1
            for player in state.players
            if player.alive and not player.is_you and player.id in alive_ids
        )
        threshold = (voter_count + 1) // 2
        executed_now = _sim_vote(state, alive_ids)
        stalemate = executed_now is None
        if executed_now is not None:
            executed_now.alive = False
            alive_ids.discard(executed_now.id)
        winner = _judge_alive_ids(roles, alive_ids, state.murderer_id)
        killed_now = None
        if winner is None and not stalemate:
            killed_now = _sim_kill(state, alive_ids)
            if killed_now is not None:
                killed_now.alive = False
                alive_ids.discard(killed_now.id)
                winner = _judge_alive_ids(roles, alive_ids, state.murderer_id)
        _push_history(
            state,
            _sim_day_entry(
                day,
                executed_now,
                killed_now,
                dict(tally),
                threshold,
                stalemate,
            ),
        )
        day += 1
    return winner


def _end_with_you_out(
    state: BloodState,
    reason: str,
    executed: BloodPlayer | None = None,
    killed: BloodPlayer | None = None,
) -> None:
    """真人出局后进入终局，并用纯规则补全卷宗摘要与最终胜负。"""
    winner = _simulate_aftermath(state)
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



def _other_name_terms(state: BloodState, target: BloodPlayer) -> list[str]:
    """收集 target 以外所有玩家的人名与称呼。"""
    terms: list[str] = []
    for player in state.players:
        if player.id == target.id:
            continue
        aliases = AGENT_ADDRESS_ALIASES.get(player.id, (player.name,))
        for alias in (*aliases, player.name):
            if alias:
                terms.append(alias)
    return terms


def _reason_names_other(
    state: BloodState,
    reason: str,
    target: BloodPlayer,
) -> bool:
    """判断理由里是否出现了 target 以外的玩家姓名或称呼。"""
    return any(term in reason for term in _other_name_terms(state, target))


def _names_self(reason: str) -> bool:
    """理由里出现“投我自己/我自己”等自指时判为不合格。"""
    return any(term in reason for term in ("我自己", "投我自己", "投我"))


def _retarget_self_reference(reason: str, target: BloodPlayer) -> str:
    """target 是真人时，把“我投你”改写成“我投旅客”，避免自指。"""
    if not target.is_you:
        return reason
    return reason.replace("我投你", f"我投{target.name}").replace(
        "投你", f"投{target.name}"
    )


def _split_clauses(text: str) -> list[str]:
    return re.split(r"[，。；！？!?;]", text)


def _reason_quote(state: BloodState, target: BloodPlayer) -> str:
    """只从 target 当天发言里取一句干净、完整、不牵连他人的小句。"""
    for entry in reversed(state.public_log):
        if entry.speaker_id != target.id or entry.day != state.day:
            continue
        for clause in reversed(_split_clauses(entry.text)):
            clean = clause.strip(" \t，,。；;：:\"'“”")
            if len(clean) < BLOOD_VOTE_REASON_MIN_QUOTE_CHARS:
                continue
            if len(clean) > BLOOD_VOTE_REASON_QUOTE_CHARS:
                continue
            if "我自己" in clean or "我投" in clean:
                continue
            if any(term in clean for term in VOTE_REASON_PLACEHOLDERS):
                continue
            if any(term in clean for term in BLOOD_SECRET_CLAIM_TERMS):
                continue
            if _reason_names_other(state, clean, target):
                continue
            return clean
    return ""


def _norm_text(text: str) -> str:
    return re.sub(r"[\s，。；：、！？!?\"“”「」]", "", text)


def _quotes_faithful(
    state: BloodState,
    target: BloodPlayer,
    reason: str,
) -> bool:
    """理由里的引文必须来自 target 当天发言，且不允许嵌套引号。"""
    if reason.count("“") != reason.count("”"):
        return False
    if reason.count("「") != reason.count("」"):
        return False
    quotes = re.findall(r"[“「]([^“”「」]{1,60})[”」]", reason)
    if not quotes:
        return True
    day_text = _norm_text(
        "".join(
            entry.text
            for entry in state.public_log
            if entry.speaker_id == target.id and entry.day == state.day
        )
    )
    if not day_text:
        return False
    for quote in quotes:
        cleaned = _norm_text(quote)
        if not cleaned or cleaned not in day_text:
            return False
    return True


def _valid_reason(
    state: BloodState,
    reason: str,
    target: BloodPlayer,
) -> bool:
    """投票理由的硬约束：围绕 target、无占位、引文保真、句末收束。"""
    if not reason:
        return False
    if target.name not in reason:
        return False
    if any(term in reason for term in VOTE_REASON_PLACEHOLDERS):
        return False
    if _names_self(reason):
        return False
    if _reason_names_other(state, reason, target):
        return False
    if any(claim in reason for claim in FORBIDDEN_AGENT_CLAIMS):
        return False
    if any(term in reason for term in BLOOD_SECRET_CLAIM_TERMS):
        return False
    if reason[-1] not in SENTENCE_ENDS:
        return False
    return _quotes_faithful(state, target, reason)


def _fallback_reason(
    state: BloodState,
    voter: BloodPlayer,
    target: BloodPlayer,
) -> str:
    """按 voter/target 轮换生成不重样、且绑定当日发言的兜底理由。"""
    quote = _reason_quote(state, target)
    voter_index = int(voter.id[1:])
    target_index = int(target.id[1:])
    if quote:
        index = (voter_index * 5 + target_index * 3) % len(
            VOTE_REASON_FALLBACKS
        )
        candidate = _clip_sentence(
            VOTE_REASON_FALLBACKS[index].format(
                name=target.name,
                quote=quote,
            ),
            BLOOD_VOTE_REASON_MAX_CHARS,
        )
        if _valid_reason(state, candidate, target):
            return candidate
    no_quote_index = (voter_index * 3 + target_index) % len(
        VOTE_REASON_NO_QUOTE_FALLBACKS
    )
    candidate = _clip_sentence(
        VOTE_REASON_NO_QUOTE_FALLBACKS[no_quote_index].format(
            name=target.name
        ),
        BLOOD_VOTE_REASON_MAX_CHARS,
    )
    return candidate


def _aligned_reason(
    state: BloodState,
    voter: BloodPlayer,
    target: BloodPlayer,
    raw: str,
) -> str:
    """把理由绑定到实际投票目标；错引、占位或攀扯旁人时改用轮换模板。"""
    reason = _clip_sentence(raw, BLOOD_VOTE_REASON_MAX_CHARS)
    if not reason:
        return _fallback_reason(state, voter, target)
    reason = _retarget_self_reference(reason, target)
    if not _valid_reason(state, reason, target):
        return _fallback_reason(state, voter, target)
    return reason


def _follow_target(
    state: BloodState,
    agent: BloodPlayer,
    follow_id: str | None,
) -> BloodPlayer | None:
    """按 follow_prob 决定是否跟随真人/盟约目标，绝不投自己。"""
    if not follow_id or agent.follow_prob <= 0.0:
        return None
    candidate = _player(state, follow_id)
    if candidate is None or not candidate.alive or candidate.id == agent.id:
        return None
    if state.rng.random() >= agent.follow_prob:
        return None
    return candidate


def _agent_vote(
    state: BloodState,
    agent: BloodPlayer,
    reply_fn: ReplyFn,
    follow_id: str | None = None,
) -> VoteResult | None:
    """agent 投给最怀疑的人；密谈结盟时按 follow_prob 跟随一次。"""
    target = _follow_target(state, agent, follow_id)
    if target is None:
        target = _player(state, _top_suspicion_target(state, agent))
    if target is None:
        return None
    state.pending_hint = "vote_reason"
    state.pending_target_id = target.id
    reason = ""
    try:
        raw = reply_fn(state, agent)
        reason = _clip_sentence(raw, BLOOD_VOTE_REASON_MAX_CHARS)
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


def _no_execution_message(tally: dict[str, int], threshold: int) -> str:
    """区分平票流局与未达门槛，并说明当夜凶手也没敢动手。"""
    if not tally:
        return "平票，今晚无人被处决；凶手也没敢动手。"
    top = max(tally.values())
    leaders = [count for count in tally.values() if count == top]
    if len(leaders) > 1:
        return "平票，今晚无人被处决；凶手也没敢动手。"
    return (
        f"最高 {top} 票，未达 {threshold} 票门槛，今晚无人被处决；"
        "凶手也没敢动手。"
    )


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
        follow_id = state.confide_intents.get(agent.id, target.id)
        agent_vote = _agent_vote(state, agent, reply_fn, follow_id)
        if agent_vote is not None:
            votes.append(agent_vote)
    tally, threshold, executed = _resolve_votes(state, votes)
    stalemate = executed is None
    if executed is not None:
        executed.alive = False
        _say(state, "system", "旁白", f"{executed.name} 被投票处决。")
        state.message = f"{executed.name} 被处决，天黑了。"
    else:
        state.message = _no_execution_message(tally, threshold)
    _record_vote_day(state, executed, tally, threshold, votes, stalemate)
    _log(state, _vote_log_entry(state, votes))
    winner = _judge(state)
    if not you.alive:
        _end_with_you_out(
            state,
            f"{you.name} 出局了，本局到此为止。",
            executed=executed,
        )
    elif winner is not None:
        _declare_winner(state, winner, _win_text(winner))
    else:
        state.phase = "night"
        state.night_blocked = stalemate
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
        day_history=tuple(state.day_history),
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
    if state.night_blocked:
        state.night_blocked = False
        _record_night(state, None, True)
        _log(
            state,
            {
                "type": "night",
                "day": state.day,
                "killed": None,
                "stalemate": True,
            },
        )
        winner = _judge(state)
        if winner is not None:
            _declare_winner(state, winner, _win_text(winner))
        else:
            _reset_day(state)
        state.message = "平票，今晚无人被处决；凶手也没敢动手。"
        return NightOutcome(
            ok=True,
            error=None,
            killed=None,
            day=state.day,
            phase=state.phase,
            winner=state.winner,
            reveal=_reveal_of(state),
            message=state.message,
            aftermath=tuple(state.aftermath),
            day_history=tuple(state.day_history),
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
    _record_night(state, victim, False)
    _log(
        state,
        {
            "type": "night",
            "day": state.day,
            "killed": victim.id if victim is not None else None,
        },
    )
    winner = _judge(state)
    if not you.alive:
        _end_with_you_out(
            state,
            f"{you.name} 没能等到天亮，本局到此为止。",
            killed=victim,
        )
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
            day_history=tuple(state.day_history),
        )
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
            day_history=tuple(state.day_history),
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
        day_history=tuple(state.day_history),
    )


def _clip_trust(value: float) -> float:
    return min(100.0, max(0.0, value))


def _adjust_suspicion(
    player: BloodPlayer,
    target_id: str,
    delta: float,
) -> None:
    current = player.suspicion.get(target_id, 0.0)
    player.suspicion[target_id] = _clip(current + delta)


def _lie_propensity(state: BloodState, player: BloodPlayer) -> float:
    if player.role_id is None:
        return 0.3
    for role in state.script.roles:
        if role.id == player.role_id:
            return role.lie_propensity
    return 0.3


def _confide_resolution(
    state: BloodState,
    target: BloodPlayer,
    text: str,
) -> tuple[str, bool]:
    """先按话术定 stance；承诺类再按 lie_propensity 掷出是否守信。"""
    if any(term in text for term in CONFIDE_THREAT_TERMS):
        return "threaten", False
    if any(term in text for term in CONFIDE_EVIDENCE_TERMS):
        return "refuse", False
    if any(term in text for term in CONFIDE_PROMISE_TERMS):
        keep_prob = 1.0 - _lie_propensity(state, target)
        if target.role == "murderer":
            keep_prob *= 0.7
        keep_prob = min(0.95, max(0.05, keep_prob))
        if state.rng.random() < keep_prob:
            return "accept", True
        if state.rng.random() < 0.5:
            return "accept", False
        return "evade", False
    return "evade", False


def _confide_intent(
    state: BloodState,
    target: BloodPlayer,
    text: str,
) -> str | None:
    """从密谈正文里读出玩家希望一起投的人，供次日跟随。"""
    for player in state.players:
        if player.id in (target.id, YOU_ID) or not player.alive:
            continue
        aliases = AGENT_ADDRESS_ALIASES.get(player.id, (player.name,))
        if any(alias and alias in text for alias in (*aliases, player.name)):
            return player.id
    if state.nominee_id is not None and state.nominee_id != target.id:
        return state.nominee_id
    return None


def _sanitize_confide_reply(
    state: BloodState,
    player: BloodPlayer,
    text: str,
    stance: str,
    you_text: str,
) -> str:
    """私下回复也受事实边界约束：不认玩家编的物证、不念档案、不造人名。"""
    fallback = CONFIDE_STANCE_FALLBACKS.get(
        stance,
        CONFIDE_STANCE_FALLBACKS["evade"],
    )
    flat = _clip_sentence(text, CONFIDE_REPLY_MAX_CHARS)
    if not flat:
        return fallback
    if any(claim in flat for claim in FORBIDDEN_AGENT_CLAIMS):
        return fallback
    if any(term in flat for term in BLOOD_SECRET_CLAIM_TERMS):
        return fallback
    if (
        any(term in you_text for term in CONFIDE_PLAYER_EVIDENCE_TERMS)
        and any(term in flat for term in CONFIDE_ENDORSE_TERMS)
    ):
        return fallback
    flat = _strip_memory_tail(flat)
    flat = _scrub_private_fact_text(state, player, flat)
    if not flat:
        return fallback
    flat = _filter_unknown_names(state, flat)
    if any(term in flat for term in VOTE_REASON_PLACEHOLDERS):
        return fallback
    return flat


def confide(
    store: BloodStore,
    game_id: str,
    target_id: str,
    text: str,
    confide_fn: ConfideFn,
) -> ConfideOutcome:
    """真人私下找一名 agent 说话，每天 1 次、每局最多 3 次。"""
    state = store.get(game_id)
    if state is None:
        return ConfideOutcome(ok=False, error="game_not_found")
    if state.phase == "ended":
        return ConfideOutcome(ok=False, error="game_ended")
    if state.phase not in ("discussion", "defense"):
        return ConfideOutcome(ok=False, error="wrong_phase")
    you = _you(state)
    if not you.alive:
        return ConfideOutcome(ok=False, error="you_are_dead")
    if state.confide_count >= LIMIT_PER_GAME:
        return ConfideOutcome(ok=False, error="confide_limit")
    if state.confide_day == state.day:
        return ConfideOutcome(ok=False, error="confide_used_day")
    target = _player(state, target_id)
    if target is None:
        return ConfideOutcome(ok=False, error="target_not_found")
    if target.is_you:
        return ConfideOutcome(ok=False, error="confide_self")
    if not target.alive:
        return ConfideOutcome(ok=False, error="target_dead")
    clean_text = _flat_line(text)
    if not clean_text or len(clean_text) > CONFIDE_TEXT_MAX_CHARS:
        return ConfideOutcome(ok=False, error="confide_text_invalid")

    stance, kept = _confide_resolution(state, target, clean_text)
    if stance == "accept":
        if kept:
            target.trust = _clip_trust(target.trust + CONFIDE_TRUST_ACCEPT)
            _adjust_suspicion(target, you.id, CONFIDE_SUSPICION_ACCEPT)
            target.follow_prob = min(
                FOLLOW_MAX,
                target.follow_prob + FOLLOW_ACCEPT_DELTA,
            )
        else:
            target.trust = _clip_trust(target.trust + BETRAY_TRUST_DELTA)
            _adjust_suspicion(target, you.id, BETRAY_SUSPICION_DELTA)
            state.pending_leaks[target.id] = CONFIDE_BETRAY_LINE
    elif stance == "refuse":
        target.trust = _clip_trust(target.trust + CONFIDE_TRUST_REFUSE)
        _adjust_suspicion(target, you.id, CONFIDE_SUSPICION_REFUSE)
    elif stance == "threaten":
        target.trust = _clip_trust(target.trust + CONFIDE_TRUST_THREATEN)
        _adjust_suspicion(target, you.id, CONFIDE_SUSPICION_THREATEN)

    if target.id not in state.pending_leaks:
        leak_rate = (
            LEAK_RATE_MURDERER
            if target.role == "murderer"
            else LEAK_RATE_NORMAL
        )
        if state.rng.random() < leak_rate:
            state.pending_leaks[target.id] = clean_text

    intent = _confide_intent(state, target, clean_text)
    if intent is not None:
        state.confide_intents[target.id] = intent

    raw = ""
    try:
        raw = confide_fn(state, target, clean_text, stance)
    except Exception:
        logger.warning("密谈回复生成失败：%s", target.id, exc_info=True)
    reply = _sanitize_confide_reply(
        state,
        target,
        raw,
        stance,
        clean_text,
    )
    entry = ConfideEntry(
        seq=len(state.private_log) + 1,
        day=state.day,
        target_id=target.id,
        target_name=target.name,
        text=clean_text,
        stance=stance,
        reply=reply,
    )
    state.private_log.append(entry)
    state.confide_day = state.day
    state.confide_count += 1
    public_line = f"你与{target.name}在廊下低声说了几句。"
    _say(state, "system", "旁白", public_line)
    _log(
        state,
        {
            "type": "confide",
            "day": state.day,
            "target_id": target.id,
        },
    )
    state.message = public_line
    return ConfideOutcome(
        ok=True,
        error=None,
        target=target,
        stance=stance,
        reply=reply,
        trust=int(round(target.trust)),
        suspicion=int(round(target.suspicion.get(you.id, 0.0) * 100)),
        follow_prob=round(target.follow_prob, 3),
        public_line=public_line,
        remaining=max(0, LIMIT_PER_GAME - state.confide_count),
        entry=entry,
    )


def last_words(
    store: BloodStore,
    game_id: str,
    text: str,
) -> LastWordsOutcome:
    """真人出局后可留一条遗言，进入公开日志且不改变胜负。"""
    state = store.get(game_id)
    if state is None:
        return LastWordsOutcome(ok=False, error="game_not_found")
    you = _you(state)
    if you.alive:
        return LastWordsOutcome(ok=False, error="you_are_alive")
    if state.last_words_used:
        return LastWordsOutcome(ok=False, error="last_words_used")
    clean = _clip_sentence(text, BLOOD_LAST_WORDS_MAX_CHARS)
    if not clean:
        return LastWordsOutcome(ok=False, error="last_words_invalid")
    state.last_words_used = True
    _say(state, you.id, you.name, clean)
    _log(
        state,
        {
            "type": "last_words",
            "day": state.day,
            "text": clean,
        },
    )
    if state.day_history:
        for index in range(len(state.day_history) - 1, -1, -1):
            if state.day_history[index].get("day") != state.day:
                continue
            state.day_history[index]["last_words"] = clean
            if index < len(state.aftermath):
                state.aftermath[index] = dict(state.day_history[index])
            break
    state.message = f"{you.name} 留下了最后一句话。"
    return LastWordsOutcome(
        ok=True,
        error=None,
        text=clean,
        message=state.message,
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
    state.night_blocked = False
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
        day_history=tuple(state.day_history),
        you_alive=you.alive,
    )


def build_log(state: BloodState) -> list[dict[str, object]]:
    """返回不含秘密字段的回看日志。"""
    return [dict(entry) for entry in state.log]