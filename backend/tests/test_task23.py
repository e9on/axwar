"""Task 23: 읽기는 저장 값을 바꾸지 않음, 지표 반대 판정의 역할 이름은 정책, AI 브리핑 입력은 지금 결재선."""
from datetime import date

import pytest

from app import policy
from app.calc.cash import Window
from app.engine.flow import Engine
from app.rules.approver import decide_contract, decide_plan
from app.rules.models import ContractFacts, PlanFacts
from app.store.db import open_db


@pytest.fixture
def store(tmp_path):
    s = open_db(tmp_path / "t.db")
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _clean_policy():
    policy.set_overrides({})
    yield
    policy.set_overrides({})


# ---- 1. 읽기가 저장 값을 바꾸지 않게 ----

def _snapshot(store, cid):
    return (store.get_case(cid)["facts"], store.events(cid), store.get_approver_changes(cid),
            store.get_case(cid)["status"])


@pytest.mark.usefixtures("legacy_scenes")
def test_viewer를_줘도_저장된_사실_이벤트_권한이동은_그대로이고_판정만_새_값_기준(store):
    eng = Engine(store)
    cid = eng.seed("scenario_1_escalate")[0]
    eng.run_script("scenario_1_escalate", upto=2)
    row = store.get_plan(store.get_case(cid)["ref_id"])
    before_roles = store.get_case(cid)["facts"]["approvers"]
    assert before_roles == ["마케팅팀"]
    store.update_plan(row["id"], {"requested_budget_krw": 99_000_000}, "시험")  # 건별 한도 초과 -> 승인권자 바뀜
    snap = _snapshot(store, cid)
    d = eng.case_detail(cid, viewer="Masil 대표")
    assert _snapshot(store, cid) == snap  # 읽기는 저장을 바꾸지 않음
    assert d["facts"]["amount_krw"] != 99_000_000
    assert d["viewer"]["role"] == "Masil 대표" and d["viewer"]["can_decide"] is True  # 판정은 새 값 기준
    assert eng.case_detail(cid, viewer="마케팅팀장")["viewer"]["can_decide"] is False
    assert _snapshot(store, cid) == snap
    eng.decide(cid, "Masil 대표", "승인")  # decide는 지금처럼 갱신
    assert store.get_case(cid)["facts"]["amount_krw"] == 99_000_000
    assert len(store.get_approver_changes(cid)) == 1


# ---- 2. 지표 반대 판정의 역할 이름은 정책 ----

W = [Window(date(2026, 7, 21), date(2026, 8, 22))]


def _plan(amount, total, good=False):
    return PlanFacts("PLAN-X", "CAMP-1", "INF-1", amount, total, date(2026, 9, 30), date(2026, 7, 20), "확대", good)


def test_정책의_역할_이름을_바꾸면_지표_반대_추가_승인권자도_따라_바뀐다():
    assert policy.get("roles.ceo") == "CEO" and policy.get("roles.head") == "Masil 대표"
    d = decide_plan(_plan(10_000_001, 90_000_000), W)
    assert d.approvers == ("Masil 대표", "그룹 보고", "그룹 확인")
    policy.set_overrides({"roles.head": ("대표이사", "시험", "t")})
    d = decide_plan(_plan(10_000_001, 90_000_000), W)
    assert d.approvers == ("대표이사", "그룹 보고", "그룹 확인")
    assert "대표이사" in d.hits[0].text and "Masil 대표" not in d.hits[0].text
    policy.set_overrides({"roles.ceo": ("총괄", "시험", "t")})
    c = ContractFacts("CT-1", 9_000_000_000, date(2026, 7, 20), date(2026, 12, 31), "갱신", False)
    d = decide_contract(c, W)
    assert d.approvers[0] == "총괄" and d.approvers[-1] == "이사회 의결"


def test_새_역할_정책은_사람_목록에_없는_이름으로_바꿀_수_없다(store):
    eng = Engine(store)
    with pytest.raises(ValueError):
        eng.change_policy("Masil 대표", "roles.ceo", "없는역할", "시험")


# ---- 3. AI 브리핑 입력이 지금 결재선을 씀 ----

def _esc(store, upto):
    eng = Engine(store)
    cid = eng.seed("scenario_1_escalate")[0]
    eng.run_script("scenario_1_escalate", upto=upto)
    return eng, cid


@pytest.mark.usefixtures("legacy_scenes")
def test_브리핑_입력은_상신_뒤_지금_결재선을_쓰고_옛_전결_문장은_처음_판정으로만(store):
    eng, cid = _esc(store, 2)
    before = eng._brief_basis(store.get_case(cid))
    assert any("마케팅팀 전결" in t and not t.startswith("(처음 판정)") for t in before["규칙 근거"])
    eng.run_script("scenario_1_escalate", upto=3)
    after = eng._brief_basis(store.get_case(cid))
    lines = after["규칙 근거"]
    assert "상신" in lines[0] and not lines[0].startswith("(처음 판정)")
    old = [t for t in lines if "마케팅팀 전결" in t]
    assert old and all(t.startswith("(처음 판정)") for t in old)
    assert eng._fingerprint(before) != eng._fingerprint(after)
