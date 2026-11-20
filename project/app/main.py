"""FastAPI HTTP 适配层：只做请求与响应映射。"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from app.config import MAX_QUESTION_CHARS
from app.game import (
    AskOutcome,

    GameStore,
    GameView,
    ask,
    accuse,
    build_view,
    confront,
    get_view,
    present_clue,
)
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
    """指认请求。"""

    suspect_id: str = Field(min_length=1)


class TruthFact(APIModel):
    """真相时间线上的一条事实。"""

    fact_id: str
    text: str


class AccuseResponse(APIModel):
    """指认结果。"""

    correct: bool
    timeline: list[TruthFact]
    missed_fact_ids: list[str]


GAME_ERRORS: dict[str, tuple[int, str]] = {
    "game_not_found": (404, "找不到这一局"),
    "npc_not_found": (404, "找不到这个角色"),
    "clue_not_found": (404, "找不到这张线索"),
    "clue_not_unlocked": (409, "这张线索还没有解锁，不能出示"),
    "clue_already_presented": (409, "这张线索你已经给他看过了"),
    "no_question_asked": (409, "还没有向这个角色提问，无法让他重新回答"),
    "game_ended": (409, "本局已经结束，请开始新的一局"),
    "empty_question": (422, "问题不能为空"),
    "question_too_long": (422, f"问题不能超过 {MAX_QUESTION_CHARS} 字"),
    "confront_needs_two": (422, "对质需要两个不同的人"),

    "confront_failed": (500, "两人的回答没有形成可比的口径"),
}


def create_app(
    script: Script | None = None,
    store: GameStore | None = None,
) -> FastAPI:
    """创建 FastAPI 应用，可注入剧本与内存存储以便测试。"""
    game_script = script or load_script(
        os.environ.get("SCRIPT_PATH") or DEFAULT_SCRIPT_PATH
    )
    game_store = store or GameStore()
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
        """出示已解锁线索，提升压力并立即重答上一问。"""
        outcome = present_clue(
            game_store,
            game_id,
            request.npc_id,
            request.clue_id,
        )
        _raise_error(outcome.error)
        return _ask_public(outcome)

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
        outcome = accuse(game_store, game_id, request.suspect_id)
        _raise_error(outcome.error)
        return AccuseResponse(
            correct=outcome.correct,
            timeline=[
                TruthFact(fact_id=fact.id, text=fact.text)
                for fact in outcome.timeline
            ],
            missed_fact_ids=list(outcome.missed_fact_ids),
        )

    application.mount(
        "/",
        StaticFiles(directory=WEB_DIR, html=True),
        name="web",
    )
    return application


def _clue_public(clue: Clue) -> CluePublic:
    return CluePublic(id=clue.id, name=clue.name, desc=clue.desc)


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



app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)