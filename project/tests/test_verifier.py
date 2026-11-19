"""草稿一致性校验测试。"""

from __future__ import annotations

from app.engine.verifier import verify_reply
from app.models import Role

ROLE = Role(
    id="r1",
    name="沈玉兰",
    public="老板娘",
    secret="三年前那场火是她忘了吹灭油灯引起的，前老板娘因此丧命",
    goal="让所有人相信火灾是意外",
    lie_propensity=0.85,
    alibi="我一直在房里",
    relations={},
)

ALLOWED = "23:00，阿蘅上楼送炭，看见沈玉兰从书房出来，右袖沾着灰"


def test_exact_time_passes() -> None:
    result = verify_reply(
        "23:00，我上楼送炭，看见她出来。",
        ALLOWED,
        ROLE,
    )

    assert result.ok is True
    assert result.reason is None


def test_vague_chinese_time_is_rejected() -> None:
    result = verify_reply(
        "十一点多吧，我看见她出来。",
        ALLOWED,
        ROLE,
    )

    assert result.ok is False
    assert "时间和事实不符" in (result.reason or "")


def test_different_time_is_rejected() -> None:
    result = verify_reply(
        "23:05，我看见她出来。",
        ALLOWED,
        ROLE,
    )

    assert result.ok is False
    assert "23:05" in (result.reason or "")


def test_fullwidth_colon_is_normalized() -> None:
    result = verify_reply(
        "23：00，我看见她出来。",
        ALLOWED,
        ROLE,
    )

    assert result.ok is True


def test_allowed_number_passes() -> None:
    result = verify_reply(
        "我挪用了三百大洋。",
        "周砚青挪用了旅馆三百大洋去填赌债",
        ROLE,
    )

    assert result.ok is True


def test_new_number_is_rejected() -> None:
    result = verify_reply(
        "我挪用了五百大洋。",
        "周砚青挪用了旅馆三百大洋去填赌债",
        ROLE,
    )

    assert result.ok is False
    assert "五百" in (result.reason or "")


def test_empty_reply_is_rejected() -> None:
    result = verify_reply("   ", ALLOWED, ROLE)

    assert result.ok is False
    assert "回答为空" in (result.reason or "")


def test_long_reply_is_rejected() -> None:
    result = verify_reply("啊" * 81, ALLOWED, ROLE)

    assert result.ok is False
    assert "80 字" in (result.reason or "")


def test_secret_leak_is_rejected() -> None:
    result = verify_reply(
        "三年前那场火是她忘了吹灭油灯引起的。",
        "22:50，沈玉兰抓起壁炉边的拨火棍，从背后打了陈守义",
        ROLE,
    )

    assert result.ok is False
    assert "秘密" in (result.reason or "")


def test_secret_overlap_allowed_by_given_fact_passes() -> None:
    result = verify_reply(ROLE.secret, ROLE.secret, ROLE)

    assert result.ok is True