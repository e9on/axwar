from datetime import date

from app.calc.cash import Window
from app.rules.split import make_split, phase2_gate, return_stop_threshold

W = [Window(date(2026, 7, 21), date(2026, 8, 22))]


def _split(logi=1800, spare=7376, end=date(2026, 8, 31)):
    return make_split(4000, logi, spare, date(2026, 7, 27), date(2026, 8, 18), W, end)


def test_장면2_분할안():
    p = _split()
    assert p.phase1_qty == 1800
    assert p.phase2_qty == 2200
    assert p.phase2_date == date(2026, 8, 24)


def test_1차는_물류한도와_여유재고_중_작은값():
    assert _split(logi=9000, spare=3670).phase1_qty == 3670


def test_2차가_계약만료_뒤면_날짜없음():
    p = _split(end=date(2026, 8, 20))
    assert p.phase2_date is None
    assert any("계약 만료" in h.text for h in p.hits)


def test_자동보류_기준은_기준선과_주문수로_계산():
    assert round(return_stop_threshold(0.0438, 1800), 3) == 0.052
    assert round(return_stop_threshold(0.0377, 1800), 3) == 0.045


def gate(**kw):
    a = dict(
        phase1_orders=1800, change_of_mind_returns=50, color_returns=40,
        baseline_change_of_mind=0.0438, baseline_color=0.0377, days_since_phase1=28,
        color_review_flagged=False, content_fix_confirmed=False, renewal_confirmed=True,
        phase2_date=date(2026, 8, 24), contract_end=date(2026, 8, 31),
    )
    a.update(kw)
    return phase2_gate(**a)


def test_관찰_28일_전에는_열리지_않는다():
    g = gate(days_since_phase1=27)
    assert not g.open and not g.auto_stopped
    assert any("관찰" in r for r in g.reasons)


def test_색상불만_반품이_기준을_넘으면_자동보류():
    g = gate(color_returns=90)
    assert not g.open and g.auto_stopped
    assert "2차 자동 보류" in g.actions


def test_기준선보다_조금_높은_것은_우연으로_본다():
    g = gate(color_returns=75)
    assert not g.auto_stopped and g.open


def test_색상불일치_리뷰는_멈추지_않고_수정요청과_사람확인():
    g = gate(color_review_flagged=True)
    assert not g.open and not g.auto_stopped
    assert "콘텐츠 수정 요청" in g.actions and "사람 확인" in g.actions


def test_수정이_확인되면_열린다():
    assert gate(color_review_flagged=True, content_fix_confirmed=True).open


def test_갱신_미확정이면_만료_뒤_2차_차단():
    g = gate(renewal_confirmed=False, phase2_date=date(2026, 9, 2))
    assert not g.open


def test_모두_괜찮으면_열린다():
    g = gate()
    assert g.open and not g.auto_stopped and g.reasons == () and g.actions == ()


def test_1차_주문_0건이면_반품_판정_불가로_잠긴다():
    g = gate(phase1_orders=0)
    assert not g.open and not g.auto_stopped
    assert any("0건" in r for r in g.reasons)


def test_임계값은_주문수_0이하면_오류():
    import pytest

    with pytest.raises(ValueError, match="1차 주문 수는 1 이상이어야 함"):
        return_stop_threshold(0.04, 0)


def test_2차_수량이_0이면_날짜도_없다():
    p = make_split(1000, 1800, 7376, date(2026, 7, 27), date(2026, 8, 18), W, date(2026, 8, 31))
    assert p.phase2_qty == 0 and p.phase2_date is None and p.hits == ()


def test_관찰일수를_인자로_바꿀_수_있다():
    assert gate(days_since_phase1=14, observe_days=14).open


def test_만료_규칙_id는_snake_case():
    assert _split(end=date(2026, 8, 20)).hits[0].rule_id == "split_expiry"


def test_갱신_미확정이고_만료_뒤면_차단_표시():
    g = gate(renewal_confirmed=False, phase2_date=date(2026, 9, 2))
    assert g.blocked and not g.open


def test_갱신이_확정됐거나_만료_전이면_차단_아님():
    assert not gate(renewal_confirmed=True, phase2_date=date(2026, 9, 2)).blocked
    assert not gate(renewal_confirmed=False, phase2_date=date(2026, 8, 24)).blocked


def test_반품_자동보류는_차단이_아니다():
    g = gate(color_returns=90)
    assert g.auto_stopped and not g.blocked
