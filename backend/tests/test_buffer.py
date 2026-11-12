"""기한 여유 3일(사용자 결정 2026-11-12): 기본 거부는 기한 - buffer_days일 아침, 승인·상신은 그 전날까지.

1차(기안·전속계약)·2차(집행일)·decide·escalate·일일 점검이 모두 rules/deadline.py의 같은 규칙을 쓴다.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import policy
from app.api.main import create_app
from app.rules.deadline import approval_deadline, deny_date
from app.store.db import open_db

sys.path.insert(0, str(Path(__file__).parent))
from test_final_fix import OPIN, WHY, Day, ops_wait  # noqa: E402
from test_flow_11b import LACK, NOTICE, scene3  # noqa: E402
from test_flow_fix1 import facts, status  # noqa: E402
from test_flow_fix2 import ample, make_open  # noqa: E402,F401

DEADLINE = date(2026, 9, 11)          # 운영 시험 기안의 확정 기한
DENY = date(2026, 9, 8)               # 기본 거부 실행일(기한 - 3일)
LAST_OK = date(2026, 9, 7)            # 승인 마감일(실행일 전날)


@pytest.fixture
def day():
    return Day(date(2026, 9, 1))


@pytest.fixture
def store(tmp_path, day):
    s = open_db(tmp_path / "t.db", today=day)
    yield s
    s.close()


@pytest.fixture
def fix_store(tmp_path):
    s = open_db(tmp_path / "f.db")
    yield s
    s.close()


# ---------------------------------------------------------------- 1차 기안

def test_기한과_기본_거부_실행일과_승인_마감일은_규칙_함수와_같다():
    assert (deny_date(DEADLINE), approval_deadline(DEADLINE)) == (DENY, LAST_OK)


def test_1차_일일_점검은_기한_3일_전_아침에_기본_거부한다(store, day):
    eng, cid = ops_wait(store)
    day.d = LAST_OK
    eng.check_deadlines()
    assert status(store, cid) == "승인 대기"
    day.d = DENY
    out = eng.check_deadlines()
    assert status(store, cid) == "확정 보류" and [a["action"] for a in out if a["case_id"] == cid] == ["기본거부"]
    assert any(t["title"] == "확정 보류(철회) 처리" and t["due"] == DENY.isoformat() for t in store.list_tasks(cid))


def test_1차_승인은_마감일까지_통과한다(store, day):
    eng, cid = ops_wait(store)
    day.d = LAST_OK
    assert eng.decide(cid, "마케팅팀장", "승인")["status"] == "1차 집행"


def test_1차_승인_실행일_당일은_기본_거부로_처리된다(store, day):
    eng, cid = ops_wait(store)
    day.d = DENY
    r = eng.decide(cid, "마케팅팀장", "승인")
    assert r["changed"] is False and r["status"] == "확정 보류" and "기본 거부" in r["message"]


def test_1차_상신은_마감일에_되고_실행일_당일은_거부된다(store, day):
    eng, cid = ops_wait(store)
    day.d = DENY
    r = eng.escalate(cid, "마케팅팀장", "1차", OPIN, WHY)
    assert r["changed"] is False and r["status"] == "확정 보류"


def test_1차_상신_마감일(store, day):
    eng, cid = ops_wait(store)
    day.d = LAST_OK
    assert eng.escalate(cid, "마케팅팀장", "1차", OPIN, WHY)["changed"] is True


def test_1차_조기_경고는_기본_거부_실행일_기준이다(store, day):
    eng, cid = ops_wait(store)
    day.d = DENY - timedelta(days=6)  # 9/2: 실행일 6일 전, 창(5일) 밖
    eng.check_deadlines()
    assert store.events(cid, kind="조기경고") == []
    day.d = DENY - timedelta(days=5)  # 9/3
    out = eng.check_deadlines()
    assert [a["action"] for a in out if a["case_id"] == cid] == ["조기경고"]


def test_건_상세와_할_일_목록에_승인_마감일과_기한이_둘_다_나온다(store, day):
    eng, cid = ops_wait(store)
    c = TestClient(create_app(store, eng))
    d = c.get(f"/api/cases/{cid}").json()
    assert d["deadline"] == DEADLINE.isoformat() and d["approval_deadline"] == LAST_OK.isoformat()
    assert d["deny_date"] == DENY.isoformat()
    todo = c.get("/api/todo/마케팅팀장").json()["승인 대기"][0]
    assert todo["deadline"] == DEADLINE.isoformat() and todo["approval_deadline"] == LAST_OK.isoformat()
    row = c.get("/api/cases").json()[0]
    assert row["deadline"] == DEADLINE.isoformat() and row["approval_deadline"] == LAST_OK.isoformat()


# ---------------------------------------------------------------- 전속계약 7/17 (장면 3)

def test_전속계약_7_17은_7_14에_기본_거부되고_통보_작업이_생긴다(fix_store):
    eng, fake, ids, st = scene3(fix_store, NOTICE, LACK)
    contract = ids[3]
    assert fix_store.get_case(contract)["facts"]["deadline"] == "2026-07-17"
    eng.advance(date(2026, 7, 13))
    assert fix_store.get_case(contract)["status"] == "승인 대기" and not fake.calls
    eng.advance(date(2026, 7, 14))
    assert fix_store.get_case(contract)["status"] == "통보 초안"
    send = [t for t in fix_store.list_tasks(contract) if t["title"] == "통보 발송"]
    assert len(send) == 1 and send[0]["dept"] == "계약 담당" and send[0]["due"] == "2026-07-17"
    assert [fix_store.get_case(p)["status"] for p in ids[:3]] == ["확정 보류"] * 3


def test_전속계약_승인은_7_13까지_허용된다(fix_store):
    eng, fake, ids, st = scene3(fix_store, NOTICE)
    eng.advance(date(2026, 7, 13))
    assert eng.decide(ids[3], "그룹 CEO", "승인")["changed"] is True


def test_장면3_대본은_기본_거부_실행일_7_14에_맞춰_있다():
    from app.engine import scenarios
    dates = [s["date"] for s in scenarios.load("scenario_3").script if "date" in s]
    assert dates[:2] == ["2026-07-12", "2026-07-14"]


# ---------------------------------------------------------------- 2차

def test_2차_승인은_집행일_4일_전_마감일까지_된다(fix_store, monkeypatch, ample):
    eng, cid, today = make_open(fix_store, monkeypatch, 10)
    f = facts(fix_store, cid)
    planned = today + timedelta(days=10)
    assert f["phase2"]["date"] == planned.isoformat() and f["phase2_deadline"] == planned.isoformat()
    assert "phase2_planned_date" not in f  # 연기 없음
    fix_store.set_clock(planned - timedelta(days=4))  # 승인 마감일 = 집행일 - 4일
    assert eng.decide_phase2(cid, "Masil 대표", "승인")["changed"] is True


def test_2차_실행일_당일_승인은_기본_거부(fix_store, monkeypatch, ample):
    eng, cid, today = make_open(fix_store, monkeypatch, 10)
    fix_store.set_clock(today + timedelta(days=7))  # 집행일 - 3일
    r = eng.decide_phase2(cid, "Masil 대표", "승인")
    assert r["changed"] is False and r["status"] == "완료"


def test_2차_일일_점검은_집행일_3일_전_아침에_기본_거부(fix_store, monkeypatch, ample):
    eng, cid, today = make_open(fix_store, monkeypatch, 10)
    eng.advance(today + timedelta(days=6))
    assert status(fix_store, cid) == "2차 승인 대기"
    eng.advance(today + timedelta(days=7))
    assert status(fix_store, cid) == "완료"
    assert fix_store.get_case(cid)["facts"]["phase2_result"]["result"] == "기본 거부"


def test_2차_조기_경고는_기본_거부_실행일_기준(fix_store, monkeypatch, ample):
    eng, cid, today = make_open(fix_store, monkeypatch, 20)  # 실행일 today+17, 창 today+12~
    eng.advance(today + timedelta(days=11))
    assert fix_store.events(cid, kind="조기경고") == []
    eng.advance(today + timedelta(days=12))
    assert fix_store.events(cid, kind="조기경고")


@pytest.mark.parametrize("ahead", [0, 1, 2, 3])
def test_2차_승인_시간이_모자라면_집행일을_진입일_더하기_4일로_민다(tmp_path, monkeypatch, ample, ahead):
    s = open_db(tmp_path / "p.db")
    eng, cid, today = make_open(s, monkeypatch, ahead)
    f = facts(s, cid)
    assert f["phase2"]["date"] == (today + timedelta(days=4)).isoformat()  # 진입일 + 1일 + 3일
    assert f["phase2_planned_date"] == (today + timedelta(days=ahead)).isoformat()
    assert f["phase2_deadline"] == f["phase2"]["date"]
    assert deny_date(date.fromisoformat(f["phase2_deadline"])) == today + timedelta(days=1)
    ev = s.events(cid, kind="2차집행일연기")
    assert ev and ev[-1]["detail"]["to"] == f["phase2"]["date"]
    s.close()


def test_2차_진입일_더하기_1일이_실행일과_같으면_밀지_않는다(fix_store, monkeypatch, ample):
    eng, cid, today = make_open(fix_store, monkeypatch, 4)  # 실행일 = 진입일 + 1 = 진입일 + min_approval_days
    f = facts(fix_store, cid)
    assert f["phase2"]["date"] == (today + timedelta(days=4)).isoformat() and "phase2_planned_date" not in f


def test_2차_밀린_뒤_승인_마감일은_진입일이다(tmp_path, monkeypatch, ample):
    s1 = open_db(tmp_path / "a.db")
    eng, cid, today = make_open(s1, monkeypatch, 0)
    assert eng.decide_phase2(cid, "Masil 대표", "승인")["changed"] is True  # 진입일 당일 = 승인 마감일
    s2 = open_db(tmp_path / "b.db")
    eng2, cid2, today2 = make_open(s2, monkeypatch, 0)
    s2.set_clock(today2 + timedelta(days=1))
    r = eng2.decide_phase2(cid2, "Masil 대표", "승인")
    assert r["changed"] is False and r["status"] == "완료"
    s1.close()
    s2.close()


def test_2차_상신도_실행일_당일은_거부(fix_store, monkeypatch, ample):
    eng, cid, today = make_open(fix_store, monkeypatch, 10)
    fix_store.set_clock(today + timedelta(days=7))
    r = eng.escalate(cid, "Masil 대표", "2차", OPIN, WHY)
    assert r["changed"] is False and r["status"] == "완료"


def test_2차_API_응답에_승인_마감일과_기한(fix_store, monkeypatch, ample):
    eng, cid, today = make_open(fix_store, monkeypatch, 10)
    c = TestClient(create_app(fix_store, eng))
    d = c.get(f"/api/cases/{cid}").json()
    planned = today + timedelta(days=10)
    assert d["phase2"]["deadline"] == planned.isoformat()
    assert d["phase2"]["approval_deadline"] == (planned - timedelta(days=4)).isoformat()
    todo = c.get("/api/todo/Masil 대표").json()["승인 대기"]
    row = [x for x in todo if x.get("stage") == "2차"][0]
    assert row["deadline"] == planned.isoformat()
    assert row["approval_deadline"] == (planned - timedelta(days=4)).isoformat()


# ---------------------------------------------------------------- 같은 함수

def test_정책_여유일을_바꾸면_1차_2차_모두_같이_움직인다(fix_store, monkeypatch, ample):
    policy.set_overrides({"deadline.buffer_days": (1, "시험", "t")})
    eng, cid, today = make_open(fix_store, monkeypatch, 10)
    planned = today + timedelta(days=10)
    fix_store.set_clock(planned - timedelta(days=1))  # 여유 1일이면 실행일 = 집행일 - 1일
    assert eng.decide_phase2(cid, "Masil 대표", "승인")["changed"] is False
