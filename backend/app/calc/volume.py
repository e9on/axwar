"""기안 물량과 날짜별 부하(25건 공통 공식). 원본 CSV만 읽는다.

주 = 주문일이 속한 주의 월요일. hist_units = Σ(캠페인 표본 주문 수 / 그 주·SKU 전체
표본 주문 수 × 실제 sold_qty). multiplier = 기안 expected_gmv / 캠페인 표본 GMV.
일별 비중 = (주문일 - 캠페인 시작일) 일수별 주문 수 / 총 주문 수. 최대 비중 일수를
settlement_date에 맞춘다. 최대 비중이 동률이면 가장 작은 일수를 최대일로 한다.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from app.data.loader import read_table

_MKT = "02_masil/marketing/"


@dataclass(frozen=True)
class PlanVolume:
    plan_id: str
    campaign_id: str
    product_line: str
    multiplier: float
    hist_units: float
    plan_units: float
    peak_share: float
    sample_share: float
    low_confidence: bool


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _plans() -> list[dict]:
    return read_table(_MKT + "mkt_budget_plan_ms.csv")


def _campaigns() -> dict[str, dict]:
    return {r["campaign_id"]: r for r in read_table("02_masil/master/m_campaign_ms.csv")}


def _orders_by_campaign() -> tuple[dict[str, list[dict]], Counter]:
    by_camp: dict[str, list[dict]] = defaultdict(list)
    total: Counter = Counter()  # (sku, 월요일) -> 전체 표본 주문 수
    for o in read_table(_MKT + "mkt_orders_ms.csv"):
        total[(o["sku_id"], _monday(o["order_date"]))] += 1
        if o["campaign_id"] is not None:
            by_camp[o["campaign_id"]].append(o)
    return by_camp, total


def _sold() -> dict[tuple[str, date], float]:
    return {(r["sku_id"], r["week"]): r["sold_qty"] for r in read_table("02_masil/inventory/sku_weekly_sales_ms.csv")}


def _day_shares(plan: dict, orders: list[dict], campaign: dict) -> dict[int, float]:
    n = len(orders)
    days = Counter((o["order_date"] - campaign["start_date"]).days for o in orders)
    return {dd: c / n for dd, c in days.items()}


def _volume(plan: dict, campaigns, by_camp, total, sold) -> PlanVolume:
    cid = plan["campaign_id"]
    camp = campaigns[cid]
    orders = by_camp[cid]
    pairs = Counter((o["sku_id"], _monday(o["order_date"])) for o in orders)
    hist = sum(c / total[k] * sold[k] for k, c in pairs.items() if k in sold)
    sample_share = sum(pairs.values()) / sum(total[k] for k in pairs)
    gmv = sum(o["gmv_krw"] for o in orders)
    multiplier = plan["expected_gmv_krw"] / gmv
    shares = _day_shares(plan, orders, camp)
    return PlanVolume(
        plan_id=plan["plan_id"],
        campaign_id=cid,
        product_line=camp["product_line"],
        multiplier=multiplier,
        hist_units=hist,
        plan_units=hist * multiplier,
        peak_share=max(shares.values()),
        sample_share=sample_share,
        low_confidence=sample_share >= 0.9,
    )


def all_plan_volumes() -> list[PlanVolume]:
    campaigns = _campaigns()
    by_camp, total = _orders_by_campaign()
    sold = _sold()
    return [_volume(p, campaigns, by_camp, total, sold) for p in _plans()]


def plan_volume(plan_id: str) -> PlanVolume:
    for v in all_plan_volumes():
        if v.plan_id == plan_id:
            return v
    raise KeyError(plan_id)


def _daily_loads() -> dict[str, dict[date, float]]:
    campaigns = _campaigns()
    by_camp, total = _orders_by_campaign()
    sold = _sold()
    out: dict[str, dict[date, float]] = {}
    for p in _plans():
        v = _volume(p, campaigns, by_camp, total, sold)
        shares = _day_shares(p, by_camp[p["campaign_id"]], campaigns[p["campaign_id"]])
        peak_day = max(shares, key=lambda dd: (shares[dd], -dd))  # 동률이면 가장 이른 일수
        out[p["plan_id"]] = {
            p["settlement_date"] + timedelta(days=dd - peak_day): v.plan_units * s for dd, s in shares.items()
        }
    return out


def daily_load(plan_id: str) -> dict[date, float]:
    return _daily_loads()[plan_id]


def total_daily_load(start: date, end: date) -> dict[date, dict[str, float]]:
    out: dict[date, dict[str, float]] = defaultdict(dict)
    for pid, load in _daily_loads().items():
        for d, units in load.items():
            if start <= d <= end:
                out[d][pid] = units
    return dict(out)
