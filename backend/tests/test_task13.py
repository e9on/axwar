"""Task 13: 담당 역할 이름은 정책(roles.*), 물량 입력 기한은 마지막 승인일 기준, 새 시연 대본."""
import sys
from datetime import date
from pathlib import Path

import pytest

from app import policy
from app.ai.providers import FakeProvider
from app.engine import scenarios
from app.engine.flow import Engine
from app.store.db import open_db

sys.path.insert(0, str(Path(__file__).parent))
from test_flow_11b import ACCEPT, SCM_PART, scene2, to_scm_reply  # noqa: E402


@pytest.fixture
def store(tmp_path):
    s = open_db(tmp_path / "t.db")
    yield s
    s.close()


# ---- 1. 담당 역할 이름은 정책에서

def test_역할_항목이_가정으로_정책에_있다():
    for key in ("roles.campaign", "roles.contract", "roles.logistics", "roles.cs"):
        value, source, desc = policy.base_entry(key)
        assert source.startswith("가정") and desc and key in policy.keys()
    assert policy.get("roles.campaign") == "캠페인 담당"


def test_캠페인_역할을_바꾸면_그_역할만_공지할_수_있다(store):
    eng, _, cid, st = scene2(store, ACCEPT, SCM_PART)
    to_scm_reply(eng, store, cid, st, "3,000개까지 허용합니다.")
    eng.play(st[4]); eng.play(st[5])
    eng.change_policy("Masil 대표", "roles.campaign", "품질", "시험")
    with pytest.raises(PermissionError, match="품질"):
        eng.announce(cid, "캠페인 담당자")
    assert eng.announce(cid, "품질 담당자", qty=3000)["changed"] is True


def test_역할을_사람_목록에_없는_이름으로_바꾸면_거부(store):
    eng = Engine(store, provider=FakeProvider([]))
    with pytest.raises(ValueError, match="사람 목록"):
        eng.change_policy("Masil 대표", "roles.campaign", "없는역할", "시험")
    assert policy.get("roles.campaign") == "캠페인 담당" and store.policy_history() == []


def test_엔진을_만들_때_사람_목록에_없는_역할이_있으면_무엇이_빠졌는지_알린다(store):
    people = scenarios.People({"마케팅팀장": "마케팅팀", "Masil 대표": "Masil 대표"}, ("마케팅팀", "Masil 대표"))
    with pytest.raises(ValueError, match="roles.campaign.*roles.contract"):
        Engine(store, provider=FakeProvider([]), people=people)


# ---- 2. 물량 입력 기한

def _volume_task(store, cid):
    return next(t for t in store.list_tasks(cid) if t["title"] == "물량 입력")


def _new_plan(store, plan_id="NEW-1", deadline="2026-09-11"):
    store.add_plan({"plan_id": plan_id, "campaign_id": "CMP-0005", "influencer_id": "INF-002", "channel": "자사몰",
                    "requested_budget_krw": 3000000, "expected_gmv_krw": 30000000,
                    "settlement_date": "2026-10-01", "contract_deadline": deadline}, "캠페인 담당자", origin="시연")


def test_물량_입력_기한은_마지막_승인일보다_이틀_이르다(store):
    _new_plan(store)
    eng = Engine(store, provider=FakeProvider([ACCEPT]))
    cid = eng.open_plan("NEW-1")
    assert _volume_task(store, cid)["due"] == "2026-09-05"  # 확정 기한 9/11 → 마지막 승인일 9/7 − 2


def test_정책을_바꾸면_새_기안에_반영된다(store):
    _new_plan(store, "NEW-1")
    _new_plan(store, "NEW-2")
    eng = Engine(store, provider=FakeProvider([ACCEPT]))
    eng.change_policy("Masil 대표", "volume.input_lead_days", 4, "시험")
    assert _volume_task(store, eng.open_plan("NEW-2"))["due"] == "2026-09-03"


def test_오늘보다_이르면_오늘로(store):
    _new_plan(store)
    store.set_clock(date(2026, 9, 6))
    eng = Engine(store, provider=FakeProvider([ACCEPT]))
    assert _volume_task(store, eng.open_plan("NEW-1"))["due"] == "2026-09-06"


def test_등록부_확정_기한이_바뀌면_작업_기한도_맞춘다(store):
    _new_plan(store)
    eng = Engine(store, provider=FakeProvider([ACCEPT]))
    cid = eng.open_plan("NEW-1")
    eng.update_plan("NEW-1", {"contract_deadline": "2026-09-21"}, "캠페인 담당자")
    assert _volume_task(store, cid)["due"] == "2026-09-15"  # 마지막 승인일 9/17 − 2


def test_기본_거부로_확정_보류가_되면_남은_물량_입력_작업은_닫는다(store):
    _new_plan(store)
    eng = Engine(store, provider=FakeProvider([ACCEPT]))
    cid = eng.open_plan("NEW-1")
    eng.advance(date(2026, 9, 8))  # 기한 3일 전 아침 = 기본 거부
    assert store.get_case(cid)["status"] == "확정 보류"
    assert _volume_task(store, cid)["status"] == "완료"


# ---- 3. 새 시연 대본(상신·예외 승인·계약 거절)

NOTICE = "조건변경 통보 초안입니다. 성과 피 기준은 공제 후 순액으로 바꾸는 안을 제안드립니다."


def _run(store, name, *responses):
    eng = Engine(store, provider=FakeProvider(list(responses)))
    ids = eng.seed(name)
    return eng, ids, [eng.play(s) for s in scenarios.load(name).script]


def test_상신_대본은_상신_이벤트와_재결재로_끝난다(store):
    eng, (cid,), out = _run(store, "scenario_1_escalate", ACCEPT, ACCEPT)
    c = store.get_case(cid)
    assert c["status"] == "1차 집행" and store.get_clock() == date(2026, 9, 7)
    ups = store.events(cid, kind="상신")
    assert len(ups) == 1 and ups[0]["actor"] == "Masil 대표" and ups[0]["detail"]["opinion"] == "승인 권고"
    assert out[2]["to"] == "CEO" and out[2]["required_roles"] == ["CEO"]
    assert c["facts"]["approved_roles"] == ["CEO"]  # 상신한 Masil 대표는 결재선에서 빠지고 CEO가 다시 결재
    assert {(t["dept"], t["title"]) for t in store.list_tasks(cid)} >= {("물류", "물류 출고"), ("CS", "CS 대비")}


def test_계약_거절_대본은_통보_초안과_발송_작업_완료로_끝난다(store):
    eng, (cid,), out = _run(store, "scenario_3_reject", NOTICE)
    c = store.get_case(cid)
    assert c["kind"] == "계약" and c["status"] == "상대 회신 대기" and store.get_clock() == date(2026, 7, 13)
    assert [e["detail"]["to"] for e in store.events(cid, kind="상태변경")][-4:] == ["조건변경 승인", "통보 초안", "통보 발송", "상대 회신 대기"]
    assert [t["status"] for t in store.list_tasks(cid) if t["title"] == "통보 발송"] == ["완료"]
    assert c["facts"]["notice"]["sent_text"] == NOTICE and c["facts"]["notice"]["sent_by"] == "계약 담당자"


def test_예외_승인_대본은_2차_집행까지_간다(store):
    eng, (cid,), out = _run(store, "scenario_2_exception", ACCEPT, SCM_PART)
    c = store.get_case(cid)
    assert c["status"] == "완료" and store.get_clock() == date(2026, 9, 2)
    ex = store.events(cid, kind="2차예외승인")
    assert len(ex) == 1 and ex[0]["actor"] == "Masil 대표" and ex[0]["detail"]["qty_after"] == 6000 and ex[0]["detail"]["reason"]
    assert store.events(cid, kind="2차보류")  # 반품으로 자동 보류됐다가
    assert {(t["dept"], t["title"]) for t in store.list_tasks(cid)} >= {("물류", "물류 출고(2차)"), ("CS", "CS 대비(2차)")}  # 2차 집행
    assert c["facts"]["phase2"]["qty"] <= 6000


def test_새_대본_단계_형식_검증(tmp_path):
    base = {"title": "t", "description": "d", "plans": ["PLAN-019"], "contracts": [], "requests": []}
    import json
    def load(step):
        (tmp_path / "x.json").write_text(json.dumps({**base, "script": [{"plan": "PLAN-019", **step}]}, ensure_ascii=False), encoding="utf-8")
        return scenarios.load("x", tmp_path)
    load({"action": "상신", "actor": "a", "stage": "1차", "opinion": "승인 권고", "reason": "r"})
    load({"action": "예외 승인", "actor": "a", "qty": 5, "reason": "r"})
    for bad in ({"action": "상신", "actor": "a", "stage": "3차", "opinion": "승인 권고", "reason": "r"},
                {"action": "상신", "actor": "a", "stage": "1차", "opinion": "몰라", "reason": "r"},
                {"action": "상신", "actor": "a", "stage": "1차", "opinion": "승인 권고", "reason": " "},
                {"action": "예외 승인", "actor": "a", "qty": 0, "reason": "r"},
                {"action": "예외 승인", "actor": "a", "reason": "r"}):
        with pytest.raises(ValueError):
            load(bad)
