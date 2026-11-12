"""Task 16: 건 근거 상세(GET /api/cases/{id}/evidence). 장면 숫자는 이 시험에만 둔다."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import policy
from app.ai.providers import FakeProvider
from app.api.main import create_app
from app.calc.signals import risk_signals
from app.engine import scenarios
from app.engine.flow import Engine
from app.store.db import open_db

sys.path.insert(0, str(Path(__file__).parent))
from test_flow_11b import ACCEPT  # noqa: E402

LINE_KEYS = {"formula", "inputs", "sources", "policies"}


@pytest.fixture
def store(tmp_path):
    s = open_db(tmp_path / "t.db")
    yield s
    s.close()


def _eng(store):
    return Engine(store, provider=FakeProvider([ACCEPT, ACCEPT, ACCEPT, ACCEPT]))


def _open_plan(store, plan_id):
    eng = _eng(store)
    scenarios.register_plan(store, plan_id)
    return eng, eng.open_plan(plan_id)


def _by_key(lines):
    return {x["key"]: x for x in lines}


def _check_detail(d):
    assert set(d) == LINE_KEYS
    assert d["formula"]
    for i in d["inputs"]:
        assert set(i) == {"label", "value"}
    for p in d["policies"]:
        assert set(p) == {"key", "value", "source", "description"}
        assert policy.get(p["key"]) == p["value"]


def test_혜인_기안_PLAN001_근거(store):
    eng, cid = _open_plan(store, "PLAN-001")
    ev = eng.case_evidence(cid)
    assert ev["available"] is True and ev["reason"] is None
    assert len(ev["signals"]) == 7
    sig = _by_key(ev["signals"])
    assert set(sig) == {s.key for s in risk_signals("PLAN-001")}
    for s in ev["signals"]:
        assert {"key", "label", "value", "compare", "level", "badge", "judgment", "exclude_reason", "detail"} <= set(s)
        _check_detail(s["detail"])
        assert s["detail"]["sources"], s["key"]
        if s["badge"] == "가정":
            assert s["detail"]["policies"], s["key"]
    assert sig["forecast_gap"]["judgment"] == "참고" and sig["forecast_gap"]["exclude_reason"]
    assert {p["key"] for p in sig["spend_concentration"]["detail"]["policies"]} == {"signals.hhi_limit"}
    assert {p["key"] for p in sig["channel_return_vs_benchmark"]["detail"]["policies"]} == {"signals.return_ratio_red"}
    assert sig["coupon_stacking"]["detail"]["inputs"]
    assert all(p["key"] for s in ev["signals"] for p in s["detail"]["policies"])
    # 쓰인 정책이 있는 줄은 근거·설명이 정책 파일 값 그대로
    hhi = sig["spend_concentration"]["detail"]["policies"][0]
    assert hhi["source"] == policy.entry("signals.hhi_limit")[1] and hhi["value"] == 1800


def test_혜인_핵심_지표(store):
    eng, cid = _open_plan(store, "PLAN-001")
    k = _by_key(eng.case_evidence(cid)["key_indicators"])
    assert round(k["real_roas"]["value"], 3) == -0.198 and k["real_roas"]["rank"] == 9 and k["real_roas"]["of"] == 10
    assert round(k["spend_share"]["value"], 1) == 40.6 and k["spend_share"]["rank"] == 1
    assert k["allocation_inversion"]["value"] is True
    assert round(k["simple_change_return"]["value"], 4) == 0.0358
    assert round(k["simple_change_return"]["compare_value"], 4) == 0.0175
    for line in k.values():
        _check_detail(line["detail"])
        assert line["detail"]["sources"]


def test_혜인_비용_분해(store):
    eng, cid = _open_plan(store, "PLAN-001")
    cb = eng.case_evidence(cid)["cost_breakdown"]
    assert "곱하지 않" in cb["note"]
    rows = _by_key(cb["rows"])
    assert [r["key"] for r in cb["rows"]] == ["gmv", "pre_marketing", "influencer_fee", "other_media", "after_fee", "final"]
    assert rows["gmv"]["amount"] == 422424676 and rows["pre_marketing"]["amount"] == 248666838
    assert rows["final"]["amount"] == -61308789
    for r in cb["rows"]:
        assert r["badge"] == "계산"
        _check_detail(r["detail"])
        assert r["detail"]["sources"]


def test_본전_조건과_측정_한계(store):
    eng, cid = _open_plan(store, "PLAN-001")
    ev = eng.case_evidence(cid)
    assert ev["breakeven"]["key"] == "breakeven_hidden_sales"
    _check_detail(ev["breakeven"]["detail"])
    assert ev["breakeven"]["detail"]["sources"]
    assert "마지막 클릭" in ev["attribution_note"]


def test_결재선_이유와_지표_반대_근거_줄에_detail(store):
    eng, cid = _open_plan(store, "PLAN-001")
    rule = eng.case_evidence(cid)["rule"]
    assert rule["approver_hits"] and rule["indicator_hits"]
    for h in rule["approver_hits"] + rule["indicator_hits"]:
        assert {"rule_id", "text", "source", "badge"} <= set(h)
        _check_detail(h["detail"])
    for h in rule["approver_hits"]:
        if h["rule_id"] == "covenant_window":
            assert {p["key"] for p in h["detail"]["policies"]} == {"cash.horizon_days"}
            assert h["detail"]["sources"]
    # 지표 반대 근거는 신호 줄의 detail을 따른다
    sig = _by_key(eng.case_evidence(cid)["signals"])
    for h in rule["indicator_hits"]:
        if h["rule_id"] in sig:
            assert h["detail"]["formula"] == sig[h["rule_id"]]["detail"]["formula"]


def test_옛_저장_행처럼_detail이_없어도_읽힌다(store):
    eng, cid = _open_plan(store, "PLAN-001")
    case = store.get_case(cid)
    f = case["facts"]
    for key in ("approver_hits", "indicator_hits"):
        f[key] = [{k: v for k, v in h.items() if k != "detail"} for h in f[key]]
    store.update_facts(cid, f, "시험", "옛 형식으로 되돌림")
    ev = eng.case_evidence(cid)
    for h in ev["rule"]["approver_hits"] + ev["rule"]["indicator_hits"]:
        _check_detail(h["detail"])


def test_장면1_PLAN019_신호_7개와_detail(store):
    eng, cid = _open_plan(store, "PLAN-019")
    ev = eng.case_evidence(cid)
    assert len(ev["signals"]) == 7
    for s in ev["signals"]:
        _check_detail(s["detail"])
        assert s["detail"]["sources"]
        if s["badge"] == "가정":
            assert s["detail"]["policies"]
    assert round(_by_key(ev["key_indicators"])["real_roas"]["value"], 3) == 3.703  # 1위 인플루언서


def test_전속계약_건은_미래_가치_지표(store):
    eng = _eng(store)
    scenarios.register_contract(store, "INF-001")
    cid = eng.open_contract("INF-001")
    ev = eng.case_evidence(cid)
    assert ev["available"] is True
    assert [s["key"] for s in ev["signals"]] == ["repurchase_rate", "post_contribution"]
    for s in ev["signals"]:
        _check_detail(s["detail"])
        assert s["detail"]["sources"]
    assert {p["key"] for p in _by_key(ev["signals"])["repurchase_rate"]["detail"]["policies"]} == {"split.stop_z"}
    assert ev["cost_breakdown"]["rows"][0]["amount"] == 422424676
    assert round(_by_key(ev["key_indicators"])["real_roas"]["value"], 3) == -0.198
    assert ev["breakeven"]["key"] == "breakeven_hidden_sales"
    assert ev["rule"]["approver_hits"]


def test_원본에_없는_기안은_묶음을_비우고_이유를_준다(store):
    eng = _eng(store)
    store.add_plan({"plan_id": "NEW-1", "campaign_id": "C", "requested_budget_krw": 7,
                    "settlement_date": "2030-01-02", "contract_deadline": "2030-01-01"}, "담당자")
    cid = eng.open_plan("NEW-1")
    ev = eng.case_evidence(cid)
    assert ev["available"] is False
    assert ev["reason"] == "원본 기안 파일에 없는 기안이라 지표 근거 없음"
    assert ev["signals"] == [] and ev["key_indicators"] == [] and ev["cost_breakdown"] is None
    assert ev["breakeven"] is None and ev["attribution_note"] is None
    # 결재선 이유는 규칙 근거라 그대로 나온다
    assert ev["rule"]["approver_hits"]


def test_시연_기안은_base_원본_기안으로_계산된다(store):
    eng = Engine(store, provider=FakeProvider([ACCEPT, ACCEPT]))
    (cid,) = eng.seed("scenario_1_escalate")
    assert store.get_case(cid)["ref_id"].startswith("DEMO-")
    ev = eng.case_evidence(cid)
    assert ev["available"] is True
    base = {s.key: s.value for s in risk_signals("PLAN-019")}
    assert {s["key"]: s["value"] for s in ev["signals"]} == base


def test_API_200과_404(store):
    eng, cid = _open_plan(store, "PLAN-001")
    c = TestClient(create_app(store, eng))
    r = c.get(f"/api/cases/{cid}/evidence")
    assert r.status_code == 200 and len(r.json()["signals"]) == 7
    assert c.get("/api/cases/99999/evidence").status_code == 404


def test_한도_규칙_줄은_쓴_정책_키를_담는다():
    from datetime import date

    from app.rules.approver import decide_contract, decide_plan
    from app.rules.models import ContractFacts, PlanFacts

    item, total = policy.get("approval.item_limit_krw"), policy.get("approval.total_limit_krw")
    day = date(2030, 1, 10)
    over = decide_plan(PlanFacts("P", "C", "I", item + 1, total + 1, day, day, "확대", True), [])
    keys = {h.rule_id: set(h.detail["policy_keys"]) for h in over.hits}
    assert keys["plan_item_over_limit"] == {"approval.item_limit_krw"}
    assert keys["plan_total_over_limit"] == {"approval.total_limit_krw"}
    within = decide_plan(PlanFacts("P", "C", "I", 1, 1, day, day, "확대", True), [])
    assert set(within.hits[0].detail["policy_keys"]) == {"approval.item_limit_krw", "approval.total_limit_krw"}
    c = decide_contract(ContractFacts("I", policy.get("approval.contract_limit_krw") + 1, day, day, "갱신", True), [])
    assert set(c.hits[0].detail["policy_keys"]) == {"approval.contract_limit_krw"}


# ---- 수정 회차 1 ----
def test_배분_역전은_기안_요청_비중_순위로_본다(store):
    """M1: 요청 비중 = 원본 기안 파일의 인플루언서별 요청액 합 ÷ 기안 총액(INF-001: 50,690,961 / 180,803,272)."""
    eng, cid = _open_plan(store, "PLAN-001")
    k = _by_key(eng.case_evidence(cid)["key_indicators"])
    req = k["request_share"]
    assert round(req["value"], 2) == 28.04 and req["rank"] == 1 and req["of"] == 10
    assert k["spend_share"]["rank"] == 1 and round(k["spend_share"]["value"], 1) == 40.6  # 광고비 비중 줄은 따로 남는다
    inv = k["allocation_inversion"]
    assert inv["value"] is True and inv["badge"] == "가정"
    assert {p["key"] for p in inv["detail"]["policies"]} == {"signals.reversal_cut"}
    assert policy.get("signals.reversal_cut") == 0.5
    assert policy.entry("signals.reversal_cut")[1].startswith("가정")
    inputs = {i["label"]: i["value"] for i in inv["detail"]["inputs"]}
    assert inputs["기안 요청 비중 순위"] == 1 and inputs["실질 ROAS 순위"] == 9
    assert "mkt_budget_plan_ms.csv" in " ".join(inv["detail"]["sources"])


def test_배분_역전_경계는_정책을_따른다(store):
    eng, cid = _open_plan(store, "PLAN-001")
    policy.set_overrides({"signals.reversal_cut": (0.05, "시험", "2030-01-01")})  # 상위 5% = 10명 중 0.5위 이내 -> 1위도 밖
    try:
        k = _by_key(eng.case_evidence(cid)["key_indicators"])
        assert k["allocation_inversion"]["value"] is False
    finally:
        policy.clear_overrides()


def test_2차_결재선_이유도_나온다(store):
    eng, cid = _open_plan(store, "PLAN-001")
    assert eng.case_evidence(cid)["rule"]["phase2_approver_hits"] == []
    f = store.get_case(cid)["facts"]
    f["phase2_approver_hits"] = [{"rule_id": "x2", "text": "2차 이유", "source": "s", "badge": "계산",
                                  "detail": {"formula": "f", "inputs": [], "sources": [], "policy_keys": ["cash.horizon_days"]}}]
    store.update_facts(cid, f, "시험", "2차 결재선")
    h = eng.case_evidence(cid)["rule"]["phase2_approver_hits"][0]
    assert h["stage"] == "2차" and h["rule_id"] == "x2"
    _check_detail(h["detail"])
    assert {p["key"] for p in h["detail"]["policies"]} == {"cash.horizon_days"}


def test_case_detail에는_풀리지_않은_policy_keys가_없다(store):
    eng, cid = _open_plan(store, "PLAN-001")
    d = eng.case_detail(cid)
    hits = (d["facts"]["approver_hits"] + d["facts"]["indicator_hits"] + d["rule"]["hits"]
            + d["evidence"]["indicators"]["hits"])
    assert hits and all("detail" not in h for h in hits)
    assert "policy_keys" not in str(d)
    assert eng.case_evidence(cid)["rule"]["approver_hits"][0]["detail"]["formula"]  # 저장본은 그대로


def test_결제_지연_줄_sources에_캠페인_마스터(store):
    eng, cid = _open_plan(store, "PLAN-001")
    sig = _by_key(eng.case_evidence(cid)["signals"])
    assert "02_masil/master/m_campaign_ms.csv" in sig["slow_payment_channel"]["detail"]["sources"]


def _all_sources(ev):
    out = []

    def walk(x):
        if isinstance(x, dict):
            if "sources" in x:
                out.extend(x["sources"])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(ev)
    return out


@pytest.mark.parametrize("plan_id", ["PLAN-001", "PLAN-019"])
def test_모든_sources_경로는_실제_파일(store, plan_id):
    from app.config import data_root
    eng, cid = _open_plan(store, plan_id)
    srcs = _all_sources(eng.case_evidence(cid))
    assert len(srcs) > 20
    root = data_root()
    for s in set(srcs):
        assert (root / s).is_file(), s
