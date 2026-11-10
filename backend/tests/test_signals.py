from app.calc.signals import cost_breakdown, future_value_signals, risk_signals
from app.calc.volume import _plans


def _by_key(signals):
    return {s.key: s for s in signals}


def test_혜인_비용분해():
    b = cost_breakdown("INF-001")
    assert b.gmv == 422424676
    assert b.pre_marketing == 248666838
    assert b.influencer_fee == 161187327
    assert b.other_media == 148788300
    assert b.after_fee == 87479511
    assert b.final == -61308789


def test_혜인_재구매는_업계보다_낮아_빨강():
    h = _by_key(future_value_signals("INF-001"))["repurchase_90d"]
    assert round(h.value, 4) == 0.0852
    assert h.level == "red"
    d = _by_key(future_value_signals("INF-002"))["repurchase_90d"]
    assert round(d.value, 3) == 0.241
    assert d.level == "green"


def test_이후주문_포함해도_음수면_빨강():
    s = _by_key(future_value_signals("INF-001"))["post_contribution"]
    assert s.level == "red"
    assert "최종 공헌에 이미 포함" in s.basis


def test_예상실적_괴리():
    s = _by_key(risk_signals("PLAN-001"))["forecast_gap"]
    assert round(s.value, 2) == 11.25
    assert s.level == "red"
    for p in _plans():
        assert _by_key(risk_signals(p["plan_id"]))["forecast_gap"].level == "red"


def test_쿠폰중복():
    s = _by_key(risk_signals("PLAN-001"))["coupon_stacking"]
    assert round(s.value, 3) == 0.175
    assert s.level == "red"


def test_결제지연_채널():
    s = _by_key(risk_signals("PLAN-001"))["slow_payment_channel"]
    assert round(s.value, 3) == 0.294
    assert s.level == "red"
    g = _by_key(risk_signals("PLAN-019"))["slow_payment_channel"]
    assert g.value == 0.0
    assert g.level == "green"


def test_광고비_쏠림():
    s = _by_key(risk_signals("PLAN-001"))["spend_concentration"]
    assert round(s.value, 0) == 2462
    assert s.level == "red"
    assert _by_key(risk_signals("PLAN-019"))["spend_concentration"].level == "green"


def test_채널반품_기준선():
    lv = lambda p: _by_key(risk_signals(p))["channel_return_vs_benchmark"].level
    assert lv("PLAN-001") == "green"
    assert lv("PLAN-003") == "yellow"
    assert lv("PLAN-002") == "red"


def test_회차추세():
    assert _by_key(risk_signals("PLAN-001"))["trend"].level == "yellow"


def test_잠식은_측정불가():
    s = _by_key(risk_signals("PLAN-001"))["cannibalization"]
    assert s.level == "unmeasurable"
    assert "표본" in s.basis
