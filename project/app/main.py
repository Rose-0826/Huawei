"""FastAPI HTTP 适配层：只做请求与响应映射。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from app import blood, blood_ai
from app.blood import (
    BloodLogEntry,
    BloodState,
    BloodStore,
    BloodView,
    DefenseOutcome,
    NightOutcome,
    TalkOutcome,
    VoteOutcome,
)
from app.config import (
    BLOOD_MAX_DEFENSE_SPEAK_PER_DAY,
    BLOOD_MAX_SPEAK_PER_DAY,
    MAX_QUESTION_CHARS,
)
from app.engine.social import SocialEvent
from app.game import (
    AskOutcome,
    CombineOutcome,
    GameStore,
    GameView,
    ask,
    accuse,
    build_view,
    combine,
    confront,
    get_event,
    get_log,
    get_view,
    present_clue,
    resolve_event_choice,
)
from app.llm import LLMClient
from app.models import Clue, Script
from app.script_loader import DEFAULT_SCRIPT_PATH, load_script

WEB_DIR = Path(__file__).resolve().parents[1] / "web"


class APIModel(BaseModel):
    """接口模型基类：拒绝未知字段。"""

    model_config = ConfigDict(extra="forbid")


class VictimPublic(APIModel):
    """玩家可见的死者信息。"""

    id: str
    name: str
    desc: str


class RolePublic(APIModel):
    """玩家可见的角色信息。"""

    id: str
    name: str
    public: str


class CluePublic(APIModel):
    """玩家可见的线索信息。"""

    id: str
    name: str
    desc: str


class VerdictOptionPublic(APIModel):
    """指认面板上的一个可选项。"""

    id: str
    label: str


class GameStateResponse(APIModel):
    """开始或查询一局时返回的公开状态。"""

    game_id: str
    title: str
    era: str
    opening: str
    victim: VictimPublic
    roles: list[RolePublic]
    clues: list[CluePublic]
    pressure: dict[str, float]
    ended: bool
    combine_remaining: int
    combine_max: int
    verdict_options: dict[str, list[VerdictOptionPublic]]


class AskRequest(APIModel):
    """提问请求。"""

    npc_id: str = Field(min_length=1)
    question: str = Field(min_length=1)


class AskResponse(APIModel):
    """提问或出示线索后的台词与状态变化。"""

    reply: str
    pressure: float
    unlocked_clue: CluePublic | None = None


class PresentClueRequest(APIModel):
    """出示线索请求。"""

    npc_id: str = Field(min_length=1)
    clue_id: str = Field(min_length=1)


class CombineRequest(APIModel):
    """线索对撞请求：两张物证 id。"""

    clue_ids: list[str]


class CombineReactionPublic(APIModel):
    """对撞命中后相关角色的一句模板反应。"""

    npc_id: str
    name: str
    line: str


class CombineResponse(APIModel):
    """线索对撞结果：新推断、受压角色、反应与剩余次数。"""

    title: str
    text: str
    pressure: dict[str, float]
    remaining: int
    reaction: CombineReactionPublic | None = None
    target_npc_id: str | None = None


class ConfrontRequest(APIModel):
    """对质请求：两个不同角色与同一个问题。"""

    npc_ids: list[str] = Field(min_length=2, max_length=2)
    question: str = Field(min_length=1)


class ConfrontReplyPublic(APIModel):
    """对质中一个角色的原话。"""

    npc_id: str
    name: str
    reply: str


class ConfrontResponse(APIModel):
    """对质结果：两人原话与口径判断。"""

    alignment: str
    replies: list[ConfrontReplyPublic]
    unlocked_clues: list[CluePublic]
    pressure: dict[str, float]


class AccuseRequest(APIModel):
    """指认请求：凶手必填，动机、手法、时间可选。"""

    suspect_id: str = Field(min_length=1)
    motive: str | None = Field(default=None, min_length=1)
    method: str | None = Field(default=None, min_length=1)
    time: str | None = Field(default=None, min_length=1)


class TruthFact(APIModel):
    """真相时间线上的一条事实。"""

    fact_id: str
    text: str


class DimensionPublic(APIModel):
    """一个指认维度的判定结果。"""

    id: str
    label: str
    choice: str
    correct: bool


class AccuseResponse(APIModel):
    """指认结果。"""

    correct: bool
    partial: bool
    dimensions: list[DimensionPublic]
    timeline: list[TruthFact]
    missed_fact_ids: list[str]


class EventSpeakerPublic(APIModel):
    """主动插话里的说话人或对象。"""

    id: str
    name: str


class EventChoicePublic(APIModel):
    """玩家对主动插话的一个回应选项。"""

    id: str
    label: str


class EventPublic(APIModel):
    """一次主动插话的公开内容。"""

    id: str
    kind: str
    speaker: EventSpeakerPublic
    target: EventSpeakerPublic | None
    line: str
    choices: list[EventChoicePublic]


class EventResponse(APIModel):
    """查询主动插话的响应，没有待处理事件时 event 为空。"""

    event: EventPublic | None


class EventChoiceRequest(APIModel):
    """回应主动插话的请求。"""

    choice: Literal["press", "dismiss"]


class EventChoiceResponse(APIModel):
    """回应主动插话后的结果。"""

    reply: str
    pressure: dict[str, float]
    event: EventPublic | None = None


class LogResponse(APIModel):
    """本局玩家可见日志，条目类型由 type 字段区分。"""

    game_id: str
    entries: list[dict[str, object]]


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
    role: Literal["villager", "murderer"]
    private_info: list[str]
    teammates: list[str]


class BloodLogEntryPublic(APIModel):
    """公开频道里的一条发言。"""

    seq: int
    speaker_id: str
    speaker_name: str
    text: str


class BloodRevealPublic(APIModel):
    """终局揭晓的凶手身份。"""

    murderer_id: str
    murderer_name: str


class BloodStateResponse(APIModel):
    """阵营模式一局的公开状态。"""

    game_id: str
    day: int
    phase: Literal["discussion", "defense", "night", "ended"]
    players: list[BloodPlayerPublic]
    you: BloodYouPublic
    public_log: list[BloodLogEntryPublic]
    dead: list[BloodDeadPublic]
    message: str
    winner: Literal["good", "murderer"] | None = None
    reveal: BloodRevealPublic | None = None
    aftermath: list[dict[str, object]] = Field(default_factory=list)
    you_alive: bool = True


class BloodReplyPublic(APIModel):
    """一名 agent 的一句回应。"""

    speaker_id: str
    speaker_name: str
    text: str


class BloodTalkResponse(APIModel):
    """讨论或真人发言后的结果。"""

    replies: list[BloodReplyPublic]
    public_log: list[BloodLogEntryPublic]
    phase: Literal["discussion", "defense", "night", "ended"]


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

    phase: Literal["discussion", "defense", "night", "ended"]
    target: BloodNomineePublic
    defense: BloodReplyPublic
    public_log: list[BloodLogEntryPublic]


class BloodVoteRequest(APIModel):
    """真人投票，可投提名目标之外的人，理由可选。"""

    target_id: str = Field(min_length=1)
    reason: str | None = None


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
    phase: Literal["discussion", "defense", "night", "ended"]
    aftermath: list[dict[str, object]] = Field(default_factory=list)


class BloodNightRequest(APIModel):
    """夜晚行动：真人是凶手时必须给目标。"""

    target_id: str | None = None


class BloodNightResponse(APIModel):
    """夜晚结算结果。"""

    killed: BloodDeadPublic | None
    day: int
    phase: Literal["discussion", "defense", "night", "ended"]
    winner: Literal["good", "murderer"] | None
    reveal: BloodRevealPublic | None = None
    message: str
    public_log: list[BloodLogEntryPublic]
    aftermath: list[dict[str, object]] = Field(default_factory=list)


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
}


GAME_ERRORS: dict[str, tuple[int, str]] = {
    "game_not_found": (404, "找不到这一局"),
    "npc_not_found": (404, "找不到这个角色"),
    "clue_not_found": (404, "找不到这张线索"),
    "clue_not_unlocked": (409, "这张线索还没有解锁，还不能使用"),
    "clue_already_presented": (409, "这张线索你已经给他看过了"),
    "no_question_asked": (409, "还没有向这个角色提问，无法让他重新回答"),
    "game_ended": (409, "本局已经结束，请开始新的一局"),
    "empty_question": (422, "问题不能为空"),
    "question_too_long": (422, f"问题不能超过 {MAX_QUESTION_CHARS} 字"),
    "confront_needs_two": (422, "对质需要两个不同的人"),
    "combine_needs_two": (422, "对撞需要两张不同的物证"),
    "combine_not_found": (422, "这两张物证对不上"),
    "combine_already_used": (409, "这两张物证已经对撞过了"),
    "combine_limit_reached": (409, "本局的对撞次数已经用完"),
    "confront_failed": (500, "两人的回答没有形成可比的口径"),
    "no_pending_event": (409, "现在没有人主动开口"),
}

COMBINE_FAILURE_TEMPLATES: dict[str, str] = {
    "combine_needs_two": "对撞需要两张不同的物证（本局还剩 {remaining} 次）",
    "combine_not_found": (
        "这两张物证对不上，试试有共同人物或时间的物证"
        "（本局还剩 {remaining} 次）"
    ),
    "combine_already_used": "这两张物证已经对撞过了（本局还剩 {remaining} 次）",
    "combine_limit_reached": "本局的对撞次数已经用完（本局还剩 {remaining} 次）",
    "clue_not_unlocked": "这张线索还没有解锁，还不能使用（本局还剩 {remaining} 次）",
}


def create_app(
    script: Script | None = None,
    store: GameStore | None = None,
    blood_store: BloodStore | None = None,
    blood_llm: LLMClient | None = None,
) -> FastAPI:
    """创建 FastAPI 应用，可注入剧本、内存存储与模型客户端以便测试。"""
    game_script = script or load_script(
        os.environ.get("SCRIPT_PATH") or DEFAULT_SCRIPT_PATH
    )
    game_store = store or GameStore()
    blood_games = blood_store or BloodStore()
    blood_reply = blood_ai.make_reply_fn(blood_llm)
    application = FastAPI(title="雾镇", version="0.1.0")

    @application.post("/games", response_model=GameStateResponse)
    def start_game() -> GameStateResponse:
        """开始一局，返回开场白与公开角色信息。"""
        state = game_store.start(game_script)
        return _state_public(build_view(state))

    @application.post(
        "/games/{game_id}/ask",
        response_model=AskResponse,
    )
    def ask_question(game_id: str, request: AskRequest) -> AskResponse:
        """向角色提问，返回一条事实生成的完整台词。"""
        outcome = ask(game_store, game_id, request.npc_id, request.question)
        _raise_error(outcome.error)
        return _ask_public(outcome)

    @application.post(
        "/games/{game_id}/clues",
        response_model=AskResponse,
    )
    def present_clue_route(
        game_id: str,
        request: PresentClueRequest,
    ) -> AskResponse:
        """出示已解锁线索，提升压力并返回针对物证的回应。"""
        outcome = present_clue(
            game_store,
            game_id,
            request.npc_id,
            request.clue_id,
        )
        _raise_error(outcome.error)
        return _ask_public(outcome)

    @application.post(
        "/games/{game_id}/combine",
        response_model=CombineResponse,
    )
    def combine_clues(
        game_id: str,
        request: CombineRequest,
    ) -> CombineResponse:
        """把两张已解锁物证对撞成一条新推断，并提升相关角色压力。"""
        outcome = combine(game_store, game_id, tuple(request.clue_ids))
        if outcome.error is not None:
            status, _ = GAME_ERRORS.get(outcome.error, (400, "请求无法处理"))
            raise HTTPException(
                status_code=status,
                detail=_combine_error_detail(
                    outcome.error,
                    outcome.remaining,
                ),
            )
        return CombineResponse(
            title=outcome.title or "",
            text=outcome.text or "",
            pressure=dict(outcome.pressure),
            remaining=outcome.remaining,
            reaction=(
                CombineReactionPublic(
                    npc_id=outcome.reaction.npc_id,
                    name=outcome.reaction.name,
                    line=outcome.reaction.line,
                )
                if outcome.reaction is not None
                else None
            ),
            target_npc_id=outcome.target_npc_id,
        )

    @application.post(
        "/games/{game_id}/confront",
        response_model=ConfrontResponse,
    )
    def confront_witnesses(
        game_id: str,
        request: ConfrontRequest,
    ) -> ConfrontResponse:
        """让两人回答同一问题，返回原话与口径是否一致。"""
        outcome = confront(
            game_store,
            game_id,
            tuple(request.npc_ids),
            request.question,
        )
        _raise_error(outcome.error)
        return ConfrontResponse(
            alignment=outcome.alignment or "unclear",
            replies=[
                ConfrontReplyPublic(
                    npc_id=reply.npc_id,
                    name=reply.name,
                    reply=reply.reply,
                )
                for reply in outcome.replies
            ],
            unlocked_clues=[
                _clue_public(clue) for clue in outcome.unlocked_clues
            ],
            pressure=dict(outcome.pressure),
        )

    @application.get(
        "/games/{game_id}/event",
        response_model=EventResponse,
    )
    def get_pending_event(game_id: str) -> EventResponse:
        """查询当前是否有 NPC 主动开口。"""
        outcome = get_event(game_store, game_id)
        _raise_error(outcome.error)
        return EventResponse(event=_event_public(outcome.event))

    @application.post(
        "/games/{game_id}/event",
        response_model=EventChoiceResponse,
    )
    def choose_event(
        game_id: str,
        request: EventChoiceRequest,
    ) -> EventChoiceResponse:
        """追问或让人走，结算说话人的压力变化。"""
        outcome = resolve_event_choice(
            game_store,
            game_id,
            request.choice,
        )
        _raise_error(outcome.error)
        return EventChoiceResponse(
            reply=outcome.reply or "",
            pressure=dict(outcome.pressure),
            event=None,
        )

    @application.get(
        "/games/{game_id}/log",
        response_model=LogResponse,
    )
    def get_game_log(game_id: str) -> LogResponse:
        """返回本局按操作顺序记录的玩家可见日志。"""
        entries = get_log(game_store, game_id)
        if entries is None:
            _raise_error("game_not_found")
        return LogResponse(game_id=game_id, entries=entries)

    @application.get(
        "/games/{game_id}",
        response_model=GameStateResponse,
    )
    def get_game(game_id: str) -> GameStateResponse:
        """查询一局的公开状态。"""
        view = get_view(game_store, game_id)
        if view is None:
            _raise_error("game_not_found")
        return _state_public(view)

    @application.post(
        "/games/{game_id}/accuse",
        response_model=AccuseResponse,
    )
    def accuse_suspect(
        game_id: str,
        request: AccuseRequest,
    ) -> AccuseResponse:
        """指认凶手，返回命中结果、真相时间线与漏掉的事实 id。"""
        outcome = accuse(
            game_store,
            game_id,
            request.suspect_id,
            motive=request.motive,
            method=request.method,
            time=request.time,
        )
        _raise_error(outcome.error)
        missed = set(outcome.missed_fact_ids)
        return AccuseResponse(
            correct=outcome.correct,
            partial=outcome.partial,
            dimensions=[
                DimensionPublic(
                    id=dimension.id,
                    label=dimension.label,
                    choice=dimension.choice,
                    correct=dimension.correct,
                )
                for dimension in outcome.dimensions
            ],
            timeline=[
                TruthFact(
                    fact_id=fact.id,
                    text="" if fact.id in missed else fact.text,
                )
                for fact in outcome.timeline
            ],
            missed_fact_ids=list(outcome.missed_fact_ids),
        )

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
        you_alive=view.you_alive,
    )


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
    )


def _blood_reveal_public(
    reveal: blood.RevealView | None,
) -> BloodRevealPublic | None:
    if reveal is None:
        return None
    return BloodRevealPublic(
        murderer_id=reveal.murderer_id,
        murderer_name=reveal.murderer_name,
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
    )


def _raise_blood_error(error: str | None) -> None:
    if error is None:
        return
    status, message = BLOOD_ERRORS.get(error, (400, "请求无法处理"))
    raise HTTPException(status_code=status, detail=message)


def _clue_public(clue: Clue) -> CluePublic:
    return CluePublic(id=clue.id, name=clue.name, desc=clue.desc)


def _event_public(event: SocialEvent | None) -> EventPublic | None:
    """把插话对象转成只含公开字段的接口模型。"""
    if event is None:
        return None
    return EventPublic(
        id=event.id,
        kind=event.kind,
        speaker=EventSpeakerPublic(
            id=event.speaker_id,
            name=event.speaker_name,
        ),
        target=(
            EventSpeakerPublic(
                id=event.target_id,
                name=event.target_name or "",
            )
            if event.target_id is not None
            else None
        ),
        line=event.line,
        choices=[
            EventChoicePublic(id=choice.id, label=choice.label)
            for choice in event.choices
        ],
    )


def _state_public(view: GameView) -> GameStateResponse:
    return GameStateResponse(
        game_id=view.game_id,
        title=view.title,
        era=view.era,
        opening=view.opening,
        victim=VictimPublic(
            id=view.victim.id,
            name=view.victim.name,
            desc=view.victim.desc,
        ),
        roles=[
            RolePublic(id=role.id, name=role.name, public=role.public)
            for role in view.roles
        ],
        clues=[
            CluePublic(id=clue.id, name=clue.name, desc=clue.desc)
            for clue in view.clues
        ],
        pressure=dict(view.pressure),
        ended=view.ended,
        combine_remaining=view.combine_remaining,
        combine_max=view.combine_max,
        verdict_options={
            dimension: [
                VerdictOptionPublic(id=option.id, label=option.label)
                for option in options
            ]
            for dimension, options in view.verdict_options.items()
        },
    )


def _ask_public(outcome: AskOutcome) -> AskResponse:
    return AskResponse(
        reply=outcome.reply or "",
        pressure=outcome.pressure,
        unlocked_clue=(
            _clue_public(outcome.unlocked_clue)
            if outcome.unlocked_clue is not None
            else None
        ),
    )


def _raise_error(error: str | None) -> None:
    if error is None:
        return
    status, message = GAME_ERRORS.get(error, (400, "请求无法处理"))
    raise HTTPException(status_code=status, detail=message)


def _combine_error_detail(error: str, remaining: int) -> str:
    """把对撞失败的错误码翻成带方向与剩余次数的提示。"""
    template = COMBINE_FAILURE_TEMPLATES.get(error)
    if template is None:
        return GAME_ERRORS.get(error, (400, "请求无法处理"))[1]
    return template.format(remaining=max(remaining, 0))



app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)