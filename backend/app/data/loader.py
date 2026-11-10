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


# 계산이 읽는 파일별 필수 열. 목록에 없는 파일을 읽으면 개발 중 실수로 보고 오류를 낸다.
_FIN = "02_masil/financials/"
_INV = "02_masil/inventory/"
_MKT = "02_masil/marketing/"
_MST = "02_masil/master/"
REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    _FIN + "fin_cash_daily_ms.csv": ("date", "closing_balance", "covenant_min_krw"),
    _FIN + "fin_cash_forecast_ms.csv": ("projected_closing_krw",),
    _FIN + "fin_ar_aging_ms.csv": ("channel_id", "invoice_date", "due_date", "outstanding_krw"),
    _FIN + "fin_ap_aging_ms.csv": ("po_id", "payment_due_date", "amount_krw"),
    _INV + "sc_purchase_orders_ms.csv": ("po_id", "sku_id", "order_date", "lead_time_weeks", "payment_due_date", "amount_krw"),
    _INV + "sku_inventory_ms.csv": ("sku_id", "snapshot_date", "on_hand_qty"),
    _INV + "sku_weekly_sales_ms.csv": ("week", "sku_id", "sold_qty"),
    _MKT + "mkt_ad_spend_ms.csv": ("campaign_id", "media", "ad_cost_krw"),
    _MKT + "mkt_budget_plan_ms.csv": ("plan_id", "campaign_id", "requested_budget_krw", "expected_gmv_krw", "settlement_date"),
    _MKT + "mkt_cost_master_ms.csv": ("sku_id", "channel_id", "product_cost_krw", "channel_fee_pct", "shipping_cost_krw", "return_logistics_cost_krw"),
    _MKT + "mkt_coupons_ms.csv": ("order_id", "stacked_flag"),
    _MKT + "mkt_orders_ms.csv": ("order_id", "order_date", "customer_ref", "channel_id", "sku_id", "campaign_id", "gmv_krw"),
    _MKT + "mkt_repurchase_ms.csv": ("customer_ref", "reorder_within_90d"),
    _MKT + "mkt_returns_ms.csv": ("order_id", "refund_amount_krw", "reason"),
    _MST + "m_campaign_ms.csv": ("campaign_id", "influencer_id", "sales_channel", "product_line", "start_date"),
    _MST + "m_channel_ms.csv": ("channel_id", "channel_type", "partner_code", "payment_terms_days"),
    _MST + "m_sku_ms.csv": ("sku_id", "safety_stock_weeks_min"),
    "05_external/benchmark/ext_channel_benchmark.csv": ("channel_type", "return_rate_pct"),
    "05_external/benchmark/ext_industry_benchmark.csv": ("metric", "value"),
}


def _check_columns(rel_path: str, fieldnames) -> None:
    missing = [c for c in REQUIRED_COLUMNS[rel_path] if c not in (fieldnames or [])]
    if missing:
        raise DataFormatError(f"{rel_path}에 필수 열이 없음: {', '.join(missing)}")


@lru_cache(maxsize=None)
def _read(root: str, rel_path: str) -> tuple:
    if rel_path not in REQUIRED_COLUMNS:
        raise DataFormatError(f"필수 열 미등록 파일: {rel_path} (loader.REQUIRED_COLUMNS에 등록 필요)")
    with open(f"{root}/{rel_path}", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter="|")
        _check_columns(rel_path, reader.fieldnames)
        return tuple({k: _convert(v) for k, v in row.items()} for row in reader)


def read_table(rel_path: str) -> list[dict]:
    """캐시된 결과의 복사본을 돌려준다(호출자가 바꿔도 캐시는 안전)."""
    return [dict(r) for r in _read(str(data_root()), rel_path)]


def read_raw_text(rel_path: str, key_column: str, key: str, column: str) -> str:
    """key_column == key인 첫 행의 column 원문 문자열(형 변환 없이). 소수 자릿수 같은 표기 정보가 필요할 때 쓴다."""
    if rel_path not in REQUIRED_COLUMNS:
        raise DataFormatError(f"필수 열 미등록 파일: {rel_path} (loader.REQUIRED_COLUMNS에 등록 필요)")
    with open(f"{data_root()}/{rel_path}", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter="|")
        _check_columns(rel_path, reader.fieldnames)
        for row in reader:
            if row[key_column].strip() == key:
                return row[column].strip()
    raise DataFormatError(f"{rel_path}에서 {key_column}={key} 행을 찾지 못함")


@dataclass(frozen=True)
class PaymentTermNotice:
    partner_code: str
    old_days: int
    new_days: int
    effective: date  # 적용 시점(월 1일). 통보문에 없으면 date.min
    source_file: str


_NOTICE_DIR = "02_masil/financials"
_NOTICE_GLOB = "*payment_term_notice*.md"
_CODE = re.compile(r"\(([A-Za-z]+-\d+)\)")
_DAYS = re.compile(r"(\d+)\s*일\s*(?:에서|→|->)\s*(\d+)\s*일")
_APPLIED = re.compile(r"적용[^\n]*?(\d{4})\s*년\s*(\d{1,2})\s*월")


def _parse_notice(path) -> PaymentTermNotice:
    text = path.read_text(encoding="utf-8").replace("*", "")
    lines = text.splitlines()
    partner = None
    for i, line in enumerate(lines):
        if "발신" in line:
            m = _CODE.search(line) or _CODE.search(" ".join(lines[i + 1:i + 3]))
            if m:
                partner = m.group(1)
                break
    days = None
    for sentence in re.split(r"[.\n]", text):
        if "결제조건" in sentence:
            days = _DAYS.search(sentence)
            if days:
                break
    if not partner or not days:
        raise DataFormatError(f"{path.name}에서 발신 파트너 코드 또는 결제조건 일수 문구를 찾지 못함")
    ap = _APPLIED.search(text)
    effective = date(int(ap.group(1)), int(ap.group(2)), 1) if ap else date.min
    return PaymentTermNotice(partner, int(days.group(1)), int(days.group(2)), effective, path.name)


def payment_term_notices() -> dict[str, PaymentTermNotice]:
    """결제조건 통보문을 모두 읽어 파트너 코드별로 적용 시점이 가장 늦은 통보를 돌려준다."""
    files = sorted((data_root() / _NOTICE_DIR).glob(_NOTICE_GLOB))
    if not files:
        raise DataFormatError(f"{_NOTICE_DIR}/{_NOTICE_GLOB} 통보문이 없음")
    best: dict[str, PaymentTermNotice] = {}
    for f in files:
        n = _parse_notice(f)
        cur = best.get(n.partner_code)
        if cur is None or (n.effective, n.source_file) > (cur.effective, cur.source_file):
            best[n.partner_code] = n
    return best
