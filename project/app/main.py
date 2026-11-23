"""FastAPI HTTP 适配层：只做请求与响应映射。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from app import blood, blood_ai
from app.blood import (
    AdvanceOutcome,
    BloodLogEntry,
    BloodState,
    BloodStore,
    BloodView,
    ConfideOutcome,
    DefenseOutcome,
    InspectOutcome,
    LastWordsOutcome,
    NightOutcome,
    RunoffCandidate,
    TalkOutcome,
    VoteOutcome,
)
from app.config import (
    BLOOD_MAX_DEFENSE_SPEAK_PER_DAY,
    BLOOD_MAX_SPEAK_PER_DAY,
    CONFIDE_TEXT_MAX_CHARS,
    LIMIT_PER_GAME,
)
from app.llm import LLMClient
from app.models import Script
from app.script_loader import DEFAULT_SCRIPT_PATH, load_script

WEB_DIR = Path(__file__).resolve().parents[1] / "web"


class APIModel(BaseModel):
    """接口模型基类：拒绝未知字段。"""

    model_config = ConfigDict(extra="forbid")


class BloodPlayerPublic(APIModel):
    """阵营模式里一名玩家的公开信息。"""

    id: str
    name: str
    public: str
    alive: bool
    is_you: bool


class BloodDeadPublic(APIModel):
    """已出局玩家。"""

    id: str
    name: str


class BloodYouPublic(APIModel):
    """只返回给真人的身份与私有信息。"""

    id: str
    name: str
    role: Literal["villager", "murderer", "minion"]
    private_info: list[str]
    teammates: list[str]


class BloodLogEntryPublic(APIModel):
    """公开频道里的一条发言。"""

    seq: int
    speaker_id: str
    speaker_name: str
    text: str


class BloodSuccessionPublic(APIModel):
    """一次恶魔传位。"""

    day: int
    from_id: str
    from_name: str
    to_id: str
    to_name: str


class BloodRevealPublic(APIModel):
    """终局揭晓：最初的恶魔、爪牙、传位链与中毒者。"""

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
    succession: list[BloodSuccessionPublic] = Field(default_factory=list)


class BloodRunoffCandidatePublic(APIModel):
    """重投阶段的一名候选。"""

    id: str
    name: str


class BloodStateResponse(APIModel):
    """阵营模式一局的公开状态。"""

    game_id: str
    day: int
    phase: Literal["discussion", "defense", "runoff", "night", "spectating", "ended"]
    players: list[BloodPlayerPublic]
    you: BloodYouPublic
    public_log: list[BloodLogEntryPublic]
    dead: list[BloodDeadPublic]
    message: str
    winner: Literal["good", "murderer"] | None = None
    reveal: BloodRevealPublic | None = None
    aftermath: list[dict[str, object]] = Field(default_factory=list)
    day_history: list[dict[str, object]] = Field(default_factory=list)
    you_alive: bool = True
    runoff_candidates: list[BloodRunoffCandidatePublic] = Field(
        default_factory=list
    )
    stalemate_count: int = 0
    ghost_vote_available: bool = False
    your_result: Literal["win", "lose", "draw"] | None = None
    you_win: bool | None = None


class BloodReplyPublic(APIModel):
    """一名 agent 的一句回应。"""

    speaker_id: str
    speaker_name: str
    text: str


class BloodTalkResponse(APIModel):
    """讨论或真人发言后的结果。"""

    replies: list[BloodReplyPublic]
    public_log: list[BloodLogEntryPublic]
    phase: Literal["discussion", "defense", "runoff", "night", "spectating", "ended"]
    notice: str = ""


class BloodSpeakRequest(APIModel):
    """真人公开发言。"""

    text: str = Field(min_length=1)


class BloodNominateRequest(APIModel):
    """真人提名一个处决目标。"""

    target_id: str = Field(min_length=1)


class BloodNomineePublic(APIModel):
    """被提名者的公开信息。"""

    id: str
    name: str


class BloodNominateResponse(APIModel):
    """提名后进入自辩阶段。"""

    phase: Literal["discussion", "defense", "runoff", "night", "spectating", "ended"]
    target: BloodNomineePublic
    defense: BloodReplyPublic
    public_log: list[BloodLogEntryPublic]


class BloodVoteRequest(APIModel):
    """真人投票，可投提名目标之外的人；死者可投唯一一枚亡者票。"""

    target_id: str = Field(min_length=1)
    reason: str | None = None
    ghost: bool = False


class BloodVotePublic(APIModel):
    """一张选票，agent 附带一句公开理由。"""

    voter_id: str
    voter_name: str
    target_id: str
    target_name: str
    reason: str


class BloodVoteResponse(APIModel):
    """投票与处决结算。"""

    votes: list[BloodVotePublic]
    tally: dict[str, int]
    threshold: int
    executed: BloodDeadPublic | None
    winner: Literal["good", "murderer"] | None
    reveal: BloodRevealPublic | None
    message: str
    public_log: list[BloodLogEntryPublic]
    phase: Literal["discussion", "defense", "runoff", "night", "spectating", "ended"]
    aftermath: list[dict[str, object]] = Field(default_factory=list)
    runoff_candidates: list[BloodRunoffCandidatePublic] = Field(
        default_factory=list
    )
    stalemate_count: int = 0


class BloodNightRequest(APIModel):
    """夜晚行动：真人是凶手时必须给目标。"""

    target_id: str | None = None


class BloodNightResponse(APIModel):
    """夜晚结算结果。"""

    killed: BloodDeadPublic | None
    day: int
    phase: Literal["discussion", "defense", "runoff", "night", "spectating", "ended"]
    winner: Literal["good", "murderer"] | None
    reveal: BloodRevealPublic | None = None
    message: str
    public_log: list[BloodLogEntryPublic]
    aftermath: list[dict[str, object]] = Field(default_factory=list)
    you_alive: bool = True


class BloodAdvanceResponse(APIModel):
    """观战推进：agent 代跑当天流程后的状态。"""

    phase: Literal["discussion", "defense", "runoff", "night", "spectating", "ended"]
    day: int
    public_log: list[BloodLogEntryPublic]
    votes: list[BloodVotePublic]
    executed: BloodDeadPublic | None = None
    killed: BloodDeadPublic | None = None
    winner: Literal["good", "murderer"] | None = None
    reveal: BloodRevealPublic | None = None
    ghost_vote_available: bool = False
    new_entries: list[BloodLogEntryPublic] = Field(default_factory=list)


class BloodConfideRequest(APIModel):
    """真人私下找一名 agent 说话。"""

    target_id: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=CONFIDE_TEXT_MAX_CHARS)


class BloodConfideResponse(APIModel):
    """一次密谈的结果，正文只回给真人。"""

    stance: Literal["accept", "refuse", "evade", "threaten"]
    reply: str
    trust: int
    suspicion: int
    public_line: str
    betrayed: bool = False


class BloodInspectRequest(APIModel):
    """真人查验一名在场者；reveal 为真才公开结果。"""

    target_id: str = Field(min_length=1)
    reveal: bool = False


class BloodInspectResponse(APIModel):
    """查验结果只答是否凶手，不返回角色细节。"""

    result: Literal["murderer", "not_murderer"]
    public_line: str
    remaining: int
    revealed: bool = False


class BloodPrivateEntryPublic(APIModel):
    """只给真人看的密谈记录。"""

    day: int
    target_id: str
    target_name: str
    text: str
    stance: Literal["accept", "refuse", "evade", "threaten"]
    reply: str


class BloodPrivateLogResponse(APIModel):
    """真人私有密谈日志。"""

    entries: list[BloodPrivateEntryPublic]


class BloodLastWordsRequest(APIModel):
    """真人出局后的遗言。"""

    text: str = Field(min_length=1)


class BloodLastWordsResponse(APIModel):
    """遗言写入公开频道后的结果。"""

    text: str
    message: str
    public_log: list[BloodLogEntryPublic]


class BloodGameLogResponse(APIModel):
    """阵营模式回看日志。"""

    game_id: str
    entries: list[dict[str, object]]


BLOOD_ERRORS: dict[str, tuple[int, str]] = {
    "game_not_found": (404, "找不到这一局"),
    "target_not_found": (404, "找不到这个投票目标"),
    "game_ended": (409, "本局已经结束，请开始新的一局"),
    "wrong_phase": (409, "当前阶段不能做这件事"),
    "you_are_dead": (409, "你已经出局，只能旁观"),
    "discuss_used": (409, "今天已经讨论过了"),
    "speak_limit": (409, f"今天最多回应 {BLOOD_MAX_SPEAK_PER_DAY} 次"),
    "defense_speak_limit": (
        409,
        f"今天质证最多 {BLOOD_MAX_DEFENSE_SPEAK_PER_DAY} 次",
    ),
    "nominate_used": (409, "今天已经提名过了"),
    "target_dead": (409, "这个人已经死了"),
    "target_invalid": (422, "不能选择这个目标"),
    "night_target_required": (422, "你是凶手，必须选择今晚下手的对象"),
    "confide_used_day": (409, "今天已经密谈过了"),
    "confide_limit": (409, f"本局最多密谈 {LIMIT_PER_GAME} 次"),
    "confide_self": (422, "不能与自己密谈"),
    "confide_text_invalid": (422, "密谈内容为空或过长"),
    "inspect_unavailable": (409, "你现在没有可用的查验"),
    "inspect_used": (409, "这次查验已经用过了"),
    "ghost_not_available": (409, "你还活着，用不上亡者票"),
    "ghost_vote_used": (409, "这枚亡者票已经投过了"),
    "you_are_alive": (409, "你还在场上，不能留遗言"),
    "last_words_used": (409, "遗言已经留过了"),
    "last_words_invalid": (422, "遗言内容为空或过长"),
}


def create_app(
    script: Script | None = None,
    blood_store: BloodStore | None = None,
    blood_llm: LLMClient | None = None,
) -> FastAPI:
    """创建 FastAPI 应用，可注入剧本、内存存储与模型客户端以便测试。"""
    game_script = script or load_script(
        os.environ.get("SCRIPT_PATH") or DEFAULT_SCRIPT_PATH
    )
    blood_games = blood_store or BloodStore()
    blood_reply = blood_ai.make_reply_fn(blood_llm)
    blood_confide = blood_ai.make_confide_fn(blood_llm)
    application = FastAPI(title="雾镇", version="0.1.0")

    @application.post(
        "/blood/games",
        response_model=BloodStateResponse,
    )
    def start_blood_game() -> BloodStateResponse:
        """开一局阵营模式，随机一名凶手。"""
        state = blood_games.start(game_script)
        return _blood_state_public(blood.build_view(state))

    @application.get(
        "/blood/games/{game_id}",
        response_model=BloodStateResponse,
    )
    def get_blood_game(game_id: str) -> BloodStateResponse:
        """查询阵营模式一局的当前状态。"""
        state = blood_games.get(game_id)
        if state is None:
            _raise_blood_error("game_not_found")
        return _blood_state_public(blood.build_view(state))

    @application.post(
        "/blood/games/{game_id}/discuss",
        response_model=BloodTalkResponse,
    )
    def discuss_blood_game(game_id: str) -> BloodTalkResponse:
        """让所有存活 agent 各公开说一句。"""
        outcome = blood.discuss(blood_games, game_id, blood_reply)
        _raise_blood_error(outcome.error)
        return _blood_talk_public(blood_games.get(game_id), outcome)

    @application.post(
        "/blood/games/{game_id}/speak",
        response_model=BloodTalkResponse,
    )
    def speak_blood_game(
        game_id: str,
        request: BloodSpeakRequest,
    ) -> BloodTalkResponse:
        """真人公开发言一次，触发一名 agent 回应。"""
        outcome = blood.speak(
            blood_games,
            game_id,
            request.text,
            blood_reply,
        )
        _raise_blood_error(outcome.error)
        return _blood_talk_public(blood_games.get(game_id), outcome)

    @application.post(
        "/blood/games/{game_id}/nominate",
        response_model=BloodNominateResponse,
    )
    def nominate_blood_game(
        game_id: str,
        request: BloodNominateRequest,
    ) -> BloodNominateResponse:
        """提名一名在场者，由被提名者先自辩，不立即处决。"""
        outcome = blood.nominate(
            blood_games,
            game_id,
            request.target_id,
            blood_reply,
        )
        _raise_blood_error(outcome.error)
        state = blood_games.get(game_id)
        if state is None:
            _raise_blood_error("game_not_found")
        return _blood_nominate_public(state, outcome)

    @application.post(
        "/blood/games/{game_id}/vote",
        response_model=BloodVoteResponse,
    )
    def vote_blood_game(
        game_id: str,
        request: BloodVoteRequest,
    ) -> BloodVoteResponse:
        """全体投票，得票达到向上取整半数才处决。"""
        outcome = blood.vote(
            blood_games,
            game_id,
            request.target_id,
            blood_reply,
            reason=request.reason or "",
            ghost=request.ghost,
        )
        _raise_blood_error(outcome.error)
        state = blood_games.get(game_id)
        if state is None:
            _raise_blood_error("game_not_found")
        return _blood_vote_public(state, outcome)

    @application.post(
        "/blood/games/{game_id}/night",
        response_model=BloodNightResponse,
    )
    def night_blood_game(
        game_id: str,
        request: BloodNightRequest,
    ) -> BloodNightResponse:
        """结算夜晚。"""
        outcome = blood.night(blood_games, game_id, request.target_id)
        _raise_blood_error(outcome.error)
        state = blood_games.get(game_id)
        if state is None:
            _raise_blood_error("game_not_found")
        return _blood_night_public(state, outcome)

    @application.post(
        "/blood/games/{game_id}/advance",
        response_model=BloodAdvanceResponse,
    )
    def advance_blood_game(game_id: str) -> BloodAdvanceResponse:
        """观战推进：agent 代跑讨论、提名、投票与夜晚。"""
        outcome = blood.advance(blood_games, game_id)
        _raise_blood_error(outcome.error)
        return _blood_advance_public(outcome)

    @application.post(
        "/blood/games/{game_id}/confide",
        response_model=BloodConfideResponse,
    )
    def confide_blood_game(
        game_id: str,
        request: BloodConfideRequest,
    ) -> BloodConfideResponse:
        """真人私下找一名 agent 说话，正文只进 private-log。"""
        outcome = blood.confide(
            blood_games,
            game_id,
            request.target_id,
            request.text,
            blood_confide,
        )
        _raise_blood_error(outcome.error)
        return BloodConfideResponse(
            stance=outcome.stance,
            reply=outcome.reply,
            trust=outcome.trust,
            suspicion=outcome.suspicion,
            public_line=outcome.public_line,
            betrayed=outcome.betrayed,
        )

    @application.post(
        "/blood/games/{game_id}/inspect",
        response_model=BloodInspectResponse,
    )
    def inspect_blood_game(
        game_id: str,
        request: BloodInspectRequest,
    ) -> BloodInspectResponse:
        """真人查验一名在场者是否凶手，每局 1 次。"""
        outcome = blood.inspect(
            blood_games,
            game_id,
            request.target_id,
            reveal=request.reveal,
        )
        _raise_blood_error(outcome.error)
        return BloodInspectResponse(
            result=outcome.result,
            public_line=outcome.public_line,
            remaining=outcome.remaining,
            revealed=outcome.revealed,
        )

    @application.get(
        "/blood/games/{game_id}/private-log",
        response_model=BloodPrivateLogResponse,
    )
    def get_blood_private_log(game_id: str) -> BloodPrivateLogResponse:
        """只返回真人自己的密谈记录，含正文。"""
        state = blood_games.get(game_id)
        if state is None:
            _raise_blood_error("game_not_found")
        return BloodPrivateLogResponse(
            entries=[
                BloodPrivateEntryPublic(
                    day=entry.day,
                    target_id=entry.target_id,
                    target_name=entry.target_name,
                    text=entry.text,
                    stance=entry.stance,
                    reply=entry.reply,
                )
                for entry in state.private_log
            ]
        )

    @application.post(
        "/blood/games/{game_id}/last-words",
        response_model=BloodLastWordsResponse,
    )
    def last_words_blood_game(
        game_id: str,
        request: BloodLastWordsRequest,
    ) -> BloodLastWordsResponse:
        """真人出局后留一条遗言，进入公开频道。"""
        outcome = blood.last_words(
            blood_games,
            game_id,
            request.text,
        )
        _raise_blood_error(outcome.error)
        state = blood_games.get(game_id)
        if state is None:
            _raise_blood_error("game_not_found")
        return BloodLastWordsResponse(
            text=outcome.text,
            message=outcome.message,
            public_log=_blood_log_public(state.public_log),
        )

    @application.get(
        "/blood/games/{game_id}/log",
        response_model=BloodGameLogResponse,
    )
    def get_blood_log(game_id: str) -> BloodGameLogResponse:
        """返回阵营模式的不含秘密字段回看日志。"""
        state = blood_games.get(game_id)
        if state is None:
            _raise_blood_error("game_not_found")
        return BloodGameLogResponse(
            game_id=game_id,
            entries=blood.build_log(state),
        )

    @application.get("/blood", include_in_schema=False)
    def blood_page() -> FileResponse:
        """返回圆桌模式的静态页面。"""
        return FileResponse(WEB_DIR / "blood.html")

    @application.get("/", include_in_schema=False)
    def root_redirect() -> RedirectResponse:
        """根路径跳转到电子血染页面。"""
        return RedirectResponse(url="/blood", status_code=307)

    application.mount(
        "/",
        StaticFiles(directory=WEB_DIR, html=True),
        name="web",
    )
    return application


def _blood_log_public(
    entries: Iterable[BloodLogEntry],
) -> list[BloodLogEntryPublic]:
    return [
        BloodLogEntryPublic(
            seq=entry.seq,
            speaker_id=entry.speaker_id,
            speaker_name=entry.speaker_name,
            text=entry.text,
        )
        for entry in entries
    ]


def _blood_state_public(view: BloodView) -> BloodStateResponse:
    return BloodStateResponse(
        game_id=view.game_id,
        day=view.day,
        phase=view.phase,
        players=[
            BloodPlayerPublic(
                id=player.id,
                name=player.name,
                public=player.public,
                alive=player.alive,
                is_you=player.is_you,
            )
            for player in view.players
        ],
        you=BloodYouPublic(
            id=view.you.id,
            name=view.you.name,
            role=view.you.role,
            private_info=list(view.you.private_info),
            teammates=list(view.you.teammates),
        ),
        public_log=_blood_log_public(view.public_log),
        dead=[
            BloodDeadPublic(id=player.id, name=player.name)
            for player in view.dead
        ],
        message=view.message,
        winner=view.winner,
        reveal=_blood_reveal_public(view.reveal),
        aftermath=[dict(item) for item in view.aftermath],
        day_history=[dict(item) for item in view.day_history],
        you_alive=view.you_alive,
        runoff_candidates=_blood_runoff_public(view.runoff_candidates),
        stalemate_count=view.stalemate_count,
        ghost_vote_available=view.ghost_vote_available,
        your_result=view.your_result,
        you_win=view.you_win,
    )


def _blood_runoff_public(
    candidates: Iterable[RunoffCandidate],
) -> list[BloodRunoffCandidatePublic]:
    return [
        BloodRunoffCandidatePublic(id=item.id, name=item.name)
        for item in candidates
    ]


def _blood_talk_public(
    state: BloodState | None,
    outcome: TalkOutcome,
) -> BloodTalkResponse:
    return BloodTalkResponse(
        replies=[
            BloodReplyPublic(
                speaker_id=reply.speaker_id,
                speaker_name=reply.speaker_name,
                text=reply.text,
            )
            for reply in outcome.replies
        ],
        public_log=_blood_log_public(state.public_log if state else ()),
        phase=outcome.phase,
        notice=outcome.notice,
    )


def _blood_nominate_public(
    state: BloodState,
    outcome: DefenseOutcome,
) -> BloodNominateResponse:
    if outcome.target is None or outcome.defense is None:
        raise HTTPException(status_code=500, detail="提名结算缺少自辩内容")
    return BloodNominateResponse(
        phase=outcome.phase,
        target=BloodNomineePublic(
            id=outcome.target.id,
            name=outcome.target.name,
        ),
        defense=BloodReplyPublic(
            speaker_id=outcome.defense.speaker_id,
            speaker_name=outcome.defense.speaker_name,
            text=outcome.defense.text,
        ),
        public_log=_blood_log_public(state.public_log),
    )


def _blood_vote_public(
    state: BloodState,
    outcome: VoteOutcome,
) -> BloodVoteResponse:
    return BloodVoteResponse(
        votes=[
            BloodVotePublic(
                voter_id=vote.voter_id,
                voter_name=vote.voter_name,
                target_id=vote.target_id,
                target_name=vote.target_name,
                reason=vote.reason,
            )
            for vote in outcome.votes
        ],
        tally=dict(outcome.tally),
        threshold=outcome.threshold,
        executed=(
            BloodDeadPublic(
                id=outcome.executed.id,
                name=outcome.executed.name,
            )
            if outcome.executed is not None
            else None
        ),
        winner=outcome.winner,
        reveal=_blood_reveal_public(outcome.reveal),
        message=outcome.message,
        public_log=_blood_log_public(state.public_log),
        phase=outcome.phase,
        aftermath=[dict(item) for item in outcome.aftermath],
        runoff_candidates=_blood_runoff_public(outcome.runoff_candidates),
        stalemate_count=outcome.stalemate_count,
    )


def _blood_reveal_public(
    reveal: blood.RevealView | None,
) -> BloodRevealPublic | None:
    if reveal is None:
        return None
    return BloodRevealPublic(
        murderer_id=reveal.murderer_id,
        murderer_name=reveal.murderer_name,
        final_murderer_id=reveal.final_murderer_id,
        final_murderer_name=reveal.final_murderer_name,
        minion_id=reveal.minion_id,
        minion_name=reveal.minion_name,
        poisoned_id=reveal.poisoned_id,
        poisoned_name=reveal.poisoned_name,
        poisoned_note=reveal.poisoned_note,
        killed_id=reveal.killed_id,
        killed_name=reveal.killed_name,
        succession=[
            BloodSuccessionPublic(
                day=int(item.get("day", 0)),
                from_id=str(item.get("from_id", "")),
                from_name=str(item.get("from_name", "")),
                to_id=str(item.get("to_id", "")),
                to_name=str(item.get("to_name", "")),
            )
            for item in reveal.succession
        ],
    )


def _blood_night_public(
    state: BloodState,
    outcome: NightOutcome,
) -> BloodNightResponse:
    return BloodNightResponse(
        killed=(
            BloodDeadPublic(
                id=outcome.killed.id,
                name=outcome.killed.name,
            )
            if outcome.killed is not None
            else None
        ),
        day=outcome.day,
        phase=outcome.phase,
        winner=outcome.winner,
        reveal=_blood_reveal_public(outcome.reveal),
        message=outcome.message,
        public_log=_blood_log_public(state.public_log),
        aftermath=[dict(item) for item in outcome.aftermath],
        you_alive=outcome.you_alive,
    )


def _blood_advance_public(outcome: AdvanceOutcome) -> BloodAdvanceResponse:
    return BloodAdvanceResponse(
        phase=outcome.phase,
        day=outcome.day,
        public_log=_blood_log_public(outcome.public_log),
        votes=[
            BloodVotePublic(
                voter_id=vote.voter_id,
                voter_name=vote.voter_name,
                target_id=vote.target_id,
                target_name=vote.target_name,
                reason=vote.reason,
            )
            for vote in outcome.votes
        ],
        executed=(
            BloodDeadPublic(
                id=outcome.executed.id,
                name=outcome.executed.name,
            )
            if outcome.executed is not None
            else None
        ),
        killed=(
            BloodDeadPublic(
                id=outcome.killed.id,
                name=outcome.killed.name,
            )
            if outcome.killed is not None
            else None
        ),
        winner=outcome.winner,
        reveal=_blood_reveal_public(outcome.reveal),
        ghost_vote_available=outcome.ghost_vote_available,
        new_entries=_blood_log_public(outcome.new_entries),
    )


def _raise_blood_error(error: str | None) -> None:
    if error is None:
        return
    status, message = BLOOD_ERRORS.get(error, (400, "请求无法处理"))
    raise HTTPException(status_code=status, detail=message)


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)