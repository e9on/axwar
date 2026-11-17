"""Masil 현금 시뮬레이션(계산 정의 1.2). 원본 CSV만 읽는다."""
# hardcode-allow: 100_000_000 (억 단위 표기 변환, 정책 값 아님)
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from app import policy
from app.data.loader import DataFormatError, payment_term_notices, read_table

_DAILY = "02_masil/financials/fin_cash_daily_ms.csv"


@dataclass(frozen=True)
class Window:
    start: date
    end: date


@dataclass(frozen=True)
class DailyCash:
    day: date
    inflow: int
    outflow: int
    closing: int


def _last_daily() -> dict:
    return max(read_table(_DAILY), key=lambda r: r["date"])


def _opening_balance() -> int:
    return _last_daily()["closing_balance"]


def covenant_min_krw() -> int:
    """약정 최저 잔액. 자금일보 마지막 날의 covenant_min_krw 열."""
    return _last_daily()["covenant_min_krw"]


def sim_start() -> date:
    """시뮬레이션 시작일 = 자금일보 마지막 날(기초잔액 종가일) 다음 날."""
    return _last_daily()["date"] + timedelta(days=1)


def forecast_window() -> Window:
    """현금 전망 구간. 시작일부터 정책 cash.horizon_days일(시작일 포함)."""
    start = sim_start()
    return Window(start, start + timedelta(days=policy.get("cash.horizon_days") - 1))


def _flows() -> tuple[dict, dict]:
    inflow: dict[date, int] = defaultdict(int)
    outflow: dict[date, int] = defaultdict(int)
    for r in read_table("02_masil/financials/fin_ar_aging_ms.csv"):
        inflow[r["due_date"]] += r["outstanding_krw"]
    for r in read_table("02_masil/financials/fin_ap_aging_ms.csv"):
        if r["po_id"] is None:  # po_id가 있으면 발주 대금과 중복이라 제외
            outflow[r["payment_due_date"]] += r["amount_krw"]
    for r in read_table("02_masil/inventory/sc_purchase_orders_ms.csv"):
        outflow[r["payment_due_date"]] += r["amount_krw"]
    return inflow, outflow


def simulate_cash(start: date, end: date) -> list[DailyCash]:
    """start~end의 모든 날(거래 없는 날 포함) 일별 현금. 잔액은 시뮬레이션 시작일부터 이어서 계산한다."""
    inflow, outflow = _flows()
    balance = _opening_balance()
    out: list[DailyCash] = []
    day = sim_start()
    while day <= end:
        i, o = inflow.get(day, 0), outflow.get(day, 0)
        balance += i - o
        if day >= start:
            out.append(DailyCash(day, i, o, balance))
        day += timedelta(days=1)
    return out


def breach_windows(days: list[DailyCash], min_krw: int | None = None) -> list[Window]:
    """종가가 min_krw(없으면 자금일보의 약정 최저 잔액) 미만인 연속 구간들."""
    if min_krw is None:
        min_krw = covenant_min_krw()
    windows: list[Window] = []
    start = prev = None
    for d in days:
        if d.closing < min_krw:
            if start is None:
                start = d.day
            prev = d.day
        elif start is not None:
            windows.append(Window(start, prev))
            start = None
    if start is not None:
        windows.append(Window(start, prev))
    return windows


def _md(d: date) -> str:
    return f"{d.month}/{d.day}"


def _po_cluster() -> tuple[date, int, int]:
    """발주 대금이 가장 크게 몰린 지급일과 그날의 건수·금액."""
    by_day: dict[date, list[int]] = defaultdict(list)
    for r in read_table("02_masil/inventory/sc_purchase_orders_ms.csv"):
        by_day[r["payment_due_date"]].append(r["amount_krw"])
    day = max(by_day, key=lambda d: sum(by_day[d]))
    return day, len(by_day[day]), sum(by_day[day])


def _delayed_collection_sentence(notice) -> str:
    channels = [r for r in read_table("02_masil/master/m_channel_ms.csv") if r["partner_code"] == notice.partner_code]
    if not channels:
        raise DataFormatError(f"채널 마스터에 통보문({notice.source_file})의 파트너 코드 {notice.partner_code}가 없음")
    channel = channels[0]
    dues = [r["due_date"] for r in read_table("02_masil/financials/fin_ar_aging_ms.csv") if r["channel_id"] == channel["channel_id"]]
    if not dues:
        raise DataFormatError(f"매출채권(fin_ar_aging_ms.csv)에 채널 {channel['channel_id']} 행이 없음")
    text = (
        f"{notice.partner_code}({channel['channel_id']}) 결제조건 {notice.old_days}일→{notice.new_days}일 변경으로 "
        f"회수가 {_md(min(dues))}~{_md(max(dues))}로 밀림"
    )
    if channel["payment_terms_days"] != notice.new_days:
        text += f"(채널 마스터는 아직 {channel['payment_terms_days']}일)"
    return text


def official_forecast_gap() -> dict:
    forecast = read_table("02_masil/financials/fin_cash_forecast_ms.csv")
    official_min = min(r["projected_closing_krw"] for r in forecast)
    w = forecast_window()
    defined_min = min(d.closing for d in simulate_cash(w.start, w.end))
    day, n, amount = _po_cluster()
    return {
        "official_min": official_min,
        "defined_min": defined_min,
        "causes": [
            f"{_md(day)} 발주 대금 {n}건 약 {amount / 100_000_000:.1f}억 일시 유출이 주별 평균 전망에 반영되지 않음",
        ] + [_delayed_collection_sentence(n) for n in payment_term_notices().values()],
    }
