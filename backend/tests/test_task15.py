"""Task 15: 시연용 기안(demo_plans) — 마케팅팀장 상신 시연."""
import json
import shutil
import sys
from pathlib import Path

import pytest

from app import config
from app.ai.providers import FakeProvider
from app.engine import scenarios
from app.engine.flow import Engine
from app.store.db import open_db

sys.path.insert(0, str(Path(__file__).parent))
from test_flow_11b import ACCEPT  # noqa: E402


@pytest.fixture
def store(tmp_path):
    s = open_db(tmp_path / "t.db")
    yield s
    s.close()


def _write(tmp_path, demo_plans, plans=("DEMO-PLAN-001",), script=()):
    body = {"title": "t", "description": "d", "plans": list(plans), "contracts": [], "requests": [],
            "demo_plans": demo_plans, "script": list(script)}
    (tmp_path / "x.json").write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    shutil.copy(config.demo_dir() / "people.json", tmp_path / "people.json")
    return tmp_path


GOOD = {"id": "DEMO-PLAN-001", "base": "PLAN-019", "override": {"requested_budget_krw": 5000000}, "note": "시연용 가정: 금액을 낮춤"}


def test_시연_기안은_원본을_복사하고_override만_바꿔_시연_출처로_등록된다(store, tmp_path):
    eng = Engine(store, provider=FakeProvider([ACCEPT]), demo_dir=_write(tmp_path, [GOOD]))
    eng.seed("x")
    row = store.get_plan("DEMO-PLAN-001")
    assert row["origin"] == "시연" and row["requested_budget_krw"] == 5000000
    assert row["campaign_id"] == "CMP-0005" and row["expected_gmv_krw"] == 50082515  # base 그대로
    assert row["raw"]["note"] == "시연용 가정: 금액을 낮춤"
    with pytest.raises(KeyError):
        store.get_plan("PLAN-019")  # 원본 기안은 불러오지 않았다(등록부에 안 넣음)


def test_초기화하면_시연_기안이_지워진다(store, tmp_path):
    eng = Engine(store, provider=FakeProvider([ACCEPT]), demo_dir=_write(tmp_path, [GOOD]))
    eng.seed("x")
    store.reset("시연")
    with pytest.raises(KeyError):
        store.get_plan("DEMO-PLAN-001")


@pytest.mark.parametrize("bad", [
    {**GOOD, "base": "PLAN-999"},
    {**GOOD, "id": "PLAN-019"},
    {**GOOD, "override": {"모르는키": 1}},
    {**GOOD, "override": {"plan_id": "X"}},
    {**GOOD, "override": {"settlement_date": "내일"}},
    {**GOOD, "note": " "},
    {k: v for k, v in GOOD.items() if k != "note"},
])
def test_시연_기안_형식_오류는_거부(tmp_path, bad):
    with pytest.raises(ValueError):
        scenarios.load("x", _write(tmp_path, [bad]))


def test_같은_id_두_번은_거부(tmp_path):
    with pytest.raises(ValueError, match="겹침|중복"):
        scenarios.load("x", _write(tmp_path, [GOOD, GOOD]))


def test_운영_모드에서는_시연_기안을_불러올_수_없다(store, tmp_path):
    eng = Engine(store, provider=FakeProvider([]), demo_dir=_write(tmp_path, [GOOD]))
    store.set_mode("운영")
    with pytest.raises(PermissionError):
        eng.seed("x")


def test_상신_전_건_화면에서_마케팅팀장이_상신할_수_있다(store):
    eng = Engine(store, provider=FakeProvider([ACCEPT, ACCEPT]))
    (cid,) = eng.seed("scenario_1_escalate")
    d = eng.case_detail(cid, "마케팅팀장")
    assert d["rule"]["approvers"] == ["마케팅팀"] and d["viewer"]["can_escalate"] is True
    assert d["viewer"]["can_decide"] is True
    plan = store.get_plan(d["case"]["ref_id"])
    assert plan["origin"] == "시연" and plan["raw"]["note"].startswith("시연용 가정")
