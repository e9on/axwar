"""Task 12 수정 회차 1: 사건 출처에 따른 초기화 범위, 리뷰·반품 입력 권한, 2차 승인·집행 단계."""
import json
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
from test_flow_11b import ACCEPT, COLOR, SCM_PART, scene2  # noqa: E402

HAPPY = json.dumps({"reason": "만족", "sentiment": "긍정", "content_gap": False, "confidence": 0.9}, ensure_ascii=False)
PLAN = {"plan_id": "PLAN-운영", "campaign_id": "CMP-0005", "influencer_id": "INF-002", "channel": "라이브",
        "requested_budget_krw": 5_000_000, "expected_gmv_krw": 40_000_000,
        "settlement_date": "2026-09-14", "contract_deadline": "2026-09-11"}


@pytest.fixture
def store(tmp_path):
    s = open_db(tmp_path / "t.db")
    yield s
    s.close()


def ops_case(store, *responses):
    """운영 모드에서 화면 등록 기안으로 연 운영 사건."""
    eng = Engine(store, provider=FakeProvider(list(responses)))
    store.set_mode("운영")
    store.add_plan(PLAN, "캠페인 담당자")
    return eng, eng.open_plan("PLAN-운영")


# ---------------------------------------------------------------- 판정 1: 운영 사건은 초기화 뒤 남는다

def test_시연_초기화를_해도_운영_사건과_딸린_기록이_남는다(store):
    eng, ops = ops_case(store)
    assert store.get_case(ops)["origin"] == "운영" and store.list_requests(ops)
    store.set_mode("시연")
    cids = eng.seed("scenario_1")
    assert ops not in cids and store.get_case(ops)["ref_id"] == "PLAN-운영"
    assert store.get_case(ops)["status"] == "회신 대기" and store.list_requests(ops)
    assert all(store.get_case(c)["origin"] == "시연" for c in cids)
    eng.seed("scenario_1")  # 다시 불러와도 운영 사건은 그대로, 시연 사건만 새로
    assert store.get_case(ops)["ref_id"] == "PLAN-운영"
    assert sum(1 for c in store.list_cases() if c["origin"] == "운영") == 1


# ---------------------------------------------------------------- 판정 2: 리뷰·반품 입력 권한

def test_정책에_리뷰_반품_입력_역할이_있고_가정으로_표시된다():
    for key, roles in (("admin.review_inputters", ["캠페인 담당", "CS"]), ("admin.return_inputters", ["CS", "캠페인 담당"])):
        value, source, _ = policy.base_entry(key)
        assert [r.strip() for r in value.split(",")] == roles and source.startswith("가정")


def test_운영에서_권한_없는_사람의_반품_입력은_거부되고_저장되지_않는다(store):
    eng, cid = ops_case(store)
    for who in ("물류 담당자", "그룹 CEO", None):  # 마지막은 시연 대본 재생(시스템)
        with pytest.raises(PermissionError):
            eng.add_returns(cid, 1, 1, actor=who)
    assert "returns" not in store.get_case(cid)["facts"]
    eng.add_returns(cid, 1, 2, actor="CS 담당자")
    assert store.get_case(cid)["facts"]["returns"]["color"] == 2
    eng.add_returns(cid, 0, 0, actor="캠페인 담당자")


def test_운영에서_권한_없는_사람의_리뷰_입력은_거부되고_AI도_안_부른다(store):
    eng, cid = ops_case(store, HAPPY)
    for who in ("물류 담당자", "마케팅팀장", None):
        with pytest.raises(PermissionError):
            eng.add_reviews(cid, [("립", "좋아요")], actor=who)
    assert store.list_reviews(cid) == [] and eng._fixed.calls == []
    eng.add_reviews(cid, [("립", "좋아요")], actor="캠페인 담당자")
    assert len(store.list_reviews(cid)) == 1


def test_입력_역할을_정책에서_바꾸면_따른다(store):
    eng, cid = ops_case(store)
    store.change_policy("admin.return_inputters", "품질", "Masil 대표", "시험")
    with pytest.raises(PermissionError):
        eng.add_returns(cid, 1, 1, actor="CS 담당자")
    eng.add_returns(cid, 1, 1, actor="품질 담당자")


def test_시연_모드에서는_대본_재생이_행위자_없이_입력할_수_있다(store):
    eng = Engine(store, provider=FakeProvider([HAPPY]))
    cid = eng.seed("scenario_2")[0]
    eng.add_returns(cid, 1, 1)
    eng.add_reviews(cid, [("립", "좋아요")])
    assert len(store.list_reviews(cid)) == 1


# ---------------------------------------------------------------- 판정 3: 2차 승인·집행 단계

WAIT, EXEC = "2차 승인 대기", "2차 집행"


def sales_scene(store, orders=2600, returns=50, extra=()):
    """scenario_2_sales를 판매 실적 입력 직전까지(8/24 반품 입력 뒤) 진행한 엔진. 판매는 직접 넣는다."""
    eng, _, cid, st = scene2(store, ACCEPT, SCM_PART, *extra, name="scenario_2_sales")
    first_p2 = next((i for i, x in enumerate(st) if x.get("stage") == "2차" or x["action"] == "판매"), len(st))
    for step in st[:first_p2]:
        eng.play(step)
    return eng, cid


def to_wait(store):
    eng, cid = sales_scene(store)
    eng.record_phase1_sales(cid, "캠페인 담당자", 2600, 50)
    return eng, cid


def facts(store, cid):
    return store.get_case(cid)["facts"]


def status(store, cid):
    return store.get_case(cid)["status"]


def test_판매율_조절로_2차가_열리면_2차_승인_대기에_들어간다(store):
    eng, cid = to_wait(store)
    f = facts(store, cid)
    assert status(store, cid) == WAIT
    assert f["phase2_deadline"] == "2026-08-25"  # 집행일 전날(8/23)은 이미 지나 최소 승인 일수만큼 늘림
    assert eng.phase2_view(cid)["pending_roles"] == ["Masil 대표", "그룹"]
    ev = store.events(cid, kind="2차승인대기")
    assert len(ev) == 1 and "Masil 대표" in ev[0]["detail"]["text"]
    todo = eng.todo("Masil 대표")["승인 대기"]
    assert [(i["case_id"], i["stage"], i["deadline"]) for i in todo] == [(cid, "2차", "2026-08-25")]
    assert eng.todo("그룹 CEO")["승인 대기"] == []  # 1차 승인권자는 2차 대상이 아님


def test_보류_상태에서는_2차_승인_대기에_들어가지_않는다(store):
    eng, cid = sales_scene(store)
    eng.record_phase1_sales(cid, "캠페인 담당자", 1000, 0)  # 판매율 33% < 하한
    assert status(store, cid) == "2차 보류" and "phase2_deadline" not in facts(store, cid)
    assert store.events(cid, kind="2차승인대기") == []


def test_반품_자동_보류면_들어가지_않는다(store):
    eng, cid = sales_scene(store)
    eng.add_returns(cid, 900, 900)  # 기준선을 크게 넘음
    assert status(store, cid) == "2차 보류"
    eng.record_phase1_sales(cid, "캠페인 담당자", 2600, 50)
    assert status(store, cid) == "2차 보류" and store.events(cid, kind="2차승인대기") == []


def test_리뷰_잠금이면_들어가지_않는다(store):
    eng, cid = sales_scene(store, extra=(COLOR,))
    eng.add_reviews(cid, [("립", "색이 영상과 달라요")])
    eng.record_phase1_sales(cid, "캠페인 담당자", 2600, 50)
    assert status(store, cid) == "2차 잠금" and store.events(cid, kind="2차승인대기") == []


def test_판매_실적이_없으면_들어가지_않는다(store):
    eng, cid = sales_scene(store)
    assert status(store, cid) == "2차 잠금"


def test_2차_승인권자가_모두_승인하면_2차_집행_그리고_집행일이_지나면_완료(store):
    eng, cid = to_wait(store)
    r = eng.decide_phase2(cid, "Masil 대표", "승인", "2차 진행")
    assert r["changed"] and r["status"] == WAIT and r["pending"] == ["그룹"]
    assert facts(store, cid)["phase2_approved_roles"] == ["Masil 대표"]
    r = eng.decide_phase2(cid, "그룹 재무", "승인")
    assert r["status"] == EXEC
    t = {(x["dept"], x["title"]): x["due"] for x in store.list_tasks(cid)}
    assert t[("물류", "물류 출고(2차)")] == "2026-08-26" and t[("CS", "CS 대비(2차)")] == "2026-08-26"
    assert any(e["detail"]["target"] == "그룹" and "2차" in e["detail"]["text"]
               for e in store.events(cid, kind="그룹보고"))
    eng.advance(date(2026, 8, 26))  # 집행일(8/24에서 승인 기간 확보로 8/26) 당일은 아직 집행 중
    assert status(store, cid) == EXEC
    eng.advance(date(2026, 8, 27))
    assert status(store, cid) == "완료"
    res = facts(store, cid)["phase2_result"]
    assert res["result"] == "집행" and "2차" in res["text"]
    assert [e["detail"]["to"] for e in store.events(cid, kind="상태변경")][-3:] == [WAIT, EXEC, "완료"]


def test_2차_승인은_2차_승인권자만(store):
    eng, cid = to_wait(store)
    for who in ("그룹 CEO", "캠페인 담당자", "이사회"):
        with pytest.raises(PermissionError, match="2차 승인권자"):
            eng.decide_phase2(cid, who, "승인")
    with pytest.raises(ValueError, match="승인 또는 거절"):
        eng.decide_phase2(cid, "Masil 대표", "분할승인")
    assert facts(store, cid).get("phase2_approved_roles") == []


def test_2차_승인_대기가_아닌_건은_2차_결정을_못한다(store):
    eng, cid = sales_scene(store)  # 2차 잠금
    with pytest.raises(ValueError, match="2차 승인 대기"):
        eng.decide_phase2(cid, "Masil 대표", "승인")


def test_2차_거절이면_2차_없이_완료되고_통보는_만들지_않는다(store):
    eng, cid = to_wait(store)
    before_cases, before_tasks = len(store.list_cases()), len(store.list_tasks(cid))
    r = eng.decide_phase2(cid, "그룹 재무", "거절", "재고 부담")
    assert r["status"] == "완료" and r["changed"]
    res = facts(store, cid)["phase2_result"]
    assert res["result"] == "거절" and "재고 부담" in res["text"]
    assert len(store.list_tasks(cid)) == before_tasks and len(store.list_cases()) == before_cases
    assert not [x for x in store.list_tasks(cid) if "(2차)" in x["title"] or "통보" in x["title"]]
    assert [e["detail"]["result"] for e in store.events(cid, kind="2차결정")] == ["거절"]


def test_2차_기한까지_승인이_없으면_기본_거부로_완료(store):
    eng, cid = to_wait(store)
    eng.advance(date(2026, 8, 25))
    assert status(store, cid) == "완료"
    res = facts(store, cid)["phase2_result"]
    assert res["result"] == "기본 거부" and "기본 거부" in res["text"] and "8/25" in res["text"]
    assert not [x for x in store.list_tasks(cid) if "(2차)" in x["title"] or "통보" in x["title"]]
    assert [e["detail"]["result"] for e in store.events(cid, kind="2차결정")] == ["기본 거부"]
    with pytest.raises(ValueError, match="2차 승인 대기"):
        eng.decide_phase2(cid, "Masil 대표", "승인")


def test_기한이_지난_뒤_결정하려_해도_기본_거부(store):
    eng, cid = to_wait(store)
    store.set_clock(date(2026, 8, 25))  # 기준일만 옮김(기한 점검 없이)
    r = eng.decide_phase2(cid, "Masil 대표", "승인")
    assert r["changed"] is False and r["status"] == "완료" and "기본 거부" in r["message"]


def test_일부_승인_뒤에도_다른_역할이_거절하면_완료(store):
    eng, cid = to_wait(store)
    eng.decide_phase2(cid, "Masil 대표", "승인")
    eng.decide_phase2(cid, "그룹 재무", "거절", "그룹 반대")
    assert status(store, cid) == "완료" and facts(store, cid)["phase2_result"]["result"] == "거절"
    assert not [x for x in store.list_tasks(cid) if "(2차)" in x["title"]]


def test_판매율_보류를_계속으로_판단하면_2차_승인_대기에_들어간다(store):
    eng, cid = sales_scene(store)
    eng.record_phase1_sales(cid, "캠페인 담당자", 1000, 0)
    assert status(store, cid) == "2차 보류"
    r = eng.continue_phase2(cid, "캠페인 담당자", 500, "재방송 예정")
    assert r["status"] == WAIT and status(store, cid) == WAIT and facts(store, cid)["phase2"]["qty"] == 500


@pytest.fixture
def ample(monkeypatch):
    monkeypatch.setattr(inventory, "line_spare", lambda category, day: 10**9)


def open_phase2(store, monkeypatch, days_ahead):
    """2차 집행일이 days_ahead일 뒤인 2차 잠금 사건에서 판매 실적을 넣어 승인 대기로 만든다."""
    eng = Engine(store, provider=FakeProvider([]))
    monkeypatch.setattr(eng, "_contract_terms", lambda inf: (date(2099, 1, 1), True))
    cid = eng.seed("scenario_1")[0]
    f = facts(store, cid)
    today = store.get_clock()
    f["phase1"] = {"qty": 1000, "date": (today - timedelta(days=28)).isoformat()}
    f["phase2"] = {"qty": 1000, "date": (today + timedelta(days=days_ahead)).isoformat(), "amount_krw": 2_000_001}
    eng._phase2_approvers(f, cid)
    store.update_facts(cid, f, "시험", "2차 준비")
    store.set_status(cid, "2차 잠금", "시험", "")
    eng.record_phase1_sales(cid, "캠페인 담당자", 950, 50)
    return eng, cid


def test_2차_기한은_집행일_전날(store, monkeypatch, ample):
    eng, cid = open_phase2(store, monkeypatch, days_ahead=10)
    assert facts(store, cid)["phase2_deadline"] == (store.get_clock() + timedelta(days=9)).isoformat()


def test_2차_기한_조기_경고와_방치_올림과_기본_거부(store, monkeypatch, ample):
    eng, cid = open_phase2(store, monkeypatch, days_ahead=10)
    assert status(store, cid) == WAIT
    deadline = date.fromisoformat(facts(store, cid)["phase2_deadline"])
    eng.advance(deadline - timedelta(days=6))  # 경고 창(기한 5일 전) 전
    assert store.events(cid, kind="조기경고") == []
    eng.advance(deadline - timedelta(days=5))
    warn = store.events(cid, kind="조기경고")
    assert len(warn) == 1 and warn[0]["detail"]["stage"] == "2차" and "2차 승인 기한" in warn[0]["detail"]["text"]
    target = warn[0]["detail"]["target"]
    assert [(i["case_id"]) for i in eng.todo(target)["기한 임박"]] == [cid]
    eng.advance(deadline - timedelta(days=4))  # 같은 대상에게 다시 경고하지 않음
    assert len(store.events(cid, kind="조기경고")) == 1
    eng.advance(deadline - timedelta(days=3))  # 경고 뒤 정책 일수(2일) 지남 -> 방치 올림
    stale = store.events(cid, kind="방치올림")
    assert len(stale) == 1 and stale[0]["detail"]["key"] == "2차 승인"
    assert status(store, cid) == WAIT
    assert [i["case_id"] for i in eng.todo(stale[0]["detail"]["target"])["알림"]] == [cid]
    eng.advance(deadline)
    assert status(store, cid) == "완료"
    assert facts(store, cid)["phase2_result"]["result"] == "기본 거부"
    assert eng.todo(stale[0]["detail"]["target"])["알림"] == []  # 끝난 건의 올림 알림은 내려감


def test_방치_올림을_받은_상급자가_2차를_승인하면_아래_역할_몫을_채운다(store, monkeypatch, ample):
    eng, cid = open_phase2(store, monkeypatch, days_ahead=12)
    # 2차 승인권자를 마케팅팀만으로 바꿔 올림 대상(Masil 대표)이 승인권자 밖이 되게 한다
    f = facts(store, cid)
    f["phase2_approvers"], f["phase2_approver_hits"] = ["마케팅팀"], []
    store.update_facts(cid, f, "시험", "")
    deadline = date.fromisoformat(f["phase2_deadline"])
    with pytest.raises(PermissionError):
        eng.decide_phase2(cid, "Masil 대표", "승인")  # 아직 올림 전
    eng.advance(deadline - timedelta(days=5))
    eng.advance(deadline - timedelta(days=3))
    assert store.events(cid, kind="방치올림")[0]["detail"]["target"] == "Masil 대표"
    r = eng.decide_phase2(cid, "Masil 대표", "승인")
    assert r["status"] == EXEC and facts(store, cid)["phase2_approved_roles"] == ["마케팅팀"]
