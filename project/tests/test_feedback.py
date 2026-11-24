"""玩家评分与意见反馈接口测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import feedback
from app.main import create_app


def test_feedback_summary_empty(tmp_path: Path) -> None:
    app = create_app(
        feedback_path=tmp_path / "feedback.jsonl",
        feedback_cooldown_seconds=0,
    )
    client = TestClient(app)
    res = client.get("/blood/feedback/summary")
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 0
    assert body["avg_rating"] == 0.0
    assert body["recent"] == []
    assert body["distribution"] == {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}


def test_feedback_submit_and_aggregate(tmp_path: Path) -> None:
    store = tmp_path / "feedback.jsonl"
    app = create_app(feedback_path=store, feedback_cooldown_seconds=0)
    client = TestClient(app)

    r1 = client.post(
        "/blood/feedback",
        json={
            "rating": 5,
            "comment": "亡者票翻盘太爽了",
            "nickname": "北邮路人",
            "game_id": "g1",
            "role": "镇民",
            "outcome": "好人胜",
            "day": 2,
        },
    )
    assert r1.status_code == 200
    assert r1.json() == {"ok": True, "count": 1, "avg_rating": 5.0}

    r2 = client.post(
        "/blood/feedback",
        json={"rating": 4, "comment": "  手机上也挺流畅  "},
    )
    assert r2.status_code == 200
    assert r2.json() == {"ok": True, "count": 2, "avg_rating": 4.5}

    summary = client.get("/blood/feedback/summary").json()
    assert summary["count"] == 2
    assert summary["avg_rating"] == 4.5
    assert summary["distribution"]["5"] == 1
    assert summary["distribution"]["4"] == 1
    assert len(summary["recent"]) == 2
    assert summary["recent"][0]["nickname"] == "匿名旅客"
    assert summary["recent"][0]["comment"] == "手机上也挺流畅"
    assert summary["recent"][1]["nickname"] == "北邮路人"


def test_feedback_validation_rejects_bad_rating_and_extra_fields(
    tmp_path: Path,
) -> None:
    app = create_app(
        feedback_path=tmp_path / "feedback.jsonl",
        feedback_cooldown_seconds=0,
    )
    client = TestClient(app)

    assert client.post("/blood/feedback", json={"rating": 0}).status_code == 422
    assert client.post("/blood/feedback", json={"rating": 6}).status_code == 422
    assert (
        client.post(
            "/blood/feedback",
            json={"rating": 5, "unknown_field": "x"},
        ).status_code
        == 422
    )


def test_feedback_rate_limit_returns_429(tmp_path: Path) -> None:
    store = tmp_path / "feedback.jsonl"
    client = TestClient(
        create_app(feedback_path=store, feedback_cooldown_seconds=10.0)
    )

    first = client.post("/blood/feedback", json={"rating": 5})
    assert first.status_code == 200
    assert first.json()["count"] == 1

    second = client.post("/blood/feedback", json={"rating": 1})
    assert second.status_code == 429
    assert second.json() == {"detail": "提交太快了，请稍后再试"}

    persisted = [json.loads(line) for line in store.read_text("utf-8").splitlines()]
    assert len(persisted) == 1
    assert persisted[0]["rating"] == 5

    other_ip = client.post(
        "/blood/feedback",
        json={"rating": 3},
        headers={"X-Forwarded-For": "203.0.113.7, 10.0.0.1"},
    )
    assert other_ip.status_code == 200
    assert other_ip.json() == {"ok": True, "count": 2, "avg_rating": 4.0}

    # 首段为空时回落到 request.client.host，仍处于冷却窗口内
    blank_forwarded = client.post(
        "/blood/feedback",
        json={"rating": 2},
        headers={"X-Forwarded-For": ", 10.1.1.1"},
    )
    assert blank_forwarded.status_code == 429

    assert len(store.read_text("utf-8").splitlines()) == 2

    # cooldown <= 0 时完全跳过限流，连续提交都通过
    open_client = TestClient(
        create_app(feedback_path=tmp_path / "open.jsonl", feedback_cooldown_seconds=0)
    )
    codes = [
        open_client.post("/blood/feedback", json={"rating": rating}).status_code
        for rating in (5, 4, 3)
    ]
    assert codes == [200, 200, 200]
    recent = open_client.get("/blood/feedback/summary").json()["recent"]
    assert [entry["rating"] for entry in recent] == [3, 4, 5]


def test_feedback_outcome_normalized_on_write_path(tmp_path: Path) -> None:
    store = tmp_path / "feedback.jsonl"
    client = TestClient(
        create_app(feedback_path=store, feedback_cooldown_seconds=0)
    )

    submitted = ["murderer", "evil", "good", "villagers", "MURDERER", "x"]
    for raw in submitted:
        assert (
            client.post(
                "/blood/feedback",
                json={"rating": 4, "outcome": raw},
            ).status_code
            == 200
        )

    persisted = [
        json.loads(line)["outcome"] for line in store.read_text("utf-8").splitlines()
    ]
    assert persisted == ["凶手胜", "凶手胜", "好人胜", "好人胜", "凶手胜", ""]

    recent = client.get("/blood/feedback/summary").json()["recent"]
    assert [entry["outcome"] for entry in reversed(recent)] == persisted


def test_feedback_outcome_normalized_on_read_path(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.jsonl"
    records = [
        {"rating": 4, "comment": "旧记录一", "outcome": "murderer"},
        {"rating": 5, "comment": "旧记录二", "outcome": "x"},
        {"rating": 3, "comment": "旧记录三", "outcome": "villagers"},
        {"rating": 2, "comment": "旧记录四", "outcome": "夜晚"},
    ]
    legacy.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records),
        encoding="utf-8",
    )
    client = TestClient(
        create_app(feedback_path=legacy, feedback_cooldown_seconds=0)
    )

    recent = client.get("/blood/feedback/summary").json()["recent"]
    assert [entry["outcome"] for entry in recent] == ["夜晚", "好人胜", "", "凶手胜"]


def test_normalize_outcome_whitelist_and_aliases() -> None:
    for label in feedback.OUTCOME_LABELS:
        assert feedback.normalize_outcome(label) == label

    assert feedback.normalize_outcome("  murderer  ") == "凶手胜"
    assert feedback.normalize_outcome("EVIL") == "凶手胜"
    assert feedback.normalize_outcome("Good") == "好人胜"
    assert feedback.normalize_outcome("villagers") == "好人胜"

    assert feedback.normalize_outcome("x") == ""
    assert feedback.normalize_outcome("村民胜") == ""
    assert feedback.normalize_outcome("") == ""
    assert feedback.normalize_outcome(None) == ""
    assert feedback.normalize_outcome(0) == ""

    # 幂等：对归一化结果再次归一化，值保持不变
    for raw in ("murderer", "good", "x", "夜晚"):
        once = feedback.normalize_outcome(raw)
        assert feedback.normalize_outcome(once) == once

def test_feedback_summary_skips_damaged_history(tmp_path: Path) -> None:
    store = tmp_path / "damaged.jsonl"
    store.write_text(
        "\nnot-json\n"
        + json.dumps({"rating": 9, "comment": "越界", "outcome": "murderer"})
        + "\n"
        + json.dumps({"rating": 4, "comment": "有效", "outcome": "good"})
        + "\n",
        encoding="utf-8",
    )
    client = TestClient(
        create_app(feedback_path=store, feedback_cooldown_seconds=0)
    )

    body = client.get("/blood/feedback/summary").json()
    assert body["count"] == 1
    assert body["avg_rating"] == 4.0
    assert body["recent"] == [
        {
            "created_at": "",
            "rating": 4,
            "comment": "有效",
            "nickname": "匿名旅客",
            "outcome": "好人胜",
            "day": 0,
        }
    ]


def test_resolve_feedback_path_prefers_override_then_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    explicit = tmp_path / "explicit.jsonl"
    env_path = tmp_path / "env.jsonl"
    monkeypatch.setenv("FEEDBACK_FILE", str(env_path))

    assert feedback.resolve_feedback_path(explicit) == explicit
    assert feedback.resolve_feedback_path() == env_path

    monkeypatch.setenv("FEEDBACK_FILE", "   ")
    assert feedback.resolve_feedback_path() == feedback.DEFAULT_FEEDBACK_PATH