"""4단계 최종 수정(Opus 검토 반영) 2: 상신 재결재(H4), 계약 거절 통보 경로(H2), 반품 보류 출구(H3),
2차 종료 경로(2차 차단·비분할), 2차 승인 대기 중 게이트 재판정(M8), 낮음 항목(L2·L4·L6·L7).
"""
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import policy
from app.ai.providers import FakeProvider
from app.api.main import create_app
from app.calc import inventory
from app.engine.flow import Engine
from app.store.db import open_db

sys.path.insert(0, str(Path(__file__).parent))
from test_flow_11b import ACCEPT, COLOR, NOTICE, SCM_PART, scene2, scene3, statuses  # noqa: E402
from test_flow_fix1 import EXEC, WAIT, facts, sales_scene, status, to_wait  # noqa: E402

OPIN, WHY = "승인 권고", "한도 근처라 윗선 확인이 필요합니다"


@pytest.fixture
def store(tmp_path):
    s = open_db(tmp_path / "t.db")
    yield s
    s.close()


@pytest.fixture
def ample(monkeypatch):
    monkeypatch.setattr(inventory, "line_spare", lambda category, day: 10**9)


def scene_one(store):
    """장면 2의 물류 회신 직후: 1차 승인 대기, 승인권자 CEO·이사회."""
    eng, _, cid, st = scene2(store, ACCEPT, SCM_PART)
    eng.play(st[0])
    assert status(store, cid) == "승인 대기"
    return eng, cid


# ---------------------------------------------------------------- H4. 상신 재결재

@pytest.mark.parametrize("opinion", ["승인 권고", "반대 권고"])
def test_H4_상급자가_이미_승인했으면_상신으로_그_결정은_무효이고_확정되지_않는다(store, opinion):
    eng, cid = scene_one(store)
    eng.decide(cid, "이사회", "분할승인", "먼저 승인")
    assert facts(store, cid)["approved_roles"] == ["이사회"]
    r = eng.escalate(cid, "그룹 CEO", "1차", opinion, WHY)  # CEO가 이사회로 올림
    assert r["changed"] is True and r["voided_decision"] is True
    assert r["status"] == "승인 대기" and r["pending"] == ["이사회"] and r["required_roles"] == ["이사회"]
    f = facts(store, cid)
    assert f["approved_roles"] == [] and "split_chosen" not in f
    assert not [t for t in store.list_tasks(cid) if t["title"] == "물류 출고"]
    ev = store.events(cid, kind="상신")[-1]["detail"]
    assert "이전 결정 무효" in ev["text"]
    assert [e for e in store.events(cid, kind="재승인알림") if e["detail"]["target"] == "이사회"
            and "이전 결정 무효" in e["detail"]["text"]]
    # 상급자가 다시 결재해야 한다(SCM 회신이 열려 있는 장면이라 결재가 모여도 SCM 회신을 기다린다)
    r2 = eng.decide(cid, "이사회", "분할승인", "의견 확인")
    assert r2["changed"] is True and facts(store, cid)["approved_roles"] == ["이사회"] and r2["pending"] == []


def test_H4_상급자가_아직_결정하지_않았으면_결정_무효_표시가_없다(store):
    eng, cid = scene_one(store)
    r = eng.escalate(cid, "그룹 CEO", "1차", OPIN, WHY)
    assert r["voided_decision"] is False and r["status"] == "승인 대기" and r["pending"] == ["이사회"]
    assert "이전 결정 무효" not in store.events(cid, kind="상신")[-1]["detail"]["text"]


def test_H4_2차_상신도_상급자의_이전_결정을_무효로_하고_확정하지_않는다(store):
    eng, cid = to_wait(store)
    f = facts(store, cid)
    f["phase2_approvers"], f["phase2_approved_roles"] = ["CEO", "Masil 대표"], ["CEO"]  # CEO가 이미 2차 승인
    store.update_facts(cid, f, "시험", "2차 결재선 준비")
    r = eng.escalate(cid, "Masil 대표", "2차", "반대 권고", WHY)
    assert r["voided_decision"] is True and r["status"] == WAIT and r["pending"] == ["CEO"]
    assert facts(store, cid)["phase2_approved_roles"] == [] and status(store, cid) == WAIT


# ---------------------------------------------------------------- H2. 계약 거절은 통보 경로

def test_H2_계약_거절은_조건변경_승인을_거쳐_통보_초안과_발송_작업을_만든다(store):
    eng, fake, ids, st = scene3(store, NOTICE)
    contract = ids[3]
    r = eng.decide(contract, "그룹 CEO", "거절", "조건 재협상이 필요")
    assert r["changed"] is True and r["status"] == "통보 초안"
    assert statuses(store, contract) == ["승인 대기", "조건변경 승인", "통보 초안"]
    c = store.get_case(contract)
    assert c["facts"]["notice"]["ok"] is True and "공제 후" in fake.calls[0][1]
    send = [t for t in store.list_tasks(contract) if t["title"] == "통보 발송"]
    assert len(send) == 1 and send[0]["dept"] == "계약 담당" and send[0]["due"] == "2026-07-17"  # 통보 기한까지
    assert [x["decision"] for x in store.list_approvals(contract)] == ["거절"]
    assert eng.execution_check("INF-001", date(2026, 9, 1))["allowed"] is False  # 갱신이 확정된 것이 아님


def test_H2_계약_담당이_통보_기한_전에_발송하면_상대_회신_대기(store):
    eng, _, ids, _ = scene3(store, NOTICE)
    eng.decide(ids[3], "그룹 CEO", "거절", "조건 재협상이 필요")
    assert eng.send_notice(ids[3], "계약 담당자")["status"] == "상대 회신 대기"


def test_H2_통보_기한이_지나도록_통보가_없으면_경고하고_정책_일수_뒤_방치_올림(store):
    eng, _, ids, _ = scene3(store, NOTICE)
    contract = ids[3]
    eng.decide(contract, "그룹 CEO", "거절", "조건 재협상이 필요")
    eng.advance(date(2026, 7, 17))  # 통보 기한 당일까지는 경고하지 않는다
    assert [e for e in store.events(contract, kind="조기경고") if e["detail"].get("notice_overdue")] == []
    eng.advance(date(2026, 7, 18))
    warn = [e for e in store.events(contract, kind="조기경고") if e["detail"].get("notice_overdue")]
    assert len(warn) == 1 and warn[0]["detail"]["target"] == "계약 담당"
    assert any(x["case_id"] == contract for x in eng.todo("계약 담당자")["기한 임박"])
    eng.advance(date(2026, 7, 18) + timedelta(days=5))  # 여러 번 점검해도 한 번씩만
    assert len([e for e in store.events(contract, kind="조기경고") if e["detail"].get("notice_overdue")]) == 1
    stale = store.events(contract, kind="방치올림")
    assert len(stale) == 1 and stale[0]["detail"]["key"] == "통보 발송"
    target = stale[0]["detail"]["target"]
    assert any(x["case_id"] == contract for x in eng.todo(target)["알림"])
    with pytest.raises(PermissionError):
        eng.send_notice(contract, "물류 담당자")
    assert store.get_case(contract)["status"] == "통보 초안"  # 자동 처리 없음
    assert eng.send_notice(contract, [n for n, r in eng.people.people.items() if r == target][0])["changed"] is True
    assert all(x["case_id"] != contract for x in eng.todo(target)["알림"] if x["kind"] == "방치올림")


def test_H2_기본_거부로_생긴_통보_초안도_같은_경고_방치_올림을_받는다(store):
    eng, _, ids, _ = scene3(store, NOTICE)
    contract = ids[3]
    eng.advance(date(2026, 7, 17))  # 기본 거부 → 통보 초안
    assert store.get_case(contract)["status"] == "통보 초안"
    eng.advance(date(2026, 7, 19))
    assert len(store.events(contract, kind="방치올림")) == 1


def test_L2_기안_거절도_확정_보류_처리_작업을_만든다(store):
    eng, cid = scene_one(store)
    eng.decide(cid, "그룹 CEO", "거절", "보류 판단")
    assert status(store, cid) == "거절"
    t = [x for x in store.list_tasks(cid) if x["title"] == "확정 보류(철회) 처리"]
    assert len(t) == 1 and t[0]["dept"] == "캠페인 담당"


# ---------------------------------------------------------------- H3. 반품 보류의 출구

def return_hold(store):
    eng, cid = sales_scene(store)
    eng.add_returns(cid, 900, 900)  # 기준선을 크게 넘음
    assert status(store, cid) == "2차 보류"
    return eng, cid


def test_H3_반품_보류는_캠페인_담당의_판단_작업이_생긴다(store):
    eng, cid = return_hold(store)
    f = facts(store, cid)
    assert f["phase2_hold"]["cause"] == "반품" and f["phase2_hold"]["reasons"]
    t = [x for x in store.list_tasks(cid) if x["title"] == "2차 보류 판단"]
    assert len(t) == 1 and t[0]["dept"] == "캠페인 담당" and t[0]["status"] == "대기"
    assert "2차 취소" in t[0]["detail"] and "예외 승인" in t[0]["detail"]
    assert [x["title"] for x in eng.todo("캠페인 담당자")["작업"] if x["case_id"] == cid].count("2차 보류 판단") == 1


def test_H3_캠페인_담당은_2차_취소만_할_수_있고_2차_없음으로_완료된다(store):
    eng, cid = return_hold(store)
    with pytest.raises(ValueError, match="판매율이 하한 미만"):
        eng.continue_phase2(cid, "캠페인 담당자", 300, "계속")
    with pytest.raises(PermissionError):
        eng.cancel_phase2(cid, "물류 담당자", "취소")
    r = eng.cancel_phase2(cid, "캠페인 담당자", "반품이 많아 중단")
    assert r["status"] == "완료" and r["qty_after"] == 0
    res = facts(store, cid)["phase2_result"]
    assert res["result"] == "2차 없음" and "반품이 많아 중단" in res["text"]
    assert facts(store, cid)["phase2_decision"]["choice"] == "2차 취소"
    assert [t["status"] for t in store.list_tasks(cid) if t["title"] == "2차 보류 판단"] == ["완료"]


def test_H3_판단_작업도_방치_올림_대상이고_올려_받은_사람이_취소한다(store):
    eng, cid = return_hold(store)
    made = store.get_clock()
    eng.advance(made + timedelta(days=policy.get("escalation.after_days")))
    ev = store.events(cid, kind="방치올림")
    assert len(ev) == 1 and ev[0]["detail"]["key"] == "2차 보류 판단"
    target = ev[0]["detail"]["target"]
    who = [n for n, r in eng.people.people.items() if r == target][0]
    assert eng.cancel_phase2(cid, who, "올림 받아 취소")["status"] == "완료"


def test_H3_예외_승인은_2차_승인권자_중_최고_역할만_이유와_수량으로(store):
    eng, cid = return_hold(store)
    plan_qty, plan_amt = facts(store, cid)["phase2"]["qty"], facts(store, cid)["phase2"].get("amount_krw")
    for who in ("캠페인 담당자", "그룹 재무", "물류 담당자", "그룹 CEO"):
        with pytest.raises(PermissionError, match="최고 역할"):
            eng.approve_phase2_exception(cid, who, 100, "사유")
    for qty in (0, plan_qty + 1, "많이", True, None):
        with pytest.raises(ValueError):
            eng.approve_phase2_exception(cid, "Masil 대표", qty, "사유")
    for reason in ("", "   ", None):
        with pytest.raises(ValueError, match="이유"):
            eng.approve_phase2_exception(cid, "Masil 대표", 100, reason)
    assert status(store, cid) == "2차 보류" and "phase2_exception" not in facts(store, cid)
    r = eng.approve_phase2_exception(cid, "Masil 대표", plan_qty // 2, "재방송으로 반품이 줄 것으로 판단")
    f = facts(store, cid)
    assert f["phase2"]["qty"] == plan_qty // 2
    if plan_amt:
        assert f["phase2"]["amount_krw"] == plan_amt * (plan_qty // 2) // plan_qty
    assert f["phase2_exception"]["role"] == "Masil 대표" and "재방송" in f["phase2_exception"]["reason"]
    assert r["status"] == "2차 잠금" and status(store, cid) == "2차 잠금"  # 판매 실적이 아직 없어 잠금(실적 입력 작업)
    ev = store.events(cid, kind="2차예외승인")
    assert len(ev) == 1 and ev[0]["detail"]["reason"].startswith("재방송")
    assert [t["status"] for t in store.list_tasks(cid) if t["title"] == "2차 보류 판단"] == ["완료"]
    # 판매 실적을 넣으면 반품이 기준을 넘은 채로도 2차 승인 대기(예외 승인이 반품 보류를 대신한다)
    eng.record_phase1_sales(cid, "캠페인 담당자", 2600, 50)
    assert status(store, cid) == WAIT
    eng.add_returns(cid, 900, 900)  # 예외 승인 뒤 반품이 더 들어와도 다시 보류하지 않는다
    assert status(store, cid) == WAIT


def test_H3_예외_승인은_보류가_아닌_건에는_거부(store):
    eng, cid = to_wait(store)
    with pytest.raises(ValueError, match="보류 상태"):
        eng.approve_phase2_exception(cid, "Masil 대표", 10, "사유")


def test_H3_판매율_보류는_예외_승인이_아니다(store):
    eng, cid = sales_scene(store)
    eng.record_phase1_sales(cid, "캠페인 담당자", 1000, 0)  # 33% < 하한
    assert status(store, cid) == "2차 보류"
    with pytest.raises(ValueError, match="2차 계속"):
        eng.approve_phase2_exception(cid, "Masil 대표", 10, "사유")


def test_H3_예외_승인_API(store):
    eng, cid = return_hold(store)
    c = TestClient(create_app(store, eng))
    body = {"actor": "캠페인 담당자", "qty": 100, "reason": "사유"}
    assert c.post(f"/api/cases/{cid}/phase2/exception", json=body).status_code == 409
    ok = c.post(f"/api/cases/{cid}/phase2/exception", json={**body, "actor": "Masil 대표"})
    assert ok.status_code == 200 and ok.json()["choice"] == "예외 승인"


# ---------------------------------------------------------------- M8. 2차 승인 대기 중 반품·리뷰

def test_M8_2차_승인_대기_중_반품이_기준을_넘으면_2차_보류이고_받은_승인은_무효(store):
    eng, cid = to_wait(store)
    eng.decide_phase2(cid, "Masil 대표", "승인")
    assert facts(store, cid)["phase2_approved_roles"] == ["Masil 대표"]
    g = eng.add_returns(cid, 900, 900)
    assert g.auto_stopped is True and status(store, cid) == "2차 보류"
    f = facts(store, cid)
    assert f["phase2_approved_roles"] == [] and f["phase2_hold"]["cause"] == "반품"
    assert store.events(cid, kind="2차보류")[-1]["detail"]["voided_roles"] == ["Masil 대표"]
    assert [t for t in store.list_tasks(cid) if t["title"] == "2차 보류 판단" and t["status"] == "대기"]
    with pytest.raises(ValueError, match="2차 승인 대기"):
        eng.decide_phase2(cid, "그룹 재무", "승인")
    # 예외 승인으로 다시 2차 승인 대기에 들어오면 처음부터 다시 받는다
    eng.approve_phase2_exception(cid, "Masil 대표", facts(store, cid)["phase2"]["qty"], "예외")
    assert status(store, cid) == WAIT and facts(store, cid)["phase2_approved_roles"] == []


def test_M8_기준_아래_반품은_2차_승인_대기를_그대로_둔다(store):
    eng, cid = to_wait(store)
    eng.decide_phase2(cid, "Masil 대표", "승인")
    g = eng.add_returns(cid, 0, 0)
    assert g.auto_stopped is False and status(store, cid) == WAIT
    assert facts(store, cid)["phase2_approved_roles"] == ["Masil 대표"]


def test_M8_2차_승인_대기_중_색상불일치_리뷰가_들어오면_2차_잠금으로_되돌린다(store):
    eng, cid = sales_scene(store, extra=(COLOR, ACCEPT))
    eng.record_phase1_sales(cid, "캠페인 담당자", 2600, 50)
    eng.decide_phase2(cid, "Masil 대표", "승인")
    assert status(store, cid) == WAIT
    eng.add_reviews(cid, [("립", "색이 영상과 달라요")])
    assert status(store, cid) == "2차 잠금" and facts(store, cid)["phase2_approved_roles"] == []
    req = [r for r in store.list_requests(cid) if r["purpose"] == "콘텐츠 수정"][0]
    eng.reply(req["id"], "수정본을 첨부합니다", 1)  # 콘텐츠 수정 확인 → 2차 승인 대기로 되돌아감
    assert status(store, cid) == WAIT and facts(store, cid)["phase2_approved_roles"] == []


# ---------------------------------------------------------------- 2차 종료 경로

def test_2차_차단은_계약_만료가_지나도록_갱신이_없으면_2차_없음으로_완료된다(store):
    eng, _, cid, st = scene2(store, ACCEPT, SCM_PART)
    eng.update_contract(store.list_contracts()[0]["id"], {"expiry_date": "2026-08-10"}, "계약 담당자")
    eng.play(st[0]); eng.play(st[1]); eng.play(st[2])
    eng.reply([r for r in store.list_requests(cid) if r["dept"] == "SCM"][0]["id"], "3,000개까지 허용합니다.")
    eng.play(st[4]); eng.play(st[5])
    assert status(store, cid) == "2차 차단"
    now = store.get_clock()
    end = date(2026, 8, 10)
    if now <= end:
        eng.advance(end)
        assert status(store, cid) == "2차 차단"  # 만료일 당일까지는 갱신될 수 있음
    eng.advance(max(now, end) + timedelta(days=1))
    assert status(store, cid) == "완료"
    res = facts(store, cid)["phase2_result"]
    assert res["result"] == "2차 없음" and "갱신" in res["text"] and "8/10" in res["text"]


def test_2차_차단_중_갱신이_확정되면_차단이_풀린다_완료되지_않는다(store):
    eng, _, cid, st = scene2(store, ACCEPT, SCM_PART)
    eng.update_contract(store.list_contracts()[0]["id"], {"expiry_date": "2026-08-10"}, "계약 담당자")
    eng.play(st[0]); eng.play(st[1]); eng.play(st[2])
    eng.reply([r for r in store.list_requests(cid) if r["dept"] == "SCM"][0]["id"], "3,000개까지 허용합니다.")
    eng.play(st[4]); eng.play(st[5])
    ccid = eng.open_contract("INF-001")
    for who in ("그룹 CEO", "이사회"):
        eng.decide(ccid, who, "승인")
    eng.advance(max(store.get_clock(), date(2026, 8, 10)) + timedelta(days=3))
    assert status(store, cid) != "완료"


def test_비분할_승인은_1차_집행일과_반품_관찰_기간_뒤_2차_없음으로_완료된다(store):
    eng = Engine(store, provider=FakeProvider([ACCEPT, ACCEPT]))
    cid = eng.seed("scenario_1")[0]
    eng.run_script("scenario_1")
    f = facts(store, cid)
    assert status(store, cid) == "1차 집행" and f["phase2_dropped"]["why"].startswith("분할 없음")
    end = date.fromisoformat(f["phase1"]["date"]) + timedelta(days=policy.get("split.return_observe_days"))
    eng.advance(end - timedelta(days=1))
    assert status(store, cid) == "1차 집행"  # 관찰 기간이 끝나기 전에는 반품을 받는다
    eng.advance(end)
    assert status(store, cid) == "완료"
    res = facts(store, cid)["phase2_result"]
    assert res["result"] == "2차 없음" and "분할 없음" in res["text"]
    assert len(store.events(cid, kind="2차결정")) == 1


# ---------------------------------------------------------------- 낮음

def test_L7_1차_집행일이_지난_뒤나_끝난_건은_공지할_수_없다(store):
    eng, _, cid, st = scene2(store, ACCEPT, SCM_PART)
    eng.play(st[0]); eng.play(st[1]); eng.play(st[2])
    eng.reply([r for r in store.list_requests(cid) if r["dept"] == "SCM"][0]["id"], "3,000개까지 허용합니다.")
    eng.play(st[4]); eng.play(st[5])
    eng.advance(date.fromisoformat(facts(store, cid)["phase1"]["date"]) + timedelta(days=1))  # 1차 집행일이 지남
    with pytest.raises(ValueError, match="공지할 수 없음"):
        eng.announce(cid, "캠페인 담당자")
    assert "announce" not in facts(store, cid)


def test_L4_비율_정책은_1_이하여야_한다(store):
    eng = Engine(store, provider=FakeProvider([]))
    for key in ("split.sellthrough_hold_ratio", "allocate.capacity_fallback_ratio", "volume.low_confidence_share",
                "scm.stockout_loss_pct"):
        with pytest.raises(ValueError, match="1 이하"):
            eng.change_policy("Masil 대표", key, 1.5, "시험")
        eng.change_policy("Masil 대표", key, 1.0, "시험")  # 1은 허용
    with pytest.raises(ValueError):
        policy.validate("signals.return_ratio_red", -1)
    policy.validate("signals.return_ratio_red", 2.0)  # 배수 항목은 1을 넘어도 된다


def test_L6_이벤트_limit은_1_이상(store):
    eng = Engine(store, provider=FakeProvider([]))
    c = TestClient(create_app(store, eng))
    assert c.get("/api/events", params={"limit": -1}).status_code == 422
    assert c.get("/api/events", params={"limit": 1}).status_code == 200
