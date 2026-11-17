"""원본 CSV(`|` 구분, `NONE`은 값 없음)를 읽기 전용으로 불러온다."""
import csv
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

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
    _MKT + "mkt_budget_plan_ms.csv": ("plan_id", "campaign_id", "requested_budget_krw", "expected_gmv_krw", "settlement_date", "contract_deadline"),
    _MKT + "mkt_cost_master_ms.csv": ("sku_id", "channel_id", "product_cost_krw", "channel_fee_pct", "shipping_cost_krw", "return_logistics_cost_krw"),
    _MKT + "mkt_coupons_ms.csv": ("order_id", "stacked_flag"),
    _MKT + "mkt_orders_ms.csv": ("order_id", "order_date", "customer_ref", "channel_id", "sku_id", "campaign_id", "gmv_krw"),
    _MKT + "mkt_repurchase_ms.csv": ("customer_ref", "reorder_within_90d"),
    _MKT + "mkt_returns_ms.csv": ("order_id", "refund_amount_krw", "reason"),
    _MST + "m_campaign_ms.csv": ("campaign_id", "campaign_name", "influencer_id", "sales_channel", "product_line", "start_date"),
    _MST + "m_influencer_ms.csv": ("influencer_id", "influencer_name"),
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


# ---------------------------------------------------------------- 캠페인 기안 원본

PLAN_SOURCE = _MKT + "mkt_budget_plan_ms.csv"  # 캠페인 확대 기안이 든 원본 파일


def campaign_master_rows() -> list[dict]:
    """캠페인 마스터(캠페인 -> 인플루언서·판매 채널)."""
    return read_table(_MST + "m_campaign_ms.csv")


def influencer_rows() -> list[dict]:
    """인플루언서 마스터(인플루언서 ID -> 이름)."""
    return read_table(_MST + "m_influencer_ms.csv")


def plan_rows() -> list[dict]:
    """캠페인 기안 원본 행(필수 열 검사 포함)."""
    return read_table(PLAN_SOURCE)


# ---------------------------------------------------------------- 전속계약 통보문


@dataclass(frozen=True)
class ContractNotice:
    influencer_code: str
    influencer_name: str
    annual_fixed_krw: int
    performance_fee_text: str  # 성과 피 조건 원문
    notice_deadline: date  # 해지·조건변경 통보 기한
    expiry: date  # 현 계약 만료일
    auto_renew: bool  # 미통보 시 자동 갱신 여부
    source_file: str


_CONTRACT_DIR = "02_masil/marketing"
_CONTRACT_GLOB = "*exclusive_contract_notice*.md"
_WHO = re.compile(r"([가-힣A-Za-z]+)\(([A-Za-z]+-\d+)\)")
_CREATOR = re.compile(r"(?:크리에이터|인플루언서)\s*([가-힣A-Za-z]+)\(([A-Za-z]+-\d+)\)")
_FEE_START = re.compile(r"고정\s*피\s*(?:연\s*)?")
_AMOUNT_TOKEN = r"\d[\d,]*(?:\.\d+)?\s*(?:조|억|천만|백만|만|천|백)?"
_AMOUNT_ALL = re.compile(rf"(?:{_AMOUNT_TOKEN}\s*)+")
_AMOUNT_PART = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(조|억|천만|백만|만|천|백)?")
# 한글 금액 단위 변환(원 단위)
_UNIT = {"조": 10**12, "억": 10**8, "천만": 10**7, "백만": 10**6, "만": 10**4, "천": 10**3, "백": 10**2, "": 1}
_RENEW = re.compile(r"자동(?:으로)?(?:갱신|연장)")
# 부정은 갱신·연장 동사에 바로 붙은 형태만 인정한다("자동 갱신되며, 위약금 없음"의 '없음'은 갱신과 무관)
_RENEW_NEGATED = re.compile(r"자동(?:으로)?(?:갱신|연장)(?:조항|규정|약정)?(?:이|은|을)?(?:되지|하지|되진|되질)?(?:않|안|아니|없|불가)")


def _money_krw(text: str) -> int | None:
    """'28억', '28.5억원', '28억 5천만원', '2,800,000,000원'을 원 단위 정수로. 형식이 다르거나 정수가 아니면 None."""
    body = text.strip()
    if body.endswith("원"):
        body = body[:-1].strip()
    if not _AMOUNT_ALL.fullmatch(body):
        return None
    total = Decimal(0)
    parts = _AMOUNT_PART.findall(body)
    ranks = [_UNIT[u] for _, u in parts]
    # 단위는 큰 쪽에서 작은 쪽으로 한 번씩만(28억 5천만), 단위 없는 숫자는 혼자일 때만 허용
    if len(parts) > 1 and (any(not u for _, u in parts) or any(a <= b for a, b in zip(ranks, ranks[1:]))):
        return None
    for num, unit in parts:
        total += Decimal(num.replace(",", "")) * _UNIT[unit]
    return int(total) if total == total.to_integral_value() and total > 0 else None


def _table_rows(text: str) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("|"):
            rows.append([c.strip() for c in line.strip("|").split("|")])
    return rows


def _source_name(path: Path) -> str:
    """등록부 키로 쓰는 출처 이름: 데이터 폴더 기준 상대 경로(밖에 있으면 전체 경로)."""
    try:
        return path.resolve().relative_to(data_root().resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def parse_contract_notice(path) -> ContractNotice:
    """전속계약 통보문의 표·문장에서 연 고정 피·만료일·통보 기한·자동 연장을 읽는다.

    못 찾거나 해석이 애매하면 조용히 넘어가지 않고 파일·항목 이름을 담은 DataFormatError.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8").replace("*", "")
    rows = _table_rows(text)

    def cell(*keys: str) -> str:
        for r in rows:
            if len(r) >= 2 and any(k in r[0] for k in keys):
                return r[1]
        raise DataFormatError(f"{path.name}에서 '{keys[0]}' 항목을 찾지 못함")

    who = _CREATOR.search(text)
    if not who:  # 발신·수신 줄(에이전시 코드가 있을 수 있음)을 뺀 첫 "이름(코드)"
        body = "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith(("수신", "발신")))
        who = _WHO.search(body)
    if not who:
        raise DataFormatError(f"{path.name}에서 인플루언서 이름(코드)을 찾지 못함")
    pay = cell("보수")
    start = _FEE_START.search(pay)
    if not start:
        raise DataFormatError(f"{path.name}의 '보수 구조' 항목에서 고정 피 문구를 찾지 못함: {pay!r}")
    amount_text = re.split(r"원|\+", pay[start.end():], maxsplit=1)[0]
    fixed = _money_krw(amount_text)
    if fixed is None:
        raise DataFormatError(f"{path.name}의 '보수 구조' 항목의 고정 피 금액을 해석하지 못함: {pay!r}")

    def day(*keys: str) -> date:
        m = _DATE.search(cell(*keys))
        if not m:
            raise DataFormatError(f"{path.name}의 '{keys[0]}' 항목에서 날짜를 찾지 못함")
        return date.fromisoformat(m.group(0))

    renew_cell = cell("미통보")
    renew_text = re.sub(r"\s+", "", renew_cell)
    negated = [m for m in _RENEW.finditer(renew_text) if _RENEW_NEGATED.match(renew_text, m.start())]
    positive = [m for m in _RENEW.finditer(renew_text) if not _RENEW_NEGATED.match(renew_text, m.start())]
    if bool(negated) == bool(positive):  # 둘 다 없거나 섞여 있으면 판단하지 않는다
        raise DataFormatError(f"{path.name}의 '미통보 시' 항목에서 자동 갱신 여부를 판단하지 못함: {renew_cell!r}")
    auto = bool(positive)

    return ContractNotice(
        who.group(2), who.group(1), fixed,
        pay.split("+", 1)[1].strip() if "+" in pay else "",
        day("통보 기한"), day("만료"), auto, _source_name(path))


def contract_notices() -> dict[str, ContractNotice]:
    """전속계약 통보문을 모두 읽어 인플루언서 코드별로 만료일이 가장 늦은 통보를 돌려준다."""
    files = sorted((data_root() / _CONTRACT_DIR).glob(_CONTRACT_GLOB))
    if not files:
        raise DataFormatError(f"{_CONTRACT_DIR}/{_CONTRACT_GLOB} 통보문이 없음")
    best: dict[str, ContractNotice] = {}
    for f in files:
        n = parse_contract_notice(f)
        cur = best.get(n.influencer_code)
        if cur is None or (n.expiry, n.source_file) > (cur.expiry, cur.source_file):
            best[n.influencer_code] = n
    return best
