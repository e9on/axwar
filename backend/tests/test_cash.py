from datetime import date, timedelta

import pytest

from app import config, policy
from app.calc.cash import Window, breach_windows, forecast_window, official_forecast_gap, simulate_cash
from app.data import loader
from app.data.loader import read_table


def _days():
    w = forecast_window()
    return simulate_cash(w.start, w.end)


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
    assert len(days) == policy.get("cash.horizon_days")  # 거래 없는 날 포함 모든 날


def test_공식전망과_차이를_설명한다():
    gap = official_forecast_gap()
    assert gap["official_min"] > 5_000_000_000
    assert gap["defined_min"] == 1_921_839_555
    text = " ".join(gap["causes"])
    assert len(gap["causes"]) == 2
    assert "LC-0001" in text and "7/21" in text


def test_시작일은_자금일보_마지막날_다음날_끝날은_전망기간():
    last = read_table("02_masil/financials/fin_cash_daily_ms.csv")[-1]["date"]
    w = forecast_window()
    assert w.start == last + timedelta(days=1)
    assert (w.end - w.start).days + 1 == policy.get("cash.horizon_days")


def test_전망기간을_정책에서_바꾸면_끝날이_따라간다(monkeypatch, tmp_path):
    f = tmp_path / "p.toml"
    f.write_text(policy.DEFAULT_PATH.read_text(encoding="utf-8").replace("value = 90", "value = 30"), encoding="utf-8")
    monkeypatch.setenv("AXWAR_POLICY_FILE", str(f))
    policy.reload()
    try:
        w = forecast_window()
        assert (w.end - w.start).days + 1 == 30
    finally:
        monkeypatch.undo()
        policy.reload()


def _copy_data(tmp_path, monkeypatch, extra_cash_row=True, drop_column=None):
    import shutil
    dst = tmp_path / "data"
    shutil.copytree(config.data_root(), dst)
    daily = dst / "02_masil/financials/fin_cash_daily_ms.csv"
    if extra_cash_row:
        lines = daily.read_text(encoding="utf-8-sig").splitlines()
        cols = lines[-1].split("|")
        nxt = date.fromisoformat(cols[0]) + timedelta(days=1)
        closing = int(cols[4])
        lines.append("|".join([nxt.isoformat(), str(closing), "0", "0", str(closing), cols[5], "False"]))
        daily.write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setenv("AXWAR_DATA_ROOT", str(dst))
    loader._read.cache_clear()
    return dst


@pytest.fixture
def _clean_cache():
    yield
    loader._read.cache_clear()


def test_자금일보를_하루_늘리면_시작일이_하루_밀린다(tmp_path, monkeypatch, _clean_cache):
    before = forecast_window()
    _copy_data(tmp_path, monkeypatch)
    after = forecast_window()
    assert after.start == before.start + timedelta(days=1)
    assert after.end == before.end + timedelta(days=1)
    assert simulate_cash(after.start, after.end)[0].day == after.start


def test_공식전망_원인문장의_숫자는_데이터와_같다():
    text = " ".join(official_forecast_gap()["causes"])
    po = [r for r in read_table("02_masil/inventory/sc_purchase_orders_ms.csv")]
    day = max({r["payment_due_date"] for r in po}, key=lambda d: sum(r["amount_krw"] for r in po if r["payment_due_date"] == d))
    rows = [r for r in po if r["payment_due_date"] == day]
    assert f"{day.month}/{day.day} 발주 대금 {len(rows)}건 약 {sum(r['amount_krw'] for r in rows) / 1e8:.1f}억" in text
    assert "45일→90일" in text
    assert "8/23~9/6" in text


def test_발주를_바꾸면_문장_숫자가_따라간다(tmp_path, monkeypatch, _clean_cache):
    dst = _copy_data(tmp_path, monkeypatch, extra_cash_row=False)
    p = dst / "02_masil/inventory/sc_purchase_orders_ms.csv"
    lines = p.read_text(encoding="utf-8-sig").splitlines()
    p.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")  # 1건 제거
    loader._read.cache_clear()
    text = " ".join(official_forecast_gap()["causes"])
    assert "13건" in text and "14건" not in text
