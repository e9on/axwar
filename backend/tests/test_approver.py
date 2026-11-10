from datetime import date

from app.calc.cash import Window
from app.rules.approver import decide_contract, decide_plan, diff_approver
from app.rules.models import ContractFacts, PlanFacts

W = [Window(date(2026, 7, 21), date(2026, 8, 22))]
TOTAL = 180_803_272


def plan(amount, settle, total=TOTAL, direction="확대", good=True, pid="PLAN-X"):
    return PlanFacts(pid, "CAMP-1", "INF-1", amount, total, settle,
                     date(2026, 7, 20), direction, good)


def contract(annual, direction="갱신", good=True):
    return ContractFacts("CT-1", annual, date(2026, 7, 20), date(2026, 12, 31), direction, good)


def ids(d):
    return {h.rule_id for h in d.hits}


def test_PLAN001은_하회구간이라_CEO와_이사회_그리고_지표반대로_의결추가():
    d = decide_plan(plan(18_962_703, date(2026, 7, 27), good=False, pid="PLAN-001"), W)
    assert d.approvers == ("CEO", "이사회", "이사회 의결")
    assert {"covenant_window", "indicator_opposite"} <= ids(d)


def test_PLAN019는_대표와_그룹보고():
    d = decide_plan(plan(4_807_921, date(2026, 9, 14), pid="PLAN-019"), W)
    assert d.approvers == ("Masil 대표", "그룹 보고")
    assert "plan_total_over_1억" in ids(d)


def test_건별_1천만원과_총액_1억원_이하는_마케팅_전결():
    d = decide_plan(plan(10_000_000, date(2026, 9, 30), total=90_000_000), W)
    assert d.approvers == ("마케팅팀",)
    assert "plan_within_delegation" in ids(d)


def test_건별_1천만원_초과는_대표():
    d = decide_plan(plan(10_000_001, date(2026, 9, 30), total=90_000_000), W)
    assert d.approvers == ("Masil 대표", "그룹 보고")
    assert "plan_item_over_1천만" in ids(d)


def test_구간_경계일은_포함():
    for day in (date(2026, 7, 21), date(2026, 8, 22)):
        assert decide_plan(plan(1_000, day, total=1_000), W).approvers[0] == "CEO"
    for day in (date(2026, 7, 20), date(2026, 8, 23)):
        assert decide_plan(plan(1_000, day, total=1_000), W).approvers[0] != "CEO"


def test_전속계약_28억은_CEO와_이사회():
    d = decide_contract(contract(2_800_000_000), W)
    assert d.approvers == ("CEO", "이사회")
    assert "contract_over_10억" in ids(d)


def test_전속계약_10억_이하는_대표():
    d = decide_contract(contract(1_000_000_000), W)
    assert d.approvers == ("Masil 대표",)
    assert "contract_under_10억" in ids(d)


def test_지표_좋은데_줄이면_추가승인():
    d = decide_plan(plan(20_000_000, date(2026, 9, 30), direction="축소", good=True), W)
    assert "그룹 확인" in d.approvers


def test_2차_집행일을_8월24일로_옮기면_CEO에서_대표로_이동():
    old = decide_plan(plan(18_962_703, date(2026, 7, 27), good=False, pid="PLAN-001"), W)
    new = decide_plan(plan(18_962_703, date(2026, 8, 24), good=False, pid="PLAN-001"), W)
    ch = diff_approver(old, new, date(2026, 8, 24))
    assert ch.before[0] == "CEO"
    assert ch.after[0] == "Masil 대표"
    assert "하회 구간" in ch.reason and "8/24" in ch.reason


def test_승인권자가_같으면_변경_없음():
    d = decide_plan(plan(4_807_921, date(2026, 9, 14)), W)
    assert diff_approver(d, d, date(2026, 9, 14)) is None
