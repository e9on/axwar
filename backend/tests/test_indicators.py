"""핵심 지표 판정(설계 4.4): 실질 ROAS 부호와 단순변심 반품률 비교. 값은 테스트에만 둔다."""
from app.calc.indicators import key_indicators


def test_실질_ROAS_1위_인플루언서는_지표가_좋다():
    k = key_indicators("INF-002")
    assert k.good is True
    assert round(k.real_roas, 3) == 3.703 and k.rank == 1
    assert k.change_of_mind_rate < k.others_change_of_mind_rate
    assert all(h.badge == "계산" for h in k.hits)


def test_혜인은_실질_ROAS_음수와_변심_반품률이_높아_지표가_나쁘다():
    k = key_indicators("INF-001")
    assert k.good is False
    assert round(k.real_roas, 3) == -0.198 and k.rank == 9
    assert round(k.change_of_mind_rate * 100, 2) == 3.58 and round(k.others_change_of_mind_rate * 100, 2) == 1.75
    ids = {h.rule_id for h in k.hits}
    assert ids == {"real_roas_negative", "change_of_mind_high"}
    assert any("-0.198" in h.text for h in k.hits)


def test_실적이_없는_인플루언서는_판정할_수_없어_나쁨으로_본다():
    k = key_indicators("INF-없음")
    assert k.good is False and k.real_roas is None
    assert [h.rule_id for h in k.hits] == ["no_performance"]
