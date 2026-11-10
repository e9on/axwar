from datetime import date

from app.calc.cash import Window, breach_windows, official_forecast_gap, simulate_cash
from app.data.loader import read_table


def _days():
    return simulate_cash(date(2026, 7, 1), date(2026, 10, 31))


def test_기초잔액은_6월30일_종가():
    rows = read_table("02_masil/financials/fin_cash_daily_ms.csv")
    assert rows[-1]["closing_balance"] == 5_148_063_540
    d = simulate_cash(date(2026, 7, 1), date(2026, 7, 1))[0]
    assert d.closing == 5_148_063_540 + d.inflow - d.outflow


def test_7월21일_발주대금_일시유출():
    by_day = {d.day: d for d in _days()}
    assert by_day[date(2026, 7, 21)].closing == 2_191_749_959


def test_하회구간은_7월21일부터_8월22일():
    assert breach_windows(_days()) == [Window(date(2026, 7, 21), date(2026, 8, 22))]


def test_최저잔액():
    w = Window(date(2026, 7, 21), date(2026, 8, 22))
    assert min(d.closing for d in _days() if w.start <= d.day <= w.end) == 1_921_839_555


def test_발주대금_이중계상_없음():
    # po_id가 있는 매입채무는 발주 대금과 같은 돈이다. 둘 다 넣으면 7/21에 14건이
    # 두 번 빠져 잔액이 음수가 된다.
    ap = read_table("02_masil/financials/fin_ap_aging_ms.csv")
    po_ap = [r for r in ap if r["po_id"] is not None]
    assert po_ap
    days = _days()
    d721 = next(d for d in days if d.day == date(2026, 7, 21))
    double = sum(r["amount_krw"] for r in po_ap if r["payment_due_date"] == date(2026, 7, 21))
    assert d721.closing + 0 > 0
    assert d721.closing - double < 0
    assert len(days) == 123  # 거래 없는 날 포함 모든 날


def test_공식전망과_차이를_설명한다():
    gap = official_forecast_gap()
    assert gap["official_min"] > 5_000_000_000
    assert gap["defined_min"] == 1_921_839_555
    text = " ".join(gap["causes"])
    assert len(gap["causes"]) == 2
    assert "LC-0001" in text and "7/21" in text
