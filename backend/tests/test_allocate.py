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


def test_예약이_안되면_공지할_수_없다():
    r = allocate_day(D1, {"A": 4000}, {"A": "L"}, {"L": BIG}, 4000)
    assert can_announce("A", D1, 4000, r) is True
    assert can_announce("A", D1, 5000, r) is False
    assert can_announce("없는기안", D1, 1, r) is False


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
