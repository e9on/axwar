"""SKU 여유 재고와 입고 예정일. 원본 CSV만 읽는다."""
import math
from dataclasses import dataclass
from datetime import date, timedelta

from app.data.loader import read_table

_INV = "02_masil/inventory/"


def _recent_avg_sales(sku_id: str, weeks: int = 4) -> float:
    rows = [r for r in read_table(_INV + "sku_weekly_sales_ms.csv") if r["sku_id"] == sku_id]
    rows.sort(key=lambda r: r["week"])
    last = rows[-weeks:]
    return sum(r["sold_qty"] for r in last) / len(last)


def spare_stock(sku_id: str) -> int:
    """on_hand − 안전재고 최소주수 × 최근 4주 평균 판매량, 정수 내림."""
    inv = [r for r in read_table(_INV + "sku_inventory_ms.csv") if r["sku_id"] == sku_id]
    on_hand = max(inv, key=lambda r: r["snapshot_date"])["on_hand_qty"]
    sku = next(r for r in read_table("02_masil/master/m_sku_ms.csv") if r["sku_id"] == sku_id)
    return math.floor(on_hand - sku["safety_stock_weeks_min"] * _recent_avg_sales(sku_id))


def restock_date(sku_id: str) -> date:
    """발주 order_date + lead_time_weeks × 7일."""
    po = next(r for r in read_table(_INV + "sc_purchase_orders_ms.csv") if r["sku_id"] == sku_id)
    return po["order_date"] + timedelta(days=po["lead_time_weeks"] * 7)


# ---- 재고 장부 (설계 4.5) ----
# 상품(SKU)별로 스냅샷 재고에서 시작해 날마다 (입고 − 평소 판매)를 더한다. 평소 판매 = 최근 4주 평균 ÷ 7.
# 라인 = 상품 분류(category): 같은 분류 상품의 재고·안전재고·판매를 합쳐 본다(기안은 분류 단위로 상품을 가리킨다).
# 다른 기안이 이미 보낸 양은 빼지 않는다(평소 판매만 반영 — 장부는 캠페인 없이 평소 판매만 본 확인값).
_MASTER = "02_masil/master/m_sku_ms.csv"
DAYS_PER_WEEK = 7


@dataclass(frozen=True)
class SkuState:
    sku_id: str
    name: str
    category: str
    stock: float
    weekly_sale: float
    min_weeks: int
    max_weeks: int


def _skus() -> list[dict]:
    return read_table(_MASTER)


def line_skus(category: str) -> list[str]:
    out = [r["sku_id"] for r in _skus() if r["category"] == category]
    if not out:
        raise KeyError(category)
    return out


def _snapshot(sku_id: str) -> dict:
    rows = [r for r in read_table(_INV + "sku_inventory_ms.csv") if r["sku_id"] == sku_id]
    return max(rows, key=lambda r: r["snapshot_date"])


def _inbound(sku_id: str, after: date) -> list[tuple[date, int]]:
    """스냅샷 뒤에 도착하는 발주 입고(도착일 = 발주일 + 리드타임 주수 × 7일)."""
    out = []
    for po in read_table(_INV + "sc_purchase_orders_ms.csv"):
        if po["sku_id"] == sku_id:
            arrive = po["order_date"] + timedelta(days=po["lead_time_weeks"] * DAYS_PER_WEEK)
            if arrive > after:
                out.append((arrive, po["order_qty"]))
    return out


def sku_stock(sku_id: str, day: date) -> float:
    """day 끝의 장부 재고 = 스냅샷 재고 + 그날까지 입고 − 지난 날수 × 평소 판매(하루). 음수도 그대로(바닥난 정도)."""
    snap = _snapshot(sku_id)
    inbound = sum(q for d, q in _inbound(sku_id, snap["snapshot_date"]) if d <= day)
    days = (day - snap["snapshot_date"]).days
    return snap["on_hand_qty"] + inbound - days * _recent_avg_sales(sku_id) / DAYS_PER_WEEK


def line_stock(category: str, day: date) -> int:
    return sum(round(sku_stock(s, day)) for s in line_skus(category))  # 상품별로 반올림해 더함(설계 확인값과 같게)


def line_safety_min(category: str) -> int:
    by_id = {r["sku_id"]: r for r in _skus()}
    return round(sum(by_id[s]["safety_stock_weeks_min"] * _recent_avg_sales(s) for s in line_skus(category)))


def line_spare(category: str, day: date) -> int:
    """쓸 수 있는 재고 = 장부 재고 − 안전재고 최소 주수분, 모자라면 0."""
    return max(0, line_stock(category, day) - line_safety_min(category))


def line_daily_sale(category: str) -> float:
    return sum(_recent_avg_sales(s) for s in line_skus(category)) / DAYS_PER_WEEK


def line_restock_date(category: str) -> date:
    """라인 입고일 = 라인 상품 중 가장 늦게 입고되는 날(모든 상품이 들어온 날)."""
    return max(restock_date(s) for s in line_skus(category))


def stock_state(day: date) -> list[SkuState]:
    """모든 상품의 day 끝 장부 재고와 안전재고 주수(재고 과잉·부족 판정 입력)."""
    return [SkuState(r["sku_id"], r["sku_name"], r["category"], sku_stock(r["sku_id"], day),
                     _recent_avg_sales(r["sku_id"]), r["safety_stock_weeks_min"], r["safety_stock_weeks_max"])
            for r in _skus()]
