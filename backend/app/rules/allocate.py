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
    # 재고·물류가 모자라 공지 예약분을 못 채운 양(이상 신호). 품절과 섞지 않는다.
    reservation_shortfall: dict[str, int] = field(default_factory=dict)


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
    pct = f"{config.CAPACITY_FALLBACK_RATIO:.0%}"
    hit = RuleHit(
        rule_id="capacity_fallback",
        text=(
            f"안정 처리량 없음: 최대 {maximum:,}의 {pct}인 {cap:,}을 쓴다 "
            f"(Kingman 대기행렬 관행: 가동률 {pct}를 넘으면 대기가 급증)"
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
        if p not in line_of:
            raise ValueError(f"예약 기안 {p}의 라인을 모른다")
        if line_of[p] not in stock_by_line:
            raise ValueError(f"라인 {line_of[p]}의 재고를 모른다")

    stock = dict(stock_by_line)
    cap_left = capacity
    shipped: dict[str, int] = {}
    sold_out: dict[str, int] = {}
    shortfall: dict[str, int] = {}
    # ② 남은 공지 수량을 먼저 뗀다. 같은 비율 원칙: 남은 공지 수량 비율대로(순서 무관).
    res_line: dict[str, int] = {}
    for p, q in reserved.items():
        res_line[line_of[p]] = res_line.get(line_of[p], 0) + q
    # 물류는 수요 없는 날 미리 잠그지 않는다: 분모는 그날 예약 경로 기안들의 want 합계
    wants = {p: min(demand.get(p, 0), q) for p, q in reserved.items()}
    want_total = sum(wants.values())
    if cap_left is None or want_total == 0:
        rcap = Fraction(1)
    else:
        rcap = min(Fraction(1), Fraction(cap_left, want_total))
    for p, q in reserved.items():
        ln = line_of[p]
        rstock = (
            min(Fraction(1), Fraction(stock[ln], res_line[ln])) if res_line[ln] else Fraction(1)
        )
        want = wants[p]
        n = min(want, floor(want * rcap), floor(q * rstock))
        shipped[p] = n
        shortfall[p] = want - n
        sold_out[p] = max(0, demand.get(p, 0) - q)  # 상한 초과분은 이월하지 않는다
    if cap_left is not None:
        cap_left = max(0, cap_left - sum(shipped[p] for p in reserved))
    # 예약 잠금: 남은 공지 수량은 수요가 없어도 다른 기안이 못 쓴다
    for ln, q in res_line.items():
        stock[ln] = max(0, stock[ln] - q)

    pool = {p: q for p, q in demand.items() if p not in reserved}
    carry: dict[str, int] = {p: 0 for p in reserved}
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
    for p, q in pool.items():
        ratio = min(cap_ratio, stock_ratio[line_of[p]])
        shipped[p] = min(q, floor(q * ratio))
        carry[p] = q - shipped[p]  # ⑥ 이월
    return DayAllocation(
        day=day,
        shipped=shipped,
        carry=carry,
        capacity_ratio=float(cap_ratio),
        stock_ratio={ln: float(r) for ln, r in stock_ratio.items()},
        sold_out=sold_out,
        reservation_shortfall=shortfall,
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
    """날마다 재고 += 입고 - 평소 판매 - 보낸 양. 공지 수량은 공지일부터 누적 상한."""
    if end < start:
        raise ValueError("end가 start보다 앞")
    announced = announced or {}
    stock = dict(opening_stock)
    scm_left = dict(scm_allowance or {})
    carry: dict[str, int] = {}
    cum: dict[str, int] = {}  # 공지 기안의 누적 보낸 양
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
        reserved = {p: q - cum.get(p, 0) for p, (d, q) in announced.items() if d <= day}
        lines = {line_of[p] for p in (*demand, *reserved) if p in line_of}
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
        for p in reserved:
            cum[p] = cum.get(p, 0) + res.shipped.get(p, 0)
        carry = {p: q for p, q in res.carry.items() if q > 0}
        out.append(res)
        day += timedelta(days=1)
    return out


def can_announce(
    plan_id: str,
    day: date,
    qty: int,
    line_of: dict[str, str],
    stock_by_line: dict[str, int],
    capacity: int | None,
    reserved_by_line: dict[str, int] | None = None,
    reserved_capacity: int = 0,
) -> bool:
    """예약 시뮬레이션: 쓸 수 있는 재고(안전재고 위 + SCM 허용분)와 물류 처리 능력에서
    이미 예약된 양을 빼고도 qty를 먼저 뗄 수 있으면 True. day는 호출 기록용이다."""
    if qty < 0 or reserved_capacity < 0:
        raise ValueError("qty·reserved_capacity가 음수")
    if plan_id not in line_of or line_of[plan_id] not in stock_by_line:
        raise ValueError(f"기안 {plan_id}의 라인 또는 재고를 모른다")
    ln = line_of[plan_id]
    free = stock_by_line[ln] - (reserved_by_line or {}).get(ln, 0)
    if free < qty:
        return False
    return capacity is None or capacity - reserved_capacity >= qty


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
        for name, d in (
            ("safety_min_weeks", safety_min_weeks),
            ("safety_max_weeks", safety_max_weeks),
        ):
            if sku not in d:
                raise ValueError(f"{sku}가 {name}에 없다")
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
