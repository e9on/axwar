"""당사자 알림(사용자 결정 2026-11-12).

- 조기 경고는 상급자가 아니라 아직 승인하지 않은 승인권자 본인에게 간다.
- 집행일(1차·2차)이 바뀌면 바뀐 그때 캠페인 담당·물류·CS·그 단계 승인권자에게 알린다.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.store.db import open_db

sys.path.insert(0, str(Path(__file__).parent))
from test_final_fix import Day, ops_wait  # noqa: E402
from test_flow_11b import ACCEPT, SCM_REFUSE, SHIFT_DAY, fake_spare, scene2  # noqa: E402
from test_flow_fix2 import ample, make_open  # noqa: E402,F401

DENY = date(2026, 9, 8)


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


def _changed(eng, person):
    return [a for a in eng.todo(person)["알림"] if a["kind"] == "집행일 변경"]


def test_1차_조기_경고는_남은_승인권자_본인에게(store, day):
    eng, cid = ops_wait(store)
    day.d = DENY - timedelta(days=5)
    out = [a for a in eng.check_deadlines() if a["case_id"] == cid and a["action"] == "조기경고"]
    assert len(out) == 1 and out[0]["targets"] == ["마케팅팀"]
    assert len(eng.todo("마케팅팀장")["기한 임박"]) == 1
    assert eng.todo("Masil 대표")["기한 임박"] == []
    eng.check_deadlines()
    assert len(store.events(cid, kind="조기경고")) == 1  # 한 사람에게 한 번


def test_2차_조기_경고도_승인권자_본인에게(fix_store, monkeypatch, ample):
    eng, cid, today = make_open(fix_store, monkeypatch, 20)
    eng.advance(today + timedelta(days=12))
    from app.engine.flow import _pending_roles
    pending = _pending_roles(fix_store.get_case(cid)["facts"], "2차")
    targets = [e["detail"]["target"] for e in fix_store.events(cid, kind="조기경고")]
    assert pending and targets == pending  # 상급자가 아니라 남은 승인권자 그대로
    assert [x for x in eng.todo("그룹 CEO")["기한 임박"] if x.get("stage") == "2차"]


def test_2차_집행일이_밀리면_그때_알린다(fix_store, monkeypatch, ample):
    eng, cid, today = make_open(fix_store, monkeypatch, 0)  # 승인 기간을 확보하려고 집행일을 민다
    new = fix_store.get_case(cid)["facts"]["phase2"]["date"]
    for person in ("캠페인 담당자", "물류 담당자", "CS 담당자", "Masil 대표"):
        got = _changed(eng, person)
        assert len(got) == 1 and got[0]["stage"] == "2차", person
        nd = date.fromisoformat(new)
        assert f"{today.month}/{today.day}→{nd.month}/{nd.day}" in got[0]["text"]
    assert _changed(eng, "품질 담당자") == []


def test_1차_집행일이_SCM_거절로_밀리면_그때_알린다(store, monkeypatch):
    eng, fake, cid, st = scene2(store, ACCEPT, SCM_REFUSE, name="scenario_2_reject")
    fake_spare(monkeypatch, (date(2026, 8, 20), 0), (date(2026, 8, 21), 9000), (SHIFT_DAY, 20000))
    eng.play(st[0]); eng.play(st[1]); eng.play(st[2]); eng.play(st[3])
    for person in ("캠페인 담당자", "물류 담당자", "CS 담당자", "그룹 CEO"):
        got = _changed(eng, person)
        assert len(got) == 1 and got[0]["stage"] == "1차" and "7/27→8/22" in got[0]["text"], person


def test_등록부에서_집행일을_고쳐도_그때_알린다(store, day):
    eng, cid = ops_wait(store)
    ref = store.get_case(cid)["ref_id"]
    old = store.get_plan(ref)["settlement_date"]
    new = (date.fromisoformat(old) + timedelta(days=3)).isoformat()
    eng.update_plan(ref, {"settlement_date": new}, "캠페인 담당자")
    got = _changed(eng, "물류 담당자")
    assert len(got) == 1 and got[0]["stage"] == "1차"
    assert len(_changed(eng, "마케팅팀장")) == 1
