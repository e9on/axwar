"""분할안 작성과 2차 집행 중단 판정. 순수 함수."""
import math
from dataclasses import dataclass
from datetime import date, timedelta

from app import policy
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
    blocked: bool = False  # 갱신 미확정인데 2차 집행일이 계약 만료 뒤(또는 날짜 없음): 시간이 지나도 못 연다


def make_split(
    requested_qty: int,
    logistics_limit: int,
    spare_stock: int,
    phase1_date: date,
    restock_date: date,
    windows: list[Window],
    contract_end: date,
    observe_days: int | None = None,
) -> SplitPlan:
    if observe_days is None:
        observe_days = policy.get("split.return_observe_days")
    phase1 = max(0, min(logistics_limit, spare_stock, requested_qty))
    phase2 = requested_qty - phase1
    # 반품 관찰이 끝난 뒤 승인할 여유(기본 거부 여유 + 최소 승인 일수)까지 둔 날 이후로 계획한다(중간에 2차 집행일을 미루지 않게)
    approval_room = policy.get("deadline.buffer_days") + policy.get("phase2.min_approval_days")
    candidates = [restock_date + timedelta(days=1), phase1_date + timedelta(days=observe_days + approval_room)]
    if windows:
        candidates.append(max(w.end for w in windows) + timedelta(days=1))
    p2_date: date | None = max(candidates) if phase2 > 0 else None
    hits: list[RuleHit] = []
    if p2_date is not None and p2_date > contract_end:
        hits.append(RuleHit(
            "split_expiry",
            f"2차 집행일 {p2_date}이 계약 만료({contract_end}) 뒤라 날짜를 정할 수 없다",
            "계약 만료일", "계산",
        ))
        p2_date = None
    return SplitPlan(phase1, phase1_date, phase2, p2_date, tuple(hits))


CHANGE_OF_MIND, COLOR_RETURN = "단순변심", "색상불만"  # 원본 반품 사유 값이자 2차 게이트의 반품 항목 이름
RETURN_KEYS = {CHANGE_OF_MIND: "change_of_mind", COLOR_RETURN: "color"}  # 반품 사유 -> 건에 저장하는 반품 건수 키. 게이트와 관찰 화면이 같이 읽음


def observation_done(days_since_phase1: int, observe_days: int | None = None) -> bool:
    """반품 관찰 기간(정책 split.return_observe_days)이 끝났는지. 2차 게이트와 관찰 화면이 같이 씀."""
    if observe_days is None:
        observe_days = policy.get("split.return_observe_days")
    return days_since_phase1 >= observe_days


def return_stop_threshold(baseline: float, n_orders: int, z: float | None = None) -> float:
    if z is None:
        z = policy.get("split.stop_z")
    if n_orders <= 0:
        raise ValueError("1차 주문 수는 1 이상이어야 함")
    return baseline + z * math.sqrt(baseline * (1 - baseline) / n_orders)


def return_check(count: int, n_orders: int, baseline: float, z: float | None = None) -> dict:
    """반품 건수 하나의 통계 기준 판정: 반품률, 한계값(기준선 + z × 표준오차), 초과 여부. 2차 게이트와 관찰 화면이 같이 쓴다."""
    rate = count / n_orders
    limit = return_stop_threshold(baseline, n_orders, z)
    return {"rate": rate, "limit": limit, "over": rate > limit}


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
    observe_days: int | None = None,
) -> GateResult:
    reasons: list[str] = []
    actions: list[str] = []
    auto_stopped = False

    if observe_days is None:
        observe_days = policy.get("split.return_observe_days")
    if not observation_done(days_since_phase1, observe_days):
        reasons.append(f"관찰 {observe_days}일 미만({days_since_phase1}일)")
    if phase1_orders <= 0:
        reasons.append("1차 주문 0건: 반품 판정 불가")

    for label, count, base in (
        (CHANGE_OF_MIND, change_of_mind_returns, baseline_change_of_mind),
        (COLOR_RETURN, color_returns, baseline_color),
    ):
        if phase1_orders > 0:
            chk = return_check(count, phase1_orders, base)
            if chk["over"]:
                auto_stopped = True
                reasons.append(f"{label} 반품률 {chk['rate']:.1%}이 기준 {chk['limit']:.1%} 초과")
    if auto_stopped:
        actions.append("2차 자동 보류")

    if color_review_flagged and not content_fix_confirmed:
        reasons.append("리뷰 색상불일치 표시, 콘텐츠 수정 미확인")
        actions.extend(["콘텐츠 수정 요청", "사람 확인"])

    blocked = not renewal_confirmed and phase2_date > contract_end
    if blocked:
        reasons.append("갱신 미확정인데 2차 집행일이 계약 만료 뒤")

    return GateResult(not reasons, auto_stopped, tuple(reasons), tuple(actions), blocked)
