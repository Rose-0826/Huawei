"""阵营模式「电子血染」的状态机：只做状态转移，不调用模型。"""

from __future__ import annotations

import logging
import random
import re
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from copy import copy
from dataclasses import dataclass, field
from typing import Callable, Literal

from app.config import (
    BETRAY_SUSPICION_DELTA,
    BETRAY_TRUST_DELTA,
    BLOOD_HEARSAY_PREFIX,
    BLOOD_INITIAL_SUSPICION_BASE,
    BLOOD_INITIAL_SUSPICION_JITTER,
    BLOOD_INSPECT_PUBLIC_TEMPLATE,
    BLOOD_INSPECT_SUSPICION_INNOCENT,
    BLOOD_INSPECT_SUSPICION_MURDERER,
    BLOOD_INSPECT_USE_PER_GAME,
    BLOOD_KNOWN_PERSON_TERMS,
    BLOOD_EXECUTE_MESSAGE,
    BLOOD_LAST_WORDS_MAX_CHARS,
    BLOOD_MAX_DAYS,
    BLOOD_MAX_DEFENSE_SPEAK_PER_DAY,
    BLOOD_MAX_FACTS_PER_DAY,
    BLOOD_MAX_LINE_CHARS,
    BLOOD_MAX_SPEAK_PER_DAY,
    BLOOD_MAX_SUSPICION,
    BLOOD_MEMORY_MARKERS,
    BLOOD_MINION_COUNT,
    BLOOD_NIGHT_MESSAGE,
    BLOOD_DYNAMIC_CLEAR_TEMPLATE,
    BLOOD_DYNAMIC_PAIR_TEMPLATE,
    BLOOD_PACT_NOTE_TEMPLATE,
    BLOOD_POISON_FALLBACK_TEXT,
    BLOOD_POISON_NOTE,
    BLOOD_POISON_NOTE_DYNAMIC,
    BLOOD_POISON_TIME_SHIFT_MINUTES,
    BLOOD_PRIVATE_FACTS_MAX,
    BLOOD_PRIVATE_FACTS_MIN,
    BLOOD_PRIVATE_MAX_SENSITIVITY,
    BLOOD_RUNOFF_MESSAGE,
    BLOOD_SECRET_CLAIM_TERMS,
    BLOOD_SECRET_IDENTITY_TERMS,
    BLOOD_SUCCESSOR_PUBLIC_TEXT,
    BLOOD_SUSPICION_FACT,
    BLOOD_SUSPICION_MENTION,
    BLOOD_SUSPICION_MURDERER,
    BLOOD_STALEMATE_MIN_THRESHOLD,
    BLOOD_STALEMATE_RELIEF_AFTER,
    BLOOD_STILL_TIE_MESSAGE,
    BLOOD_VAGUE_REWRITE,
    BLOOD_VOTE_REASON_MAX_CHARS,
    BLOOD_VOTE_REASON_MIN_QUOTE_CHARS,
    BLOOD_VOTE_REASON_QUOTE_CHARS,
    BLOOD_WHISPER_PUBLIC_TEMPLATE,
    BLOOD_WHISPER_SUSPICION_DELTA,
    BLOOD_WHISPER_TRUST_DELTA,
    CONFIDE_REPLY_MAX_CHARS,
    CONFIDE_SUSPICION_ACCEPT,
    CONFIDE_SUSPICION_EVADE,
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
    OWNERSHIP_KEY_TERMS,
)
from app.models import Script

logger = logging.getLogger(__name__)

RoleKind = Literal["villager", "murderer", "minion"]
EvilRole = Literal["murderer", "minion"]
Phase = Literal[
    "discussion", "defense", "runoff", "night", "spectating", "ended"
]
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
DEFENSE_FALLBACKS_AI: dict[str, str] = {
    "p1": "既然把我推上桌，我把话说明白：那晚我进过二楼，是点灯油查账，没进书房。要查就查谁在我之后下了楼。",
    "p2": "既然把我推上桌，这笔账我不认。那晚我在楼梯口听见书房吵得凶，就没敢往前——听见和动手是两回事。",
    "p3": "既然把我推上桌，我把话说明白：我上楼送过炭，灯太暗，书房门是掩着的，我没进去。谁最后出来，你们该问。",
    "p4": "既然把我推上桌，我认我去过二楼。我是听见闷响才探头，没敢声张。可要说动手，我连拨火棍都没碰过。",
    "p5": "既然把我推上桌，我认我没说全。那晚我在马厩添草，后来端热水进去，人已经没了。我瞒的是别的，不是人命。",
}
DEFENSE_FALLBACK_DEFAULT_AI: str = (
    "既然把我推上桌，我不能不答。那晚我在哪儿、做过什么，我都说了，没进过书房。"
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
    "当众说",
    "当众讲",
    "当众抖",
    "跟我走",
    "跟我投",
    "按我说的投",
    "不然我",
    "不然现在",
    "别怪我说",
    "抖出去",
    "捅出去",
    "掀出来",
    "我就当没看见",
    "你会后悔的",
    "你掂量",
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
CONFIDE_BETRAY_REPLY: str = "话我先应着；真到了桌上，我只按自己的证据投。"
CONFIDE_DENIAL_TERMS: tuple[str, ...] = (
    "我没见过",
    "没见过这东西",
    "我没碰过",
    "没碰过",
    "我不认得",
    "我不认识",
    "没拿过",
    "我没拿",
)
CONFIDE_OBJECT_TERMS: tuple[str, ...] = (
    "手帕",
    "拨火棍",
    "银元",
    "登记簿",
    "簿子",
    "账本",
    "铜纽扣",
    "炭",
    "热水",
    "水壶",
)
CONFIDE_ENDORSE_VERBS: tuple[str, ...] = (
    "攥着",
    "拿着",
    "收着",
    "握着",
    "我见过",
    "我认得",
    "袖口",
    "身上",
    "手里",
)
UNKNOWN_PLACE_TERMS: tuple[str, ...] = (
    "西厢密室",
    "密室",
    "暗室",
    "地窖",
    "柴房",
    "阁楼",
    "偏院",
)
FEMALE_IDS: frozenset[str] = frozenset({"p1", "p3"})
EVIL_ROLES: frozenset[str] = frozenset({"murderer", "minion"})
TIME_MENTION_PATTERN = re.compile(
    r"\d{1,2}[:：]\d{2}|[零一二三四五六七八九十两]{1,3}点(?:半)?|二更|三更|后半夜|天亮前"
)
TIME_POISON_PATTERN = re.compile(r"(\d{1,2})[:：](\d{2})")
PLACE_EVIDENCE_TERMS: tuple[str, ...] = (
    "书房",
    "楼梯口",
    "廊下",
    "马厩",
    "马棚",
    "后堂",
    "内宅",
    "下房",
    "账房",
    "客房",
    "前厅",
    "后院",
    "门房",
    "灶间",
)
ACTION_EVIDENCE_TERMS: tuple[str, ...] = (
    "翻页",
    "翻账",
    "账页",
    "翻簿",
    "翻登记",
    "翻那本",
    "添炭",
    "端水",
    "拨火棍",
    "手帕",
    "银元",
    "铜纽扣",
)
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
    poisoned: bool = False
    pact_ids: set[str] = field(default_factory=set)
    trust_map: dict[str, float] = field(default_factory=dict)
    dynamic_indexes: set[int] = field(default_factory=set)
    pact_indexes: set[int] = field(default_factory=set)
    dynamic_evil_name: str = ""
    dynamic_clear_name: str = ""


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
    confide_day: int = 0
    confide_count: int = 0
    private_log: list[ConfideEntry] = field(default_factory=list)
    confide_intents: dict[str, str] = field(default_factory=dict)
    vote_reason_log: list[dict[str, object]] = field(default_factory=list)
    pending_leaks: dict[str, str] = field(default_factory=dict)
    private_denials: dict[str, set[str]] = field(default_factory=dict)
    last_words_used: bool = False
    inspect_used: bool = False
    runoff: bool = False
    runoff_candidates: list[str] = field(default_factory=list)
    stalemate_count: int = 0
    ghost_vote_used: bool = False
    pending_night: bool = False
    minion_id: str = ""
    original_murderer_id: str = ""
    succession: list[dict[str, object]] = field(default_factory=list)
    poisoned_id: str | None = None
    poisoned_clue_original: str = ""
    poisoned_clue_rewritten: str = ""
    poisoned_clue_kind: str = ""
    defense_origin: str = ""
    focus_by_day: dict[int, dict[str, str]] = field(default_factory=dict)
    whisper_days: dict[int, list[str]] = field(default_factory=dict)
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
    """终局揭晓：凶手、爪牙、传位链与中毒者。"""

    murderer_id: str
    murderer_name: str
    final_murderer_id: str = ""
    final_murderer_name: str = ""
    minion_id: str = ""
    minion_name: str = ""
    poisoned_id: str = ""
    poisoned_name: str = ""
    poisoned_note: str = ""
    killed_id: str = ""
    killed_name: str = ""
    succession: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True)
class RunoffCandidate:
    """重投阶段的一名候选。"""

    id: str
    name: str


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
    runoff_candidates: tuple[RunoffCandidate, ...] = ()
    stalemate_count: int = 0
    ghost_vote_available: bool = False
    your_result: str | None = None
    you_win: bool | None = None


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
    runoff_candidates: tuple[RunoffCandidate, ...] = ()
    stalemate_count: int = 0


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
    you_alive: bool = True


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
    betrayed: bool = False
    entry: ConfideEntry | None = None


@dataclass(frozen=True)
class InspectOutcome:
    """真人一次查验的结果，只答是否凶手。"""

    ok: bool
    error: str | None
    target: BloodPlayer | None = None
    result: str = ""
    public_line: str = ""
    remaining: int = 0
    revealed: bool = False


@dataclass(frozen=True)
class AdvanceOutcome:
    """观战推进：agent 代跑讨论、提名、投票与夜晚后的结果。"""

    ok: bool
    error: str | None
    phase: Phase = "discussion"
    day: int = 1
    public_log: tuple[BloodLogEntry, ...] = ()
    votes: tuple[VoteResult, ...] = ()
    executed: BloodPlayer | None = None
    killed: BloodPlayer | None = None
    winner: Winner | None = None
    reveal: RevealView | None = None
    ghost_vote_available: bool = False
    new_entries: tuple[BloodLogEntry, ...] = ()


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
        original_murderer_id=murderer.id,
        rng=rng,
    )
    for player in players:
        player.private_info = _private_info(script, player, rng)
    rest = [player for player in players if player.id != murderer.id]
    minion = rest[rng.randrange(len(rest))]
    minion.role = "minion"
    state.minion_id = minion.id
    if minion.is_you:
        minion.private_info[-1] = (
            f"只有你知道：{murderer.name} 是昨夜动手的恶魔，你们是一伙的。"
        )
    _inject_dynamic_clues(state, rng)
    _apply_poison(state, rng)
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


def _inject_dynamic_clues(state: BloodState, rng: random.Random) -> None:
    """给好人镇民追加两条本局专属当夜线索，真人为好人时优先拿到清白佐证。"""
    you = _you(state)
    good_agents = [
        player
        for player in state.players
        if player.role == "villager" and not player.is_you
    ]
    if len(good_agents) < 2:
        return
    rng.shuffle(good_agents)
    receivers: list[BloodPlayer] = []
    if you.role == "villager":
        receivers.append(you)
    receivers.extend(good_agents)
    clear_receiver = receivers[0]
    pair_receiver = next(
        player for player in receivers[1:] if player.id != clear_receiver.id
    )
    clear_pool = [
        player
        for player in state.players
        if player.role == "villager" and player.id != clear_receiver.id
    ]
    if not clear_pool:
        return
    clear_target = rng.choice(clear_pool)
    _append_dynamic_clue(
        clear_receiver,
        BLOOD_DYNAMIC_CLEAR_TEMPLATE.format(good=clear_target.name),
        clear_name=clear_target.name,
    )
    evil = _player(state, state.murderer_id)
    good_pool = [
        player
        for player in state.players
        if player.role == "villager"
        and not player.is_you
        and player.id != pair_receiver.id
        and (evil is None or player.id != evil.id)
    ]
    if evil is None or not good_pool:
        return
    good = rng.choice(good_pool)
    _append_dynamic_clue(
        pair_receiver,
        BLOOD_DYNAMIC_PAIR_TEMPLATE.format(evil=evil.name, good=good.name),
        evil_name=evil.name,
    )


def _append_dynamic_clue(
    player: BloodPlayer,
    text: str,
    evil_name: str = "",
    clear_name: str = "",
) -> None:
    """把一条当夜线索追加到私密信息末尾，并记录可被下药改写的索引。"""
    player.private_info.append(text)
    player.dynamic_indexes.add(len(player.private_info) - 1)
    if evil_name:
        player.dynamic_evil_name = evil_name
    if clear_name:
        player.dynamic_clear_name = clear_name


def _apply_poison(state: BloodState, rng: random.Random) -> None:
    """随机给一名镇民下药，优先污染其本局当夜线索。"""
    candidates = [
        player
        for player in state.players
        if player.role == "villager" and not player.is_you and player.private_info
    ]
    if not candidates:
        return
    dynamic = [player for player in candidates if player.dynamic_indexes]
    victim = rng.choice(dynamic or candidates)
    index = _poison_index(state, victim, rng)
    original = victim.private_info[index]
    rewritten = _poison_text(state, victim, original, rng)
    victim.private_info[index] = rewritten
    victim.poisoned = True
    state.poisoned_id = victim.id
    state.poisoned_clue_original = original
    state.poisoned_clue_rewritten = rewritten
    if victim.dynamic_clear_name:
        state.poisoned_clue_kind = "清白佐证"
    elif victim.dynamic_evil_name:
        state.poisoned_clue_kind = "双人排查线索"


def _poison_index(
    state: BloodState,
    victim: BloodPlayer,
    rng: random.Random,
) -> int:
    """优先改写受害者手里的本局当夜线索，其次挑含时刻或他人姓名的条目。"""
    if victim.dynamic_indexes:
        return rng.choice(sorted(victim.dynamic_indexes))
    timed = [
        index
        for index, text in enumerate(victim.private_info)
        if TIME_POISON_PATTERN.search(text)
    ]
    named = [
        index
        for index, text in enumerate(victim.private_info)
        if any(
            other.id != victim.id and other.name in text
            for other in state.players
        )
    ]
    pool = timed or named or list(range(len(victim.private_info)))
    return rng.choice(pool)


def _poison_text(
    state: BloodState,
    victim: BloodPlayer,
    text: str,
    rng: random.Random,
) -> str:
    """把一条私有信息改写成错误的时辰、人物或地点，且绝不与原文相同。"""
    if victim.dynamic_evil_name and victim.dynamic_evil_name in text:
        pool = [
            player.name
            for player in state.players
            if player.id != victim.id
            and player.role == "villager"
            and player.name not in text
        ]
        if pool:
            return text.replace(
                victim.dynamic_evil_name,
                rng.choice(pool),
                1,
            )
    if victim.dynamic_clear_name and victim.dynamic_clear_name in text:
        pool = [
            player.name
            for player in state.players
            if player.id != victim.id
            and player.role in EVIL_ROLES
            and player.name not in text
        ]
        if pool:
            return text.replace(
                victim.dynamic_clear_name,
                rng.choice(pool),
                1,
            )
    match = TIME_POISON_PATTERN.search(text)
    if match is not None:
        hour = int(match.group(1))
        minute = int(match.group(2))
        total = (
            hour * 60 + minute + BLOOD_POISON_TIME_SHIFT_MINUTES
        ) % (24 * 60)
        wrong = f"{total // 60:02d}:{total % 60:02d}"
        return f"{text[: match.start()]}{wrong}{text[match.end() :]}"
    mentioned = [
        player
        for player in state.players
        if player.id != victim.id and player.name in text
    ]
    if mentioned:
        swapped = mentioned[0]
        pool = [
            player.name
            for player in state.players
            if player.id not in (victim.id, swapped.id)
            and player.name not in text
        ]
        if pool:
            return text.replace(swapped.name, rng.choice(pool), 1)
    places = [term for term in PLACE_EVIDENCE_TERMS if term in text]
    if places:
        pool = [term for term in PLACE_EVIDENCE_TERMS if term not in text]
        if pool:
            return text.replace(places[0], rng.choice(pool), 1)
    return BLOOD_POISON_FALLBACK_TEXT


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
            if player.role in EVIL_ROLES and other.role == "villager":
                value += BLOOD_SUSPICION_MURDERER
            if player.role in EVIL_ROLES and other.role in EVIL_ROLES:
                value = min(
                    value,
                    BLOOD_INITIAL_SUSPICION_BASE - 0.05,
                )
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
    """按当天的条数上限，取一条尚未公开、且当天尽量不与他人重样的私密信息。"""
    if player.is_you:
        return None
    if player.released_day != state.day:
        player.released_day = state.day
        player.released_today = 0
    if player.released_today >= allow:
        return None
    used_today = set(state.focus_by_day.get(state.day, {}).values())
    for index in _focus_order(state, player, used_today):
        if index in player.released or index in player.pact_indexes:
            continue
        player.released.add(index)
        player.released_today += 1
        text = player.private_info[index]
        state.focus_by_day.setdefault(state.day, {})[player.id] = text
        _log(
            state,
            {
                "type": "release",
                "day": state.day,
                "speaker": player.id,
                "index": index,
                "focus": text,
            },
        )
        return text
    return None


def _focus_order(
    state: BloodState,
    player: BloodPlayer,
    used_today: set[str],
) -> list[int]:
    """按天与玩家偏移轮换私有信息，并把当天已被别人用过的条目排到后面。"""
    count = len(player.private_info)
    if count == 0:
        return []
    offset = (state.day + int(player.id[1:])) % count
    order = [(offset + step) % count for step in range(count)]
    fresh = [
        index for index in order if player.private_info[index] not in used_today
    ]
    stale = [index for index in order if index not in fresh]
    return fresh + stale


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
    allowed_ids: set[str] | None = None,
    avoid_pacts: bool = False,
) -> str | None:
    """取最怀疑的存活者；串供结盟时先避开同伴互咬。"""
    candidates = [
        other
        for other in state.players
        if other.alive
        and other.id != player.id
        and (allowed_ids is None or other.id in allowed_ids)
    ]
    if not candidates:
        return None
    if avoid_pacts and player.pact_ids:
        loyal = [
            other for other in candidates if other.id not in player.pact_ids
        ]
        if loyal:
            candidates = loyal
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


def _self_terms(player: BloodPlayer) -> tuple[str, ...]:
    """收集发言人的姓名与公开称呼，长词优先替换。"""
    terms = {player.name, *AGENT_ADDRESS_ALIASES.get(player.id, ())}
    return tuple(sorted((term for term in terms if term), key=len, reverse=True))


def _scrub_self_reference(player: BloodPlayer, text: str) -> str:
    """agent 用第三人称说自己时，改写为第一人称自指。"""
    for term in _self_terms(player):
        text = text.replace(f"我和{term}自己", "我自己")
        text = text.replace(f"我跟{term}自己", "我自己")
        text = text.replace(f"我和{term}", "我自己")
        text = text.replace(f"我跟{term}", "我自己")
        text = text.replace(f"{term}自己", "我自己")
        text = text.replace(term, "我")
    while "我我" in text:
        text = text.replace("我我", "我")
    return text


def _holder_has_term(
    state: BloodState,
    player: BloodPlayer,
    term: str,
) -> bool:
    """判断这名玩家是否凭私有信息或剧本持有人身份持有该线索物件。"""
    if any(term in text for text in player.private_info):
        return True
    if player.role_id is None:
        return False
    return any(
        player.role_id in fact.holders and term in fact.text
        for fact in state.script.facts
    )


def _scrub_misattributed_claim(
    state: BloodState,
    player: BloodPlayer,
    text: str,
) -> str:
    """把别人的线索认成自己亲历，或把线索扣给不持有者时整句弃用。"""
    for term in OWNERSHIP_KEY_TERMS:
        if term not in text:
            continue
        speaker_has = _holder_has_term(state, player, term)
        for other in state.players:
            if other.id == player.id:
                continue
            aliases = AGENT_ADDRESS_ALIASES.get(other.id, (other.name,))
            if not any(alias in text for alias in (*aliases, other.name)):
                continue
            other_has = _holder_has_term(state, other, term)
            if speaker_has and not other_has:
                return ""
            if other_has and not speaker_has and "我" in text:
                return ""
    return text


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
    flat = _scrub_self_reference(player, flat)
    flat = _scrub_misattributed_claim(state, player, flat)
    if not flat:
        return ""
    if _conflicts_with_denial(state, player, flat):
        return ""
    flat = _filter_unknown_names(state, flat)
    flat = _filter_unknown_places(flat)
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


def _filter_unknown_places(text: str) -> str:
    """把剧本里没有登记的地点（如西厢密室）替换成「别处」。"""
    for term in UNKNOWN_PLACE_TERMS:
        text = text.replace(term, "别处")
    return text


def _is_female(player: BloodPlayer) -> bool:
    """按角色 id 判断旁白与理由里该用「她」还是「他」。"""
    return player.id in FEMALE_IDS


def _gendered(text: str, target: BloodPlayer) -> str:
    """女性角色的第三人称一律用「她」，避免旁白与理由串性别。"""
    if not _is_female(target):
        return text
    return text.replace("他", "她")


def _record_denials(
    state: BloodState,
    player: BloodPlayer,
    you_text: str,
    reply: str,
) -> None:
    """记下 agent 在廊下否认过的物件，防止公开场合改口承认。"""
    if not any(term in reply for term in CONFIDE_DENIAL_TERMS):
        return
    denied = {
        term for term in CONFIDE_OBJECT_TERMS if term in you_text
    }
    if denied:
        state.private_denials.setdefault(player.id, set()).update(denied)


def _conflicts_with_denial(
    state: BloodState,
    player: BloodPlayer,
    text: str,
) -> bool:
    """公开场合把廊下否认过的物件说成自己攥着/拿着时判为自相矛盾。"""
    denied = state.private_denials.get(player.id, set())
    if not denied:
        return False
    if any(term in text for term in CONFIDE_DENIAL_TERMS):
        return False
    return any(
        term in text and any(verb in text for verb in CONFIDE_ENDORSE_VERBS)
        for term in denied
    )


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


def _add_pact_note(player: BloodPlayer, other: BloodPlayer) -> None:
    """把廊下默契写进双方私密信息，且不占用每天可公开的私密片段。"""
    marker = f"与{other.name}低声通过气"
    if any(marker in text for text in player.private_info):
        return
    player.private_info.append(BLOOD_PACT_NOTE_TEMPLATE.format(other=other.name))
    player.pact_indexes.add(len(player.private_info) - 1)


def _maybe_whisper(state: BloodState) -> None:
    """每天讨论阶段随机两名 agent 私下串供：公开只留一句旁白。"""
    if state.day in state.whisper_days:
        return
    agents = _alive_agents(state)
    if len(agents) < 2:
        return
    ordered = sorted(agents, key=lambda player: player.id)
    index = state.day % len(ordered)
    first = ordered[index]
    second = ordered[(index + 1) % len(ordered)]
    first.pact_ids.add(second.id)
    second.pact_ids.add(first.id)
    first.trust_map[second.id] = _clip_trust(
        first.trust_map.get(second.id, CONFIDE_TRUST_START)
        + BLOOD_WHISPER_TRUST_DELTA
    )
    second.trust_map[first.id] = _clip_trust(
        second.trust_map.get(first.id, CONFIDE_TRUST_START)
        + BLOOD_WHISPER_TRUST_DELTA
    )
    _adjust_suspicion(first, second.id, BLOOD_WHISPER_SUSPICION_DELTA)
    _adjust_suspicion(second, first.id, BLOOD_WHISPER_SUSPICION_DELTA)
    _add_pact_note(first, second)
    _add_pact_note(second, first)
    line = BLOOD_WHISPER_PUBLIC_TEMPLATE.format(
        a=first.name,
        b=second.name,
    )
    state.whisper_days[state.day] = [first.id, second.id]
    _say(state, "system", "旁白", line)
    _log(
        state,
        {
            "type": "whisper",
            "day": state.day,
            "pair": [first.id, second.id],
            "trust": round(BLOOD_WHISPER_TRUST_DELTA, 2),
        },
    )


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


def _second_speaker(
    state: BloodState,
    first: BloodPlayer,
) -> BloodPlayer | None:
    """挑第二个顺势接话的人：优先爪牙护主，否则选最怀疑被点名者的人。"""
    candidates = [
        player
        for player in _alive_agents(state)
        if player.id != first.id
    ]
    if not candidates:
        return None
    demon = _player(state, state.murderer_id)
    if demon is not None and demon.alive and demon.id == first.id:
        minion = next(
            (player for player in candidates if player.role == "minion"),
            None,
        )
        if minion is not None:
            return minion
    candidates.sort(
        key=lambda player: (
            -player.suspicion.get(first.id, 0.0),
            player.id,
        )
    )
    return candidates[0]


def _talk_precheck(state: BloodState) -> str | None:
    if state.phase == "ended":
        return "game_ended"
    if not _you(state).alive:
        return "you_are_dead"
    if state.phase not in ("discussion", "defense"):
        return "wrong_phase"
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
    _maybe_whisper(state)
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
    if len(agents) == 1 and len(_alive_agents(state)) >= 2:
        first = agents[0]
        second = _second_speaker(state, first)
        if second is not None:
            is_shield = (
                first.id == state.murderer_id
                and second.role == "minion"
            )
            replies.append(
                _agent_speak(
                    state,
                    second,
                    reply_fn,
                    hint="shield" if is_shield else "followup",
                    target_id=first.id,
                    allow_fact=1,
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
        state.message = (
            "话头被两个人接住了。"
            if len(replies) > 1
            else "话头被抛了出去，有人接了一句。"
        )
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


def _succeed_demon(state: BloodState) -> bool:
    """恶魔已死且仍有存活爪牙时，由爪牙接任新恶魔并继续游戏。"""
    demon = _player(state, state.murderer_id)
    if demon is not None and demon.alive:
        return False
    heir = next(
        (
            player
            for player in state.players
            if player.alive and player.role == "minion"
        ),
        None,
    )
    if heir is None:
        return False
    heir.role = "murderer"
    from_id = demon.id if demon is not None else ""
    from_name = demon.name if demon is not None else "原恶魔"
    state.succession.append(
        {
            "day": state.day,
            "from_id": from_id,
            "from_name": from_name,
            "to_id": heir.id,
            "to_name": heir.name,
        }
    )
    state.murderer_id = heir.id
    _log(
        state,
        {
            "type": "succession",
            "day": state.day,
            "from": from_id,
            "to": heir.id,
        },
    )
    _say(state, "system", "旁白", BLOOD_SUCCESSOR_PUBLIC_TEXT)
    return True


def _settle_win(state: BloodState) -> Winner | None:
    """先处理恶魔传位，再按当前在场阵营判定胜负。"""
    _succeed_demon(state)
    return _judge(state)


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


def _escape_text() -> str:
    """第 8 天仍无胜负时的雪停旁白。"""
    return (
        f"第 {BLOOD_MAX_DAYS} 天，雪终于停了；仍没人能定下凶手，"
        "他趁乱摸黑出了旅馆。凶手脱身。"
    )


def _declare_escape(state: BloodState) -> None:
    """雪停收场：判定凶手脱身并进入终局。"""
    _log(state, {"type": "escape", "day": state.day})
    _declare_winner(state, "murderer", _escape_text())


def _ghost_vote_available(state: BloodState) -> bool:
    """死者是否还能投出唯一一枚亡者票。"""
    return (
        not _you(state).alive
        and not state.ghost_vote_used
        and state.phase in ("defense", "runoff")
    )


def _vote_threshold(alive_count: int, stalemate_count: int) -> int:
    """严格过半门槛；连续僵局达到上限后本轮 -1，最低为 2。"""
    base = alive_count // 2 + 1
    relief = (
        1 if stalemate_count >= BLOOD_STALEMATE_RELIEF_AFTER else 0
    )
    return max(BLOOD_STALEMATE_MIN_THRESHOLD, base - relief)


def _declare_winner(state: BloodState, winner: Winner, reason: str) -> None:
    state.winner = winner
    state.phase = "ended"
    state.message = reason
    _log(state, {"type": "win", "day": state.day, "winner": winner})
    _log(
        state,
        {
            "type": "end",
            "day": state.day,
            "reason": winner,
            "winner": winner,
        },
    )
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
    else:
        entry["note"] = f"{note}；这一夜没有人死。"
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
    else:
        note = note.rstrip("。") + "；这一夜没有人死。"
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
        target_id = _top_suspicion_target(
            state,
            voter,
            alive_ids,
            avoid_pacts=True,
        )
        if target_id is None:
            continue
        tally[target_id] += 1
    return tally


def _sim_vote(
    state: BloodState,
    alive_ids: set[str],
    stalemate_count: int = 0,
) -> BloodPlayer | None:
    """模拟一轮 agent 投票：各投最怀疑的存活者，严格过半才处决。"""
    tally = _sim_tally(state, alive_ids)
    threshold = _vote_threshold(len(alive_ids), stalemate_count)
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
        if player.alive
        and player.id in alive_ids
        and player.id != murderer.id
        and player.role not in EVIL_ROLES
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda player: murderer.suspicion.get(player.id, 0.0),
    )


def _simulate_aftermath(state: BloodState) -> Winner | None:
    """真人出局后，用纯规则推演剩余处决与夜杀，逐日补进卷宗。"""
    winner = _settle_win(state)
    day = state.day + 1
    stale = 0
    while winner is None and day <= BLOOD_MAX_DAYS:
        alive_ids = {player.id for player in state.players if player.alive}
        tally = _sim_tally(state, alive_ids)
        threshold = _vote_threshold(len(alive_ids), stale)
        executed_now = _sim_vote(state, alive_ids, stale)
        stalemate = executed_now is None
        if executed_now is not None:
            executed_now.alive = False
        winner = _settle_win(state)
        killed_now = None
        if winner is None:
            alive_ids = {
                player.id for player in state.players if player.alive
            }
            killed_now = _sim_kill(state, alive_ids)
            if killed_now is not None:
                killed_now.alive = False
                winner = _settle_win(state)
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
        _log(
            state,
            {
                "type": "aftermath_day",
                "day": day,
                "executed": (
                    executed_now.id if executed_now is not None else None
                ),
                "killed": killed_now.id if killed_now is not None else None,
                "tally": dict(tally),
                "threshold": threshold,
                "stalemate": stalemate,
                "winner": winner,
            },
        )
        if stalemate:
            stale += 1
        else:
            stale = 0
        day += 1
    if winner is None:
        winner = "murderer"
        _log(state, {"type": "escape", "day": day - 1})
    return winner


def _end_with_you_out(
    state: BloodState,
    reason: str,
    executed: BloodPlayer | None = None,
    killed: BloodPlayer | None = None,
) -> None:
    """真人出局后进入终局，并用纯规则补全卷宗摘要与最终胜负。"""
    winner = _simulate_aftermath(state)
    if winner is None:
        winner = "murderer"
    state.winner = winner
    if winner == "good":
        suffix = "余下的人把凶手揪了出来。"
    else:
        suffix = "剩下的日子里，凶手笑到了最后，雪停前没人能定他的罪。"
    reason = f"{reason}{suffix}"
    state.phase = "ended"
    state.message = reason
    _log(state, {"type": "win", "day": state.day, "winner": winner})
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
        if player.alive
        and player.id != murderer.id
        and player.role not in EVIL_ROLES
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


def _denies_time_evidence(
    state: BloodState,
    reason: str,
    target: BloodPlayer,
) -> bool:
    """target 当天明明给过时辰，理由却说他没给，判为时间线矛盾。"""
    if not any(term in reason for term in ("没一句", "没提过", "没说过", "从没")):
        return False
    if "时辰" not in reason and "时间" not in reason:
        return False
    day_text = "".join(
        entry.text
        for entry in state.public_log
        if entry.speaker_id == target.id and entry.day == state.day
    )
    return bool(TIME_MENTION_PATTERN.search(day_text))


def _mentions_unsupported_evidence(
    state: BloodState,
    reason: str,
    target: BloodPlayer,
) -> bool:
    """理由里的时辰、地点、动作必须来自 target 当天原话，不能自己编。"""
    day_text = "".join(
        entry.text
        for entry in state.public_log
        if entry.speaker_id == target.id and entry.day == state.day
    )
    for token in TIME_MENTION_PATTERN.findall(reason):
        if token not in day_text:
            return True
    for term in PLACE_EVIDENCE_TERMS:
        if term in reason and term not in day_text:
            return True
    for term in ACTION_EVIDENCE_TERMS:
        if term in reason and term not in day_text:
            return True
    return False


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
    if _mentions_unsupported_evidence(state, reason, target):
        return False
    if _denies_time_evidence(state, reason, target):
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
            return _gendered(candidate, target)
    no_quote_index = (voter_index * 3 + target_index) % len(
        VOTE_REASON_NO_QUOTE_FALLBACKS
    )
    candidate = _clip_sentence(
        VOTE_REASON_NO_QUOTE_FALLBACKS[no_quote_index].format(
            name=target.name
        ),
        BLOOD_VOTE_REASON_MAX_CHARS,
    )
    return _gendered(candidate, target)


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
    reason = _scrub_self_reference(voter, reason)
    reason = _scrub_misattributed_claim(state, voter, reason)
    if not reason:
        return _fallback_reason(state, voter, target)
    if not _valid_reason(state, reason, target):
        return _fallback_reason(state, voter, target)
    return _gendered(reason, target)


def _follow_target(
    state: BloodState,
    agent: BloodPlayer,
    follow_id: str | None,
    allowed_ids: set[str] | None = None,
) -> BloodPlayer | None:
    """按 follow_prob 决定是否跟随真人/盟约目标，绝不投自己。"""
    if not follow_id or agent.follow_prob <= 0.0:
        return None
    candidate = _player(state, follow_id)
    if candidate is None or not candidate.alive or candidate.id == agent.id:
        return None
    if allowed_ids is not None and candidate.id not in allowed_ids:
        return None
    if state.rng.random() >= agent.follow_prob:
        return None
    return candidate


def _agent_vote_target(
    state: BloodState,
    agent: BloodPlayer,
    follow_id: str | None = None,
    allowed_ids: set[str] | None = None,
) -> BloodPlayer | None:
    """选出投票目标；爪牙不会主动投给仍存活的恶魔。"""
    allowed = set(allowed_ids) if allowed_ids is not None else None
    if agent.role == "minion":
        demon = _player(state, state.murderer_id)
        if demon is not None and demon.alive and demon.id != agent.id:
            if allowed is None:
                allowed = {player.id for player in state.players if player.alive}
            allowed.discard(demon.id)
    target = _follow_target(state, agent, follow_id, allowed)
    if target is None:
        target = _player(
            state,
            _top_suspicion_target(state, agent, allowed, avoid_pacts=True),
        )
    return target


def _agent_vote_reason(
    state: BloodState,
    agent: BloodPlayer,
    target: BloodPlayer,
    reply_fn: ReplyFn,
) -> VoteResult:
    """为已选定的目标生成一条投票理由，使用独立状态副本供并发调用。"""
    local = copy(state)
    local.pending_hint = "vote_reason"
    local.pending_target_id = target.id
    reason = ""
    try:
        raw = reply_fn(local, agent)
        reason = _clip_sentence(raw, BLOOD_VOTE_REASON_MAX_CHARS)
    except Exception:
        logger.warning("投票理由生成失败：%s", agent.id, exc_info=True)
    reason = _aligned_reason(state, agent, target, reason)
    return VoteResult(agent.id, agent.name, target.id, target.name, reason)


def _agent_vote(
    state: BloodState,
    agent: BloodPlayer,
    reply_fn: ReplyFn,
    follow_id: str | None = None,
    allowed_ids: set[str] | None = None,
) -> VoteResult | None:
    """agent 投给最怀疑的人；密谈结盟时按 follow_prob 跟随一次。"""
    target = _agent_vote_target(state, agent, follow_id, allowed_ids)
    if target is None:
        return None
    result = _agent_vote_reason(state, agent, target, reply_fn)
    state.vote_reason_log.append(
        {
            "day": state.day,
            "voter_id": agent.id,
            "target_id": target.id,
            "reason": result.reason,
        }
    )
    return result


def _resolve_votes(
    state: BloodState,
    votes: list[VoteResult],
) -> tuple[dict[str, int], int, BloodPlayer | None, list[str]]:
    """按严格过半处决：票数达到 alive//2+1 且唯一最高。"""
    alive_count = sum(1 for player in state.players if player.alive)
    threshold = _vote_threshold(alive_count, state.stalemate_count)
    tally = Counter(vote.target_id for vote in votes)
    if not tally:
        return {}, threshold, None, []
    top = max(tally.values())
    leaders = [target_id for target_id, count in tally.items() if count == top]
    if len(leaders) != 1 or top < threshold:
        return dict(tally), threshold, None, leaders
    return dict(tally), threshold, _player(state, leaders[0]), leaders


def _no_execution_message(
    tally: dict[str, int],
    threshold: int,
    relaxed: bool = False,
    runoff: bool = False,
) -> str:
    """区分平票流局与未达门槛；不再拼接额外的入夜说明。"""
    if not tally:
        text = "无人投票，今晚无人被处决。"
    else:
        top = max(tally.values())
        leaders = [count for count in tally.values() if count == top]
        if len(leaders) > 1:
            text = BLOOD_STILL_TIE_MESSAGE if runoff else "平票，今晚无人被处决。"
        else:
            text = f"最高 {top} 票，未达 {threshold} 票门槛。"
    if relaxed:
        text = f"{text}僵局持续，门槛已降到 {threshold} 票。"
    return text


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
    state.defense_origin = "you"
    state.defense_speak_count = 0
    _say(
        state,
        "system",
        "旁白",
        _gendered(f"{_you(state).name} 提名了 {target.name}。先听他自辩。", target),
    )
    defense = _agent_speak(
        state,
        target,
        reply_fn,
        hint="defense",
        allow_fact=BLOOD_MAX_FACTS_PER_DAY,
    )
    state.message = (
        f"{_you(state).name} 提名了 {target.name}，先自辩，随后投票。"
    )
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


def _runoff_refs(
    state: BloodState,
    candidate_ids: list[str],
) -> tuple[RunoffCandidate, ...]:
    """把候选 id 映射成公开的 id/name。"""
    refs: list[RunoffCandidate] = []
    for candidate_id in candidate_ids:
        player = _player(state, candidate_id)
        if player is not None:
            refs.append(RunoffCandidate(id=player.id, name=player.name))
    return tuple(refs)


def vote(
    store: BloodStore,
    game_id: str,
    target_id: str,
    reply_fn: ReplyFn,
    reason: str = "",
    ghost: bool = False,
) -> VoteOutcome:
    """全体投票；并列进入重投；亡者每局可投一次，处决后入夜。"""
    state = store.get(game_id)
    if state is None:
        return VoteOutcome(ok=False, error="game_not_found")
    if state.phase == "ended":
        return VoteOutcome(ok=False, error="game_ended", phase=state.phase)
    if state.phase not in ("defense", "runoff"):
        return VoteOutcome(ok=False, error="wrong_phase", phase=state.phase)
    you = _you(state)
    if you.alive and ghost:
        return VoteOutcome(
            ok=False, error="ghost_not_available", phase=state.phase
        )
    if not you.alive:
        if not ghost:
            return VoteOutcome(
                ok=False, error="you_are_dead", phase=state.phase
            )
        if state.ghost_vote_used:
            return VoteOutcome(
                ok=False, error="ghost_vote_used", phase=state.phase
            )
    target = _player(state, target_id)
    if target is None:
        return VoteOutcome(
            ok=False, error="target_not_found", phase=state.phase
        )
    if not target.alive:
        return VoteOutcome(ok=False, error="target_dead", phase=state.phase)
    if target.is_you:
        return VoteOutcome(ok=False, error="target_invalid", phase=state.phase)
    was_runoff = state.phase == "runoff"
    allowed = set(state.runoff_candidates) if was_runoff else None
    if allowed is not None and target.id not in allowed:
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
    if not you.alive:
        state.ghost_vote_used = True
        _log(
            state,
            {
                "type": "ghost_vote",
                "day": state.day,
                "target": target.id,
            },
        )
    alive_before = sum(1 for player in state.players if player.alive)
    base_threshold = alive_before // 2 + 1
    plans: list[tuple[BloodPlayer, BloodPlayer]] = []
    for agent in _alive_agents(state):
        follow_id = state.confide_intents.get(agent.id, target.id)
        planned = _agent_vote_target(state, agent, follow_id, allowed)
        if planned is not None:
            plans.append((agent, planned))
    if len(plans) > 1:
        with ThreadPoolExecutor(max_workers=min(5, len(plans))) as pool:
            futures = [
                pool.submit(_agent_vote_reason, state, agent, planned, reply_fn)
                for agent, planned in plans
            ]
            results = [future.result() for future in futures]
    else:
        results = [
            _agent_vote_reason(state, agent, planned, reply_fn)
            for agent, planned in plans
        ]
    for (agent, target), result in zip(plans, results):
        state.vote_reason_log.append(
            {
                "day": state.day,
                "voter_id": agent.id,
                "target_id": target.id,
                "reason": result.reason,
            }
        )
        votes.append(result)
    tally, threshold, executed, leaders = _resolve_votes(state, votes)
    relaxed = threshold < base_threshold
    if executed is None and len(leaders) > 1 and not was_runoff:
        state.runoff = True
        state.runoff_candidates = list(leaders)
        state.phase = "runoff"
        state.message = BLOOD_RUNOFF_MESSAGE
        _say(state, "system", "旁白", state.message)
        _log(
            state,
            {
                "type": "runoff",
                "day": state.day,
                "candidates": list(leaders),
                "tally": dict(tally),
            },
        )
        return VoteOutcome(
            ok=True,
            error=None,
            votes=tuple(votes),
            tally=dict(tally),
            threshold=threshold,
            executed=None,
            winner=state.winner,
            reveal=_reveal_of(state),
            message=state.message,
            phase=state.phase,
            aftermath=tuple(state.aftermath),
            day_history=tuple(state.day_history),
            runoff_candidates=_runoff_refs(state, list(leaders)),
            stalemate_count=state.stalemate_count,
        )
    stalemate = executed is None
    if executed is not None:
        executed.alive = False
        base_message = BLOOD_EXECUTE_MESSAGE.format(name=executed.name)
    else:
        base_message = _no_execution_message(
            tally,
            threshold,
            False,
            was_runoff,
        )
    if relaxed:
        note = f"僵局持续，门槛降低到 {threshold} 票。"
        _say(state, "system", "旁白", note)
        _log(state, {"type": "threshold_relaxed", "day": state.day,
                     "threshold": threshold})
    _record_vote_day(state, executed, tally, threshold, votes, stalemate)
    _log(state, _vote_log_entry(state, votes))
    if stalemate:
        state.stalemate_count += 1
    else:
        state.stalemate_count = 0
    state.runoff = False
    state.runoff_candidates = []
    winner = _settle_win(state)
    if winner is not None:
        _say(state, "system", "旁白", base_message)
        _declare_winner(state, winner, _win_text(winner))
    elif state.day >= BLOOD_MAX_DAYS:
        _say(state, "system", "旁白", base_message)
        _declare_escape(state)
    elif executed is not None and executed.is_you:
        state.phase = "spectating"
        state.pending_night = True
        state.message = f"{base_message}你只剩最后一枚亡者票。"
        _say(state, "system", "旁白", state.message)
    else:
        state.phase = "night"
        state.message = base_message
        _say(state, "system", "旁白", base_message)
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
        stalemate_count=state.stalemate_count,
    )


def night(
    store: BloodStore,
    game_id: str,
    target_id: str | None = None,
) -> NightOutcome:
    """夜晚结算：凶手必杀一人，天亮后进入下一天或终局。"""
    state = store.get(game_id)
    if state is None:
        return NightOutcome(ok=False, error="game_not_found", day=1)
    if state.phase == "ended":
        return NightOutcome(
            ok=False, error="game_ended", day=state.day, phase=state.phase
        )
    you = _you(state)
    if not you.alive:
        return NightOutcome(
            ok=False, error="you_are_dead", day=state.day, phase=state.phase
        )
    if state.phase != "night":
        return NightOutcome(
            ok=False, error="wrong_phase", day=state.day, phase=state.phase
        )
    murderer = _player(state, state.murderer_id)
    if murderer is None or not murderer.alive:
        _settle_win(state)
        murderer = _player(state, state.murderer_id)
        _record_night(state, None)
        _log(state, {"type": "night", "day": state.day, "killed": None})
        _declare_winner(
            state,
            "good",
            "凶手已经不在场上，天亮后剩下的都是好人。好人胜。",
        )
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
            you_alive=you.alive,
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
        if victim.is_you or victim.role in EVIL_ROLES:
            return NightOutcome(
                ok=False, error="target_invalid", day=state.day,
                phase=state.phase,
            )
    else:
        victim = _system_kill_target(state)
        if victim is None:
            _record_night(state, None)
            _log(state, {"type": "night", "day": state.day, "killed": None})
            _declare_winner(
                state,
                "good",
                "夜里没有可下手的人，凶手再也撑不住。好人胜。",
            )
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
                you_alive=you.alive,
            )
    if victim is not None:
        victim.alive = False
    night_message = (
        BLOOD_NIGHT_MESSAGE.format(name=victim.name)
        if victim is not None
        else ""
    )
    _record_night(state, victim)
    _log(
        state,
        {
            "type": "night",
            "day": state.day,
            "killed": victim.id if victim is not None else None,
        },
    )
    winner = _settle_win(state)
    if victim is not None and victim.is_you:
        if winner is not None:
            _say(state, "system", "旁白", night_message)
            _declare_winner(state, winner, _win_text(winner))
        else:
            _reset_day(state)
            state.phase = "spectating"
            state.pending_night = False
            state.message = f"{night_message}你只剩最后一枚亡者票。"
            _say(state, "system", "旁白", state.message)
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
            you_alive=you.alive,
        )
    if winner is not None:
        _say(state, "system", "旁白", night_message)
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
            you_alive=you.alive,
        )
    if state.day >= BLOOD_MAX_DAYS:
        _say(state, "system", "旁白", night_message)
        _declare_escape(state)
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
            you_alive=you.alive,
        )
    _reset_day(state)
    state.message = night_message
    _say(state, "system", "旁白", state.message)
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
        you_alive=you.alive,
    )


def inspect(
    store: BloodStore,
    game_id: str,
    target_id: str,
    reveal: bool = False,
) -> InspectOutcome:
    """真人查验一名在场者是否凶手；默认只回本人，reveal 才公开。"""
    state = store.get(game_id)
    if state is None:
        return InspectOutcome(ok=False, error="game_not_found")
    if state.phase == "ended":
        return InspectOutcome(ok=False, error="game_ended")
    you = _you(state)
    if not you.alive:
        return InspectOutcome(ok=False, error="you_are_dead")
    if state.phase not in ("discussion", "defense"):
        return InspectOutcome(ok=False, error="wrong_phase")
    if you.role == "murderer" or state.murderer_id == YOU_ID:
        return InspectOutcome(ok=False, error="inspect_unavailable")
    if state.inspect_used:
        return InspectOutcome(ok=False, error="inspect_used")
    target = _player(state, target_id)
    if target is None:
        return InspectOutcome(ok=False, error="target_not_found")
    if target.is_you:
        return InspectOutcome(ok=False, error="target_invalid")
    if not target.alive:
        return InspectOutcome(ok=False, error="target_dead")
    state.inspect_used = True
    is_murderer = target.role == "murderer" or target.id == state.murderer_id
    delta = (
        BLOOD_INSPECT_SUSPICION_MURDERER
        if is_murderer
        else BLOOD_INSPECT_SUSPICION_INNOCENT
    )

    result = "murderer" if is_murderer else "not_murderer"
    public_line = ""
    if reveal:
        public_line = BLOOD_INSPECT_PUBLIC_TEMPLATE.format(name=target.name)
        for agent in _alive_agents(state):
            if agent.id != target.id:
                _adjust_suspicion(agent, target.id, delta)
        _say(state, you.id, you.name, public_line)
        state.message = public_line
    else:
        state.message = f"你查过{target.name}，结果只有你自己知道。"
    _log(
        state,
        {
            "type": "inspect",
            "day": state.day,
            "target": target.id,
            "result": result,
            "revealed": reveal,
        },
    )
    remaining = max(0, BLOOD_INSPECT_USE_PER_GAME - 1)
    return InspectOutcome(
        ok=True,
        error=None,
        target=target,
        result=result,
        public_line=public_line,
        remaining=remaining,
        revealed=reveal,
    )


def _adjust_suspicion(
    player: BloodPlayer,
    target_id: str,
    delta: float,
) -> None:
    current = player.suspicion.get(target_id, 0.0)
    player.suspicion[target_id] = _clip(current + delta)


def _clip_trust(value: float) -> float:
    return min(100.0, max(0.0, value))


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
    flat = _filter_unknown_places(flat)
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
    betrayed = stance == "accept" and not kept
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
            state.pending_leaks[target.id] = clean_text
    elif stance == "refuse":
        target.trust = _clip_trust(target.trust + CONFIDE_TRUST_REFUSE)
        _adjust_suspicion(target, you.id, CONFIDE_SUSPICION_REFUSE)
    elif stance == "threaten":
        target.trust = _clip_trust(target.trust + CONFIDE_TRUST_THREATEN)
        _adjust_suspicion(target, you.id, CONFIDE_SUSPICION_THREATEN)
    else:
        _adjust_suspicion(target, you.id, CONFIDE_SUSPICION_EVADE)

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
    if betrayed:
        reply = CONFIDE_BETRAY_REPLY
    _record_denials(state, target, clean_text, reply)
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
        betrayed=betrayed,
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
    state.runoff = False
    state.runoff_candidates = []
    _log(state, {"type": "phase", "day": state.day, "phase": "discussion"})


def _auto_nominee(state: BloodState) -> BloodPlayer | None:
    """观战推演时，取全场怀疑度总和最高的存活者作为提名对象。"""
    candidates = [player for player in state.players if player.alive]
    if len(candidates) < 2:
        return None

    def score(player: BloodPlayer) -> float:
        return sum(
            other.suspicion.get(player.id, 0.0)
            for other in state.players
            if other.alive and not other.is_you and other.id != player.id
        )

    return max(candidates, key=score)


def _auto_open_day(state: BloodState) -> None:
    """观战推演：agent 完成讨论与提名，停在投票阶段等亡者票。"""
    state.phase = "discussion"
    if not state.discussed:
        _maybe_whisper(state)
        speakers: list[str] = []
        for player in _alive_agents(state):
            text = _vague_agent_line(player)
            _say(state, player.id, player.name, text)
            _apply_public_text(state, player.id, text)
            speakers.append(player.id)
        state.discussed = True
        _log(state, {"type": "discuss", "day": state.day, "speakers": speakers})
    target = _auto_nominee(state)
    if target is None:
        state.phase = "night"
        return
    state.nominated = True
    state.phase = "defense"
    state.nominee_id = target.id
    state.defense_origin = "ai"
    state.defense_speak_count = 0
    accuser = max(
        (
            player
            for player in state.players
            if player.alive and not player.is_you and player.id != target.id
        ),
        key=lambda player: player.suspicion.get(target.id, 0.0),
        default=None,
    )
    if accuser is not None:
        line = f"{accuser.name} 把 {target.name} 推上桌。先听他自辩。"
    else:
        line = f"桌上把 {target.name} 推上桌。先听他自辩。"
    _say(state, "system", "旁白", _gendered(line, target))
    if not target.is_you:
        _say(
            state,
            target.id,
            target.name,
            DEFENSE_FALLBACKS_AI.get(target.id, DEFENSE_FALLBACK_DEFAULT_AI),
        )
    state.message = f"{target.name} 被推上桌，先自辩，随后投票。"
    _log(
        state,
        {"type": "nominate", "day": state.day, "target": target.id},
    )


def _auto_you_target(
    state: BloodState,
    allowed: set[str] | None,
) -> BloodPlayer | None:
    """观战推演时代表的票：优先跟提名，其次取第一名合法候选。"""
    nominee = _player(state, state.nominee_id)
    if (
        nominee is not None
        and nominee.alive
        and not nominee.is_you
        and (allowed is None or nominee.id in allowed)
    ):
        return nominee
    for player in state.players:
        if not player.alive or player.is_you:
            continue
        if allowed is not None and player.id not in allowed:
            continue
        return player
    return None


def _auto_votes(
    state: BloodState,
    allowed: set[str] | None,
) -> list[VoteResult]:
    """观战推演的一轮票：含死者最后一票与各 agent 的最怀疑票。"""
    votes: list[VoteResult] = []
    you = _you(state)
    if _ghost_vote_available(state):
        target = _auto_you_target(state, allowed)
        if target is not None:
            votes.append(
                VoteResult(
                    you.id,
                    you.name,
                    target.id,
                    target.name,
                    "这是死者留下的最后一票。",
                )
            )
            state.ghost_vote_used = True
            _log(
                state,
                {"type": "ghost_vote", "day": state.day, "target": target.id},
            )
    for agent in _alive_agents(state):
        target = _player(state, _top_suspicion_target(state, agent, allowed))
        if target is None:
            continue
        votes.append(
            VoteResult(
                agent.id,
                agent.name,
                target.id,
                target.name,
                _fallback_reason(state, agent, target),
            )
        )
    return votes


def _auto_settle_vote(
    state: BloodState,
) -> tuple[list[VoteResult], BloodPlayer | None]:
    """观战推演的一轮投票结算：严过半、连续僵局降门槛、并列重投。"""
    was_runoff = state.phase == "runoff"
    allowed = set(state.runoff_candidates) if was_runoff else None
    votes = _auto_votes(state, allowed)
    alive_before = sum(1 for player in state.players if player.alive)
    base_threshold = alive_before // 2 + 1
    tally, threshold, executed, leaders = _resolve_votes(state, votes)
    relaxed = threshold < base_threshold
    _log(state, _vote_log_entry(state, votes))
    if executed is None and len(leaders) > 1 and not was_runoff:
        state.runoff = True
        state.runoff_candidates = list(leaders)
        state.phase = "runoff"
        names = "、".join(_name_of(state, cid) for cid in leaders)
        state.message = f"票数并列：{names}。最高票之间再投一轮。"
        _say(state, "system", "旁白", state.message)
        _log(
            state,
            {
                "type": "runoff",
                "day": state.day,
                "candidates": list(leaders),
                "tally": dict(tally),
            },
        )
        return votes, None
    stalemate = executed is None
    if executed is not None:
        executed.alive = False
        _say(state, "system", "旁白", f"{executed.name} 被投票处决。")
        state.message = f"{executed.name} 被处决，天黑了。"
    else:
        state.message = _no_execution_message(tally, threshold, relaxed)
    if relaxed:
        _say(state, "system", "旁白", f"僵局持续，门槛降低到 {threshold} 票。")
        _log(
            state,
            {"type": "threshold_relaxed", "day": state.day,
             "threshold": threshold},
        )
    _record_vote_day(state, executed, tally, threshold, votes, stalemate)
    if stalemate:
        state.stalemate_count += 1
    else:
        state.stalemate_count = 0
    state.runoff = False
    state.runoff_candidates = []
    winner = _settle_win(state)
    if winner is not None:
        _declare_winner(state, winner, _win_text(winner))
    elif state.day >= BLOOD_MAX_DAYS:
        _declare_escape(state)
    elif executed is not None and executed.is_you:
        state.phase = "spectating"
        state.pending_night = True
        state.message = f"{executed.name} 被处决了。你只剩最后一枚亡者票。"
        _say(state, "system", "旁白", state.message)
    else:
        state.phase = "night"
    return votes, executed


def _advance_night(state: BloodState) -> BloodPlayer | None:
    """观战推演的一夜：凶手必杀，随后结算终局或进入下一天。"""
    state.phase = "night"
    murderer = _player(state, state.murderer_id)
    if murderer is None or not murderer.alive:
        _settle_win(state)
        murderer = _player(state, state.murderer_id)
        _record_night(state, None)
        _log(state, {"type": "night", "day": state.day, "killed": None})
        _declare_winner(
            state,
            "good",
            "凶手已经不在场上，天亮后剩下的都是好人。好人胜。",
        )
        return None
    victim = _system_kill_target(state)
    if victim is None:
        _record_night(state, None)
        _log(state, {"type": "night", "day": state.day, "killed": None})
        _declare_winner(
            state,
            "good",
            "夜里没有可下手的人，凶手再也撑不住。好人胜。",
        )
        return None
    victim.alive = False
    _say(
        state,
        "system",
        "旁白",
        BLOOD_NIGHT_MESSAGE.format(name=victim.name),
    )
    _record_night(state, victim)
    _log(
        state,
        {
            "type": "night",
            "day": state.day,
            "killed": victim.id,
        },
    )
    winner = _settle_win(state)
    if winner is not None:
        _declare_winner(state, winner, _win_text(winner))
    elif state.day >= BLOOD_MAX_DAYS:
        _declare_escape(state)
    else:
        _reset_day(state)
    return victim


def advance(store: BloodStore, game_id: str) -> AdvanceOutcome:
    """观战推进：agent 代跑讨论、提名、投票与夜晚，停在投票点或终局。"""
    state = store.get(game_id)
    if state is None:
        return AdvanceOutcome(ok=False, error="game_not_found")
    if state.phase == "ended":
        return AdvanceOutcome(
            ok=False, error="game_ended", phase=state.phase, day=state.day
        )
    votes: list[VoteResult] = []
    executed: BloodPlayer | None = None
    killed: BloodPlayer | None = None
    start_seq = len(state.public_log)
    if state.phase in ("defense", "runoff"):
        votes, executed = _auto_settle_vote(state)
    guard = 0
    while state.phase not in ("ended", "defense", "runoff") and guard < 20:
        guard += 1
        if state.phase == "spectating" and state.pending_night:
            killed = _advance_night(state) or killed
            state.pending_night = False
        elif state.phase in ("discussion", "spectating"):
            _auto_open_day(state)
        elif state.phase == "night":
            killed = _advance_night(state) or killed
        else:
            break
    return AdvanceOutcome(
        ok=True,
        error=None,
        phase=state.phase,
        day=state.day,
        public_log=tuple(state.public_log),
        votes=tuple(votes),
        executed=executed,
        killed=killed,
        winner=state.winner,
        reveal=_reveal_of(state),
        ghost_vote_available=_ghost_vote_available(state),
        new_entries=tuple(state.public_log[start_seq:]),
    )


def _last_night_killed(state: BloodState) -> BloodPlayer | None:
    """终局揭晓时取卷宗里最近一次夜杀，绝不与被下药者混用。"""
    for entry in reversed(state.day_history):
        killed = entry.get("killed")
        if isinstance(killed, dict) and killed.get("id"):
            return _player(state, str(killed["id"]))
    return None


def _reveal_of(state: BloodState) -> RevealView | None:
    """终局时返回最初的恶魔、爪牙、传位链、被下药者与夜杀。"""
    if state.phase != "ended":
        return None
    original = _player(
        state,
        state.original_murderer_id or state.murderer_id,
    )
    current = _player(state, state.murderer_id)
    if original is None:
        return None
    minion = _player(state, state.minion_id)
    poisoned = _player(state, state.poisoned_id)
    killed = _last_night_killed(state)
    poisoned_note = ""
    if poisoned is not None:
        if state.poisoned_clue_kind:
            poisoned_note = BLOOD_POISON_NOTE_DYNAMIC.format(
                kind=state.poisoned_clue_kind
            )
        else:
            poisoned_note = BLOOD_POISON_NOTE
    return RevealView(
        murderer_id=original.id,
        murderer_name=original.name,
        final_murderer_id=current.id if current is not None else original.id,
        final_murderer_name=(
            current.name if current is not None else original.name
        ),
        minion_id=minion.id if minion is not None else "",
        minion_name=minion.name if minion is not None else "",
        poisoned_id=poisoned.id if poisoned is not None else "",
        poisoned_name=poisoned.name if poisoned is not None else "",
        poisoned_note=poisoned_note,
        killed_id=killed.id if killed is not None else "",
        killed_name=killed.name if killed is not None else "",
        succession=tuple(dict(item) for item in state.succession),
    )


def _teammates_of(state: BloodState, you: BloodPlayer) -> tuple[str, ...]:
    """只有邪恶能看到同伴姓名，好人一律为空。"""
    if you.role not in EVIL_ROLES:
        return ()
    return tuple(
        player.name
        for player in state.players
        if player.id != you.id and player.role in EVIL_ROLES
    )


def _view_winner(state: BloodState) -> Winner | None:
    """终局必须给出阵营：兜底视为凶手脱身。"""
    if state.winner is not None:
        return state.winner
    if state.phase == "ended":
        return "murderer"
    return None


def _your_result(state: BloodState) -> tuple[str | None, bool | None]:
    """终局时按真人阵营与最终胜负，给出 win/lose/draw 与布尔标记。"""
    if state.phase != "ended":
        return None, None
    winner = _view_winner(state)
    you = _you(state)
    if winner is None:
        return "draw", None
    good_side = you.role == "villager"
    if good_side:
        won = winner == "good"
    else:
        won = winner == "murderer"
    return ("win" if won else "lose"), won


def build_view(state: BloodState) -> BloodView:
    """生成公开视图，终局时附上凶手揭晓、个人胜负与卷宗摘要。"""
    you = _you(state)
    your_result, you_win = _your_result(state)
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
            teammates=_teammates_of(state, you),
        ),
        public_log=tuple(state.public_log),
        dead=tuple(
            DeadView(id=player.id, name=player.name)
            for player in state.players
            if not player.alive
        ),
        message=state.message,
        winner=_view_winner(state),
        reveal=_reveal_of(state),
        aftermath=tuple(state.aftermath),
        day_history=tuple(state.day_history),
        you_alive=you.alive,
        runoff_candidates=_runoff_refs(state, state.runoff_candidates),
        stalemate_count=state.stalemate_count,
        ghost_vote_available=_ghost_vote_available(state),
        your_result=your_result,
        you_win=you_win,
    )


def build_log(state: BloodState) -> list[dict[str, object]]:
    """返回不含秘密字段的回看日志。"""
    return [dict(entry) for entry in state.log]