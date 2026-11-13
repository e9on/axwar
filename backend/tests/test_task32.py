"""Task 32: 근거 줄마다 쉬운 말 설명(explain). 장면 숫자는 이 시험에만 둔다."""
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.ai.providers import FakeProvider
from app.api.main import create_app
from app.calc import explain
from app.engine import scenarios
from app.engine.flow import Engine
from app.store.db import open_db

sys.path.insert(0, str(Path(__file__).parent))
from test_flow_11b import ACCEPT  # noqa: E402

WORD = {"red": "나빠요", "yellow": "주의가 필요해요", "green": "좋아요", "unmeasurable": "잴 수 없어요"}
FORBIDDEN = ("z=", "HHI", "DSO", "covenant", "🔴", "🟡", "ROAS 괴리", "forecast_gap", "coupon_stacking")
NOTE = "이 값은 예상치라 결정에는 쓰지 않아요."


@pytest.fixture
def store(tmp_path):
    s = open_db(tmp_path / "t.db")
    yield s
    s.close()


def _eng(store):
    return Engine(store, provider=FakeProvider([ACCEPT, ACCEPT, ACCEPT, ACCEPT]))


def _plan_ev(store, plan_id):
    eng = _eng(store)
    scenarios.register_plan(store, plan_id)
    cid = eng.open_plan(plan_id)
    return eng, cid, eng.case_evidence(cid)


def _contract_ev(store):
    eng = _eng(store)
    scenarios.register_contract(store, "INF-001")
    cid = eng.open_contract("INF-001")
    return eng, cid, eng.case_evidence(cid)


def _all_lines(ev):
    out = list(ev["signals"]) + list(ev["key_indicators"]) + list(ev["cost_breakdown"]["rows"] if ev["cost_breakdown"] else [])
    if ev["breakeven"]:
        out.append(ev["breakeven"])
    for k in ("approver_hits", "indicator_hits", "phase2_approver_hits"):
        out += ev["rule"][k]
    return out


def _check_plain(text):
    assert isinstance(text, str) and text.strip()
    for bad in FORBIDDEN:
        assert bad not in text, (bad, text)
    assert not re.search(r"\d\.\d{3}", text), text  # 날 소수(0.023 같은)가 없다
    assert not re.search(r"[a-z]+_[a-z_]+", text), text  # 영문 키가 없다


def test_모든_줄에_explain이_있고_내부_용어가_없다(store):
    for make in (lambda: _plan_ev(store, "PLAN-001"), lambda: _plan_ev(store, "PLAN-019")):
        _, _, ev = make()
        store.reset()
        lines = _all_lines(ev)
        assert len(lines) >= 20
        for x in lines:
            _check_plain(x["explain"])
    _, _, ev = _contract_ev(store)
    for x in _all_lines(ev):
        _check_plain(x["explain"])


def test_신호_줄의_결론_낱말은_level과_맞는다(store):
    for pid in ("PLAN-001", "PLAN-019"):
        _, _, ev = _plan_ev(store, pid)
        store.reset()
        for s in ev["signals"] + [ev["breakeven"]]:
            text = s["explain"].replace(NOTE, "").strip()
            assert text.endswith(WORD[s["level"]] + "."), (s["key"], s["level"], text)
            for lvl, w in WORD.items():
                if lvl != s["level"]:
                    assert w not in text, (s["key"], w, text)
    _, _, ev = _contract_ev(store)
    for s in ev["signals"]:
        assert s["explain"].rstrip(".").endswith(WORD[s["level"]]), (s["key"], s["explain"])


def test_혜인_PLAN001_핵심_문장(store):
    _, _, ev = _plan_ev(store, "PLAN-001")
    sig = {s["key"]: s["explain"] for s in ev["signals"]}
    assert sig["coupon_stacking"] == ("혜인 캠페인 주문 100건 중 약 18건에 쿠폰이 겹쳐 쓰였어요. "
                                      "다른 인플루언서는 100건 중 약 2건 꼴이라 훨씬 많아서 나빠요.")
    assert sig["channel_return_vs_benchmark"] == "라이브 채널 평균 반품률이 13.0%인데 혜인도 13.0%라 평균 수준이어서 좋아요."
    assert sig["trend"] == ("첫 캠페인보다 마지막 캠페인의 실질 ROAS(광고비 1원당 남긴 이익)가 0.02 낮아져서 "
                            "개선되지 않고 있어요. 주의가 필요해요.")
    assert sig["forecast_gap"].endswith(NOTE) and "나빠요" in sig["forecast_gap"]
    assert "업계 평균 회수 기간 55일" in sig["slow_payment_channel"] and sig["slow_payment_channel"].endswith("나빠요.")
    assert "광고비가 한쪽에 몰린 정도" in sig["spend_concentration"] and "약 41%" in sig["spend_concentration"]
    assert sig["cannibalization"].endswith("잴 수 없어요.")


def test_PLAN019_좋은_쪽_문장(store):
    _, _, ev = _plan_ev(store, "PLAN-019")
    sig = {s["key"]: s["explain"] for s in ev["signals"]}
    assert "100건 중 0건" in sig["coupon_stacking"] and "100건 중 약 6건" in sig["coupon_stacking"]
    assert sig["coupon_stacking"].endswith("좋아요.")
    assert sig["channel_return_vs_benchmark"].startswith("자사몰 채널 평균 반품률이 8.5%인데")
    assert "3.2%" in sig["channel_return_vs_benchmark"] and "낮아서 좋아요" in sig["channel_return_vs_benchmark"]
    assert "좋아져서 좋아요" in sig["trend"] or "개선되고 있어서 좋아요" in sig["trend"]
    assert sig["spend_concentration"].endswith("좋아요.")


def test_핵심_지표_문장(store):
    _, _, ev = _plan_ev(store, "PLAN-001")
    ki = {x["key"]: x["explain"] for x in ev["key_indicators"]}
    assert "10명 중 9위" in ki["real_roas"] and ki["real_roas"].endswith("나빠요.")
    assert "10명 중 1위" in ki["spend_share"] and "41%" in ki["spend_share"]
    assert "28%" in ki["request_share"]
    assert "요청은 많은데 성과는 낮은" in ki["allocation_inversion"] and ki["allocation_inversion"].endswith("나빠요.")
    assert "3.6%" in ki["simple_change_return"] and "1.7%" in ki["simple_change_return"]
    store.reset()
    _, _, ev2 = _plan_ev(store, "PLAN-019")
    ki2 = {x["key"]: x["explain"] for x in ev2["key_indicators"]}
    assert ki2["real_roas"].endswith("좋아요.") and ki2["allocation_inversion"].endswith("좋아요.")
    assert ki2["simple_change_return"].endswith("좋아요.")


def test_비용_분해는_앞_단계와_이어진다(store):
    _, _, ev = _plan_ev(store, "PLAN-001")
    rows = {r["key"]: r["explain"] for r in ev["cost_breakdown"]["rows"]}
    assert rows["pre_marketing"] == "매출 약 4억 2,200만 원에서 반품·원가·수수료·배송비를 빼면 약 2억 4,900만 원이 남아요."
    assert rows["influencer_fee"].startswith("그중 인플루언서에게 준 피는 약 1억 6,100만 원")
    assert "약 1억 4,900만 원" in rows["other_media"]
    assert "약 8,750만 원이 남아요" in rows["after_fee"]
    assert "약 6,130만 원 모자라" in rows["final"] and rows["final"].endswith("나빠요.")
    assert rows["gmv"].startswith("혜인 캠페인으로 팔린 매출은 약 4억 2,200만 원")


def test_본전_문장(store):
    _, _, ev = _plan_ev(store, "PLAN-001")
    assert "약 25%" in ev["breakeven"]["explain"] and ev["breakeven"]["explain"].endswith("주의가 필요해요.")
    store.reset()
    _, _, ev2 = _plan_ev(store, "PLAN-019")
    assert ev2["breakeven"]["explain"].endswith("좋아요.")


def test_결재선_이유_문장(store):
    _, _, ev = _plan_ev(store, "PLAN-001")
    hits = {h["rule_id"]: h["explain"] for h in ev["rule"]["approver_hits"]}
    assert hits["covenant_window"] == ("집행일 7월 27일이 현금이 30억 원 아래로 떨어지는 기간(7/21~8/22) 안이라 "
                                       "CEO와 이사회가 결재해요.")
    assert "지표" in hits["indicator_opposite"] and "이사회" in hits["indicator_opposite"]
    ind = {h["rule_id"]: h["explain"] for h in ev["rule"]["indicator_hits"]}
    sig = {s["key"]: s["explain"] for s in ev["signals"]}
    for k in ("coupon_stacking", "slow_payment_channel", "spend_concentration"):
        assert ind[k] == sig[k]
    store.reset()
    _, _, ev2 = _plan_ev(store, "PLAN-019")
    h2 = {h["rule_id"]: h["explain"] for h in ev2["rule"]["approver_hits"]}
    assert "총액" in h2["plan_total_over_limit"] and "1억 원" in h2["plan_total_over_limit"]
    assert "Masil 대표" in h2["plan_total_over_limit"]
    good = ev2["rule"]["indicator_hits"][0]["explain"]
    assert good.endswith("좋아요.")


def test_계약_건_문장(store):
    _, _, ev = _contract_ev(store)
    sig = {s["key"]: s["explain"] for s in ev["signals"]}
    assert "혜인" in sig["repurchase_rate"] and "업계 평균" in sig["repurchase_rate"]
    assert "적자" in sig["post_contribution"] and sig["post_contribution"].endswith("나빠요.")


def test_옛_저장_행도_설명이_붙는다(store):
    eng, cid, _ = _plan_ev(store, "PLAN-001")
    case = store.get_case(cid)
    f = case["facts"]
    for h in f["approver_hits"] + f["indicator_hits"]:
        h.pop("detail", None)
    store.update_facts(cid, f, "시험", "옛 행")
    ev = eng.case_evidence(cid)
    for h in ev["rule"]["approver_hits"] + ev["rule"]["indicator_hits"]:
        _check_plain(h["explain"])


def test_2차_반품_기준_줄에도_설명(store):
    from test_task25 import _scene  # noqa: E402
    eng, cid = _scene(store, "scenario_2_exception", 9)
    items = eng.phase2_view(cid)["returns_check"]["items"]
    assert [i["label"] for i in items] == ["단순변심", "색상불만"]
    for i in items:
        _check_plain(i["explain"])
    by = {i["label"]: i for i in items}
    assert by["색상불만"]["over"] and by["색상불만"]["explain"].endswith("나빠요.")
    assert not by["단순변심"]["over"] and by["단순변심"]["explain"].endswith("좋아요.")
    assert "색상불만" in by["색상불만"]["explain"] and "5.0%" in by["색상불만"]["explain"]


def test_API_응답에도_explain(store):
    eng, cid, _ = _plan_ev(store, "PLAN-001")
    r = TestClient(create_app(store, eng)).get(f"/api/cases/{cid}/evidence")
    assert r.status_code == 200
    assert all(x["explain"] for x in _all_lines(r.json()))


# ---- 낱말 도우미 ----

def test_금액은_억_만_단위로_세_자리만():
    assert explain.won(248666838) == "약 2억 4,900만 원"
    assert explain.won(422424676) == "약 4억 2,200만 원"
    assert explain.won(61308789) == "약 6,130만 원"
    assert explain.won(3000000000) == "30억 원"
    assert explain.won(100000000) == "1억 원"
    assert explain.won(0) == "0원"


def test_100건_중_말투():
    assert explain.per100(0.1753) == "100건 중 약 18건"
    assert explain.per100(0.0) == "100건 중 0건"
    assert explain.per100(0.004) == "100건 중 1건 미만"


def test_상신과_전결_문장():
    esc = {"rule_id": "escalation", "text": "x"}
    ins = {"올린 역할": "마케팅팀", "받는 역할": "Masil 대표", "이유": "금액이 커서"}
    t = explain.approver_hit(esc, ins)
    assert t == "마케팅팀이 판단하기 어렵다며 Masil 대표에게 올렸어요. 이제 Masil 대표가 결재해요. 올린 이유는 \"금액이 커서\"예요."
    dele = {"rule_id": "plan_within_delegation", "text": "x"}
    t2 = explain.approver_hit(dele, {"건별 요청액": 5000000, "건별 한도": 10000000, "기안 총액": 50000000, "총액 한도": 100000000}, "마케팅팀")
    assert "마케팅팀이 직접 결재해요" in t2 and "500만 원" in t2


def test_옛_문장은_내부_용어만_걷어_낸다():
    t = explain.plain("쿠폰 중복 비중 🔴(나머지 인플루언서 0.023): 두 비율 z=34.00, 한쪽 95% covenant HHI DSO")
    for bad in ("🔴", "z=", "covenant", "HHI", "DSO"):
        assert bad not in t
