"""Task 12 수정 회차 2: A 상부 상신, B 2차 기한<집행일, C 2차 없는 건의 완료."""
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.ai.providers import FakeProvider
from app.calc import inventory
from app.calc.cash import Window
from app.engine.flow import Engine
from app.store.db import open_db

sys.path.insert(0, str(Path(__file__).parent))
from test_flow_11b import ACCEPT, SCM_PART, scene2  # noqa: E402
from test_flow_fix1 import EXEC, PLAN, WAIT, facts, ops_case, sales_scene, status, to_wait  # noqa: E402


@pytest.fixture
def store(tmp_path):
    s = open_db(tmp_path / "t.db")
    yield s
    s.close()


@pytest.fixture
def ample(monkeypatch):
    monkeypatch.setattr(inventory, "line_spare", lambda category, day: 10**9)


OPIN, WHY = "승인 권고", "한도 근처라 윗선 확인이 필요합니다"


def scene_one(store):
    """장면 2의 물류 회신 직후: 1차 승인 대기, 승인권자 CEO·이사회."""
    eng, _, cid, st = scene2(store, ACCEPT, SCM_PART)
    eng.play(st[0])
    assert status(store, cid) == "승인 대기"
    return eng, cid


def ops_wait(store):
    """운영 모드 소액 기안(승인권자 마케팅팀)을 물류 회신으로 승인 대기까지."""
    eng, cid = ops_case(store, ACCEPT)
    eng.reply(store.list_requests(cid)[0]["id"], "하루 5,000개 처리 가능합니다.")
    assert status(store, cid) == "승인 대기"
    return eng, cid


def required(store, cid, stage="1차"):
    from app.engine.flow import _required_roles
    return _required_roles(facts(store, cid), stage)


# ---------------------------------------------------------------- A. 상부 상신 (1차)

def test_승인권자가_아닌_사람의_상신은_거부된다(store):
    eng, cid = scene_one(store)
    for who in ("물류 담당자", "마케팅팀장", "캠페인 담당자", "Masil 대표"):
        with pytest.raises(PermissionError, match="승인권자"):
            eng.escalate(cid, who, "1차", OPIN, WHY)
    assert "escalations" not in facts(store, cid) and store.events(cid, kind="상신") == []


def test_이미_결정한_승인권자는_상신할_수_없다(store):
    eng, cid = scene_one(store)
    eng.decide(cid, "그룹 CEO", "분할승인", "")
    with pytest.raises(ValueError, match="이미"):
        eng.escalate(cid, "그룹 CEO", "1차", OPIN, WHY)
    assert store.events(cid, kind="상신") == []


def test_의견과_이유가_없으면_거부된다(store):
    eng, cid = ops_wait(store)
    for opinion, reason in (("", WHY), ("그냥", WHY), (None, WHY), (OPIN, ""), (OPIN, "   "), (OPIN, None)):
        with pytest.raises(ValueError):
            eng.escalate(cid, "마케팅팀장", "1차", opinion, reason)
    assert required(store, cid) == ["마케팅팀"] and store.events(cid, kind="상신") == []
    with pytest.raises(ValueError, match="단계"):
        eng.escalate(cid, "마케팅팀장", "3차", OPIN, WHY)


def test_마케팅팀은_Masil_대표에게_올리고_올린_역할은_결정할_수_없다(store):
    eng, cid = ops_wait(store)
    r = eng.escalate(cid, "마케팅팀장", "1차", "반대 권고", WHY)
    assert r["to"] == "Masil 대표" and r["stage"] == "1차" and r["required_roles"] == ["Masil 대표"]
    assert facts(store, cid)["approvers"] == ["Masil 대표"]
    with pytest.raises(PermissionError):
        eng.decide(cid, "마케팅팀장", "승인")
    # 상급자는 결정할 수 있다
    out = eng.decide(cid, "Masil 대표", "승인")
    assert out["changed"] and status(store, cid) != "승인 대기"


def test_상신은_권한_이동_기록과_이벤트로_남고_상급자_화면에_의견이_보인다(store):
    eng, cid = ops_wait(store)
    eng.escalate(cid, "마케팅팀장", "1차", "반대 권고", WHY)
    ch = store.get_approver_changes(cid)[-1]
    assert ch.before == ("마케팅팀",) and ch.after == ("Masil 대표",)
    assert ch.reason.startswith("상신: ") and WHY in ch.reason and "반대 권고" in ch.reason
    ev = store.events(cid, kind="상신")
    assert len(ev) == 1 and ev[0]["actor"] == "마케팅팀장"
    d = ev[0]["detail"]
    assert (d["from"], d["to"], d["opinion"], d["reason"], d["stage"]) == ("마케팅팀", "Masil 대표", "반대 권고", WHY, "1차")
    # 할 일: 올린 사람은 권한 이동, 상급자는 승인 대기 항목에 의견
    assert [i["case_id"] for i in eng.todo("마케팅팀장")["권한 이동"]] == [cid]
    item = eng.todo("Masil 대표")["승인 대기"][0]
    assert item["case_id"] == cid and item["상신"][0]["opinion"] == "반대 권고" and item["상신"][0]["reason"] == WHY
    assert item["상신"][0]["from"] == "마케팅팀" and item["상신"][0]["actor"] == "마케팅팀장"
    assert eng.todo("마케팅팀장")["승인 대기"] == []
    # 건 상세
    det = eng.case_detail(cid, viewer="Masil 대표")
    assert det["escalations"][0]["to"] == "Masil 대표" and det["escalations"][0]["active"] is True
    assert det["viewer"]["can_decide"] is True
    assert eng.case_detail(cid, viewer="마케팅팀장")["viewer"]["can_decide"] is False
    assert any(h["kind"] == "상신" for h in det["history"])


def test_상급자가_이미_결재선에_있으면_중복으로_넣지_않는다(store):
    eng, cid = scene_one(store)  # 승인권자 CEO·이사회(표기 CEO, 이사회, 이사회 의결)
    r = eng.escalate(cid, "그룹 CEO", "1차", OPIN, WHY)
    assert r["to"] == "이사회" and required(store, cid) == ["이사회"]
    labels = facts(store, cid)["approvers"]
    assert "CEO" not in labels and len(labels) == len(set(labels))
    with pytest.raises(PermissionError):
        eng.decide(cid, "그룹 CEO", "승인")
    eng.decide(cid, "이사회", "분할승인")
    assert "이사회" in facts(store, cid)["approved_roles"]


def test_재상신은_위로_계속_올라가고_이사회에서는_막힌다(store):
    eng, cid = ops_wait(store)
    assert eng.escalate(cid, "마케팅팀장", "1차", OPIN, WHY)["to"] == "Masil 대표"
    assert eng.escalate(cid, "Masil 대표", "1차", OPIN, "대표도 윗선 확인이 필요합니다")["to"] == "CEO"
    r = eng.escalate(cid, "그룹 CEO", "1차", "반대 권고", "이사회 부의 필요")
    assert r["to"] == "이사회" and required(store, cid) == ["이사회"]  # 방치 올림과 달리 이사회 부의 허용
    with pytest.raises(ValueError, match="맨 위"):
        eng.escalate(cid, "이사회", "1차", OPIN, WHY)
    assert [x["to"] for x in facts(store, cid)["escalations"]] == ["Masil 대표", "CEO", "이사회"]
    assert len(store.events(cid, kind="상신")) == 3
    assert eng.todo("이사회")["승인 대기"][0]["상신"][0]["from"] == "CEO"


def test_상신_뒤에도_날마다_점검이_결재선을_되돌리지_않는다(store):
    eng, cid = scene_one(store)
    eng.escalate(cid, "그룹 CEO", "1차", OPIN, WHY)
    for _ in range(2):
        eng.advance(store.get_clock() + timedelta(days=1))
    assert required(store, cid) == ["이사회"] and status(store, cid) == "승인 대기"
    assert len(store.get_approver_changes(cid)) == 1 and store.events(cid, kind="상신무효") == []


def test_등록부가_바뀌어_재판정되면_상신은_무효가_된다(store):
    eng, cid = ops_wait(store)
    eng.escalate(cid, "마케팅팀장", "1차", OPIN, WHY)
    eng.update_plan("PLAN-운영", {"requested_budget_krw": PLAN["requested_budget_krw"] - 1}, "캠페인 담당자")
    f = facts(store, cid)
    assert f["approvers"] == ["마케팅팀"] and all(not x["active"] for x in f["escalations"])
    ev = store.events(cid, kind="상신무효")
    assert len(ev) == 1 and ev[0]["detail"]["stage"] == "1차" and "상신" in ev[0]["detail"]["text"]
    assert store.get_approver_changes(cid)[-1].after == ("마케팅팀",)
    eng.decide(cid, "마케팅팀장", "승인")  # 원래 승인권자가 다시 결정할 수 있다
    with pytest.raises(PermissionError):
        eng.decide(cid, "Masil 대표", "승인")


def test_상신_뒤_다시_상신할_수_있다_무효_뒤에도(store):
    eng, cid = ops_wait(store)
    eng.escalate(cid, "마케팅팀장", "1차", OPIN, WHY)
    eng.update_plan("PLAN-운영", {"requested_budget_krw": PLAN["requested_budget_krw"] - 1}, "캠페인 담당자")
    r = eng.escalate(cid, "마케팅팀장", "1차", "반대 권고", "다시 올립니다")
    assert r["to"] == "Masil 대표" and [x["active"] for x in facts(store, cid)["escalations"]] == [False, True]


def test_끝난_건과_결정_단계가_아닌_건은_상신할_수_없다(store):
    eng, cid = ops_wait(store)
    eng.decide(cid, "마케팅팀장", "거절")
    with pytest.raises(ValueError, match="결정 단계"):
        eng.escalate(cid, "마케팅팀장", "1차", OPIN, WHY)
    with pytest.raises(ValueError, match="2차 승인 대기"):
        eng.escalate(cid, "마케팅팀장", "2차", OPIN, WHY)


# ---------------------------------------------------------------- A. 상부 상신 (2차)

def test_2차_승인_단계에서도_상신한다(store):
    eng, cid = to_wait(store)  # 2차 승인권자 Masil 대표·그룹
    r = eng.escalate(cid, "Masil 대표", "2차", OPIN, "물량이 커서 CEO 확인 요청")
    assert r["stage"] == "2차" and r["to"] == "CEO" and r["pending"] == ["CEO", "그룹"]
    assert facts(store, cid)["phase2_approvers"][0] == "CEO"
    with pytest.raises(PermissionError):
        eng.decide_phase2(cid, "Masil 대표", "승인")
    item = [i for i in eng.todo("그룹 CEO")["승인 대기"] if i.get("stage") == "2차"][0]
    assert item["상신"][0]["reason"] == "물량이 커서 CEO 확인 요청"
    assert eng.case_detail(cid, "그룹 CEO")["viewer"]["can_decide_phase2"] is True
    assert store.get_approver_changes(cid)[-1].reason.startswith("상신: ")
    eng.decide_phase2(cid, "그룹 CEO", "승인")
    assert eng.decide_phase2(cid, "그룹 재무", "승인")["status"] == EXEC


def test_2차_상신_권한과_조건(store):
    eng, cid = to_wait(store)
    with pytest.raises(PermissionError):
        eng.escalate(cid, "그룹 CEO", "2차", OPIN, WHY)  # 2차 승인권자가 아님
    with pytest.raises(ValueError, match="보고 체계"):
        eng.escalate(cid, "그룹 재무", "2차", OPIN, WHY)  # 그룹은 보고 체계 밖
    eng.decide_phase2(cid, "Masil 대표", "승인")
    with pytest.raises(ValueError, match="이미"):
        eng.escalate(cid, "Masil 대표", "2차", OPIN, WHY)


def test_2차_잠금_건은_2차_상신을_못한다(store):
    eng, cid = sales_scene(store)
    with pytest.raises(ValueError, match="2차 승인 대기"):
        eng.escalate(cid, "Masil 대표", "2차", OPIN, WHY)


def test_2차_기한이_지난_뒤_상신하면_기본_거부(store):
    eng, cid = to_wait(store)
    store.set_clock(date(2026, 8, 26))
    r = eng.escalate(cid, "Masil 대표", "2차", OPIN, WHY)
    assert r["changed"] is False and r["status"] == "완료" and "기본 거부" in r["message"]


def test_2차_결재선_재판정이_일어나면_2차_상신은_무효가_된다(store):
    eng, cid = to_wait(store)
    eng.escalate(cid, "Masil 대표", "2차", OPIN, WHY)
    f = facts(store, cid)
    eng._phase2_approvers(f, cid)  # 2차 결재선을 규칙으로 다시 정함(11a 경로)
    store.update_facts(cid, f, "시험", "")
    assert facts(store, cid)["phase2_approvers"][0] == "Masil 대표"
    assert all(not x["active"] for x in facts(store, cid)["escalations"])
    assert store.events(cid, kind="상신무효")[0]["detail"]["stage"] == "2차"


# ---------------------------------------------------------------- B. 2차 기한 < 집행일

def test_장면2는_2차_승인_마감_8_24_기본_거부_8_25_집행_8_28(store):
    eng, cid = to_wait(store)
    f = facts(store, cid)
    assert f["phase2_deadline"] == "2026-08-28" and f["phase2"]["date"] == "2026-08-28"
    assert f["phase2_date"] == "2026-08-28" and f["phase2_planned_date"] == "2026-08-24"
    ev = store.events(cid, kind="2차집행일연기")
    assert len(ev) == 1 and "2차 집행일 연기(승인 기간 확보)" in ev[0]["detail"]["text"]
    assert (ev[0]["detail"]["from"], ev[0]["detail"]["to"]) == ("2026-08-24", "2026-08-28")
    eng.decide_phase2(cid, "Masil 대표", "승인")
    eng.decide_phase2(cid, "그룹 재무", "승인")
    due = {x["title"]: x["due"] for x in store.list_tasks(cid) if "(2차)" in x["title"]}
    assert set(due.values()) == {"2026-08-28"}
    assert any(c["date"] == "2026-08-28" and c["kind"] == "2차 집행일" for c in eng.calendar())
    eng.advance(date(2026, 8, 28))
    assert status(store, cid) == EXEC
    eng.advance(date(2026, 8, 29))
    assert status(store, cid) == "완료"


def make_open(store, monkeypatch, days_ahead, p2_qty=1000, orders=950, returns=50, contract=(date(2099, 1, 1), True),
              windows=None):
    eng = Engine(store, provider=FakeProvider([]))
    monkeypatch.setattr(eng, "_contract_terms", lambda inf: contract)
    if windows is not None:
        monkeypatch.setattr(eng, "_windows", lambda: windows)
    cid = eng.seed("scenario_1")[0]
    f = facts(store, cid)
    today = store.get_clock()
    f["phase1"] = {"qty": 1000, "date": (today - timedelta(days=28)).isoformat()}
    f["phase2"] = {"qty": p2_qty, "date": (today + timedelta(days=days_ahead)).isoformat(), "amount_krw": 2_000_001}
    eng._phase2_approvers(f, cid)
    store.update_facts(cid, f, "시험", "2차 준비")
    store.set_status(cid, "2차 잠금", "시험", "")
    eng.record_phase1_sales(cid, "캠페인 담당자", orders, returns)
    return eng, cid, today


def test_기본_거부_실행일은_진입일_더하기_최소_승인_일수_이후다(store, monkeypatch, ample, tmp_path):
    from app import policy
    from app.rules.deadline import approval_deadline, deny_date
    buf, mn = policy.get("deadline.buffer_days"), policy.get("phase2.min_approval_days")
    for i, ahead in enumerate((0, 1, 2, 3, 4, 10)):
        s = open_db(tmp_path / f"b{i}.db")
        eng, cid, today = make_open(s, monkeypatch, ahead)
        f = facts(s, cid)
        dl, ex = date.fromisoformat(f["phase2_deadline"]), date.fromisoformat(f["phase2"]["date"])
        planned = today + timedelta(days=ahead)
        assert dl == ex == max(planned, today + timedelta(days=mn + buf))
        assert deny_date(dl) >= today + timedelta(days=mn) and approval_deadline(dl) >= today
        assert (ex != planned) == (ahead < mn + buf)
        s.close()


def test_연기가_필요_없으면_날짜와_이벤트가_그대로다(store, monkeypatch, ample):
    eng, cid, today = make_open(store, monkeypatch, 10)
    f = facts(store, cid)
    assert f["phase2"]["date"] == (today + timedelta(days=10)).isoformat() and "phase2_planned_date" not in f
    assert store.events(cid, kind="2차집행일연기") == []


def test_집행일이_밀리면_2차_승인권자를_다시_판정한다(store, monkeypatch, ample):
    win = [Window(store.get_clock() - timedelta(days=5), store.get_clock() + timedelta(days=1))]
    eng, cid, t = make_open(store, monkeypatch, 0, windows=win)
    f = facts(store, cid)
    assert f["phase2"]["date"] == (t + timedelta(days=4)).isoformat()  # 창(t+1까지) 밖으로 밀림(진입일 + 1 + 3)
    assert "CEO" not in f["phase2_approvers"]  # 하회 구간 밖이라 covenant 승인권자가 빠짐
    last = store.get_approver_changes(cid)[-1]
    assert "CEO" in last.before and "CEO" not in last.after


def test_집행일이_밀려_계약_만료_뒤가_되면_2차_차단(store, monkeypatch, ample):
    eng, cid, t = make_open(store, monkeypatch, 0, contract=(store.get_clock(), False))
    assert status(store, cid) == "2차 차단"
    assert store.events(cid, kind="2차집행일연기") and "phase2_deadline" not in facts(store, cid)
    assert "만료" in store.events(cid, kind="상태변경")[-1]["detail"]["note"]
    # 갱신이 확정되면 차단이 풀리고 그날 기준으로 2차 승인 대기에 들어간다
    monkeypatch.setattr(eng, "_contract_terms", lambda inf: (store.get_clock(), True))
    eng.advance(store.get_clock() + timedelta(days=1))
    assert status(store, cid) == WAIT
    f = facts(store, cid)
    assert f["phase2_deadline"] == f["phase2"]["date"]  # 2차 기한 = 2차 집행일(기본 거부는 그 3일 전)


# ---------------------------------------------------------------- C. 2차 없는 건은 완료

def test_2차를_취소하면_관찰이_끝난_건은_바로_완료(store):
    eng, cid = sales_scene(store)
    eng.record_phase1_sales(cid, "캠페인 담당자", 1000, 0)
    assert status(store, cid) == "2차 보류"
    r = eng.cancel_phase2(cid, "캠페인 담당자", "재고 부담")
    assert r["status"] == "완료" and status(store, cid) == "완료"
    res = facts(store, cid)["phase2_result"]
    assert res["result"] == "2차 없음" and "재고 부담" in res["text"]
    assert not [x for x in store.list_tasks(cid) if "통보" in x["title"] or "(2차)" in x["title"]]


def test_판매율_조절로_2차가_0개가_되면_완료(store, monkeypatch, ample):
    eng, cid, _ = make_open(store, monkeypatch, 10, p2_qty=1, orders=600, returns=0)
    assert status(store, cid) == "완료"
    res = facts(store, cid)["phase2_result"]
    assert res["result"] == "2차 없음" and "0개" in res["text"]


def test_관찰_기간이_남았으면_끝나는_날_완료(store):
    eng, cid = sales_scene(store)
    eng.record_phase1_sales(cid, "캠페인 담당자", 1000, 0)
    store.change_policy("split.return_observe_days", 60, "시험", "관찰 연장")
    eng.cancel_phase2(cid, "캠페인 담당자", "재고 부담")
    assert status(store, cid) == "1차 집행" and facts(store, cid)["phase2"] is None
    end = date.fromisoformat(facts(store, cid)["phase1"]["date"]) + timedelta(days=60)
    eng.advance(end - timedelta(days=1))
    assert status(store, cid) == "1차 집행"
    eng.advance(end)
    assert status(store, cid) == "완료" and facts(store, cid)["phase2_result"]["result"] == "2차 없음"
