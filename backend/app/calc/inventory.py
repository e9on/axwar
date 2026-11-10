"""SKU 여유 재고와 입고 예정일. 원본 CSV만 읽는다."""
import math
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
