"""Task 11b 수정 회차 5: 계속 판단의 게이트 재확인, 실적 입력 작업 완료, 사람 확인 요청 단위 올림, 물류 몫 0, 올림 대상 이사회 제외.

수치는 이 시험 안에서만 정하고, 엔진은 정책값만 읽는다.
"""
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from app import policy
from app.ai.providers import FakeProvider
from app.engine.flow import P_STOCK, Engine, _required_roles
from app.store.db import open_db

sys.path.insert(0, str(Path(__file__).parent))
from test_flow_11b import ACCEPT, SCM_FULL, SCM_VAGUE, _ample_plan2, _j, scene2, scm_request, to_scm_reply  # noqa: E402
from test_flow_escalation import hold_case, scm_human_case  # noqa: E402
from test_flow_sellthrough import ACTOR, facts, locked  # noqa: E402


@pytest.fixture
def store(tmp_path):
    s = open_db(tmp_path / "t.db")
    yield s
    s.close()


def after_days():
    return policy.get("escalation.after_days")


# ---------------------------------------------------------------- 중간 1: 계속 판단이 게이트를 다시 본다

def test_판매율_보류_중_반품이_기준을_넘으면_계속_판단을_거부한다(store, monkeypatch):
    eng, cid, _ = hold_case(store, monkeypatch)
    eng.add_returns(cid, 0, 600)  # 보류 중에 색상불만 60%
    with pytest.raises(ValueError, match="반품"):
        eng.continue_phase2(cid, ACTOR, 300, "계속 진행")
    assert store.get_case(cid)["status"] == "2차 보류"
    assert "phase2_decision" not in facts(store, cid) and store.events(cid, kind="판매율판단") == []


def test_반품_보류_사유가_있어도_2차_취소는_할_수_있다(store, monkeypatch):
    eng, cid, _ = hold_case(store, monkeypatch)
    eng.add_returns(cid, 0, 600)
    assert eng.cancel_phase2(cid, ACTOR, "반품이 많아 중단")["status"] == "1차 집행"


def test_판매율_보류_중_리뷰_잠금이_생기면_계속_판단을_거부한다(store, monkeypatch):
    eng, cid, _ = hold_case(store, monkeypatch)
    f = facts(store, cid)
    f["color_review_flagged"] = True
    store.update_facts(cid, f, "시험", "리뷰 잠금")
    with pytest.raises(ValueError, match="리뷰|콘텐츠"):
        eng.continue_phase2(cid, ACTOR, 300, "계속 진행")
    assert store.get_case(cid)["status"] == "2차 보류"


def test_리뷰_잠금이_풀리면_계속_판단을_받는다(store, monkeypatch):
    eng, cid, _ = hold_case(store, monkeypatch)
    f = facts(store, cid)
    f["color_review_flagged"], f["content_fix_confirmed"] = True, True
    store.update_facts(cid, f, "시험", "수정 확인")
    assert eng.continue_phase2(cid, ACTOR, 300, "계속 진행")["status"] == "2차 승인 대기"  # 수정 회차 1: 잠금 대신 승인 대기


# ---------------------------------------------------------------- 낮음 2: 실적 입력 작업 완료

def test_판매_실적을_입력하면_실적_입력_작업이_완료된다(store, monkeypatch):
    eng, cid = locked(store, monkeypatch)
    eng.check_deadlines()
    pend = [t for t in store.list_tasks(cid) if t["title"] == "1차 판매 실적 입력"]
    assert len(pend) == 1 and pend[0]["status"] == "대기"
    eng.record_phase1_sales(cid, ACTOR, orders=900, returns=0)
    assert [t["status"] for t in store.list_tasks(cid) if t["title"] == "1차 판매 실적 입력"] == ["완료"]
    assert [x for x in eng.todo(ACTOR)["작업"] if x["title"] == "1차 판매 실적 입력"] == []


# ---------------------------------------------------------------- 낮음 3: 경고·올림은 사람 확인 요청 단위

def _second_human_check(store, eng, cid):
    """첫 사람 확인을 끝내고(요청 처리됨) 같은 건에 두 번째 SCM 사람 확인을 만든다. 새 요청 id를 돌려준다."""
    store.set_request_status(scm_request(store, cid)["id"], "처리됨", "시험", "첫 사람 확인 끝")
    rid = store.add_request(cid, "SCM", "재요청", False, P_STOCK)
    store.set_request_status(rid, "사람 확인", "AI", "애매함")
    return rid


def test_두_번째_사람_확인에도_경고와_올림이_다시_나온다(store):
    eng, cid, warned = scm_human_case(store)
    first = scm_request(store, cid)["id"]
    eng.advance(warned + timedelta(days=after_days()))
    assert len(store.events(cid, kind="방치올림")) == 1
    rid = _second_human_check(store, eng, cid)
    assert rid != first
    day = store.get_clock()
    n_warn = len([e for e in store.events(cid, kind="조기경고") if e["detail"].get("scm_human")])
    eng._warn_scm_human(store.get_case(cid), day)
    assert len([e for e in store.events(cid, kind="조기경고") if e["detail"].get("scm_human")]) == n_warn + 1
    eng._escalate_scm_human(store.get_case(cid), day + timedelta(days=after_days() - 1))
    assert len(store.events(cid, kind="방치올림")) == 1  # 두 번째 요청은 아직 정책 일수 전
    eng._escalate_scm_human(store.get_case(cid), day + timedelta(days=after_days()))
    ev = store.events(cid, kind="방치올림")
    assert len(ev) == 2 and ev[0]["detail"]["key"] != ev[1]["detail"]["key"]


def test_올려_받은_처리_권한은_그_요청에만_적용된다(store):
    eng, cid, warned = scm_human_case(store)
    eng.advance(warned + timedelta(days=after_days()))
    target = store.events(cid, kind="방치올림")[0]["detail"]["target"]
    rid = _second_human_check(store, eng, cid)
    with pytest.raises(PermissionError):
        eng.resolve_human_check(rid, target, "허용합니다")


# ---------------------------------------------------------------- 낮음 4: 물류 몫 0

def test_물류_몫이_0이면_승인도_분할_승인도_거부하고_하루_수량이_나가지_않는다(store):
    eng, cid = _ample_plan2(store, "0개까지", _j(stance="조건부수용", qty_limit=0))
    f = facts(store, cid)
    assert f["stock"]["share"] == 0 and f["stock"]["day_qty"] > 0 and f["stock"]["shortage"] is False
    role = _required_roles(f)[0]
    for action in ("승인", "분할승인"):
        with pytest.raises(ValueError, match="물류 몫"):
            eng.decide(cid, role, action)
    assert store.get_case(cid)["status"] == "승인 대기" and facts(store, cid)["phase1"] is None
    assert eng.decide(cid, role, "거절")["status"] == "거절"


# ---------------------------------------------------------------- 결정 11: 올림 대상에서 이사회 제외

@pytest.mark.parametrize("roles,expected", [
    (["CEO", "이사회"], "CEO"),
    (["이사회"], "CEO"),
    (["Masil 대표", "이사회"], "CEO"),
    (["마케팅팀"], "Masil 대표"),
])
def test_올림_대상은_이사회를_건너뛴다(store, roles, expected):
    eng = Engine(store, provider=FakeProvider([]))
    assert eng._escalation_target(roles) == expected
