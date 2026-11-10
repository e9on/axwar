from datetime import date

import pytest

from app.config import data_root
from app.data import loader
from app.data.loader import DataFormatError, read_table


def test_파이프_구분과_NONE을_읽는다():
    rows = read_table("02_masil/financials/fin_ap_aging_ms.csv")
    assert any(r["po_id"] is None for r in rows)
    assert all(isinstance(r["amount_krw"], int) for r in rows)


def test_날짜를_date로_읽는다():
    rows = read_table("02_masil/financials/fin_cash_daily_ms.csv")
    assert rows[-1]["date"] == date(2026, 6, 30)
    assert rows[-1]["closing_balance"] == 5_148_063_540


def test_원본_파일을_수정하지_않는다():
    path = data_root() / "02_masil/financials/fin_cash_daily_ms.csv"
    before = path.stat().st_mtime_ns
    read_table("02_masil/financials/fin_cash_daily_ms.csv")
    assert path.stat().st_mtime_ns == before


def test_필수_열이_빠지면_파일과_열_이름을_담은_오류(tmp_path, monkeypatch):
    import shutil
    dst = tmp_path / "data"
    shutil.copytree(data_root(), dst)
    f = dst / "02_masil/financials/fin_cash_daily_ms.csv"
    text = f.read_text(encoding="utf-8-sig").replace("closing_balance", "closing_bal", 1)
    f.write_text(text, encoding="utf-8")
    monkeypatch.setenv("AXWAR_DATA_ROOT", str(dst))
    loader._read.cache_clear()
    try:
        with pytest.raises(DataFormatError) as e:
            read_table("02_masil/financials/fin_cash_daily_ms.csv")
        assert "fin_cash_daily_ms.csv" in str(e.value) and "closing_balance" in str(e.value)
    finally:
        monkeypatch.undo()
        loader._read.cache_clear()


def test_필수_열_목록에_없는_파일은_오류(data_copy):
    with pytest.raises(DataFormatError) as e:
        read_table("02_masil/master/m_influencer_ms.csv")
    assert "필수 열 미등록 파일" in str(e.value) and "m_influencer_ms.csv" in str(e.value)


def test_계산에서_읽는_모든_파일이_등록되어_있다():
    import re
    from pathlib import Path
    app = Path(__file__).resolve().parents[1] / "app"
    used = set()
    for py in app.glob("calc/*.py"):
        src = py.read_text(encoding="utf-8")
        pre = dict(re.findall(r'^(_\w+)\s*=\s*"([^"]+/)"', src, re.M))
        for m in re.finditer(r'read_table\((?:(_\w+)\s*\+\s*)?"([^"]+\.csv)"', src):
            used.add((pre.get(m.group(1), "") if m.group(1) else "") + m.group(2))
        for m in re.finditer(r'^(_\w+)\s*=\s*"([^"]+\.csv)"', src, re.M):
            used.add(m.group(2))
    assert used and used <= set(loader.REQUIRED_COLUMNS)
