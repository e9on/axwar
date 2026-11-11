"""방치 올림(추가 결정 9)과 판매율 보류의 판단 경로(컨트롤러 판정 10). Task 11b 수정 회차 4.

수치는 이 시험 안에서만 정하고, 엔진은 정책값(escalation.after_days 등)만 읽는다.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

from app import policy
from app.ai.providers import FakeProvider
from app.calc import inventory
from app.engine.flow import Engine
from app.store.db import open_db

sys.path.insert(0, str(Path(__file__).parent))
from test_flow_11b import ACCEPT, SCM_FULL, SCM_VAGUE, scene2, scm_request, to_scm_reply  # noqa: E402
from test_flow_sellthrough import ACTOR, P2_AMOUNT, P2_QTY, facts, locked  # noqa: E402


@pytest.fixture
def store(tmp_path):
    s = open_db(tmp_path / "t.db")
    yield s
    s.close()


def stale_events(store, cid):
    return store.events(cid, kind="방치올림")


def after_days():
    return policy.get("escalation.after_days")


def scm_human_case(store):
    """승인이 모이고 SCM 회신이 사람 확인에 머문 건에서 첫 경고까지 진행한다. (엔진, 사건, 경고일)을 돌려준다."""
    eng, _, cid, st = scene2(store, ACCEPT, SCM_VAGUE, SCM_FULL)
    to_scm_reply(eng, store, cid, st, "검토해 보고 알려드릴게요.")
    assert scm_request(store, cid)["status"] == "사람 확인"
    deadline = date.fromisoformat(facts(store, cid)["deadline"])
    day = store.get_clock()
    while not [e for e in store.events(cid, kind="조기경고") if e["detail"].get("scm_human")]:
        day = store.get_clock() + timedelta(days=1)
        eng.advance(day)
        assert day <= deadline, "기한 안에 경고가 나와야 함"
    return eng, cid, day


# ---------------------------------------------------------------- 정책값

def test_올림_일수는_정책값이고_출처와_설명이_있다():
    value, source, desc = policy.entry("escalation.after_days")
    assert value == 2 and source.startswith("가정") and desc


# ---------------------------------------------------------------- SCM 사람 확인 방치 올림

def test_경고_후_1일이면_올리지_않는다(store):
    eng, cid, warned = scm_human_case(store)
    eng.advance(warned + timedelta(days=after_days() - 1))
    assert stale_events(store, cid) == []
    assert eng.todo("그룹 CEO")["알림"] == []


def test_경고_후_정확히_정책_일수가_되면_최고_승인권자에게_올린다(store):
    eng, cid, warned = scm_human_case(store)
    acts = eng.advance(warned + timedelta(days=after_days()))
    ev = stale_events(store, cid)
    assert len(ev) == 1
    d = ev[0]["detail"]
    assert d["target"] == "CEO"  # 승인권자 CEO·이사회: 이사회는 회의체라 올림 대상에서 빼고 CEO(추가 결정 11)
    assert f"방치 올림(경고 후 {after_days()}일)" in d["text"]
    assert [a for a in acts if a["action"] == "방치올림" and a["target"] == "CEO"]
    inbox = eng.todo("그룹 CEO")["알림"]
    assert [x for x in inbox if x["kind"] == "방치올림" and x["case_id"] == cid]
    assert eng.todo("이사회")["알림"] == []


def test_같은_단계는_한_번만_올린다(store):
    eng, cid, warned = scm_human_case(store)
    eng.advance(warned + timedelta(days=after_days()))
    eng.advance(warned + timedelta(days=after_days() + 1))
    again = eng.check_deadlines()
    assert len(stale_events(store, cid)) == 1
    assert [a for a in again if a["action"] == "방치올림"] == []


def test_올려도_자동_거절은_하지_않는다(store):
    eng, cid, warned = scm_human_case(store)
    eng.advance(warned + timedelta(days=after_days()))
    assert store.get_case(cid)["status"] == "승인 대기" and facts(store, cid)["scm"]["state"] == "요청"
    assert scm_request(store, cid)["status"] == "사람 확인"


def test_올림_일수는_정책값을_따른다(store):
    eng, cid, warned = scm_human_case(store)
    policy.set_overrides({"escalation.after_days": (after_days() + 1, "시험", "now")})
    eng.advance(warned + timedelta(days=2))
    assert stale_events(store, cid) == []
    eng.advance(warned + timedelta(days=3))
    assert len(stale_events(store, cid)) == 1


def test_경고_뒤_사람이_처리하면_올리지_않는다(store):
    eng, cid, warned = scm_human_case(store)
    eng.resolve_human_check(scm_request(store, cid)["id"], "캠페인 담당자", "3,000개까지 허용합니다")
    eng.advance(warned + timedelta(days=after_days() + 1))
    assert stale_events(store, cid) == []


# ---------------------------------------------------------------- 올려 받은 사람의 처리 권한

def test_올리기_전에는_담당이_아닌_사람이_처리할_수_없다(store):
    eng, cid, warned = scm_human_case(store)
    rid = scm_request(store, cid)["id"]
    with pytest.raises(PermissionError):
        eng.resolve_human_check(rid, "이사회", "전량 허용합니다")
    with pytest.raises(PermissionError):
        eng.resolve_human_check(rid, "물류 담당자", "전량 허용합니다")
    assert scm_request(store, cid)["status"] == "사람 확인"


def test_올려_받은_사람은_그_사람_확인을_직접_처리한다(store):
    eng, cid, warned = scm_human_case(store)
    eng.advance(warned + timedelta(days=after_days()))
    rid = scm_request(store, cid)["id"]
    with pytest.raises(PermissionError):  # 올려 받지 않은 승인권자(이사회)는 여전히 불가
        eng.resolve_human_check(rid, "이사회", "전량 허용합니다")
    r = eng.resolve_human_check(rid, "그룹 CEO", "전량 허용합니다")
    assert r["needs_human"] is False and scm_request(store, cid)["status"] == "처리됨"
    assert all(x["kind"] != "방치올림" for x in eng.todo("그룹 CEO")["알림"])  # 처리했으니 알림이 내려감


def test_캠페인_담당은_올리기_전에도_처리한다(store):
    eng, cid, warned = scm_human_case(store)
    r = eng.resolve_human_check(scm_request(store, cid)["id"], "캠페인 담당자", "전량 허용합니다")
    assert r["needs_human"] is False


def test_사람_확인_상태가_아닌_요청은_처리_거부(store):
    eng, cid, warned = scm_human_case(store)
    rid = scm_request(store, cid)["id"]
    eng.resolve_human_check(rid, "캠페인 담당자", "전량 허용합니다")
    with pytest.raises(ValueError):
        eng.resolve_human_check(rid, "캠페인 담당자", "다시")


# ---------------------------------------------------------------- 올림 대상 선택(일반형)

@pytest.mark.parametrize("roles,expected", [
    (["마케팅팀"], "Masil 대표"),                 # 마케팅팀뿐이면 바로 위
    (["Masil 대표"], "Masil 대표"),
    (["Masil 대표", "마케팅팀"], "Masil 대표"),
    (["CEO", "이사회"], "CEO"),
    (["그룹", "마케팅팀"], "Masil 대표"),           # 보고 체계 밖 역할은 순서에 넣지 않는다
])
def test_올림_대상은_승인권자_중_최고_역할이고_마케팅팀뿐이면_Masil_대표(store, roles, expected):
    eng = Engine(store, provider=FakeProvider([]))
    assert eng._escalation_target(roles) == expected


# ---------------------------------------------------------------- 2차 보류 판단 방치 올림

def hold_case(store, monkeypatch, near_limit=False):
    monkeypatch.setattr(inventory, "line_spare", lambda category, day: 10**9)
    eng, cid = locked(store, monkeypatch)
    if near_limit:  # 요청액이 건별 한도를 500원 넘고 기안 총액은 작은 건: 2차 승인권자는 Masil 대표, 계획 2차 금액 2000원
        f = facts(store, cid)
        f["amount_krw"], f["plan_total_krw"] = policy.get("approval.item_limit_krw") + 500, 1
        f["phase2"]["amount_krw"] = 2000
        eng._phase2_approvers(f, cid)
        store.update_facts(cid, f, "시험", "금액 설정")
    eng.record_phase1_sales(cid, ACTOR, orders=400, returns=0)  # 40% < 하한
    assert store.get_case(cid)["status"] == "2차 보류"
    return eng, cid, store.get_clock()


def test_2차_보류_판단_작업이_정책_일수_뒤_정확히_한_번_올라간다(store, monkeypatch):
    eng, cid, made = hold_case(store, monkeypatch)
    eng.advance(made + timedelta(days=after_days() - 1))
    assert stale_events(store, cid) == []
    eng.advance(made + timedelta(days=after_days()))
    eng.advance(made + timedelta(days=after_days() + 2))
    ev = stale_events(store, cid)
    assert len(ev) == 1
    roles = [r for r in facts(store, cid)["phase2_approvers"] if r != "그룹 보고"]
    assert ev[0]["detail"]["target"] == eng._escalation_target(roles)
    assert f"방치 올림(작업 생성 후 {after_days()}일)" in ev[0]["detail"]["text"]
    assert store.get_case(cid)["status"] == "2차 보류"  # 자동 처리 없음


def test_올려_받은_사람은_2차_보류를_직접_판단한다(store, monkeypatch):
    eng, cid, made = hold_case(store, monkeypatch)
    eng.advance(made + timedelta(days=after_days()))
    target = stale_events(store, cid)[0]["detail"]["target"]
    with pytest.raises(PermissionError):
        eng.cancel_phase2(cid, "물류 담당자", "사유")
    r = eng.cancel_phase2(cid, target, "판매가 너무 저조해 2차를 하지 않음")
    assert r["status"] == "1차 집행"
    assert all(x["kind"] != "방치올림" for x in eng.todo(target)["알림"])


# ---------------------------------------------------------------- 2차 계속

def test_2차_계속은_수량을_받고_금액을_같은_비율로_줄여_2차_잠금_경로로_보낸다(store, monkeypatch):
    eng, cid, _ = hold_case(store, monkeypatch)
    r = eng.continue_phase2(cid, ACTOR, 400, "인플루언서 재방송이 잡혀 있어 400개만 진행")
    f = facts(store, cid)
    assert f["phase2"]["qty"] == 400 and f["phase2"]["amount_krw"] == P2_AMOUNT * 400 // P2_QTY
    assert store.get_case(cid)["status"] == "2차 잠금" and r["status"] == "2차 잠금"
    dec = f["phase2_decision"]
    assert dec["choice"] == "2차 계속" and dec["reason"].startswith("인플루언서") and dec["actor"] == ACTOR
    ev = store.events(cid, kind="판매율판단")
    assert len(ev) == 1
    d = ev[0]["detail"]
    assert d["choice"] == "2차 계속" and d["rate"] == 0.4 and d["reason"] == dec["reason"]
    assert (d["qty_before"], d["qty_after"]) == (P2_QTY, 400)
    assert d["amount_before"] == P2_AMOUNT and d["amount_after"] == P2_AMOUNT * 400 // P2_QTY
    assert [t for t in store.list_tasks(cid) if t["title"] == "2차 보류 판단"][0]["status"] != "대기"


def test_2차_계속_수량이_계획_2차와_같으면_금액_그대로(store, monkeypatch):
    eng, cid, _ = hold_case(store, monkeypatch)
    eng.continue_phase2(cid, ACTOR, P2_QTY, "계획대로 진행")
    f = facts(store, cid)
    assert f["phase2"]["qty"] == P2_QTY and f["phase2"]["amount_krw"] == P2_AMOUNT


def test_2차_계속_수량_1은_허용(store, monkeypatch):
    eng, cid, _ = hold_case(store, monkeypatch)
    eng.continue_phase2(cid, ACTOR, 1, "시범으로 1개")
    assert facts(store, cid)["phase2"]["qty"] == 1


@pytest.mark.parametrize("qty", [0, -5, P2_QTY + 1, True, 1.5, "300", None])
def test_2차_계속_수량이_범위_밖이거나_정수가_아니면_거부하고_아무것도_바꾸지_않는다(store, monkeypatch, qty):
    eng, cid, _ = hold_case(store, monkeypatch)
    with pytest.raises(ValueError):
        eng.continue_phase2(cid, ACTOR, qty, "사유")
    assert store.get_case(cid)["status"] == "2차 보류" and facts(store, cid)["phase2"]["qty"] == P2_QTY
    assert "phase2_decision" not in facts(store, cid) and store.events(cid, kind="판매율판단") == []


@pytest.mark.parametrize("reason", ["", "   ", None])
def test_이유가_없으면_거부(store, monkeypatch, reason):
    eng, cid, _ = hold_case(store, monkeypatch)
    with pytest.raises(ValueError):
        eng.continue_phase2(cid, ACTOR, 300, reason)
    with pytest.raises(ValueError):
        eng.cancel_phase2(cid, ACTOR, reason)
    assert store.get_case(cid)["status"] == "2차 보류"


def test_2차_계속으로_금액이_줄면_승인권자를_다시_판정한다(store, monkeypatch):
    eng, cid, _ = hold_case(store, monkeypatch, near_limit=True)
    assert facts(store, cid)["phase2_approvers"][0] == "Masil 대표"
    n = len(store.get_approver_changes(cid))
    eng.continue_phase2(cid, ACTOR, 600, "일부만 진행")  # 2차 2000원 -> 1200원, 요청액이 한도 아래로
    f = facts(store, cid)
    assert f["phase2"]["amount_krw"] == 1200 and f["phase2_approvers"] == ["마케팅팀"]
    ch = store.get_approver_changes(cid)
    assert len(ch) == n + 1 and ch[-1].before[0] == "Masil 대표"
    assert any(h["rule_id"] == "sellthrough_adjust" for h in f["phase2_approver_hits"])


# ---------------------------------------------------------------- 2차 취소

def test_2차_취소는_2차_없음으로_1차_집행_상태에_둔다(store, monkeypatch):
    eng, cid, _ = hold_case(store, monkeypatch)
    r = eng.cancel_phase2(cid, ACTOR, "판매 부진으로 2차 중단")
    f = facts(store, cid)
    assert f["phase2"] is None and store.get_case(cid)["status"] == "1차 집행" and r["status"] == "1차 집행"
    d = store.events(cid, kind="판매율판단")[0]["detail"]
    assert d["choice"] == "2차 취소" and d["rate"] == 0.4 and d["reason"] == "판매 부진으로 2차 중단"
    assert (d["qty_before"], d["qty_after"]) == (P2_QTY, 0)
    assert f["phase2_decision"]["choice"] == "2차 취소"


# ---------------------------------------------------------------- 거부 조건

def test_판단은_한_번만(store, monkeypatch):
    eng, cid, _ = hold_case(store, monkeypatch)
    eng.continue_phase2(cid, ACTOR, 300, "일부 진행")
    with pytest.raises(ValueError):
        eng.cancel_phase2(cid, ACTOR, "다시 취소")
    with pytest.raises(ValueError):
        eng.continue_phase2(cid, ACTOR, 200, "다시 계속")
    assert len(store.events(cid, kind="판매율판단")) == 1


def test_취소_뒤에도_두_번째_판단은_거부(store, monkeypatch):
    eng, cid, _ = hold_case(store, monkeypatch)
    eng.cancel_phase2(cid, ACTOR, "중단")
    with pytest.raises(ValueError):
        eng.continue_phase2(cid, ACTOR, 300, "재개")


def test_반품_보류_건에는_거부(store, monkeypatch):
    monkeypatch.setattr(inventory, "line_spare", lambda category, day: 10**9)
    eng, cid = locked(store, monkeypatch)
    store.set_status(cid, "2차 보류", "시험", "반품이 기준을 넘어 2차 보류")
    with pytest.raises(ValueError):
        eng.continue_phase2(cid, ACTOR, 300, "사유")
    with pytest.raises(ValueError):
        eng.cancel_phase2(cid, ACTOR, "사유")
    assert store.get_case(cid)["status"] == "2차 보류" and facts(store, cid)["phase2"]["qty"] == P2_QTY


def test_보류가_아닌_상태에는_거부(store, monkeypatch):
    monkeypatch.setattr(inventory, "line_spare", lambda category, day: 10**9)
    eng, cid = locked(store, monkeypatch)
    with pytest.raises(ValueError):
        eng.continue_phase2(cid, ACTOR, 300, "사유")


def test_캠페인_담당이_아니고_올려_받지도_않았으면_거부(store, monkeypatch):
    eng, cid, _ = hold_case(store, monkeypatch)
    for who in ("물류 담당자", "마케팅팀장", "이사회"):
        with pytest.raises(PermissionError):
            eng.continue_phase2(cid, who, 300, "사유")
    assert store.get_case(cid)["status"] == "2차 보류"
