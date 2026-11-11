"""2차 집행 수량을 1차 판매 실적(판매율)으로 조절한다(Task 11b 수정 3, 추가 결정 8).

판매율 = (1차 주문 - 반품) / 1차 수량. 수치는 이 시험 안에서만 정하고, 엔진은 정책값(split.sellthrough_hold_ratio)만 읽는다.
"""
import json
from datetime import date, timedelta

import pytest

from app import policy
from app.ai.providers import FakeProvider
from app.calc import inventory
from app.engine import scenarios
from app.engine.flow import Engine
from app.store.db import open_db

ACTOR = "캠페인 담당자"
P1_QTY, P2_QTY, P2_AMOUNT = 1000, 1000, 2_000_001


@pytest.fixture
def store(tmp_path):
    s = open_db(tmp_path / "t.db")
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _ample(monkeypatch):
    monkeypatch.setattr(inventory, "line_spare", lambda category, day: 10**9)


def locked(store, monkeypatch, p1=P1_QTY, p2=P2_QTY, amount=P2_AMOUNT, observed=28):
    """1차 집행이 끝나 2차 잠금인 사건. 계약 만료·갱신은 문제 없게 둔다."""
    eng = Engine(store, provider=FakeProvider([]))
    monkeypatch.setattr(eng, "_contract_terms", lambda inf: (date(2099, 1, 1), True))
    cid = eng.seed("scenario_1")[0]
    f = store.get_case(cid)["facts"]
    today = store.get_clock()
    f["phase1"] = {"qty": p1, "date": (today - timedelta(days=observed)).isoformat()}
    f["phase2"] = {"qty": p2, "date": (today + timedelta(days=1)).isoformat(), "amount_krw": amount}
    eng._phase2_approvers(f, cid)
    store.update_facts(cid, f, "시험", "2차 준비")
    store.set_status(cid, "2차 잠금", "시험", "")
    return eng, cid


def facts(store, cid):
    return store.get_case(cid)["facts"]


def sell_events(store, cid):
    return store.events(cid, kind="판매율조절")


# ---------------------------------------------------------------- 비례 조절

def test_판매율이_100퍼센트_미만이면_2차_수량과_금액을_같은_비율로_내림한다(store, monkeypatch):
    eng, cid = locked(store, monkeypatch)
    r = eng.record_phase1_sales(cid, ACTOR, orders=900, returns=100)  # 순판매 800 / 1차 1000 = 80%
    f = facts(store, cid)
    assert f["sales"] == {"orders": 900, "returns": 100, "net": 800, "date": store.get_clock().isoformat()}
    assert f["phase2"]["qty"] == 800 and f["phase2"]["amount_krw"] == P2_AMOUNT * 800 // P1_QTY == 1_600_000
    assert store.get_case(cid)["status"] == "2차 잠금" and r["status"] == "2차 잠금"
    st = f["phase2_sellthrough"]
    assert st["outcome"] == "조절" and st["rate"] == 0.8
    assert (st["qty_before"], st["qty_after"]) == (1000, 800)
    assert (st["amount_before"], st["amount_after"]) == (P2_AMOUNT, 1_600_000)


def test_수량은_개_단위_금액은_원_단위로_내림(store, monkeypatch):
    eng, cid = locked(store, monkeypatch, p1=3, p2=7, amount=1000)
    eng.record_phase1_sales(cid, ACTOR, orders=2, returns=0)  # 판매율 2/3
    p2 = facts(store, cid)["phase2"]
    assert p2["qty"] == 4 and p2["amount_krw"] == 666  # 7*2/3=4.67 -> 4, 1000*2/3=666.67 -> 666


def test_이벤트와_근거에_판매율_이전_이후_수량_금액을_남긴다(store, monkeypatch):
    eng, cid = locked(store, monkeypatch)
    eng.record_phase1_sales(cid, ACTOR, orders=900, returns=100)
    ev = sell_events(store, cid)
    assert len(ev) == 1
    d = ev[0]["detail"]
    assert d["outcome"] == "조절" and d["rate"] == 0.8
    assert (d["qty_before"], d["qty_after"], d["amount_before"], d["amount_after"]) == (1000, 800, P2_AMOUNT, 1_600_000)
    for piece in ("80.0%", "1,000", "800", "2,000,001", "1,600,000"):
        assert piece in d["text"]
    hit = [h for h in facts(store, cid)["phase2_approver_hits"] if h["rule_id"] == "sellthrough_adjust"]
    assert len(hit) == 1 and "80.0%" in hit[0]["text"] and "1,000" in hit[0]["text"] and "800" in hit[0]["text"]


def test_판매율이_정확히_하한이면_보류가_아니라_비례_조절(store, monkeypatch):
    eng, cid = locked(store, monkeypatch)
    ratio = policy.get("split.sellthrough_hold_ratio")
    eng.record_phase1_sales(cid, ACTOR, orders=int(P1_QTY * ratio), returns=0)
    f = facts(store, cid)
    assert store.get_case(cid)["status"] == "2차 잠금" and f["phase2"]["qty"] == int(P2_QTY * ratio)
    assert f["phase2_sellthrough"]["outcome"] == "조절"


def test_하한_바로_아래면_자동으로_줄이지_않고_2차_보류와_캠페인_담당_작업(store, monkeypatch):
    eng, cid = locked(store, monkeypatch)
    eng.record_phase1_sales(cid, ACTOR, orders=499, returns=0)
    f = facts(store, cid)
    assert store.get_case(cid)["status"] == "2차 보류"
    assert f["phase2"]["qty"] == P2_QTY and f["phase2"]["amount_krw"] == P2_AMOUNT  # 줄이지 않음
    assert f["phase2_sellthrough"]["outcome"] == "보류"
    t = [x for x in store.list_tasks(cid) if x["title"] == "2차 보류 판단"]
    assert len(t) == 1 and t[0]["dept"] == "캠페인 담당" and "49.9%" in t[0]["detail"]
    ev = sell_events(store, cid)
    assert len(ev) == 1 and ev[0]["detail"]["outcome"] == "보류" and ev[0]["detail"]["qty_after"] == P2_QTY


def test_하한은_정책값을_따른다(store, monkeypatch):
    eng, cid = locked(store, monkeypatch)
    policy.set_overrides({"split.sellthrough_hold_ratio": (0.9, "시험", "now")})
    try:
        eng.record_phase1_sales(cid, ACTOR, orders=800, returns=0)
    finally:
        policy.clear_overrides()
    assert store.get_case(cid)["status"] == "2차 보류"


def test_주문_0건이면_판매율_0으로_보류(store, monkeypatch):
    eng, cid = locked(store, monkeypatch)
    eng.record_phase1_sales(cid, ACTOR, orders=0, returns=0)
    assert store.get_case(cid)["status"] == "2차 보류"
    assert facts(store, cid)["phase2_sellthrough"]["rate"] == 0.0


# ---------------------------------------------------------------- 품절

def test_판매율이_정확히_100퍼센트면_계획_유지하고_품절을_기록(store, monkeypatch):
    eng, cid = locked(store, monkeypatch)
    eng.record_phase1_sales(cid, ACTOR, orders=1000, returns=0)
    f = facts(store, cid)
    assert store.get_case(cid)["status"] == "2차 잠금"
    assert f["phase2"]["qty"] == P2_QTY and f["phase2"]["amount_krw"] == P2_AMOUNT
    assert f["phase2_sellthrough"]["outcome"] == "품절" and f["phase1_soldout"] is True
    ev = sell_events(store, cid)
    assert len(ev) == 1 and ev[0]["detail"]["outcome"] == "품절" and "품절" in ev[0]["detail"]["text"]


def test_판매율이_100퍼센트를_넘으면_넘친_양과_함께_품절로_기록(store, monkeypatch):
    eng, cid = locked(store, monkeypatch)
    eng.record_phase1_sales(cid, ACTOR, orders=1200, returns=100)  # 순판매 1100
    st = facts(store, cid)["phase2_sellthrough"]
    assert st["outcome"] == "품절" and st["rate"] == 1.1 and st["excess"] == 100
    assert facts(store, cid)["phase2"]["qty"] == P2_QTY


# ---------------------------------------------------------------- 입력 검증

@pytest.mark.parametrize("orders,returns", [(100, 101), (-1, 0), (10, -1)])
def test_이상한_입력은_거부하고_아무것도_바꾸지_않는다(store, monkeypatch, orders, returns):
    eng, cid = locked(store, monkeypatch)
    before = facts(store, cid)
    with pytest.raises(ValueError):
        eng.record_phase1_sales(cid, ACTOR, orders=orders, returns=returns)
    assert facts(store, cid) == before and store.get_case(cid)["status"] == "2차 잠금"


def test_숫자가_아니면_거부(store, monkeypatch):
    eng, cid = locked(store, monkeypatch)
    for bad in (True, 1.5, "10", None):
        with pytest.raises(ValueError):
            eng.record_phase1_sales(cid, ACTOR, orders=bad, returns=0)


def test_캠페인_담당만_입력하고_1차_집행_뒤에만_가능(store, monkeypatch):
    eng, cid = locked(store, monkeypatch)
    with pytest.raises(PermissionError):
        eng.record_phase1_sales(cid, "그룹 CEO", orders=10, returns=0)
    scenarios.register_plan(store, "PLAN-001")
    other = eng.open_plan("PLAN-001")
    with pytest.raises(ValueError):
        eng.record_phase1_sales(other, ACTOR, orders=10, returns=0)


def test_판정_전에는_다시_입력해_고칠_수_있고_판정_뒤에는_막는다(store, monkeypatch):
    eng, cid = locked(store, monkeypatch, observed=1)  # 관찰 기간 중이라 판정 대기
    eng.record_phase1_sales(cid, ACTOR, orders=10, returns=0)
    eng.record_phase1_sales(cid, ACTOR, orders=900, returns=0)
    assert facts(store, cid)["sales"]["orders"] == 900 and "phase2_sellthrough" not in facts(store, cid)
    f = facts(store, cid)
    f["phase1"]["date"] = (store.get_clock() - timedelta(days=28)).isoformat()
    store.update_facts(cid, f, "시험", "관찰 끝")
    eng.check_deadlines()
    assert facts(store, cid)["phase2"]["qty"] == 900 and facts(store, cid)["phase2_sellthrough"]["outcome"] == "조절"
    with pytest.raises(ValueError):
        eng.record_phase1_sales(cid, ACTOR, orders=100, returns=0)


# ---------------------------------------------------------------- 판매 실적이 없으면 열지 않음

def test_판매_실적이_없으면_2차를_열지_않고_캠페인_담당_작업을_한번만_만든다(store, monkeypatch):
    eng, cid = locked(store, monkeypatch)
    g = eng.phase2_status(cid)
    assert g.open is False and any("판매 실적" in x for x in g.reasons)
    eng.check_deadlines()
    eng.check_deadlines()
    t = [x for x in store.list_tasks(cid) if x["title"] == "1차 판매 실적 입력"]
    assert len(t) == 1 and t[0]["dept"] == "캠페인 담당"
    assert store.get_case(cid)["status"] == "2차 잠금" and facts(store, cid)["phase2"]["qty"] == P2_QTY
    eng.record_phase1_sales(cid, ACTOR, orders=900, returns=0)
    assert eng.phase2_status(cid).open is True


def test_관찰_기간_중에는_실적_입력_작업을_만들지_않는다(store, monkeypatch):
    eng, cid = locked(store, monkeypatch, observed=3)
    eng.check_deadlines()
    assert [x for x in store.list_tasks(cid) if x["title"] == "1차 판매 실적 입력"] == []
    eng.record_phase1_sales(cid, ACTOR, orders=900, returns=0)  # 입력은 받지만 판정은 게이트가 열릴 때
    assert facts(store, cid)["phase2"]["qty"] == P2_QTY and "phase2_sellthrough" not in facts(store, cid)


# ---------------------------------------------------------------- 판정 순서: 반품·리뷰 먼저

def test_반품_보류가_먼저라_판매율로_줄이지_않는다(store, monkeypatch):
    eng, cid = locked(store, monkeypatch)
    eng.add_returns(cid, 0, 600)  # 색상불만 60% -> 자동 보류
    assert store.get_case(cid)["status"] == "2차 보류"
    eng.record_phase1_sales(cid, ACTOR, orders=900, returns=0)
    f = facts(store, cid)
    assert f["sales"]["net"] == 900 and f["phase2"]["qty"] == P2_QTY and "phase2_sellthrough" not in f
    assert sell_events(store, cid) == []


def test_리뷰_잠금이_먼저라_콘텐츠_수정_확인_뒤에야_판매율로_줄인다(store, monkeypatch):
    eng, cid = locked(store, monkeypatch)
    f = facts(store, cid)
    f["color_review_flagged"] = True
    store.update_facts(cid, f, "시험", "리뷰 잠금")
    eng.record_phase1_sales(cid, ACTOR, orders=900, returns=0)
    assert facts(store, cid)["phase2"]["qty"] == P2_QTY
    f = facts(store, cid)
    f["content_fix_confirmed"] = True
    store.update_facts(cid, f, "시험", "콘텐츠 수정 확인")
    eng.check_deadlines()
    assert facts(store, cid)["phase2"]["qty"] == 900


def test_판매_실적_입력_작업은_다른_사유가_남아_있으면_만들지_않는다(store, monkeypatch):
    eng, cid = locked(store, monkeypatch)
    f = facts(store, cid)
    f["color_review_flagged"] = True
    store.update_facts(cid, f, "시험", "리뷰 잠금")
    eng.check_deadlines()
    assert [x for x in store.list_tasks(cid) if x["title"] == "1차 판매 실적 입력"] == []


# ---------------------------------------------------------------- 2차 승인권자 재판정

def _near_limit(store, eng, cid):
    """요청액이 건별 한도를 500원 넘고 기안 총액은 작은 건: 2차 승인권자는 Masil 대표."""
    f = facts(store, cid)
    f["amount_krw"], f["plan_total_krw"] = policy.get("approval.item_limit_krw") + 500, 1
    f["phase2"]["amount_krw"] = 2000
    eng._phase2_approvers(f, cid)
    store.update_facts(cid, f, "시험", "금액 설정")
    assert facts(store, cid)["phase2_approvers"][0] == "Masil 대표"


def test_조절로_2차_금액이_줄어_요청액이_한도_아래가_되면_마케팅팀_전결로_바뀌고_권한_이동에_남는다(store, monkeypatch):
    eng, cid = locked(store, monkeypatch)
    _near_limit(store, eng, cid)
    n_before = len(store.get_approver_changes(cid))
    eng.record_phase1_sales(cid, ACTOR, orders=600, returns=0)  # 60%: 2차 2000원 -> 1200원(800원 줄어 요청액이 한도 아래로)
    f = facts(store, cid)
    assert f["phase2"]["amount_krw"] == 1200
    assert f["phase2_approvers"] == ["마케팅팀"] and f["phase2_approved_roles"] == []
    ch = store.get_approver_changes(cid)
    assert len(ch) == n_before + 1 and ch[-1].before[0] == "Masil 대표" and ch[-1].after == ("마케팅팀",)
    assert "2,000" in ch[-1].reason and "1,200" in ch[-1].reason


def test_보류일_때는_승인권자를_다시_판정하지_않는다(store, monkeypatch):
    eng, cid = locked(store, monkeypatch)
    _near_limit(store, eng, cid)
    n_before = len(store.get_approver_changes(cid))
    eng.record_phase1_sales(cid, ACTOR, orders=250, returns=0)
    assert store.get_case(cid)["status"] == "2차 보류"
    assert facts(store, cid)["phase2_approvers"][0] == "Masil 대표" and len(store.get_approver_changes(cid)) == n_before


def test_승인권자가_그대로면_권한_이동을_남기지_않는다(store, monkeypatch):
    eng, cid = locked(store, monkeypatch)
    n_before = len(store.get_approver_changes(cid))
    eng.record_phase1_sales(cid, ACTOR, orders=800, returns=0)
    assert len(store.get_approver_changes(cid)) == n_before


def test_조절_결과_2차가_0개면_2차_없음으로_1차_집행에_둔다(store, monkeypatch):
    eng, cid = locked(store, monkeypatch, p1=10, p2=1, amount=100)
    eng.record_phase1_sales(cid, ACTOR, orders=5, returns=0)  # 5/10 = 0.5 -> 1*5//10 = 0
    f = facts(store, cid)
    assert f["phase2"] is None and store.get_case(cid)["status"] == "1차 집행"
    assert f["phase2_sellthrough"]["qty_after"] == 0


# ---------------------------------------------------------------- 대본(시연 파일)

def test_대본의_판매_단계를_검증한다(tmp_path):
    def write(step):
        (tmp_path / "s.json").write_text(json.dumps({
            "title": "t", "description": "d", "plans": ["PLAN-001"], "contracts": [], "requests": [],
            "script": [step]}), encoding="utf-8")
    write({"action": "판매", "plan": "PLAN-001", "actor": ACTOR, "orders": 10, "returns": 1})
    assert scenarios.load("s", tmp_path).script[0]["orders"] == 10
    for bad in ({"action": "판매", "plan": "PLAN-001", "actor": ACTOR, "orders": 10},
                {"action": "판매", "plan": "PLAN-001", "actor": ACTOR, "orders": 10, "returns": 11},
                {"action": "판매", "plan": "PLAN-001", "actor": ACTOR, "orders": -1, "returns": 0},
                {"action": "판매", "plan": "PLAN-001", "orders": 1, "returns": 0}):
        write(bad)
        with pytest.raises(ValueError):
            scenarios.load("s", tmp_path)
