from datetime import date

from app.config import DATA_ROOT
from app.data.loader import read_table


def test_파이프_구분과_NONE을_읽는다():
    rows = read_table("02_masil/financials/fin_ap_aging_ms.csv")
    assert any(r["po_id"] is None for r in rows)
    assert all(isinstance(r["amount_krw"], int) for r in rows)


def test_날짜를_date로_읽는다():
    rows = read_table("02_masil/financials/fin_cash_daily_ms.csv")
    assert rows[-1]["date"] == date(2026, 6, 30)
    assert rows[-1]["closing_balance"] == 5_148_063_540


def test_원본_파일을_수정하지_않는다():
    path = DATA_ROOT / "02_masil/financials/fin_cash_daily_ms.csv"
    before = path.stat().st_mtime_ns
    read_table("02_masil/financials/fin_cash_daily_ms.csv")
    assert path.stat().st_mtime_ns == before
