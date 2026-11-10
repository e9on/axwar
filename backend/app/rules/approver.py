"""승인권자 판정(설계 4.1). 순수 함수, 원본 데이터를 읽지 않는다."""
from datetime import date

from app import policy
from app.calc.cash import Window
from app.rules.models import (
    ApproverChange,
    ApproverDecision,
    ContractFacts,
    PlanFacts,
    RuleHit,
)

POLICY = "approval_authority_policy.md"


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


def _covenant_hit(day: date, windows: list[Window]) -> RuleHit | None:
    for w in windows:
        if w.start <= day <= w.end:
            return RuleHit(
                "covenant_window",
                f"집행일 {_md(day)}이 하회 구간({_md(w.start)}~{_md(w.end)}) 안이라 "
                "covenant 규정에 따라 CEO·이사회 승인",
                POLICY, "원본")
    return None


def _opposite_extra(approvers: tuple[str, ...], opposite: bool, text: str):
    """지표 반대면 최상위 승인권자에 따라 추가 승인을 붙인다."""
    if not opposite:
        return approvers, []
    if "CEO" in approvers:
        extra = "이사회 의결"
    elif "Masil 대표" in approvers:
        extra = "그룹 확인"
    else:
        return approvers, []
    hit = RuleHit("indicator_opposite", f"{text}라 {extra} 추가", "계산", "계산")
    return approvers + (extra,), [hit]


def decide_plan(p: PlanFacts, windows: list[Window]) -> ApproverDecision:
    item_limit = policy.get("approval.item_limit_krw")
    total_limit = policy.get("approval.total_limit_krw")
    item_txt, total_txt = _limit_text(item_limit), _limit_text(total_limit)
    hits: list[RuleHit] = []
    cov = _covenant_hit(p.settlement_date, windows)
    if cov:
        approvers: tuple[str, ...] = ("CEO", "이사회")
        hits.append(cov)
    elif p.amount_krw > item_limit or p.plan_total_krw > total_limit:
        approvers = ("Masil 대표", "그룹 보고")
        if p.amount_krw > item_limit:
            hits.append(RuleHit(
                "plan_item_over_1천만",
                f"건별 {_won(p.amount_krw)}이 {item_txt} 초과라 Masil 대표 승인·그룹 보고",
                POLICY, "원본"))
        if p.plan_total_krw > total_limit:
            hits.append(RuleHit(
                "plan_total_over_1억",
                f"기안 총액 {_won(p.plan_total_krw)}이 {total_txt} 초과라 Masil 대표 승인·그룹 보고",
                POLICY, "원본"))
    else:
        approvers = ("마케팅팀",)
        hits.append(RuleHit(
            "plan_within_delegation",
            f"건별 {item_txt} 이하, 기안 총액 {total_txt} 이하라 마케팅팀 전결",
            POLICY, "원본"))
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
    cov = _covenant_hit(c.deadline, windows)
    if cov:
        approvers: tuple[str, ...] = ("CEO", "이사회")
        hits.append(cov)
    elif c.annual_fixed_krw > contract_limit:
        approvers = ("CEO", "이사회")
        hits.append(RuleHit(
            "contract_over_10억",
            f"전속계약 연 {_won(c.annual_fixed_krw)}이 {limit_txt} 초과라 CEO·이사회 승인",
            POLICY, "원본"))
    else:
        approvers = ("Masil 대표",)
        hits.append(RuleHit(
            "contract_under_10억",
            f"전속계약 연 {_won(c.annual_fixed_krw)}이 {limit_txt} 이하라 Masil 대표 승인",
            POLICY, "원본"))
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
    parts = [h.text for h in changed] or [h.text for h in new.hits]
    reason = (f"집행일 {_md(at)} 기준으로 승인권자가 {'·'.join(old.approvers)}에서 "
              f"{'·'.join(new.approvers)}로 바뀜: " + "; ".join(parts))
    return ApproverChange(old.approvers, new.approvers, reason, changed, at)
