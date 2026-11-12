"""Task 12에서 엔진에 더한 것: 회신 대상 권한, 정책·모드 변경 권한, 시연 전용 동작의 모드 제한, 건 상세와 AI 브리핑 저장."""
import sys
from pathlib import Path

import pytest

from app import policy
from app.ai.providers import FakeProvider
from app.engine.flow import Engine
from app.store.db import open_db

sys.path.insert(0, str(Path(__file__).parent))
from test_flow_11b import ACCEPT, SCM_PART, scene2, scm_request  # noqa: E402


@pytest.fixture
def store(tmp_path):
    s = open_db(tmp_path / "t.db")
    yield s
    s.close()


def logistics_request(store, cid):
    return [r for r in store.list_requests(cid) if r["dept"] == "물류"][0]


# ---- 정책 항목: 편집 권한 역할은 정책 파일에서 읽는다

def test_정책_편집_역할이_정책_파일_항목이고_가정으로_표시된다():
    value, source, _ = policy.base_entry("admin.policy_editors")
    assert source.startswith("가정") and "admin.policy_editors" in policy.keys()
    assert [r.strip() for r in value.split(",")] == ["Masil 대표", "CEO"]


def test_덮어쓴_뒤에도_파일_출처는_그대로_보인다(store):
    store.change_policy("escalation.after_days", 4, "Masil 대표", "시험")
    assert policy.is_overridden("escalation.after_days")
    assert policy.base_entry("escalation.after_days")[0] != 4
    assert not policy.base_entry("escalation.after_days")[1].startswith("설정 화면 변경")
    assert policy.entry("escalation.after_days")[1].startswith("설정 화면 변경")


# ---- 회신 대상 권한

def test_회신은_요청_대상_역할만_제출한다(store):
    eng, _, cid, _ = scene2(store, ACCEPT)
    rid = logistics_request(store, cid)["id"]
    with pytest.raises(PermissionError, match="물류"):
        eng.submit_reply(rid, "캠페인 담당자", "하루 20,000개 가능합니다.")
    assert store.list_replies(rid) == []  # 거부된 회신은 저장하지 않는다
    r = eng.submit_reply(rid, "물류 담당자", "평소 하루 20,000개, 최대 26,000개까지 처리할 수 있습니다.")
    assert r["ignored"] is False and r["status"] == "승인 대기"


def test_모르는_사람의_회신은_거부(store):
    eng, _, cid, _ = scene2(store, ACCEPT)
    with pytest.raises(PermissionError, match="등록되지 않은"):
        eng.submit_reply(logistics_request(store, cid)["id"], "아무개", "가능")


def test_사람_확인_상태_요청은_회신으로_다시_넣을_수_없다(store):
    eng, _, cid, _ = scene2(store, ACCEPT)
    rid = logistics_request(store, cid)["id"]
    store.set_request_status(rid, "사람 확인", "시험", "시험")
    with pytest.raises(ValueError, match="사람 확인"):
        eng.submit_reply(rid, "물류 담당자", "다시 답합니다")


# ---- 정책·모드 변경 권한

def test_정책_수정은_편집_역할만(store):
    eng = Engine(store, provider=FakeProvider([]))
    with pytest.raises(PermissionError, match="정책"):
        eng.change_policy("캠페인 담당자", "escalation.after_days", 5, "시험")
    assert store.policy_history() == []
    eng.change_policy("Masil 대표", "escalation.after_days", 5, "시험")
    eng.change_policy("그룹 CEO", "escalation.after_days", 6, "시험")
    h = store.policy_history("escalation.after_days")
    assert [x["actor"] for x in h] == ["Masil 대표", "그룹 CEO"] and h[1]["before"] == 5 and h[1]["after"] == 6
    assert policy.get("escalation.after_days") == 6


def test_편집_역할_목록을_사람_목록에_없는_역할로_바꿀_수_없다(store):
    eng = Engine(store, provider=FakeProvider([]))
    with pytest.raises(ValueError, match="역할"):
        eng.change_policy("Masil 대표", "admin.policy_editors", "Masil 대표,없는역할", "시험")
    eng.change_policy("Masil 대표", "admin.policy_editors", "Masil 대표", "CEO 제외")
    with pytest.raises(PermissionError):
        eng.change_policy("그룹 CEO", "escalation.after_days", 5, "시험")


def test_모드_전환은_편집_역할만(store):
    eng = Engine(store, provider=FakeProvider([]))
    with pytest.raises(PermissionError, match="모드"):
        eng.set_mode("캠페인 담당자", "운영")
    assert store.get_mode() == "시연"
    eng.set_mode("Masil 대표", "운영")
    assert store.get_mode() == "운영"
    with pytest.raises(ValueError):
        eng.set_mode("Masil 대표", "엉뚱")


# ---- 시연 전용 동작은 운영 모드에서 막힌다

def test_운영_모드에서는_대본_재생이_막힌다(store):
    eng, _, cid, st = scene2(store, ACCEPT)
    store.set_mode("운영")
    with pytest.raises(PermissionError, match="운영 모드"):
        eng.play(st[0])
    with pytest.raises(PermissionError, match="운영 모드"):
        eng.run_script("scenario_2", 1)
    assert store.get_case(cid)["status"] == "회신 대기"


# ---- 건 상세

def test_건_상세는_근거_규칙판정_기록_권한이동을_담는다(store):
    eng, _, cid, st = scene2(store, ACCEPT, SCM_PART)
    for s in st[:6]:
        eng.play(s)
    d = eng.case_detail(cid, viewer="그룹 CEO")
    assert d["case"]["ref_id"] == "PLAN-001" and d["case"]["status"] == "2차 잠금"
    assert d["rule"]["approvers"] == ["CEO", "이사회", "이사회 의결"]
    assert d["rule"]["approved_roles"] == ["CEO", "이사회"] and d["rule"]["pending_roles"] == []
    assert {h["badge"] for h in d["rule"]["hits"]} and all("text" in h and "source" in h for h in d["rule"]["hits"])
    assert d["evidence"]["indicators"]["good"] is False and d["evidence"]["indicators"]["hits"]
    assert d["phase2"]["approvers"] == ["Masil 대표", "그룹 보고", "그룹 확인"]
    assert len(d["approver_changes"]) == 1 and d["viewer"] == {
        "person": "그룹 CEO", "role": "CEO", "can_decide": False, "can_escalate": False,
        "can_escalate_phase2": False, "can_decide_phase2": False}
    assert [r["dept"] for r in d["requests"]] == ["물류", "SCM"] and d["requests"][0]["replies"]
    assert any(e["kind"] == "상태변경" for e in d["history"]) and d["judgments"]
    assert d["briefing"] is None and d["counterpoints"] is None  # 읽기만으로는 AI를 부르지 않는다


def test_건_상세의_viewer는_승인권자_여부를_알려준다(store):
    eng, _, cid, st = scene2(store, ACCEPT)
    eng.play(st[0])
    assert eng.case_detail(cid, viewer="그룹 CEO")["viewer"]["can_decide"] is True
    assert eng.case_detail(cid, viewer="캠페인 담당자")["viewer"]["can_decide"] is False
    assert "viewer" not in eng.case_detail(cid)


def test_브리핑은_만들_때만_AI를_부르고_사실이_같으면_저장본을_쓴다(store):
    eng, fake, cid, st = scene2(store, ACCEPT)
    eng.play(st[0])
    n = len(fake.calls)
    fake._responses.extend(["브리핑 문장입니다.", "반대 근거 문장입니다."])
    out = eng.write_briefing(cid, "그룹 CEO")
    assert out["briefing"]["text"] == "브리핑 문장입니다." and out["counterpoints"]["text"] == "반대 근거 문장입니다."
    assert out["briefing"]["ok"] is True and len(fake.calls) == n + 2
    again = eng.write_briefing(cid, "그룹 CEO")  # 사실이 안 바뀌었으니 새로 부르지 않는다
    assert again["briefing"]["text"] == "브리핑 문장입니다." and len(fake.calls) == n + 2
    d = eng.case_detail(cid)
    assert d["briefing"]["text"] == "브리핑 문장입니다." and d["briefing"]["stale"] is False


def test_사실이_바뀌면_저장된_브리핑은_낡았다고_표시되고_다시_만든다(store):
    eng, fake, cid, st = scene2(store, ACCEPT, "브리핑 1", "반대 1", SCM_PART, "브리핑 2", "반대 2")
    eng.play(st[0])
    eng.write_briefing(cid, "그룹 CEO")
    eng.play(st[1]); eng.play(st[2]); eng.play(st[3])  # SCM 회신으로 분할안이 바뀜
    d = eng.case_detail(cid)
    assert d["briefing"]["text"] == "브리핑 1" and d["briefing"]["stale"] is True
    n = len(fake.calls)
    assert eng.write_briefing(cid, "그룹 CEO")["briefing"]["text"] == "브리핑 2" and len(fake.calls) == n + 2


def test_브리핑_실패는_대체_문구와_ok_거짓(store):
    eng, fake, cid, st = scene2(store, ACCEPT)
    eng.play(st[0])
    fake._responses.extend([RuntimeError("끊김"), RuntimeError("끊김")])
    out = eng.write_briefing(cid, "그룹 CEO")
    assert out["briefing"]["ok"] is False and "AI 응답 없음" in out["briefing"]["text"]


def test_모르는_사람은_브리핑을_만들_수_없다(store):
    eng, _, cid, st = scene2(store, ACCEPT)
    with pytest.raises(PermissionError):
        eng.write_briefing(cid, "아무개")
