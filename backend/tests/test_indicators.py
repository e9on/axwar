"""지표 판정(설계 4.4 위험 신호, 144줄 '🔴가 있으면 지표 반대 근거'): 판정 신호의 🔴만 쓰고,
예상치 기반 참고 신호(설계 4.5)는 뺀다. 값은 테스트에만 둔다."""
from app.calc import indicators
from app.calc.indicators import contract_indicators, plan_indicators
from app.calc.signals import JUDGE, REFERENCE, Signal


def test_장면1_기안은_기안별_빨강이_없어_지표가_좋다():
    k = plan_indicators("PLAN-019")
    assert k.good is True and k.red == ()
    assert k.excluded == ("forecast_gap",)  # 예상치 기반 신호는 판정에서 빠짐(화면 근거로는 남음)
    assert [h.rule_id for h in k.hits] == ["indicators_good"]
    assert "설계 4.5" in k.hits[0].text and "공통" not in k.hits[0].text
    assert "forecast_gap" not in [h.rule_id for h in k.hits]


def test_혜인_기초_기안은_기안별_빨강이_있어_지표가_나쁘다():
    k = plan_indicators("PLAN-001")
    assert k.good is False
    assert k.red == ("coupon_stacking", "slow_payment_channel", "spend_concentration")
    assert [h.rule_id for h in k.hits] == list(k.red)
    assert "forecast_gap" not in [h.rule_id for h in k.hits]
    assert all("🔴" in h.text for h in k.hits)


def test_측정_불가만_있으면_좋음으로_보고_이유를_남긴다(monkeypatch):
    fake = [Signal("x", "가짜 예상치", 1.0, "", "red", "", "계산", REFERENCE, "예상치 기반"),
            Signal("y", "잠식", None, "측정 불가", "unmeasurable", "고객이 완전히 나뉨", "계산", JUDGE)]
    monkeypatch.setattr(indicators, "risk_signals", lambda pid: fake)
    k = indicators.plan_indicators("PLAN-019")
    assert k.good is True and k.red == () and k.unmeasurable == ("y",) and k.excluded == ("x",)
    assert "측정 불가" in k.hits[0].text and "잠식" in k.hits[0].text


def test_원본에_없는_기안은_근거가_없어_나쁨():
    k = plan_indicators("없는-기안")
    assert k.good is False and [h.rule_id for h in k.hits] == ["no_signals"]


def test_전속계약은_인플루언서별_미래가치_신호로_판정():
    bad = contract_indicators("INF-001")
    assert bad.good is False and set(bad.red) == {"repurchase_rate", "post_contribution"}
    assert contract_indicators("INF-002").good is True
    assert contract_indicators("INF-없음").good is False
