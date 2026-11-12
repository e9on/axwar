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
    assert policy.get("roles.campaign") == "캠페인 담당" and policy.get("roles.contract") == "계약 담당"
    assert policy.get("roles.logistics") == "물류" and policy.get("roles.cs") == "CS"


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
    assert c["facts"]["phase2"] == {"qty": 4700, "date": "2026-08-28", "amount_krw": 606285}  # 판매율에 맞춰 6,000→4,700, 집행일 8/28
    assert "콘텐츠 수정" not in ex[0]["detail"]["reason"]  # 이 대본에는 콘텐츠 수정 단계가 없다


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


# ---- 수정 회차 1: 역할 이름 정책의 연쇄·공백·시작 불가

def _can(eng, key, role):
    return role in [r.strip() for r in policy.get(key).split(",")]


def test_roles_campaign을_바꾸면_admin_목록의_옛_이름도_새_이름으로_바뀐다(store):
    eng = Engine(store, provider=FakeProvider([]))
    eng.change_policy("Masil 대표", "roles.campaign", "품질", "시험")
    for key in ("admin.review_inputters", "admin.return_inputters", "admin.registry_editors"):
        assert _can(eng, key, "품질") and not _can(eng, key, "캠페인 담당")
    assert _can(eng, "admin.return_inputters", "CS") and _can(eng, "admin.registry_editors", "계약 담당")  # 다른 역할은 그대로
    auto = [h for h in store.policy_history() if h["reason"] == "roles.campaign 변경에 따라 자동 반영"]
    assert {h["key"] for h in auto} == {"admin.review_inputters", "admin.return_inputters", "admin.registry_editors"}
    assert all(h["actor"] == "Masil 대표" for h in auto)


def test_새_캠페인_역할은_운영에서_반품을_입력하고_등록부를_고치고_옛_역할은_못_한다(store):
    eng = Engine(store, provider=FakeProvider([]))
    eng.change_policy("Masil 대표", "roles.campaign", "품질", "시험")
    eng.set_mode("Masil 대표", "운영")
    assert eng.require_registry_editor("품질 담당자") == "품질"
    eng._require_inputter("품질 담당자", "admin.return_inputters", "반품")
    eng._require_inputter("품질 담당자", "admin.review_inputters", "리뷰")
    with pytest.raises(PermissionError):
        eng.require_registry_editor("캠페인 담당자")
    for key in ("admin.return_inputters", "admin.review_inputters"):
        with pytest.raises(PermissionError):
            eng._require_inputter("캠페인 담당자", key, "입력")


def test_roles_cs를_다른_역할과_같게_바꿔도_목록이_깨지지_않는다(store):
    eng = Engine(store, provider=FakeProvider([]))
    eng.change_policy("Masil 대표", "roles.cs", "물류", "시험")
    assert policy.get("admin.return_inputters") == "물류,캠페인 담당"
    eng.change_policy("Masil 대표", "roles.campaign", "물류", "시험")  # 이미 있는 이름이면 중복 없이
    assert policy.get("admin.return_inputters") == "물류"


def test_역할_이름의_앞뒤_공백은_지운_값으로_저장된다(store):
    eng = Engine(store, provider=FakeProvider([]))
    eng.change_policy("Masil 대표", "roles.campaign", " 품질 ", "시험")
    assert policy.get("roles.campaign") == "품질"
    assert store.policy_history("roles.campaign")[-1]["after"] == "품질"
    eng2 = Engine(store, provider=FakeProvider([]))  # 엔진을 다시 만들어도 시작된다
    assert eng2.campaign == "품질"


def test_쉼표_목록_정책도_앞뒤_공백을_지운다(store):
    eng = Engine(store, provider=FakeProvider([]))
    eng.change_policy("Masil 대표", "admin.return_inputters", "  CS,물류 ", "시험")
    assert policy.get("admin.return_inputters") == "CS,물류"


def test_공백_역할_이름으로도_품질_담당자가_공지할_수_있다(store):
    eng, _, cid, st = scene2(store, ACCEPT, SCM_PART)
    to_scm_reply(eng, store, cid, st, "3,000개까지 허용합니다.")
    eng.play(st[4]); eng.play(st[5])
    eng.change_policy("Masil 대표", "roles.campaign", " 품질 ", "시험")
    assert eng.announce(cid, "품질 담당자", qty=3000)["changed"] is True


def test_저장된_역할_덮어쓰기가_사람_목록에_없어도_엔진은_시작되고_경고가_남는다(store):
    eng = Engine(store, provider=FakeProvider([]))
    eng.change_policy("Masil 대표", "roles.campaign", "품질", "시험")
    people = scenarios.People({n: r for n, r in eng.people.people.items() if r != "품질"}, eng.people.escalation,
                              eng.people.escalation_skip)
    policy.clear_overrides()
    store2 = store  # 같은 저장소: 열 때 저장된 덮어쓰기를 다시 적용
    store2._apply_policy_overrides()
    assert policy.get("roles.campaign") == "품질"
    eng2 = Engine(store2, provider=FakeProvider([]), people=people)
    assert eng2.campaign == "캠페인 담당"
    warn = [e for e in store.events(kind="정책덮어쓰기무시") if "roles.campaign" in e["detail"]["text"]]
    assert warn and warn[-1]["detail"]["text"] == "정책 roles.campaign의 저장된 값 '품질'이 사람 목록에 없어 기본값 '캠페인 담당'으로 시작함"


def test_파일_값_자체가_사람_목록에_없으면_여전히_오류(store):
    people = scenarios.People({"마케팅팀장": "마케팅팀"}, ("마케팅팀",))
    with pytest.raises(ValueError, match="사람 목록"):
        Engine(store, provider=FakeProvider([]), people=people)


def test_승인권자_거절로_끝난_기안도_남은_물량_입력_작업을_닫는다(store):
    _new_plan(store)
    eng = Engine(store, provider=FakeProvider([ACCEPT]))
    cid = eng.open_plan("NEW-1")
    assert _volume_task(store, cid)["status"] != "완료"
    eng.decide(cid, "마케팅팀", "거절", "시험")
    assert store.get_case(cid)["status"] == "거절"
    assert _volume_task(store, cid)["status"] == "완료"


def test_roles_contract를_바꾸면_그_역할만_통보를_발송한다(store):
    eng = Engine(store, provider=FakeProvider([NOTICE]))
    (cid,) = eng.seed("scenario_3_reject")
    steps = scenarios.load("scenario_3_reject").script
    for s in steps[:-1]:
        eng.play(s)
    eng.change_policy("Masil 대표", "roles.contract", "품질", "시험")
    with pytest.raises(PermissionError, match="품질"):
        eng.send_notice(cid, "계약 담당자")
    assert eng.send_notice(cid, "품질 담당자")["changed"] is True


def test_roles_logistics를_바꾸면_새_기안의_물류_요청_대상이_바뀐다(store):
    _new_plan(store)
    eng = Engine(store, provider=FakeProvider([ACCEPT]))
    eng.change_policy("Masil 대표", "roles.logistics", "품질", "시험")
    cid = eng.open_plan("NEW-1")
    assert [r["dept"] for r in store.list_requests(cid) if r["purpose"] == "물류 처리 능력"] == ["품질"]
