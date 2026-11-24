"""玩家评分与意见反馈接口测试。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def test_feedback_summary_empty(tmp_path: Path) -> None:
    app = create_app(feedback_path=tmp_path / "feedback.jsonl")
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
    app = create_app(feedback_path=store)
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
    app = create_app(feedback_path=tmp_path / "feedback.jsonl")
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
