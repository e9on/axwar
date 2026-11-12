"""마지막 승인일 알림(사용자 결정 2026-11-12): 달력에 '승인 마감' 대신 알림을 두고, 알림 날은 기본 거부 실행일 하루 전.

그날 아직 승인하지 않은 승인권자 본인에게 한 번 알린다(1차·2차 모두). 승인을 마치면 알림은 내려간다.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.store.db import open_db

sys.path.insert(0, str(Path(__file__).parent))
from test_final_fix import Day, ops_wait  # noqa: E402
from test_flow_fix2 import ample, make_open  # noqa: E402,F401

DENY = date(2026, 9, 8)       # 운영 시험 기안의 기본 거부 실행일(기한 9/11 - 3일)
LAST_OK = date(2026, 9, 7)    # 마지막 승인일 = 알림 날


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


def _alarms(eng, person):
    return [a for a in eng.todo(person)["알림"] if a["kind"] == "마감 알림"]


def test_달력에는_승인_마감_대신_알림이_기본_거부_전날에_있다(store):
    eng, cid = ops_wait(store)
    rows = [r for r in eng.calendar() if r["case_id"] == cid]
    assert not any(r["kind"] == "승인 마감" for r in rows)
    alarm = [r for r in rows if r["kind"] == "알림"]
    assert len(alarm) == 1 and alarm[0]["date"] == LAST_OK.isoformat()
    assert alarm[0]["roles"] == ["마케팅팀"] and "내일" in alarm[0]["label"] and "기본 거부" in alarm[0]["label"]


def test_1차_알림은_전날_남은_승인권자에게_한_번(store, day):
    eng, cid = ops_wait(store)
    day.d = LAST_OK - timedelta(days=1)
    eng.check_deadlines()
    assert _alarms(eng, "마케팅팀장") == []
    day.d = LAST_OK
    out = eng.check_deadlines()
    assert [a["action"] for a in out if a["case_id"] == cid].count("마감알림") == 1
    got = _alarms(eng, "마케팅팀장")
    assert len(got) == 1 and "9/8" in got[0]["text"] and "오늘" in got[0]["text"]
    eng.check_deadlines()  # 같은 날 다시 돌아도 한 번
    assert len(store.events(cid, kind="마감 알림")) == 1


def test_1차_승인하면_알림이_내려간다(store, day):
    eng, cid = ops_wait(store)
    day.d = LAST_OK
    eng.check_deadlines()
    eng.decide(cid, "마케팅팀장", "승인")
    assert _alarms(eng, "마케팅팀장") == []


def test_2차_알림도_기본_거부_전날(fix_store, monkeypatch, ample):
    eng, cid, today = make_open(fix_store, monkeypatch, 10)  # 2차 집행일 today+10, 기본 거부 today+7
    rows = [r for r in eng.calendar() if r["case_id"] == cid]
    assert not any(r["kind"] == "2차 승인 마감" for r in rows)
    alarm = [r for r in rows if r["kind"] == "2차 알림"]
    assert len(alarm) == 1 and alarm[0]["date"] == (today + timedelta(days=6)).isoformat()
    eng.advance(today + timedelta(days=5))
    assert _alarms(eng, "Masil 대표") == []
    eng.advance(today + timedelta(days=6))
    got = _alarms(eng, "Masil 대표")
    assert len(got) == 1 and got[0]["stage"] == "2차"


def test_2차_대기에_들어간_날이_마지막_승인일이면_그날_바로_알림(fix_store, monkeypatch, ample):
    eng, cid, today = make_open(fix_store, monkeypatch, 0)  # 집행일이 밀려 진입일 = 마지막 승인일
    got = _alarms(eng, "Masil 대표")
    assert len(got) == 1 and got[0]["stage"] == "2차"
