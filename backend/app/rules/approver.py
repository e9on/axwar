"""승인권자 판정(설계 4.1). 순수 함수, 원본 데이터를 읽지 않는다."""
# hardcode-allow: 100_000_000 10_000 (억·만 단위 표기 변환, 정책 값 아님)
from datetime import date, timedelta

from app import policy
from app.calc.cash import Window
from app.rules.josa import josa
from app.rules.models import (
    ApproverChange,
    ApproverDecision,
    ContractFacts,
    PlanFacts,
    RuleHit,
    make_detail,
)

POLICY = "approval_authority_policy.md"
# 하회 구간 계산이 읽는 원본 파일(04_원본데이터 아래 상대 경로)
_CASH_SOURCES = ("02_masil/financials/fin_cash_daily_ms.csv", "02_masil/financials/fin_ar_aging_ms.csv",
                 "02_masil/financials/fin_ap_aging_ms.csv", "02_masil/inventory/sc_purchase_orders_ms.csv")


def _ceo() -> str:
    """최상위 승인권자 역할(정책 roles.ceo): 하회 구간·계약 한도 초과 승인, 지표 반대면 이사회 의결 추가."""
    return policy.get("roles.ceo")


def _head() -> str:
    """대표급 승인권자 역할(정책 roles.head): 건별·총액·계약 한도 판정, 지표 반대면 그룹 확인 추가."""
    return policy.get("roles.head")


def _md(d: date) -> str:
    return f"{d.month}/{d.day}"


def _won(n: int) -> str:
    return f"{n:,}원"


def _limit_text(n: int) -> str:
    """기준 금액을 사람이 읽는 말로(예: 1천만원, 1억원, 10억원). 맞지 않으면 쉼표 표기."""
    eok, rest = divmod(n, 100_000_000)
    man, low = divmod(rest, 10_000)
    if low:
        return _won(n)
    parts = []
    if eok:
        parts.append(f"{eok}억")
    if man:
        parts.append(f"{man // 1000}천만" if man % 1000 == 0 and man >= 1000 else f"{man}만")
    return "".join(parts) + "원"


def _covenant_hit(day: date, windows: list[Window], label: str = "집행일") -> RuleHit | None:
    ceo = _ceo()
    for w in windows:
        if w.start <= day <= w.end:
            return RuleHit(
                "covenant_window",
                f"{label} {_md(day)}이 하회 구간({_md(w.start)}~{_md(w.end)}) 안이라 "
                f"covenant 규정에 따라 {ceo}·이사회 승인",
                POLICY, "원본",
                make_detail(
                    f"{label}이 현금 하회 구간(예상 잔액이 약정 최저 잔액 밑인 연속 구간) 안이면 covenant 규정에 따라 {ceo}·이사회 승인",
                    ((label, day.isoformat()), ("하회 구간 시작", w.start.isoformat()), ("하회 구간 끝", w.end.isoformat())),
                    _CASH_SOURCES, ("cash.horizon_days",)))
    return None


def _opposite_extra(approvers: tuple[str, ...], opposite: bool, text: str):
    """지표 반대면 최상위 승인권자에 따라 추가 승인을 붙인다."""
    if not opposite:
        return approvers, []
    top = _ceo() if _ceo() in approvers else _head() if _head() in approvers else None
    if top == _ceo():
        extra = "이사회 의결"
    elif top == _head():
        extra = "그룹 확인"
    else:
        return approvers, []
    hit = RuleHit("indicator_opposite", f"{text}라 {extra} 추가", "계산", "계산", make_detail(
        f"결정 방향이 지표와 반대이고 최상위 승인권자가 {josa(top, '이면')} {josa(extra, '을를')} 추가 "
        "(확대·갱신인데 지표가 나쁘거나, 축소·해지인데 지표가 좋은 경우)"))
    return approvers + (extra,), [hit]


def decide_plan(p: PlanFacts, windows: list[Window]) -> ApproverDecision:
    item_limit = policy.get("approval.item_limit_krw")
    total_limit = policy.get("approval.total_limit_krw")
    item_txt, total_txt = _limit_text(item_limit), _limit_text(total_limit)
    hits: list[RuleHit] = []
    cov = _covenant_hit(p.settlement_date, windows)
    if cov:
        approvers: tuple[str, ...] = (_ceo(), "이사회")
        hits.append(cov)
    elif p.amount_krw > item_limit or p.plan_total_krw > total_limit:
        approvers = (_head(), "그룹 보고")
        if p.amount_krw > item_limit:
            hits.append(RuleHit(
                "plan_item_over_limit",
                f"건별 {_won(p.amount_krw)}이 {item_txt} 초과라 {_head()} 승인·그룹 보고",
                POLICY, "원본",
                make_detail(f"건별 요청액이 건별 한도를 넘으면 {_head()} 승인·그룹 보고",
                            (("건별 요청액", p.amount_krw), ("건별 한도", item_limit)), (), ("approval.item_limit_krw",))))
        if p.plan_total_krw > total_limit:
            hits.append(RuleHit(
                "plan_total_over_limit",
                f"기안 총액 {_won(p.plan_total_krw)}이 {total_txt} 초과라 {_head()} 승인·그룹 보고",
                POLICY, "원본",
                make_detail(f"같은 기안 문서의 요청액 합계가 총액 한도를 넘으면 {_head()} 승인·그룹 보고",
                            (("기안 총액", p.plan_total_krw), ("총액 한도", total_limit)), (), ("approval.total_limit_krw",))))
    else:
        approvers = ("마케팅팀",)
        hits.append(RuleHit(
            "plan_within_delegation",
            f"건별 {item_txt} 이하, 기안 총액 {total_txt} 이하라 마케팅팀 전결",
            POLICY, "원본",
            make_detail("건별 요청액이 건별 한도 이하이고 기안 총액이 총액 한도 이하면 마케팅팀 전결",
                        (("건별 요청액", p.amount_krw), ("건별 한도", item_limit), ("기안 총액", p.plan_total_krw),
                         ("총액 한도", total_limit)), (), ("approval.item_limit_krw", "approval.total_limit_krw"))))
    opposite = (p.direction == "확대" and not p.indicator_good) or (
        p.direction == "축소" and p.indicator_good)
    text = ("확대인데 지표가 나쁜 반대 상황" if p.direction == "확대"
            else "축소인데 지표가 좋은 반대 상황")
    approvers, extra = _opposite_extra(approvers, opposite, text)
    return ApproverDecision(approvers, tuple(hits + extra))


def decide_contract(c: ContractFacts, windows: list[Window]) -> ApproverDecision:
    contract_limit = policy.get("approval.contract_limit_krw")
    limit_txt = _limit_text(contract_limit)
    hits: list[RuleHit] = []
    # 현금이 나가기 시작하는 재계약 시작일(만료 다음 날) 기준 — 사용자 지정(2026-11-11)
    cov = _covenant_hit(c.expiry + timedelta(days=1), windows, "재계약 시작일")
    if cov:
        approvers: tuple[str, ...] = (_ceo(), "이사회")
        hits.append(cov)
    elif c.annual_fixed_krw > contract_limit:
        approvers = (_ceo(), "이사회")
        hits.append(RuleHit(
            "contract_over_limit",
            f"전속계약 연 {_won(c.annual_fixed_krw)}이 {limit_txt} 초과라 {_ceo()}·이사회 승인",
            POLICY, "원본",
            make_detail(f"전속계약 연 금액이 계약 한도를 넘으면 {_ceo()}·이사회 승인",
                        (("연 전속 금액", c.annual_fixed_krw), ("계약 한도", contract_limit)), (), ("approval.contract_limit_krw",))))
    else:
        approvers = (_head(),)
        hits.append(RuleHit(
            "contract_within_limit",
            f"전속계약 연 {_won(c.annual_fixed_krw)}이 {limit_txt} 이하라 {_head()} 승인",
            POLICY, "원본",
            make_detail(f"전속계약 연 금액이 계약 한도 이하면 {_head()} 승인",
                        (("연 전속 금액", c.annual_fixed_krw), ("계약 한도", contract_limit)), (), ("approval.contract_limit_krw",))))
    opposite = (c.direction == "갱신" and not c.indicator_good) or (
        c.direction == "해지" and c.indicator_good)
    text = ("갱신인데 지표가 나쁜 반대 상황" if c.direction == "갱신"
            else "해지인데 지표가 좋은 반대 상황")
    approvers, extra = _opposite_extra(approvers, opposite, text)
    return ApproverDecision(approvers, tuple(hits + extra))


def diff_approver(old: ApproverDecision, new: ApproverDecision, at: date) -> ApproverChange | None:
    if old.approvers == new.approvers:
        return None
    old_ids = {h.rule_id for h in old.hits}
    new_ids = {h.rule_id for h in new.hits}
    gone = [h for h in old.hits if h.rule_id not in new_ids]
    came = [h for h in new.hits if h.rule_id not in old_ids]
    changed = tuple(gone + came)
    # 새 근거와 해제된 근거를 나눠 적는다(해제된 근거의 옛 값이 현재 근거처럼 읽히지 않게)
    now = [h.text for h in came] or [h.text for h in new.hits]
    reason = (f"집행일 {_md(at)} 기준으로 승인권자가 {'·'.join(old.approvers)}에서 "
              f"{'·'.join(new.approvers)}로 바뀜. 새 근거: " + "; ".join(now))
    if gone:
        reason += ". 더는 적용되지 않는 근거: " + "; ".join(h.text for h in gone)
    return ApproverChange(old.approvers, new.approvers, reason, changed, at)
