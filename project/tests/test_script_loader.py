"""剧本加载与校验测试。"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import get_args

import pytest

from app.models import TOPICS, Script, Topic
from app.script_loader import (
    ScriptLoadError,
    ScriptValidationError,
    format_overview,
    load_script,
    main,
    parse_script,
)

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "scripts"
    / "mistvale-inn.json"
)


@pytest.fixture
def valid_data() -> dict:
    return copy.deepcopy(
        json.loads(SCRIPT_PATH.read_text(encoding="utf-8"))
    )


def _fact(data: dict, fact_id: str) -> dict:
    return next(fact for fact in data["facts"] if fact["id"] == fact_id)


def _role(data: dict, role_id: str) -> dict:
    return next(role for role in data["roles"] if role["id"] == role_id)


def _assert_issue(
    exc: ScriptValidationError,
    path: str,
    keyword: str,
) -> None:
    matched = [
        issue
        for issue in exc.issues
        if issue.path == path and keyword in issue.message
    ]
    assert matched, (
        f"未找到路径 {path!r} 且包含 {keyword!r} 的错误，实际错误：\n{exc}"
    )


def test_load_real_script() -> None:
    script = load_script(SCRIPT_PATH)

    assert isinstance(script, Script)
    assert script.id == "mistvale-inn"
    assert script.title == "雾镇旅馆"
    assert script.culprit == "r1"
    assert script.solution_path == ["f05", "f06", "f08", "f15", "f16"]
    assert len(script.roles) == 5
    assert len(script.facts) == 23
    assert len(script.clues) == 8
    assert script.victim.name == "陈守义"


def test_model_reads_actual_json_fields(valid_data: dict) -> None:
    script = parse_script(valid_data)

    culprit = next(role for role in script.roles if role.id == "r1")
    mistaken = next(fact for fact in script.facts if fact.id == "f03")
    clue = next(clue for clue in script.clues if clue.id == "c01")

    assert culprit.lie_propensity == 0.85
    assert culprit.relations["r5"].trust == 0.8
    assert mistaken.belief["r2"].startswith("那场争吵")
    assert mistaken.source_of_error == "r1"
    assert clue.from_ == "f05"


def test_fact_holders_define_knowledge_boundary() -> None:
    script = load_script(SCRIPT_PATH)
    facts = {fact.id: fact for fact in script.facts}

    assert "r4" not in facts["f08"].holders
    assert "r2" not in facts["f15"].holders
    assert "r3" in facts["f05"].holders


def test_culprit_must_be_existing_role(valid_data: dict) -> None:
    valid_data["culprit"] = "r9"

    with pytest.raises(ScriptValidationError) as raised:
        parse_script(valid_data)

    _assert_issue(raised.value, "culprit", "r9")


def test_solution_path_fact_must_exist(valid_data: dict) -> None:
    valid_data["solution_path"][2] = "f99"

    with pytest.raises(ScriptValidationError) as raised:
        parse_script(valid_data)

    _assert_issue(raised.value, "solution_path[2]", "f99")


def test_solution_path_fact_must_have_holder(valid_data: dict) -> None:
    _fact(valid_data, "f05")["holders"] = []

    with pytest.raises(ScriptValidationError) as raised:
        parse_script(valid_data)

    _assert_issue(raised.value, "facts[f05].holders", "持有者")


def test_role_must_hold_at_least_five_facts(valid_data: dict) -> None:
    for fact_id in ("f09", "f14", "f17", "f22", "f23"):
        _fact(valid_data, fact_id)["holders"].remove("r4")

    with pytest.raises(ScriptValidationError) as raised:
        parse_script(valid_data)

    _assert_issue(raised.value, "roles[r4]", "至少需要 5 条")


def test_relation_target_must_exist(valid_data: dict) -> None:
    _role(valid_data, "r1")["relations"]["r9"] = {
        "type": "陌生",
        "trust": 0.5,
    }

    with pytest.raises(ScriptValidationError) as raised:
        parse_script(valid_data)

    _assert_issue(
        raised.value,
        "roles[r1].relations.r9",
        "不存在的角色 id",
    )


def test_holder_must_be_existing_role(valid_data: dict) -> None:
    _fact(valid_data, "f01")["holders"].append("r9")

    with pytest.raises(ScriptValidationError) as raised:
        parse_script(valid_data)

    _assert_issue(raised.value, "facts[f01].holders", "r9")


def test_belief_target_must_exist(valid_data: dict) -> None:
    _fact(valid_data, "f03")["belief"]["r9"] = "错误版本"

    with pytest.raises(ScriptValidationError) as raised:
        parse_script(valid_data)

    _assert_issue(raised.value, "facts[f03].belief.r9", "r9")


def test_belief_holder_must_be_in_holders(valid_data: dict) -> None:
    _fact(valid_data, "f03")["belief"]["r1"] = "错误版本"

    with pytest.raises(ScriptValidationError) as raised:
        parse_script(valid_data)

    _assert_issue(raised.value, "facts[f03].belief.r1", "holders")


def test_belief_requires_source_of_error(valid_data: dict) -> None:
    del _fact(valid_data, "f03")["source_of_error"]

    with pytest.raises(ScriptValidationError) as raised:
        parse_script(valid_data)

    _assert_issue(
        raised.value,
        "facts[f03].source_of_error",
        "必须填写 source_of_error",
    )


def test_source_of_error_must_exist(valid_data: dict) -> None:
    _fact(valid_data, "f03")["source_of_error"] = "r9"

    with pytest.raises(ScriptValidationError) as raised:
        parse_script(valid_data)

    _assert_issue(raised.value, "facts[f03].source_of_error", "r9")


def test_clue_source_fact_must_exist(valid_data: dict) -> None:
    valid_data["clues"][0]["from"] = "f99"

    with pytest.raises(ScriptValidationError) as raised:
        parse_script(valid_data)

    _assert_issue(raised.value, "clues[c01].from", "f99")


def test_duplicate_fact_id(valid_data: dict) -> None:
    _fact(valid_data, "f02")["id"] = "f01"

    with pytest.raises(ScriptValidationError) as raised:
        parse_script(valid_data)

    _assert_issue(raised.value, "facts[f01]", "事实 id 重复：f01")


def test_duplicate_clue_id(valid_data: dict) -> None:
    valid_data["clues"][1]["id"] = "c01"

    with pytest.raises(ScriptValidationError) as raised:
        parse_script(valid_data)

    _assert_issue(raised.value, "clues[c01]", "线索 id 重复：c01")


def test_culprit_must_hold_two_solution_facts(valid_data: dict) -> None:
    _fact(valid_data, "f08")["holders"].append("r2")
    _fact(valid_data, "f15")["holders"].append("r2")
    for fact_id in ("f06", "f08", "f15"):
        _fact(valid_data, fact_id)["holders"].remove("r1")

    with pytest.raises(ScriptValidationError) as raised:
        parse_script(valid_data)

    _assert_issue(raised.value, "roles[r1]", "至少需要 2 条")


def test_pydantic_error_points_to_fact_and_field(valid_data: dict) -> None:
    _fact(valid_data, "f01")["sensitivity"] = 1.5

    with pytest.raises(ScriptValidationError) as raised:
        parse_script(valid_data)

    _assert_issue(
        raised.value,
        "facts[f01].sensitivity",
        "小于等于 1",
    )


def test_unknown_field_is_rejected(valid_data: dict) -> None:
    _role(valid_data, "r1")["nickname"] = "玉兰"

    with pytest.raises(ScriptValidationError) as raised:
        parse_script(valid_data)

    _assert_issue(
        raised.value,
        "roles[r1].nickname",
        "不允许的字段",
    )


def test_missing_required_field_is_rejected(valid_data: dict) -> None:
    del _fact(valid_data, "f01")["text"]

    with pytest.raises(ScriptValidationError) as raised:
        parse_script(valid_data)

    _assert_issue(
        raised.value,
        "facts[f01].text",
        "缺少必填字段",
    )


def test_top_level_must_be_object() -> None:
    with pytest.raises(ScriptValidationError) as raised:
        parse_script([])

    _assert_issue(raised.value, "$", "顶层必须是 JSON 对象")


def test_invalid_json_reports_line_and_column(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text('{"id": "x",}', encoding="utf-8")

    with pytest.raises(ScriptLoadError) as raised:
        load_script(path)

    message = str(raised.value)
    assert "第 1 行" in message
    assert str(path) in message


def test_missing_file_reports_path(tmp_path: Path) -> None:
    path = tmp_path / "missing.json"

    with pytest.raises(ScriptLoadError) as raised:
        load_script(path)

    assert "无法读取剧本文件" in str(raised.value)
    assert str(path) in str(raised.value)


def test_overview_contains_key_counts() -> None:
    script = load_script(SCRIPT_PATH)
    overview = format_overview(script)

    assert "雾镇旅馆（mistvale-inn） v1.0" in overview
    assert "真凶：沈玉兰（r1）" in overview
    assert "角色（5）" in overview
    assert "事实（23 条，破案链 5 条）" in overview
    assert "破案链：f05 -> f06 -> f08 -> f15 -> f16" in overview
    assert "线索（8 张）" in overview
    assert "校验：通过" in overview
    assert "r4" in overview


def test_cli_prints_overview(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["--script", str(SCRIPT_PATH)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "雾镇旅馆" in captured.out
    assert "校验：通过" in captured.out


def test_cli_returns_one_on_invalid_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{", encoding="utf-8")

    exit_code = main(["--script", str(path)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "剧本不是合法 JSON" in captured.err

def test_topic_values_match_schema() -> None:
    assert set(get_args(Topic)) == set(TOPICS)


def test_topic_value_must_be_known(valid_data: dict) -> None:
    _fact(valid_data, "f01")["topic"] = ["time", "money"]

    with pytest.raises(ScriptValidationError) as raised:
        parse_script(valid_data)

    _assert_issue(
        raised.value,
        "facts[f01].topic[1]",
        "只允许 time / weapon / motive / relation / event",
    )