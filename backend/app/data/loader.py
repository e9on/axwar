"""원본 CSV(`|` 구분, `NONE`은 값 없음)를 읽기 전용으로 불러온다."""
import csv
import re
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

from app.config import data_root

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_INT = re.compile(r"-?\d+")
_FLOAT = re.compile(r"-?\d+\.\d+")


def _convert(value: str):
    v = value.strip()
    if v == "" or v == "NONE":
        return None
    if v == "True":
        return True
    if v == "False":
        return False
    if _INT.fullmatch(v):
        return int(v)
    if _FLOAT.fullmatch(v):
        return float(v)
    if _DATE.fullmatch(v):
        try:
            return date.fromisoformat(v)
        except ValueError:
            return v
    return v


class DataFormatError(ValueError):
    """원본 파일의 형식이 맞지 않음(파일·열 이름을 메시지에 담는다)."""


# 파일별 계산에 쓰는 필수 열. 목록에 없는 파일은 열 검사를 하지 않는다.
REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "02_masil/financials/fin_cash_daily_ms.csv": ("date", "closing_balance", "covenant_min_krw"),
    "02_masil/financials/fin_cash_forecast_ms.csv": ("projected_closing_krw",),
    "02_masil/financials/fin_ar_aging_ms.csv": ("channel_id", "invoice_date", "due_date", "outstanding_krw"),
    "02_masil/financials/fin_ap_aging_ms.csv": ("po_id", "payment_due_date", "amount_krw"),
    "02_masil/inventory/sc_purchase_orders_ms.csv": ("po_id", "payment_due_date", "amount_krw"),
    "02_masil/master/m_channel_ms.csv": ("channel_id", "partner_code", "payment_terms_days"),
}


@lru_cache(maxsize=None)
def _read(root: str, rel_path: str) -> tuple:
    with open(f"{root}/{rel_path}", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter="|")
        missing = [c for c in REQUIRED_COLUMNS.get(rel_path, ()) if c not in (reader.fieldnames or [])]
        if missing:
            raise DataFormatError(f"{rel_path}에 필수 열이 없음: {', '.join(missing)}")
        return tuple({k: _convert(v) for k, v in row.items()} for row in reader)


def read_table(rel_path: str) -> list[dict]:
    """캐시된 결과의 복사본을 돌려준다(호출자가 바꿔도 캐시는 안전)."""
    return [dict(r) for r in _read(str(data_root()), rel_path)]


@dataclass(frozen=True)
class PaymentTermNotice:
    partner_code: str
    old_days: int
    new_days: int


_NOTICE_DIR = "02_masil/financials"
_NOTICE_GLOB = "*payment_term_notice.md"


def payment_term_notice() -> PaymentTermNotice:
    """결제조건 변경 통보문에서 발신 파트너 코드와 기존·변경 일수를 읽는다."""
    files = sorted((data_root() / _NOTICE_DIR).glob(_NOTICE_GLOB))
    if not files:
        raise DataFormatError(f"{_NOTICE_DIR}/{_NOTICE_GLOB} 통보문이 없음")
    text = files[0].read_text(encoding="utf-8").replace("*", "")
    sender = re.search(r"발신:.*?\(([A-Za-z]+-\d+)\)", text)
    days = re.search(r"(\d+)일에서\s*(\d+)일로", text)
    if not sender or not days:
        raise DataFormatError(f"{files[0].name}에서 발신 파트너 코드 또는 결제조건 일수를 찾지 못함")
    return PaymentTermNotice(sender.group(1), int(days.group(1)), int(days.group(2)))
