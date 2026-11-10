"""Masil 현금 시뮬레이션(계산 정의 1.2). 원본 CSV만 읽는다."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from app.data.loader import read_table

COVENANT_MIN_KRW = 3_000_000_000
SIM_START = date(2026, 7, 1)  # 기초잔액(6/30 종가) 다음 날


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


def _opening_balance() -> int:
    return read_table("02_masil/financials/fin_cash_daily_ms.csv")[-1]["closing_balance"]


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
    """start~end의 모든 날(거래 없는 날 포함) 일별 현금. 잔액은 7/1부터 이어서 계산한다."""
    inflow, outflow = _flows()
    balance = _opening_balance()
    out: list[DailyCash] = []
    day = SIM_START
    while day <= end:
        i, o = inflow.get(day, 0), outflow.get(day, 0)
        balance += i - o
        if day >= start:
            out.append(DailyCash(day, i, o, balance))
        day += timedelta(days=1)
    return out


def breach_windows(days: list[DailyCash], min_krw: int = COVENANT_MIN_KRW) -> list[Window]:
    """종가가 min_krw 미만인 연속 구간들."""
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


def official_forecast_gap() -> dict:
    forecast = read_table("02_masil/financials/fin_cash_forecast_ms.csv")
    official_min = min(r["projected_closing_krw"] for r in forecast)
    defined_min = min(d.closing for d in simulate_cash(SIM_START, date(2026, 10, 31)))
    return {
        "official_min": official_min,
        "defined_min": defined_min,
        "causes": [
            "7/21 발주 대금 14건 약 37.5억 일시 유출이 주별 평균 전망에 반영되지 않음",
            "LC-0001(CH-03) 결제조건 45일→90일 변경으로 회수가 8/23~9/6로 밀림(채널 마스터는 아직 45일)",
        ],
    }
