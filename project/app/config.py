"""全局配置与可调阈值。"""

from __future__ import annotations

from typing import Final

LLM_TIMEOUT_SECONDS: Final[float] = 30.0
LLM_MAX_TOKENS: Final[int] = 200
LLM_TEMPERATURE: Final[float] = 0.7

# 阵营模式（电子血染）
BLOOD_INITIAL_SUSPICION_BASE: Final[float] = 0.2
BLOOD_INITIAL_SUSPICION_JITTER: Final[float] = 0.2
BLOOD_SUSPICION_FACT: Final[float] = 0.2
BLOOD_SUSPICION_MURDERER: Final[float] = 0.1
BLOOD_SUSPICION_MENTION: Final[float] = 0.05
BLOOD_MAX_SUSPICION: Final[float] = 1.0
BLOOD_MAX_SPEAK_PER_DAY: Final[int] = 3
BLOOD_PRIVATE_FACTS_MIN: Final[int] = 2
BLOOD_PRIVATE_FACTS_MAX: Final[int] = 3
BLOOD_PRIVATE_MAX_SENSITIVITY: Final[float] = 0.7
BLOOD_MAX_LINE_CHARS: Final[int] = 120
BLOOD_PROMPT_CONTEXT_LINES: Final[int] = 6
BLOOD_MAX_DEFENSE_SPEAK_PER_DAY: Final[int] = 2
BLOOD_MAX_FACTS_PER_DAY: Final[int] = 2
BLOOD_VOTE_REASON_MAX_CHARS: Final[int] = 80

BLOOD_VOTE_REASON_MIN_QUOTE_CHARS: Final[int] = 4

# 夜间必杀与雪停上限：第 8 天仍无胜负则凶手趁乱脱身
BLOOD_MAX_DAYS: Final[int] = 8
BLOOD_AFTERMATH_MAX_DAYS: Final[int] = BLOOD_MAX_DAYS
# 连续僵局的轮次数：达到后下一轮门槛 -1（最低 2）
BLOOD_STALEMATE_RELIEF_AFTER: Final[int] = 2
BLOOD_STALEMATE_MIN_THRESHOLD: Final[int] = 2

# 真人查验（每局 1 次，只答是/否凶手）
BLOOD_INSPECT_USE_PER_GAME: Final[int] = 1
BLOOD_INSPECT_SUSPICION_MURDERER: Final[float] = 0.25
BLOOD_INSPECT_SUSPICION_INNOCENT: Final[float] = -0.2
BLOOD_INSPECT_PUBLIC_TEMPLATE: Final[str] = "我查过{name}。"

# 密谈 / 结盟 v1
LIMIT_PER_DAY: Final[int] = 1
LIMIT_PER_GAME: Final[int] = 3
FOLLOW_MAX: Final[float] = 0.5
FOLLOW_ACCEPT_DELTA: Final[float] = 0.25
LEAK_RATE_NORMAL: Final[float] = 0.15
LEAK_RATE_MURDERER: Final[float] = 0.35
LEAK_QUOTE_MAX_CHARS: Final[int] = 20
CONFIDE_TEXT_MAX_CHARS: Final[int] = 200
CONFIDE_REPLY_MAX_CHARS: Final[int] = 80
CONFIDE_TRUST_START: Final[float] = 50.0
CONFIDE_TRUST_ACCEPT: Final[float] = 15.0
CONFIDE_TRUST_REFUSE: Final[float] = -5.0
CONFIDE_TRUST_THREATEN: Final[float] = -10.0
CONFIDE_SUSPICION_ACCEPT: Final[float] = -0.1
CONFIDE_SUSPICION_REFUSE: Final[float] = 0.08
CONFIDE_SUSPICION_EVADE: Final[float] = 0.03
CONFIDE_SUSPICION_THREATEN: Final[float] = 0.12
BETRAY_TRUST_DELTA: Final[float] = -15.0
BETRAY_SUSPICION_DELTA: Final[float] = 0.1
BLOOD_LAST_WORDS_MAX_CHARS: Final[int] = 200
BLOOD_SECRET_CLAIM_TERMS: Final[tuple[str, ...]] = (
    "我是凶手",
    "我是好人",
    "我是清白的",
    "我是私生女",
    "我是记者",
    "我是真凶",
    "私生女",
    "记者",
)
BLOOD_SECRET_IDENTITY_TERMS: Final[tuple[str, ...]] = ("私生女", "记者")
BLOOD_VAGUE_REWRITE: Final[str] = (
    "这些旧事我只看见一角，说不全；你还是问那晚谁上过楼吧。"
)# 会暴露“逐字念档案”的句式，公开发言里在它之前截断
BLOOD_MEMORY_MARKERS: Final[tuple[str, ...]] = ("我还记得", "档案里写着")
# 未登记人名过滤的通用词白名单，避免误伤“老板娘”“小声”等正常词
BLOOD_KNOWN_PERSON_TERMS: Final[tuple[str, ...]] = (
    "老板",
    "老板娘",
    "老家",
    "老人",
    "老账",
    "老规矩",
    "老天",
    "老实",
    "老早",
    "老远",
    "老半天",
    "老屋",
    "老墙",
    "老树",
    "小声",
    "小心",
    "小子",
    "小时",
    "小半",
    "小厮",
    "小伙",
    "小两口",
)
BLOOD_HEARSAY_PREFIX: Final[str] = "听旅客说，"
BLOOD_VOTE_REASON_QUOTE_CHARS: Final[int] = 12
# 第八轮：爪牙传位
BLOOD_MINION_COUNT: Final[int] = 1
BLOOD_SUCCESSOR_PUBLIC_TEXT: Final[str] = (
    "死了一个人，可这一局还没有完，有人接过了这摊事。"
)

# 第八轮：毒/醉假线索（每局随机 1 名镇民被下药）
BLOOD_POISON_TIME_SHIFT_MINUTES: Final[int] = 40
BLOOD_POISON_FALLBACK_TEXT: Final[str] = (
    "你只记得那晚的动静比后来众人说的早了小半个时辰。"
)

# 第八轮：agent 间低声串供
BLOOD_WHISPER_TRUST_DELTA: Final[float] = 12.0
BLOOD_WHISPER_SUSPICION_DELTA: Final[float] = -0.08
BLOOD_WHISPER_PUBLIC_TEMPLATE: Final[str] = "{a} 和 {b} 在廊下低声说了几句。"
# 第九轮：结算播报文案，必须与 public_log 末条逐字一致
BLOOD_RUNOFF_MESSAGE: Final[str] = "票数并列，进入加赛。"
BLOOD_STILL_TIE_MESSAGE: Final[str] = "仍平票，今晚无人被处决。"
BLOOD_EXECUTE_MESSAGE: Final[str] = "{name} 被投票处决。"
BLOOD_NIGHT_MESSAGE: Final[str] = "天亮时，{name} 没有下楼。"
BLOOD_POISON_NOTE: Final[str] = "被下药者的私密信息有误，与夜杀无关。"
# 第十四轮：本局专属当夜线索（双人排查 + 清白佐证）

BLOOD_DYNAMIC_PAIR_TEMPLATE: Final[str] = (
    "昨晚后半夜，你在走廊拐角看见两个身影先后经过，"
    "其中一个心里有鬼：{evil} 或 {good}。"
)
BLOOD_DYNAMIC_CLEAR_TEMPLATE: Final[str] = (
    "昨晚{good}房里的灯一直亮到后半夜，你听见这人没出过门，"
    "不像夜里动手的恶魔。"
)
BLOOD_PACT_NOTE_TEMPLATE: Final[str] = (
    "你方才在廊下与{other}低声通过气，今天先不急着互相提名。"
)
BLOOD_POISON_NOTE_DYNAMIC: Final[str] = "{kind}被下药篡改，不能作证。"
# 必须凭持有人身份才能认领的线索物件
OWNERSHIP_KEY_TERMS: Final[tuple[str, ...]] = ("名分", "银元", "手帕")