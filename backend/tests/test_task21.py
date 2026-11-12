"""Task 21: 화면에서 찾은 서버 보완 — 상신 뒤 결재선 이유, 근거 단위, 시연 note, 지금 가능한 결정, 회신별 AI 해석."""
import json

import pytest

from app.ai.providers import FakeProvider
from app.engine import scenarios
from app.engine.flow import Engine
from app.store.db import open_db

ACCEPT = json.dumps({"stance": "수용", "qty_limit": None, "next_date": None, "needs_human": False,
                     "confidence": 0.9}, ensure_ascii=False)
UNSURE = json.dumps({"stance": "정보부족", "qty_limit": None, "next_date": None, "needs_human": True,
                     "confidence": 0.3}, ensure_ascii=False)


@pytest.fixture
def store(tmp_path):
    s = open_db(tmp_path / "t.db")
    yield s
    s.close()


def _eng(store, *responses):
    return Engine(store, provider=FakeProvider(list(responses) or [ACCEPT] * 6))


def _esc_case(store, upto):
    eng = _eng(store)
    cid = eng.seed("scenario_1_escalate")[0]
    eng.run_script("scenario_1_escalate", upto=upto)
    return eng, cid


# ---- 1. 상신 뒤 결재선 이유 ----

def test_상신_전에는_결재선_이유가_그대로(store):
    eng, cid = _esc_case(store, 2)
    hits = eng.case_evidence(cid)["rule"]["approver_hits"]
    assert "마케팅팀 전결" in hits[0]["text"] and not hits[0].get("superseded")
    assert not any(h.get("superseded") for h in hits)
    d = eng.case_detail(cid)["rule"]["hits"]
    assert "마케팅팀 전결" in d[0]["text"] and not d[0].get("superseded")


def test_상신_뒤에는_첫_줄이_상신_설명이고_원래_판정은_처음_판정(store):
    eng, cid = _esc_case(store, 3)
    hits = eng.case_evidence(cid)["rule"]["approver_hits"]
    assert hits[0]["rule_id"] == "escalation" and hits[0]["badge"] == "의견"
    assert "마케팅팀장" in hits[0]["text"] and "Masil 대표" in hits[0]["text"] and "승인 권고" in hits[0]["text"]
    assert "2026-09-04" in hits[0]["text"] or "9/4" in hits[0]["text"]
    assert hits[0]["detail"]["formula"] and hits[0]["detail"]["inputs"]
    old = [h for h in hits[1:] if "마케팅팀 전결" in h["text"]]
    assert old and all(h["superseded"] is True for h in old)
    d = eng.case_detail(cid)["rule"]["hits"]
    assert d[0]["rule_id"] == "escalation"
    assert any(h.get("superseded") for h in d[1:])


# ---- 2. 근거 값 단위 ----

def test_근거_값에_단위가_붙는다(store):
    eng = _eng(store)
    from app.engine import scenarios
    scenarios.register_plan(store, "PLAN-001")
    cid = eng.open_plan("PLAN-001")
    ev = eng.case_evidence(cid)
    sig = {s["key"]: s for s in ev["signals"]}
    assert sig["coupon_stacking"]["unit"] == "ratio"
    assert sig["slow_payment_channel"]["unit"] == "ratio"
    assert sig["forecast_gap"]["unit"] == "multiple"
    assert sig["spend_concentration"]["unit"] == "multiple"
    assert sig["channel_return_vs_benchmark"]["unit"] == "multiple"
    assert sig["trend"]["unit"] == "multiple"
    assert sig["cannibalization"]["value"] is None
    ki = {k["key"]: k for k in ev["key_indicators"]}
    assert ki["real_roas"]["unit"] == "multiple"
    assert ki["spend_share"]["unit"] == "percent" and ki["request_share"]["unit"] == "percent"
    assert ki["simple_change_return"]["unit"] == "ratio"
    assert ki["allocation_inversion"]["unit"] is None
    assert all(r["unit"] == "krw" for r in ev["cost_breakdown"]["rows"])
    assert ev["breakeven"]["unit"] == "ratio"


def test_장기_가치_신호에도_단위(store):
    from app.calc.evidence import evidence
    ev = evidence("contract", "INF-001", None)
    if ev["available"]:
        units = {s["key"]: s["unit"] for s in ev["signals"]}
        assert units == {"repurchase_rate": "ratio", "post_contribution": "krw"}


# ---- 3. 시연 기안 note ----

def test_건_상세에_시연_기안_note와_원본_기안(store):
    eng = _eng(store)
    cid = eng.seed("scenario_1_escalate")[0]
    case = eng.case_detail(cid)["case"]
    assert case["note"].startswith("시연용 가정") and case["source_plan_id"] == "PLAN-019"


def test_일반_기안은_note가_없다(store):
    from app.engine import scenarios
    eng = _eng(store)
    scenarios.register_plan(store, "PLAN-001")
    cid = eng.open_plan("PLAN-001")
    case = eng.case_detail(cid)["case"]
    assert case["note"] is None and "source_plan_id" in case


# ---- 4. 지금 가능한 결정과 막힌 이유 ----

def _scene2(store):
    """장면 1(재고 부족) 건: 물류 회신 뒤 SCM이 답하기 전."""
    eng = _eng(store)
    cid = eng.seed("scenario_1")[0]
    eng.run_script("scenario_1", upto=1)
    return eng, cid


def test_재고_부족이면_승인_막힘_분할_승인만(store):
    eng, cid = _scene2(store)
    v = eng.case_detail(cid, viewer="Masil 대표")["viewer"]
    assert "승인" not in v["actions"] and "분할승인" in v["actions"] and "거절" in v["actions"]
    blocked = {b["action"]: b["reason"] for b in v["blocked"]}
    assert "분할 승인만" in blocked["승인"]
    sp = v["split_preview"]
    assert sp["phase1_qty"] + sp["phase2_qty"] > 0
    # 실제 분할 승인 결과와 같다
    eng.decide(cid, "Masil 대표", "분할승인")
    eng.play(scenarios.load("scenario_1").script[1])  # SCM 전량 허용 -> 분할안 그대로라 확정
    f = store.get_case(cid)["facts"]
    assert sp["phase1_qty"] == f["phase1"]["qty"] and sp["phase1_date"] == f["phase1"]["date"]
    assert sp["phase1_amount_krw"] == eng._plan_amount_of(f, f["phase1"]["qty"])
    # 2차로 넘어가는 수량이 없는 분할안이면 확정 뒤에도 2차가 없다
    assert (sp["phase2_qty"] == 0 and f["phase2"] is None and sp["phase2_amount_krw"] == 0) or (
        sp["phase2_qty"] == f["phase2"]["qty"] and sp["phase2_date"] == f["phase2"]["date"]
        and sp["phase2_amount_krw"] == f["phase2"]["amount_krw"])


def test_SCM이_전량_허용하면_승인_가능(store):
    eng, cid = _scene2(store)
    eng.play(scenarios.load("scenario_1").script[1])  # 대본의 SCM 회신
    v = eng.case_detail(cid, viewer="Masil 대표")["viewer"]
    assert "승인" in v["actions"] and not [b for b in v["blocked"] if b["action"] == "승인"]


def test_승인권자가_아니면_actions가_비었다(store):
    eng, cid = _scene2(store)
    v = eng.case_detail(cid, viewer="물류 담당자")["viewer"]
    assert v["actions"] == [] and v["blocked"] == []


def test_회신_대기면_승인_막힘_이유(store):
    eng = _eng(store)
    cid = eng.seed("scenario_1")[0]
    v = eng.case_detail(cid, viewer="Masil 대표")["viewer"]
    blocked = {b["action"]: b["reason"] for b in v["blocked"]}
    assert "회신" in blocked["승인"] and "거절" in v["actions"] and "승인" not in v["actions"]


# ---- 5. 회신마다 자기 AI 해석 ----

def test_같은_글_회신이_두_번_와도_각자_자기_해석(store):
    eng = _eng(store, UNSURE, ACCEPT)
    cid = eng.seed("scenario_1")[0]
    req = store.list_requests(cid)[0]
    eng.reply(req["id"], "검토해 보겠습니다", 0)  # 사람 확인
    assert store.get_request(req["id"])["status"] == "사람 확인"
    eng.resolve_human_check(req["id"], "캠페인 담당자", "검토해 보겠습니다", 0)
    replies = eng.case_detail(cid)["requests"][0]["replies"]
    assert len(replies) == 2 and replies[0]["text"] == replies[1]["text"]
    j0, j1 = replies[0]["judgment"], replies[1]["judgment"]
    assert j0["stance"] == "정보부족" and j0["needs_human"] is True and j0["confidence"] == 0.3
    assert j1["stance"] == "수용" and j1["needs_human"] is False
    assert {"stance", "qty_limit", "next_date", "needs_human", "confidence", "model", "human_confirmed",
            "confirmed_by"} <= set(j0)
    assert j0["human_confirmed"] is True and j0["confirmed_by"] == "캠페인 담당자"
    assert j1["human_confirmed"] is True and j1["confirmed_by"] == "캠페인 담당자"


def test_사람_확인_전_회신은_확인_안_됨(store):
    eng = _eng(store, UNSURE)
    cid = eng.seed("scenario_1")[0]
    req = store.list_requests(cid)[0]
    eng.reply(req["id"], "검토해 보겠습니다", 0)
    j = eng.case_detail(cid)["requests"][0]["replies"][0]["judgment"]
    assert j["needs_human"] is True and j["human_confirmed"] is False and j["confirmed_by"] is None
