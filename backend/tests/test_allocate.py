from datetime import date

import pytest

from app.rules.allocate import (
    allocate_day,
    can_announce,
    run_ledger,
    stock_alerts,
    stockout_days_earlier,
    usable_capacity,
)

D1 = date(2026, 8, 1)
D2 = date(2026, 8, 2)
BIG = 10**9


def test_안정처리량이_있으면_그대로():
    assert usable_capacity(20000, 26000)[0] == 20000


def test_안정값_없으면_최대의_85퍼센트_가정():
    cap, hits = usable_capacity(None, 20000)
    assert cap == 17000
    assert hits and hits[0].badge == "가정"
    assert hits[0].rule_id == "capacity_fallback"
    assert "Kingman" in hits[0].text and "85%" in hits[0].text


def test_둘_다_없으면_None():
    assert usable_capacity(None, None)[0] is None


def test_넘치면_모두_같은_비율():
    demand = {"A": 6655, "B": 6631, "C": 13314}
    line = {"A": "L", "B": "L", "C": "L"}
    r = allocate_day(D1, demand, line, {"L": BIG}, 17000)
    assert round(r.capacity_ratio, 3) == 0.639
    assert r.shipped["A"] == 4253
    assert all(r.shipped[k] <= demand[k] for k in demand)
    assert sum(r.shipped.values()) <= 17000


def test_넉넉하면_모두_다_받는다():
    demand = {"A": 6655, "B": 6631, "C": 13314}
    line = {k: "L" for k in demand}
    r = allocate_day(D1, demand, line, {"L": BIG}, 30000)
    assert r.shipped == demand
    assert r.capacity_ratio == 1.0


def test_적게_원하면_적게_받는다():
    r = allocate_day(D1, {"A": 16000, "B": 2000}, {"A": "L", "B": "L"}, {"L": BIG}, 9000)
    assert r.shipped == {"A": 8000, "B": 1000}
    assert r.capacity_ratio == 0.5


def test_재고는_같은_라인끼리_비율대로():
    demand = {"A": 6000, "B": 3000, "C": 1000}
    line = {"A": "기초", "B": "기초", "C": "색조"}
    r = allocate_day(D1, demand, line, {"기초": 6000, "색조": 5000}, None)
    assert r.shipped == {"A": 4000, "B": 2000, "C": 1000}
    assert round(r.stock_ratio["기초"], 3) == 0.667
    assert r.stock_ratio["색조"] == 1.0


def test_못보낸_양은_다음날로():
    out = run_ledger(
        D1, D2,
        {D1: {"A": 8000}, D2: {"A": 4000}},
        {"A": "L"}, {"L": BIG}, {}, {}, {D1: 5000, D2: None}, {"L": 0},
    )
    assert out[0].shipped["A"] == 5000 and out[0].carry["A"] == 3000
    assert out[1].shipped["A"] == 7000 and out[1].carry["A"] == 0


def test_공지된_수량은_먼저_예약되고_넘친_수요는_품절():
    out = run_ledger(
        D1, D2,
        {D1: {"A": 16000, "B": 9000}, D2: {"A": 0, "B": 0}},
        {"A": "L", "B": "L"}, {"L": 10000}, {}, {},
        {D1: None, D2: None}, {"L": 0},
        announced={"A": (D1, 5000)},
    )
    d1 = out[0]
    assert d1.shipped["A"] == 5000
    assert d1.sold_out["A"] == 11000
    assert d1.shipped["B"] == 5000  # 남은 재고는 다른 기안 몫
    assert d1.carry["A"] == 0
    assert out[1].shipped["A"] == 0  # 이월 없음


def test_예약_시뮬레이션으로_공지_가능_판정():
    line = {"A": "L"}
    assert can_announce("A", D1, 5000, line, {"L": 4000}, BIG) is False
    assert can_announce("A", D1, 5000, line, {"L": 6000}, BIG) is True
    assert can_announce("A", D1, 5000, line, {"L": 6000}, BIG, {"L": 2000}) is False
    assert can_announce("A", D1, 5000, line, {"L": 6000}, 4000) is False
    assert can_announce("A", D1, 5000, line, {"L": 6000}, 6000, None, 2000) is False


def test_공지_수량은_공지일부터_누적_상한():
    out = run_ledger(
        D1, date(2026, 8, 3),
        {D1: {"A": 3000}, D2: {"A": 4000}, date(2026, 8, 3): {"A": 1000}},
        {"A": "L"}, {"L": BIG}, {}, {},
        {D1: None, D2: None, date(2026, 8, 3): None}, {"L": 0},
        announced={"A": (D1, 5000)},
    )
    assert out[0].shipped["A"] == 3000
    assert out[1].shipped["A"] == 2000
    assert out[1].sold_out["A"] == 2000 and out[1].carry["A"] == 0
    assert out[2].shipped["A"] == 0 and out[2].sold_out["A"] == 1000


def test_예약은_수요가_없어도_다른_기안이_못_쓴다():
    out = run_ledger(
        D1, D1, {D1: {"B": 6000}}, {"A": "L", "B": "L"}, {"L": 8000}, {}, {},
        {D1: None}, {"L": 0}, announced={"A": (D1, 5000)},
    )
    assert out[0].shipped["B"] == 3000


def test_예약_부족은_품절과_따로_기록():
    r = allocate_day(D1, {"A": 9000}, {"A": "L"}, {"L": 3000}, None, {"A": 5000})
    assert r.shipped["A"] == 3000
    assert r.reservation_shortfall["A"] == 2000
    assert r.sold_out["A"] == 4000


def test_공지_여럿이_모자라면_남은_수량_비율대로_순서_무관():
    line = {"A": "L", "B": "L"}
    d = {"A": 9000, "B": 9000}
    r1 = allocate_day(D1, d, line, {"L": 4000}, None, {"A": 6000, "B": 2000})
    r2 = allocate_day(D1, d, line, {"L": 4000}, None, {"B": 2000, "A": 6000})
    assert r1.shipped == r2.shipped
    assert r1.shipped["A"] == 3000 and r1.shipped["B"] == 1000


def test_안전재고_아래면_여유분_0():
    out = run_ledger(
        D1, D1, {D1: {"A": 5000}}, {"A": "L"}, {"L": 8012}, {}, {},
        {D1: None}, {"L": 17794},
    )
    assert out[0].shipped["A"] == 0 and out[0].carry["A"] == 5000


def test_SCM_허용분만큼만_쓴다():
    out = run_ledger(
        D1, D1, {D1: {"A": 5000}}, {"A": "L"}, {"L": 8012}, {}, {},
        {D1: None}, {"L": 17794}, scm_allowance={"L": 3000},
    )
    assert out[0].shipped["A"] == 3000


def test_품절_앞당김():
    assert round(stockout_days_earlier(3000, 636), 1) == 4.7
    with pytest.raises(ValueError):
        stockout_days_earlier(3000, 0)


def test_재고_과잉과_부족():
    res = stock_alerts(
        {"립": 21606, "틴트": 441}, {"립": 882, "틴트": 882},
        {"립": 2, "틴트": 2}, {"립": 6, "틴트": 6},
    )
    assert ("립", "재고 과잉") in res and ("틴트", "재고 부족") in res
    with pytest.raises(ValueError):
        stock_alerts({"립": 1}, {"립": 0}, {"립": 2}, {"립": 6})
    with pytest.raises(ValueError, match="립"):
        stock_alerts({"립": 1}, {"립": 5}, {}, {"립": 6})


def test_판정_불가_입력은_오류():
    with pytest.raises(ValueError):
        allocate_day(D1, {"A": -1}, {"A": "L"}, {"L": 10}, 10)
    with pytest.raises(ValueError):
        allocate_day(D1, {"A": 1}, {"A": "L"}, {"L": -10}, 10)
    with pytest.raises(ValueError):
        allocate_day(D1, {"A": 1}, {}, {"L": 10}, 10)
    # 원하는 양 합계 0이어도 0 나눗셈 없이 비율 1.0
    r = allocate_day(D1, {"A": 0}, {"A": "L"}, {"L": 10}, 10)
    assert r.capacity_ratio == 1.0 and r.shipped["A"] == 0


def test_수요_없는_공지_잔여는_물류를_깎지_않는다():
    line = {"A": "L", "B": "L"}
    r = allocate_day(D1, {"B": 1000}, line, {"L": BIG}, 1000, {"A": 5000, "B": 1000})
    assert r.shipped == {"A": 0, "B": 1000}
    assert r.reservation_shortfall == {"A": 0, "B": 0}


def test_공지_둘_다_수요_있고_물류_부족이면_want_비율():
    line = {"A": "L", "B": "L"}
    r = allocate_day(D1, {"A": 3000, "B": 1000}, line, {"L": BIG}, 2000, {"A": 5000, "B": 1000})
    assert r.shipped == {"A": 1500, "B": 500}
