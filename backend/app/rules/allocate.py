"""재고 장부와 같은 비율 배분, 공지 수량 고정 (설계 4.5). 순수 함수만 둔다.

단위: 재고·입고·평소 판매·안전재고·SCM 허용분은 라인(line) 단위,
원하는 양·보낸 양·이월·공지는 기안(plan) 단위. line_of가 기안을 라인에 잇는다.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
from fractions import Fraction
from math import floor
from typing import Literal

from app import config
from app.rules.models import RuleHit


@dataclass(frozen=True)
class DayAllocation:
    day: date
    shipped: dict[str, int]
    carry: dict[str, int]
    capacity_ratio: float
    stock_ratio: dict[str, float]  # 라인별
    sold_out: dict[str, int] = field(default_factory=dict)


def usable_capacity(
    stable: int | None, maximum: int | None
) -> tuple[int | None, tuple[RuleHit, ...]]:
    for v in (stable, maximum):
        if v is not None and v < 0:
            raise ValueError("처리량은 음수일 수 없다")
    if stable is not None:
        return stable, ()
    if maximum is None:
        return None, ()
    cap = floor(maximum * config.CAPACITY_FALLBACK_RATIO)
    hit = RuleHit(
        rule_id="capacity_fallback",
        text=(
            f"안정 처리량 없음: 최대 {maximum:,}의 85%인 {cap:,}을 쓴다 "
            "(Kingman 대기행렬 관행: 가동률 85%를 넘으면 대기가 급증)"
        ),
        source="설계 4.5",
        badge="가정",
    )
    return cap, (hit,)


def _check_nonneg(name: str, d: dict[str, int]) -> None:
    for k, v in d.items():
        if v < 0:
            raise ValueError(f"{name}[{k}]가 음수: {v}")


def allocate_day(
    day: date,
    demand: dict[str, int],
    line_of: dict[str, str],
    stock_by_line: dict[str, int],
    capacity: int | None,
    reserved: dict[str, int] | None = None,
) -> DayAllocation:
    """stock_by_line은 이미 '쓸 수 있는 재고'(안전재고 위 여유분 + SCM 허용분)."""
    reserved = reserved or {}
    _check_nonneg("demand", demand)
    _check_nonneg("stock", stock_by_line)
    _check_nonneg("reserved", reserved)
    if capacity is not None and capacity < 0:
        raise ValueError("capacity가 음수")
    for p in demand:
        if p not in line_of:
            raise ValueError(f"기안 {p}의 라인을 모른다")
        if line_of[p] not in stock_by_line:
            raise ValueError(f"라인 {line_of[p]}의 재고를 모른다")
    for p in reserved:
        if p not in demand:
            raise ValueError(f"예약 기안 {p}에 원하는 양이 없다")

    stock = dict(stock_by_line)
    cap_left = capacity
    shipped: dict[str, int] = {}
    sold_out: dict[str, int] = {}
    # ② 공지 예약분을 먼저 뗀다 (자기 원하는 양·재고·남은 처리량을 넘기지 않는다)
    for p, q in reserved.items():
        n = min(q, demand[p], stock[line_of[p]])
        if cap_left is not None:
            n = min(n, cap_left)
            cap_left -= n
        stock[line_of[p]] -= n
        shipped[p] = n
        sold_out[p] = demand[p] - n  # 넘친 양은 이월하지 않는다

    pool = {p: q for p, q in demand.items() if p not in reserved}
    # ③ 라인별 재고 비율
    line_demand: dict[str, int] = {}
    for p, q in pool.items():
        line_demand[line_of[p]] = line_demand.get(line_of[p], 0) + q
    stock_ratio = {
        ln: min(Fraction(1), Fraction(stock[ln], tot)) if tot > 0 else Fraction(1)
        for ln, tot in line_demand.items()
    }
    # ④ 물류 비율
    total = sum(pool.values())
    if cap_left is None or total == 0:
        cap_ratio = Fraction(1)
    else:
        cap_ratio = min(Fraction(1), Fraction(cap_left, total))
    # ⑤ 보내는 양 = min, 내림
    carry: dict[str, int] = {}
    for p, q in pool.items():
        ratio = min(cap_ratio, stock_ratio[line_of[p]])
        shipped[p] = min(q, floor(q * ratio))
        carry[p] = q - shipped[p]  # ⑥ 이월
    for p in reserved:
        carry[p] = 0
    return DayAllocation(
        day=day,
        shipped=shipped,
        carry=carry,
        capacity_ratio=float(cap_ratio),
        stock_ratio={ln: float(r) for ln, r in stock_ratio.items()},
        sold_out=sold_out,
    )


def run_ledger(
    start: date,
    end: date,
    demand_by_day: dict[date, dict[str, int]],
    line_of: dict[str, str],
    opening_stock: dict[str, int],
    inbound: dict[date, dict[str, int]],
    daily_base_sale: dict[str, int],
    capacity_by_day: dict[date, int | None],
    safety_min: dict[str, int],
    announced: dict[str, tuple[date, int]] | None = None,
    scm_allowance: dict[str, int] | None = None,
) -> list[DayAllocation]:
    """날마다 재고 += 입고 - 평소 판매 - 보낸 양. 공지는 공지일 하루만 예약한다."""
    if end < start:
        raise ValueError("end가 start보다 앞")
    announced = announced or {}
    stock = dict(opening_stock)
    scm_left = dict(scm_allowance or {})
    carry: dict[str, int] = {}
    out: list[DayAllocation] = []
    day = start
    while day <= end:
        for ln, q in inbound.get(day, {}).items():
            stock[ln] = stock.get(ln, 0) + q
        for ln in stock:
            stock[ln] -= daily_base_sale.get(ln, 0)
        if day not in capacity_by_day:
            raise ValueError(f"{day} capacity 없음 (제한 없음은 None으로 명시)")
        demand = dict(demand_by_day.get(day, {}))
        for p, q in carry.items():
            demand[p] = demand.get(p, 0) + q
        reserved = {p: q for p, (d, q) in announced.items() if d == day and p in demand}
        lines = {line_of[p] for p in demand if p in line_of}
        for ln in lines:
            if ln not in stock:
                raise ValueError(f"라인 {ln}의 재고를 모른다")
        slack = {ln: max(0, stock.get(ln, 0) - safety_min.get(ln, 0)) for ln in lines}
        usable = {ln: slack[ln] + scm_left.get(ln, 0) for ln in lines}
        res = allocate_day(day, demand, line_of, usable, capacity_by_day[day], reserved)
        used: dict[str, int] = {}
        for p, n in res.shipped.items():
            used[line_of[p]] = used.get(line_of[p], 0) + n
        for ln, n in used.items():
            stock[ln] -= n
            over = max(0, n - slack[ln])  # 안전재고를 파고든 만큼 SCM 허용분 소진
            if over:
                scm_left[ln] = scm_left.get(ln, 0) - over
        carry = {p: q for p, q in res.carry.items() if q > 0}
        out.append(res)
        day += timedelta(days=1)
    return out


def can_announce(plan_id: str, day: date, qty: int, allocation: DayAllocation) -> bool:
    if qty < 0:
        raise ValueError("qty가 음수")
    if allocation.day != day:
        return False
    return allocation.shipped.get(plan_id, 0) >= qty


def stockout_days_earlier(used_qty: int, daily_base_sale: float) -> float:
    if daily_base_sale <= 0:
        raise ValueError("평소 판매량은 0보다 커야 한다")
    if used_qty < 0:
        raise ValueError("used_qty가 음수")
    return used_qty / daily_base_sale


def stock_alerts(
    ending_stock: dict[str, int],
    weekly_sale: dict[str, float],
    safety_min_weeks: dict[str, int],
    safety_max_weeks: dict[str, int],
) -> list[tuple[str, Literal["재고 과잉", "재고 부족"]]]:
    out: list[tuple[str, Literal["재고 과잉", "재고 부족"]]] = []
    for sku, stock in ending_stock.items():
        sale = weekly_sale.get(sku)
        if sale is None or sale <= 0:
            raise ValueError(f"{sku}의 주간 판매량이 없거나 0 이하: 주수를 계산할 수 없다")
        if stock < 0:
            raise ValueError(f"{sku}의 재고가 음수")
        weeks = stock / sale
        if weeks > safety_max_weeks[sku]:
            out.append((sku, "재고 과잉"))
        elif weeks < safety_min_weeks[sku]:
            out.append((sku, "재고 부족"))
    return out
