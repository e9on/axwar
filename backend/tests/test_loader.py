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
        read_table("02_masil/master/m_unregistered_ms.csv")
    assert "필수 열 미등록 파일" in str(e.value) and "m_unregistered_ms.csv" in str(e.value)


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


# ---- 전속계약 통보문 ----

def test_전속계약_통보문에서_고정피_만료_통보기한을_읽는다():
    notices = loader.contract_notices()
    n = notices["INF-001"]
    assert n.annual_fixed_krw == 2_800_000_000
    assert n.expiry == date(2026, 8, 31)
    assert n.notice_deadline == date(2026, 7, 17)
    assert n.auto_renew is True
    assert n.influencer_name == "혜인"
    assert "성과 피" in n.performance_fee_text
    assert n.source_file.endswith("inf001_exclusive_contract_notice.md")


def test_통보문_항목이_없으면_파일과_항목_이름을_담은_오류(tmp_path):
    f = tmp_path / "x_exclusive_contract_notice.md"
    f.write_text("당사 **혜인(INF-001)**\n\n| 항목 | 내용 |\n|---|---|\n| 현 계약 만료 | 2026-08-31 |\n", encoding="utf-8")
    with pytest.raises(DataFormatError, match="x_exclusive_contract_notice.md.*보수"):
        loader.parse_contract_notice(f)


def test_고정피_단위를_읽는다(tmp_path):
    f = tmp_path / "y_exclusive_contract_notice.md"
    f.write_text("당사 **지수(INF-009)**\n\n| 항목 | 내용 |\n|---|---|\n| 보수 구조 | **고정 피 연 1억 2,000만원** + 성과 피 |\n"
                 "| 현 계약 만료 | 2030-03-31 |\n| **해지·조건변경 통보 기한** | **2030-02-01** |\n| 미통보 시 | 자동 갱신되지 않음 |\n",
                 encoding="utf-8")
    n = loader.parse_contract_notice(f)
    assert n.annual_fixed_krw == 120_000_000 and n.auto_renew is False and n.influencer_code == "INF-009"


def test_기안_원본을_읽는다():
    rows = loader.plan_rows()
    assert len(rows) == 25 and rows[0]["plan_id"] == "PLAN-001"


# ---- 통보문 금액·자동 갱신·인플루언서 변형 ----

def _notice(tmp_path, pay="**고정 피 연 28억원** + 성과 피", renew="**동일 조건으로 1년 자동 갱신**", head="당사 크리에이터 **혜인(INF-001)**과"):
    f = tmp_path / "z_exclusive_contract_notice.md"
    f.write_text(f"수신: A\n발신: 에이전시(AGY-777) 파트너십팀\n\n{head} 귀사 간 계약\n\n| 항목 | 내용 |\n|---|---|\n"
                 f"| 보수 구조 | {pay} |\n| 현 계약 만료 | 2030-03-31 |\n| **해지·조건변경 통보 기한** | **2030-02-01** |\n"
                 f"| 미통보 시 | {renew} |\n", encoding="utf-8")
    return f


@pytest.mark.parametrize("pay,expected", [
    ("**고정 피 연 28억원** + 성과 피", 2_800_000_000),
    ("고정 피 연 28억 + 성과 피", 2_800_000_000),
    ("고정 피 연 28.5억원 + 성과 피", 2_850_000_000),
    ("고정 피 연 28억 5천만원 + 성과 피", 2_850_000_000),
    ("고정 피 연 28억 5000만원", 2_850_000_000),
    ("고정 피 연 2억 3백만원", 203_000_000),
    ("고정 피 연 2,800,000,000원 + 성과 피", 2_800_000_000),
    ("고정 피 2800000000원", 2_800_000_000),
    ("고정 피 연 1억 2,000만원 + 성과 피", 120_000_000),
])
def test_고정피_금액_형식을_읽는다(tmp_path, pay, expected):
    assert loader.parse_contract_notice(_notice(tmp_path, pay=pay)).annual_fixed_krw == expected


@pytest.mark.parametrize("pay", [
    "고정 피 연 28 5억원", "고정 피 연 28억 3억원", "고정 피 연 5천만 28억원", "고정 피 연 1억 2,000원",
    "고정 피 연 28억 어쩌고원", "고정 피 연 협의", "고정 피 연 28..5억원", "고정 피 연 0.0000001원", "고정 피 연 억원",
])
def test_알_수_없는_금액_형식은_파일과_항목_이름을_담은_오류(tmp_path, pay):
    with pytest.raises(DataFormatError, match="z_exclusive_contract_notice.md.*보수"):
        loader.parse_contract_notice(_notice(tmp_path, pay=pay))


@pytest.mark.parametrize("renew,expected", [
    ("**동일 조건으로 1년 자동 갱신**되며 위약금 정산", True),
    ("동일 조건으로 1년 자동갱신됩니다", True),
    ("자동으로 갱신되며 위약금", True),
    ("1년 자동 연장", True),
    ("자동 갱신되지 않음", False),
    ("자동갱신 되지 않고 계약 종료", False),
    ("자동 연장 없음", False),
    ("자동 갱신 조항 없음", False),
    ("자동갱신 불가", False),
    ("자동으로 갱신하지 않음", False),
    ("자동 연장되지 않으며 계약 종료", False),
    ("자동 갱신되며, 위약금 없음", True),
    ("자동 갱신(별도 통보 없음)", True),
    ("자동 갱신되며 해지 불가", True),
    ("자동 갱신된다", True),
])
def test_자동_갱신_표현을_읽는다(tmp_path, renew, expected):
    assert loader.parse_contract_notice(_notice(tmp_path, renew=renew)).auto_renew is expected


@pytest.mark.parametrize("renew", [
    "추후 협의", "계약 종료", "1년 연장", "갱신 안 됨",
    "자동 갱신되며 자동 갱신되지 않음",  # 긍정과 부정이 섞임
    "자동 갱신 없음, 단 자동 연장됨",
])
def test_자동_갱신_여부가_애매하면_오류(tmp_path, renew):
    with pytest.raises(DataFormatError, match="z_exclusive_contract_notice.md.*미통보"):
        loader.parse_contract_notice(_notice(tmp_path, renew=renew))


def test_인플루언서는_발신_에이전시가_아니라_크리에이터_문장에서(tmp_path):
    n = loader.parse_contract_notice(_notice(tmp_path))
    assert n.influencer_code == "INF-001" and n.influencer_name == "혜인"


def test_통보문_출처는_데이터_폴더_기준_상대_경로():
    n = loader.contract_notices()["INF-001"]
    assert n.source_file == "02_masil/marketing/inf001_exclusive_contract_notice.md"


def test_캠페인_마스터를_읽는다():
    rows = loader.campaign_master_rows()
    assert any(r["campaign_id"] == "CMP-0003" for r in rows)
