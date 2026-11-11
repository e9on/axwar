"""4단계 최종 수정(Opus 검토 반영): 시연·운영 분리(H1), 운영 모드 기한(H5), 모드·등록부(M), 계약 기간(M1·M2).

운영 모드 시험은 저장소에 오늘 날짜를 주입(Day)해 기한 앞뒤를 정확히 만든다.
"""
import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import policy
from app.ai.providers import FakeProvider
from app.api.main import build_app, create_app
from app.engine.flow import Engine
from app.store.db import open_db

sys.path.insert(0, str(Path(__file__).parent))
from test_flow_11b import ACCEPT  # noqa: E402
from test_flow_fix1 import PLAN  # noqa: E402

OPIN, WHY = "승인 권고", "한도 근처라 윗선 확인이 필요합니다"
CONTRACT = {"influencer_code": "INF-화면", "influencer_name": "화면 인플루언서", "annual_fixed_krw": 300_000_000,
            "performance_fee_text": "성과 피 5%", "notice_deadline": "2026-12-01", "expiry_date": "2027-01-31",
            "auto_renew": True}


class Day:
    """주입하는 오늘 날짜(운영 모드의 시계)."""

    def __init__(self, d: date):
        self.d = d

    def __call__(self) -> date:
        return self.d


@pytest.fixture
def day():
    return Day(date(2026, 9, 1))


@pytest.fixture
def store(tmp_path, day):
    s = open_db(tmp_path / "t.db", today=day)
    yield s
    s.close()


def status(store, cid):
    return store.get_case(cid)["status"]


def ops(store, *responses):
    """운영 모드에서 화면 등록 기안(기한 9/11)으로 연 운영 사건."""
    eng = Engine(store, provider=FakeProvider(list(responses)))
    store.set_mode("운영")
    store.add_plan(PLAN, "캠페인 담당자")
    return eng, eng.open_plan(PLAN["plan_id"])


def ops_wait(store):
    eng, cid = ops(store, ACCEPT)
    eng.reply(store.list_requests(cid)[0]["id"], "하루 5,000개 처리 가능합니다.")
    assert status(store, cid) == "승인 대기"
    return eng, cid


# ---------------------------------------------------------------- H1. 시연 동작은 시연 사건만

def test_H1_시연_기준일_이동은_운영_사건을_건드리지_않는다(store):
    eng, cid = ops(store, ACCEPT)
    store.set_mode("시연")
    n = len(store.events(cid))
    eng.advance(date(2027, 12, 31))
    assert status(store, cid) == "회신 대기" and len(store.events(cid)) == n


def test_H1_시연_대본은_같은_기안_ID의_운영_사건과_섞이지_않는다(store):
    store.set_mode("운영")
    store.import_plans_from_source()
    eng = Engine(store, provider=FakeProvider([ACCEPT, ACCEPT]))
    ops_id = eng.open_plan("PLAN-019")
    assert store.get_case(ops_id)["origin"] == "운영"
    n = len(store.events(ops_id))
    store.set_mode("시연")
    ids = eng.seed("scenario_1")
    assert ops_id not in ids and store.get_case(ids[0])["origin"] == "시연"
    eng.run_script("scenario_1")
    assert status(store, ops_id) == "회신 대기" and len(store.events(ops_id)) == n
    assert status(store, ids[0]) == "1차 집행"
    assert [x["case_id"] for x in store.list_requests(ids[0]) and []] == []  # 시연 요청은 시연 사건에만
    assert all(r["case_id"] != ops_id or r["dept"] == "물류" for r in store.all_requests())


def test_H1_운영_점검은_시연_사건을_건드리지_않는다(store, day):
    eng = Engine(store, provider=FakeProvider([]))
    cid = eng.seed("scenario_1")[0]
    store.set_mode("운영")
    day.d = date(2027, 12, 31)
    n = len(store.events(cid))
    eng.check_deadlines()
    assert status(store, cid) == "회신 대기" and len(store.events(cid)) == n


def test_H1_할_일과_캘린더는_지금_모드의_사건만_보인다(store):
    eng, cid = ops(store, ACCEPT)
    eng_cases = lambda: {i["case_id"] for k in ("승인 대기", "회신 대기", "작업") for i in eng.todo("물류 담당자")[k]}
    assert cid in eng_cases()
    store.set_mode("시연")
    assert cid not in eng_cases()
    assert all(e["case_id"] != cid for e in eng.calendar())


# ---------------------------------------------------------------- H5. 운영 모드 기한

def test_H5_기한이_지난_뒤_1차_승인은_기본_거부로_처리된다(store, day):
    eng, cid = ops_wait(store)
    day.d = date(2026, 9, 12)
    r = eng.decide(cid, "마케팅팀장", "승인")
    assert r["changed"] is False and r["status"] == "확정 보류" and "기본 거부" in r["message"]
    assert status(store, cid) == "확정 보류" and not [t for t in store.list_tasks(cid) if t["title"] == "물류 출고"]


def test_H5_기한_당일에는_1차_승인이_된다(store, day):
    eng, cid = ops_wait(store)
    day.d = date(2026, 9, 11)
    assert eng.decide(cid, "마케팅팀장", "승인")["status"] == "1차 집행"


def test_H5_기한이_지난_뒤_1차_상신도_기본_거부(store, day):
    eng, cid = ops_wait(store)
    day.d = date(2026, 9, 12)
    r = eng.escalate(cid, "마케팅팀장", "1차", OPIN, WHY)
    assert r["changed"] is False and r["status"] == "확정 보류"


def client(store, eng):
    return TestClient(create_app(store, eng))


def test_H5_운영_모드_요청은_오늘_점검이_안_돌았으면_먼저_한_번_돈다(store, day):
    eng, cid = ops_wait(store)
    c = client(store, eng)
    day.d = date(2026, 9, 12)
    assert c.get("/api/cases").json()[0]["status"] == "확정 보류"  # 점검이 먼저 돌아 반영된 뒤 읽는다
    assert store.last_daily_check() == date(2026, 9, 12)
    n = len(store.events())
    c.get("/api/cases")
    assert len(store.events()) == n  # 같은 날 두 번째 요청은 점검을 다시 돌리지 않는다
    day.d = date(2026, 9, 13)
    c.get("/api/cases")
    assert store.last_daily_check() == date(2026, 9, 13)


def test_H5_점검_엔드포인트도_오늘_점검을_기록한다(store, day):
    eng, cid = ops_wait(store)
    c = client(store, eng)
    day.d = date(2026, 9, 12)
    c.post("/api/deadlines/check")
    assert store.last_daily_check() == date(2026, 9, 12) and status(store, cid) == "확정 보류"


def test_H5_시연_모드_요청은_점검을_돌리지_않는다(store, day):
    eng = Engine(store, provider=FakeProvider([]))
    cid = eng.seed("scenario_1")[0]
    c = client(store, eng)
    day.d = date(2030, 1, 1)
    c.get("/api/cases")
    assert store.last_daily_check() is None and status(store, cid) == "회신 대기"


def test_H5_서버_시작_때_한_번_점검한다(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(Engine, "ensure_daily_check", lambda self: calls.append(1))
    monkeypatch.setenv("AXWAR_DB", str(tmp_path / "boot.db"))
    build_app()
    assert calls == [1]


# ---------------------------------------------------------------- M. 모드·전환 기록

def test_M_모드_전환은_이벤트로_남는다(store):
    eng = Engine(store, provider=FakeProvider([]))
    assert store.get_mode() == "시연"
    eng.set_mode("Masil 대표", "운영")
    ev = store.events(kind="모드전환")
    assert len(ev) == 1 and ev[0]["actor"] == "Masil 대표"
    assert ev[0]["detail"] == {"before": "시연", "after": "운영", "actor": "Masil 대표"}
    eng.set_mode("Masil 대표", "운영")  # 바뀌지 않았으면 남기지 않는다
    assert len(store.events(kind="모드전환")) == 1


def test_M_배포_환경변수로_처음_모드를_정하고_저장된_모드가_있으면_그대로(tmp_path, monkeypatch):
    path = tmp_path / "mode.db"
    monkeypatch.setenv("AXWAR_DB", str(path))
    monkeypatch.setenv("AXWAR_MODE", "운영")
    build_app()
    s = open_db(path)
    assert s.get_mode() == "운영"
    s.set_mode("시연")
    s.close()
    build_app()  # 이미 저장된 모드(시연)를 환경변수가 덮어쓰지 않는다
    s = open_db(path)
    assert s.get_mode() == "시연"
    s.close()


# ---------------------------------------------------------------- M. 등록부 쓰기 권한·시연 행 출처

def test_M_등록부_편집_역할은_정책에_있고_가정으로_표시된다():
    value, source, _ = policy.base_entry("admin.registry_editors")
    assert [r.strip() for r in value.split(",")] == ["캠페인 담당", "계약 담당", "마케팅팀", "Masil 대표", "CEO"]
    assert source.startswith("가정")


def test_M_등록부_쓰기는_편집_역할만_가능하다(store):
    eng = Engine(store, provider=FakeProvider([]))
    c = client(store, eng)
    body = {"fields": {**PLAN, "plan_id": "PLAN-권한"}, "open_case": False}
    for who in ("인플루언서 측", "에이전시", "물류 담당자", "그룹 재무"):
        r = c.post("/api/plans", json={**body, "actor": who})
        assert r.status_code == 409 and "등록부" in r.json()["detail"], who
    assert c.post("/api/plans", json={**body, "actor": "마케팅팀장"}).status_code == 201
    for who in ("인플루언서 측", "에이전시"):
        assert c.put("/api/plans/PLAN-권한", json={"actor": who, "fields": {"requested_budget_krw": 1}}).status_code == 409
        assert c.post("/api/contracts", json={"actor": who, "fields": CONTRACT}).status_code == 409
        assert c.post("/api/import/plans", json={"actor": who}).status_code == 409
        assert c.post("/api/import/contracts", json={"actor": who}).status_code == 409
        assert c.post("/api/sync", json={"actor": who}).status_code == 409
        assert c.post("/api/plans/PLAN-권한/open", json={"actor": who}).status_code == 409
    assert store.get_plan("PLAN-권한")["requested_budget_krw"] == PLAN["requested_budget_krw"]
    with pytest.raises(PermissionError):
        eng.update_plan("PLAN-권한", {"requested_budget_krw": 1}, "에이전시")


def test_M_등록부_편집_역할은_정책에서_바꾸면_따른다(store):
    eng = Engine(store, provider=FakeProvider([]))
    c = client(store, eng)
    eng.change_policy("Masil 대표", "admin.registry_editors", "품질,CEO", "시험")
    assert c.post("/api/plans", json={"actor": "마케팅팀장", "fields": {**PLAN, "plan_id": "PLAN-P"},
                                      "open_case": False}).status_code == 409
    assert c.post("/api/plans", json={"actor": "품질 담당자", "fields": {**PLAN, "plan_id": "PLAN-P"},
                                      "open_case": False}).status_code == 201
    with pytest.raises(ValueError, match="알려진 역할"):
        eng.change_policy("Masil 대표", "admin.registry_editors", "없는역할", "시험")


def test_M_시연_모드에서_등록한_행은_시연_출처이고_초기화에_지워진다(store):
    eng = Engine(store, provider=FakeProvider([]))
    c = client(store, eng)
    assert store.get_mode() == "시연"
    c.post("/api/plans", json={"actor": "캠페인 담당자", "fields": {**PLAN, "plan_id": "PLAN-시연등록"}, "open_case": False})
    c.post("/api/contracts", json={"actor": "계약 담당자", "fields": CONTRACT, "open_case": False})
    assert store.get_plan("PLAN-시연등록")["origin"] == "시연" and store.list_contracts()[0]["origin"] == "시연"
    c.post("/api/demo/reset", json={"scenario": "scenario_1"})
    with pytest.raises(KeyError):
        store.get_plan("PLAN-시연등록")
    assert not [k for k in store.list_contracts() if k["influencer_code"] == "INF-화면"]
    store.set_mode("운영")
    c.post("/api/plans", json={"actor": "캠페인 담당자", "fields": {**PLAN, "plan_id": "PLAN-운영등록"}, "open_case": False})
    assert store.get_plan("PLAN-운영등록")["origin"] == "화면"


def test_M_시연_모드에서는_시연_아닌_등록부_행을_고칠_수_없다(store):
    store.import_plans_from_source()
    eng = Engine(store, provider=FakeProvider([]))
    c = client(store, eng)
    before = store.get_plan("PLAN-001")
    r = c.put("/api/plans/PLAN-001", json={"actor": "캠페인 담당자", "fields": {"requested_budget_krw": 1}})
    assert r.status_code == 409 and "시연" in r.json()["detail"]
    after = store.get_plan("PLAN-001")
    assert after["requested_budget_krw"] == before["requested_budget_krw"] and after["origin"] == "가져오기"


# ---------------------------------------------------------------- M1·M2. 계약 기간

def approve_renewal(eng, store, code):
    cid = eng.open_contract(code)
    for who in ("Masil 대표", "그룹 재무"):  # 지표가 나빠 그룹 확인이 더해진 건: 두 역할이 모두 승인
        eng.decide(cid, who, "승인")
    assert status(store, cid) == "갱신 승인"
    return cid


def test_M2_끝난_계약_사건이_있어도_다음_계약_기간이면_새_사건을_연다(store):
    eng = Engine(store, provider=FakeProvider([]))
    store.set_mode("운영")
    store.add_contract(CONTRACT, "계약 담당자")
    c1 = approve_renewal(eng, store, "INF-화면")
    assert eng.open_contract("INF-화면") == c1  # 같은 계약 기간이면 그 사건
    store.add_contract({**CONTRACT, "expiry_date": "2028-01-31", "notice_deadline": "2027-12-01"}, "계약 담당자")
    c2 = eng.open_contract("INF-화면")
    assert c2 != c1 and status(store, c2) == "승인 대기" and status(store, c1) == "갱신 승인"
    assert store.get_case(c2)["facts"]["expiry"] == "2028-01-31"
    assert eng.open_contract("INF-화면") == c2


def test_M1_작년_갱신_사건이_올해_계약의_갱신_확정으로_세지지_않는다(store):
    eng = Engine(store, provider=FakeProvider([]))
    store.set_mode("운영")
    store.add_contract(CONTRACT, "계약 담당자")
    approve_renewal(eng, store, "INF-화면")
    assert eng.execution_check("INF-화면", date(2029, 1, 1))["allowed"] is True  # 이 계약 기간의 갱신은 확정
    store.add_contract({**CONTRACT, "expiry_date": "2028-01-31", "notice_deadline": "2027-12-01"}, "계약 담당자")
    chk = eng.execution_check("INF-화면", date(2028, 6, 1))
    assert chk["allowed"] is False and chk["renewal_confirmed"] is False  # 새 계약 기간은 아직 미확정


def test_M1_시연_사건의_합의가_운영_계약의_갱신을_확정하지_않는다(store):
    eng = Engine(store, provider=FakeProvider([]))
    store.add_contract(CONTRACT, "계약 담당자", origin="가져오기")
    cid = eng.open_contract("INF-화면")  # 시연 모드: 시연 사건
    eng.decide(cid, "Masil 대표", "승인")
    eng.decide(cid, "그룹 재무", "승인")
    assert store.get_case(cid)["origin"] == "시연" and status(store, cid) == "갱신 승인"
    store.set_mode("운영")
    assert eng.execution_check("INF-화면", date(2029, 1, 1))["renewal_confirmed"] is False
