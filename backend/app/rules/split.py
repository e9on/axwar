"""분할안 작성과 2차 집행 중단 판정. 순수 함수."""
import math
from dataclasses import dataclass
from datetime import date, timedelta

from app import config
from app.calc.cash import Window
from app.rules.models import RuleHit


@dataclass(frozen=True)
class SplitPlan:
    phase1_qty: int
    phase1_date: date
    phase2_qty: int
    phase2_date: date | None
    hits: tuple[RuleHit, ...]


@dataclass(frozen=True)
class GateResult:
    open: bool
    auto_stopped: bool
    reasons: tuple[str, ...]
    actions: tuple[str, ...]


def make_split(
    requested_qty: int,
    logistics_limit: int,
    spare_stock: int,
    phase1_date: date,
    restock_date: date,
    windows: list[Window],
    contract_end: date,
    observe_days: int = config.RETURN_OBSERVE_DAYS,
) -> SplitPlan:
    phase1 = max(0, min(logistics_limit, spare_stock, requested_qty))
    phase2 = requested_qty - phase1
    candidates = [restock_date + timedelta(days=1), phase1_date + timedelta(days=observe_days)]
    if windows:
        candidates.append(max(w.end for w in windows) + timedelta(days=1))
    p2_date: date | None = max(candidates)
    hits: list[RuleHit] = []
    if phase2 > 0 and p2_date > contract_end:
        hits.append(RuleHit(
            "SPLIT-EXPIRY",
            f"2차 집행일 {p2_date}이 계약 만료({contract_end}) 뒤라 날짜를 정할 수 없다",
            "계약 만료일", "계산",
        ))
        p2_date = None
    return SplitPlan(phase1, phase1_date, phase2, p2_date, tuple(hits))


def return_stop_threshold(baseline: float, n_orders: int, z: float = config.STOP_Z) -> float:
    return baseline + z * math.sqrt(baseline * (1 - baseline) / n_orders)


def phase2_gate(
    phase1_orders: int,
    change_of_mind_returns: int,
    color_returns: int,
    baseline_change_of_mind: float,
    baseline_color: float,
    days_since_phase1: int,
    color_review_flagged: bool,
    content_fix_confirmed: bool,
    renewal_confirmed: bool,
    phase2_date: date,
    contract_end: date,
) -> GateResult:
    reasons: list[str] = []
    actions: list[str] = []
    auto_stopped = False

    if days_since_phase1 < config.RETURN_OBSERVE_DAYS:
        reasons.append(f"관찰 {config.RETURN_OBSERVE_DAYS}일 미만({days_since_phase1}일)")

    for label, count, base in (
        ("단순변심", change_of_mind_returns, baseline_change_of_mind),
        ("색상불만", color_returns, baseline_color),
    ):
        if phase1_orders > 0:
            rate = count / phase1_orders
            limit = return_stop_threshold(base, phase1_orders)
            if rate > limit:
                auto_stopped = True
                reasons.append(f"{label} 반품률 {rate:.1%}이 기준 {limit:.1%} 초과")
    if auto_stopped:
        actions.append("2차 자동 보류")

    if color_review_flagged and not content_fix_confirmed:
        reasons.append("리뷰 색상불일치 표시, 콘텐츠 수정 미확인")
        actions.extend(["콘텐츠 수정 요청", "사람 확인"])

    if not renewal_confirmed and phase2_date > contract_end:
        reasons.append("갱신 미확정인데 2차 집행일이 계약 만료 뒤")

    return GateResult(not reasons, auto_stopped, tuple(reasons), tuple(actions))
