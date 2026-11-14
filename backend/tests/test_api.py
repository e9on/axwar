"""Task 12: HTTP API. FakeProvider로 AI를 고정하고 임시 DB를 주입한다(외부 API·키 없음).

장면 숫자는 시연 파일과 이 시험에만 둔다. API 코드는 엔진·저장소를 연결만 한다.
"""
import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import policy
from app.ai.providers import FakeProvider
from app.api.main import create_app
from app.data import loader
from app.engine import scenarios
from app.engine.flow import Engine
from app.store.db import open_db

sys.path.insert(0, str(Path(__file__).parent))
from test_flow_11b import ACCEPT, BRIEF_A, COUNTER_A, REVIEWS, SCM_PART, SCM_REFUSE  # noqa: E402


@pytest.fixture
def store(tmp_path):
    s = open_db(tmp_path / "t.db")
    yield s
    s.close()


def client(store, *responses, static_dir=None):
    fake = FakeProvider(list(responses))
    eng = Engine(store, provider=fake)
    return TestClient(create_app(store, eng, static_dir=static_dir)), fake, eng


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json()


def detail_of(r, code=409):
    assert r.status_code == code, r.text
    body = r.json()
    assert set(body) == {"detail"} and isinstance(body["detail"], str)
    return body["detail"]


class Scene:
    """대본 한 단계를 HTTP로만 실행한다(조작판이 하는 일을 시험이 대신)."""

    def __init__(self, c: TestClient, name: str):
        self.c, self.name = c, name
        ok(c.post("/api/demo/reset", json={"scenario": name}))
        self.script = ok(c.get("/api/demo/scenarios"))
        self.steps = next(s for s in self.script if s["name"] == name)["script"]
        self.roles = {p["name"]: p["role"] for p in ok(c.get("/api/people"))}

    def case_id(self, ref: str) -> int:
        return next(x["id"] for x in ok(self.c.get("/api/cases")) if x["ref_id"] == ref)

    def person(self, role: str) -> str:
        return next(n for n, r in self.roles.items() if r == role)

    def detail(self, ref: str) -> dict:
        return ok(self.c.get(f"/api/cases/{self.case_id(ref)}"))

    def play(self, step: dict):
        c = self.c
        if "date" in step:
            ok(c.post("/api/clock", json={"date": step["date"]}))
        a = step["action"]
        if a == "기준일":
            return None
        ref = step.get("plan") or step["contract"]
        cid = self.case_id(ref)
        if a == "회신":
            rid = next(r["id"] for r in self.detail(ref)["requests"] if r["dept"] == step["dept"] and r["status"] != "처리됨")
            return ok(c.post(f"/api/requests/{rid}/reply", json={
                "actor": self.person(step["dept"]), "text": step["text"], "attachments": step.get("attachments", 0)}))
        if a == "결정" and step.get("stage") == "2차":
            return ok(c.post(f"/api/cases/{cid}/phase2/decision", json={
                "actor": step["actor"], "action": step["decision"], "comment": step.get("comment", "")}))
        if a == "결정":
            return ok(c.post(f"/api/cases/{cid}/decision", json={
                "actor": step["actor"], "action": step["decision"], "comment": step.get("comment", "")}))
        if a == "공지":
            return ok(c.post(f"/api/cases/{cid}/announce", json={"actor": step["actor"]}))
        if a == "발송":
            return ok(c.post(f"/api/cases/{cid}/send-notice", json={"actor": step["actor"]}))
        if a == "리뷰":
            return ok(c.post(f"/api/cases/{cid}/reviews",
                             json={"reviews": [{"product": p, "text": t} for p, t in step["reviews"]]}))
        if a == "판매":
            return ok(c.post(f"/api/cases/{cid}/sales", json={
                "actor": step["actor"], "orders": step["orders"], "returns": step["returns"]}))
        return ok(c.post(f"/api/cases/{cid}/returns", json={
            "change_of_mind": step["change_of_mind"], "color": step["color"]}))

    def run(self, upto=None):
        return [self.play(s) for s in self.steps[:upto]]

    def run_from(self, start):
        return [self.play(s) for s in self.steps[start:]]


# ============================================================== 기본

def test_healthz(store):
    c, _, _ = client(store)
    assert ok(c.get("/healthz")) == "ok"


def test_사람_목록은_사람_목록_파일에서_읽는다(store):
    c, _, eng = client(store)
    people = ok(c.get("/api/people"))
    assert {p["name"]: p["role"] for p in people} == eng.people.people
    assert {"name": "그룹 CEO", "role": "CEO"} in people and len(people) >= 11


def test_가정_목록은_정책_파일의_가정_항목을_읽는다(store):
    c, _, _ = client(store)
    rows = ok(c.get("/api/assumptions"))
    assert len(rows) >= 8
    expected = {k for k in policy.keys() if policy.base_entry(k)[1].startswith("가정")}
    assert {r["key"] for r in rows} == expected
    r = next(x for x in rows if x["key"] == "deadline.early_warning_days")
    assert r["value"] == policy.get("deadline.early_warning_days") and r["source"].startswith("가정")
    assert r["description"]


def test_가정_목록은_값을_덮어써도_가정으로_남고_현재_값을_보인다(store):
    c, _, _ = client(store)
    ok(c.put("/api/policy/deadline.early_warning_days", json={"actor": "Masil 대표", "value": 9, "reason": "시험"}))
    r = next(x for x in ok(c.get("/api/assumptions")) if x["key"] == "deadline.early_warning_days")
    assert r["value"] == 9 and r["overridden"] is True and r["source"].startswith("가정")


def test_기안_없는_id는_404_한국어(store):
    c, _, _ = client(store)
    assert "찾을 수 없어요" in detail_of(c.get("/api/cases/999"), 404)
    assert "없는" in detail_of(c.get("/api/plans/PLAN-없음"), 404)
    assert "없는" in detail_of(c.get("/api/requests/999"), 404)
    assert "찾을 수 없어요" in detail_of(c.post("/api/cases/999/decision", json={"actor": "그룹 CEO", "action": "승인"}), 404)
    assert detail_of(c.get("/api/todo/아무개"), 404)


def test_요청_형식이_틀리면_422_한국어(store):
    c, _, _ = client(store)
    d = detail_of(c.post("/api/clock", json={"date": "엉터리"}), 422)
    assert "date" in d and "형식" in d
    detail_of(c.post("/api/cases/1/decision", json={"actor": "그룹 CEO"}), 422)


# ============================================================== 장면 2 정상 갈래: API만으로 끝까지

def test_장면2를_API만으로_끝까지(store):
    c, fake, _ = client(store, ACCEPT, SCM_PART, *REVIEWS)
    sc = Scene(c, "scenario_2")
    cid = sc.case_id("PLAN-001")
    d = sc.detail("PLAN-001")
    assert d["case"]["status"] == "회신 대기" and d["rule"]["approvers"] == ["CEO", "이사회", "이사회 의결"]
    assert {h["rule_id"] for h in d["rule"]["hits"]} >= {"covenant_window", "indicator_opposite"}
    assert d["evidence"]["indicators"]["good"] is False and d["evidence"]["indicators"]["hits"]

    sc.play(sc.steps[0])  # 물류 회신 → SCM 요청이 생김
    d = sc.detail("PLAN-001")
    assert d["case"]["status"] == "승인 대기" and [r["dept"] for r in d["requests"]] == ["물류", "SCM"]
    assert ok(c.get("/api/todo/SCM 담당자"))["회신 대기"][0]["case_id"] == cid
    assert ok(c.get("/api/todo/그룹 CEO"))["승인 대기"][0]["case_id"] == cid
    detail = ok(c.get(f"/api/cases/{cid}", params={"viewer": "그룹 CEO"}))
    assert detail["viewer"]["can_decide"] is True

    for s in sc.steps[1:4]:
        sc.play(s)
    d = sc.detail("PLAN-001")
    assert d["case"]["status"] == "재승인 대기" and d["facts"]["split"]["phase1_qty"] == 3000
    sc.play(sc.steps[4]); sc.play(sc.steps[5])
    d = sc.detail("PLAN-001")
    assert d["case"]["status"] == "2차 잠금" and d["facts"]["phase1"] == {"qty": 3000, "date": "2026-07-27"}
    assert len(d["approver_changes"]) == 1 and d["phase2"]["approvers"] == ["Masil 대표", "그룹 보고", "그룹 확인"]
    assert [x["case_id"] for x in ok(c.get("/api/todo/그룹 CEO"))["권한 이동"]] == [cid]

    sc.play(sc.steps[6])  # 공지
    sc.play(sc.steps[7])  # 8/10 리뷰
    sc.play(sc.steps[8]); sc.play(sc.steps[9])  # 8/20·8/21 2차 물류·SCM 회신
    sc.play(sc.steps[10])  # 8/24 판매 실적
    r = sc.play(sc.steps[11])  # 반품 → 2차 자동 보류
    assert r["gate"]["auto_stopped"] is True
    d = sc.detail("PLAN-001")
    assert d["case"]["status"] == "2차 보류" and d["phase2"]["gate"]["auto_stopped"] is True
    assert ok(c.get(f"/api/cases/{cid}/phase2"))["gate"]["auto_stopped"] is True
    assert ok(c.get("/api/clock"))["date"] == "2026-08-24"
    assert len(fake.calls) == 12
    ev = ok(c.get("/api/events", params={"case_id": cid}))
    assert any(e["kind"] == "상태변경" for e in ev) and all("ts" in e and "detail" in e for e in ev)


def test_장면2_거절_갈래는_1차_차단(store):
    c, _, _ = client(store, ACCEPT, SCM_REFUSE)
    sc = Scene(c, "scenario_2_reject")
    sc.run()
    d = sc.detail("PLAN-001")
    assert d["case"]["status"] == "1차 차단" and "SCM 거절" in d["facts"]["phase1_blocked"]["reason"]
    # 더 결정할 수 없다
    cid = sc.case_id("PLAN-001")
    r = ok(c.post(f"/api/cases/{cid}/decision", json={"actor": "그룹 CEO", "action": "분할승인"}))
    assert r["changed"] is False


def test_판매율_조절_갈래를_API로_2차_승인_집행_완료까지(store):
    c, _, _ = client(store, ACCEPT, SCM_PART)
    sc = Scene(c, "scenario_2_sales")
    sale = next(i for i, x in enumerate(sc.steps) if x["action"] == "판매")
    sc.run(upto=sale)
    d = sc.detail("PLAN-001")
    qty_b = d["phase2"]["plan"]["qty"]
    assert d["case"]["status"] == "2차 잠금" and "1차 판매 실적 미입력" in d["phase2"]["gate"]["reasons"]
    r = sc.play(sc.steps[sale])  # 주문 2,600·반품 50
    d = sc.detail("PLAN-001")
    assert r["sales"]["net"] == 2550 and d["phase2"]["sellthrough"]["outcome"] == "조절"
    assert d["phase2"]["plan"]["qty"] == qty_b * 2550 // 3000 and d["phase2"]["gate"]["open"] is True
    # 판매율로 조절한 2차가 2차 승인 대기로 들어간다: 승인권자는 Masil 대표·그룹, 2차 집행일(기한) 8/28·승인 마감 8/24
    assert d["case"]["status"] == "2차 승인 대기" and d["phase2"]["deadline"] == "2026-08-28"
    assert d["phase2"]["approval_deadline"] == "2026-08-24" and d["phase2"]["pending_roles"] == ["Masil 대표", "그룹"]
    assert ok(c.get("/api/todo/Masil 대표"))["승인 대기"][0]["stage"] == "2차"
    assert ok(c.get(f"/api/cases/{d['case']['id']}", params={"viewer": "Masil 대표"}))["viewer"]["can_decide_phase2"] is True
    assert ok(c.get(f"/api/cases/{d['case']['id']}", params={"viewer": "그룹 CEO"}))["viewer"]["can_decide_phase2"] is False
    cid = d["case"]["id"]
    assert "2차 승인권자" in detail_of(c.post(f"/api/cases/{cid}/phase2/decision", json={"actor": "그룹 CEO", "action": "승인"}))
    assert "승인 또는 거절" in detail_of(c.post(f"/api/cases/{cid}/phase2/decision", json={"actor": "Masil 대표", "action": "분할승인"}))
    sc.run_from(sale + 1)  # 2차 승인 두 건 → 2차 집행 → 8/29 완료
    d = sc.detail("PLAN-001")
    assert d["case"]["status"] == "완료" and d["phase2"]["result"]["result"] == "집행"
    assert d["phase2"]["exec"]["qty"] == qty_b * 2550 // 3000 and d["phase2"]["exec"]["date"] == "2026-08-28"
    assert {(t["dept"], t["title"]) for t in d["tasks"]} >= {("물류", "물류 출고(2차)"), ("CS", "CS 대비(2차)")}
    assert [a["decision"] for a in d["approvals"]][-2:] == ["2차 승인", "2차 승인"]


def test_2차_거절은_API로도_완료되고_통보가_없다(store):
    c, _, _ = client(store, ACCEPT, SCM_PART)
    sc = Scene(c, "scenario_2_sales")
    sale = next(i for i, x in enumerate(sc.steps) if x["action"] == "판매")
    sc.run(upto=sale + 1)
    cid = sc.case_id("PLAN-001")
    r = ok(c.post(f"/api/cases/{cid}/phase2/decision", json={"actor": "그룹 재무", "action": "거절", "comment": "부담"}))
    assert r["status"] == "완료" and r["changed"] is True
    d = sc.detail("PLAN-001")
    assert d["phase2"]["result"]["result"] == "거절" and not [t for t in d["tasks"] if "(2차)" in t["title"]]
    assert "2차 승인 대기" in detail_of(c.post(f"/api/cases/{cid}/phase2/decision", json={"actor": "Masil 대표", "action": "승인"}))


def test_운영_모드에서_권한_없는_리뷰_반품_입력은_409(store):
    c, fake, eng = client(store, ACCEPT)
    sc = Scene(c, "scenario_2")
    sc.play(sc.steps[0])
    cid = sc.case_id("PLAN-001")
    ok(c.put("/api/mode", json={"actor": "Masil 대표", "mode": "운영"}))
    body = {"change_of_mind": 1, "color": 1}
    assert "시연" in detail_of(c.post(f"/api/cases/{cid}/returns", json=body))  # 행위자 없음(대본 재생)
    assert "CS" in detail_of(c.post(f"/api/cases/{cid}/returns", json={**body, "actor": "물류 담당자"}))
    rev = {"reviews": [{"product": "립", "text": "색이 달라요"}]}
    calls = len(fake.calls)
    assert "캠페인 담당" in detail_of(c.post(f"/api/cases/{cid}/reviews", json={**rev, "actor": "물류 담당자"}))
    assert len(fake.calls) == calls and ok(c.get(f"/api/cases/{cid}"))["reviews"] == []
    r = ok(c.post(f"/api/cases/{cid}/returns", json={**body, "actor": "CS 담당자"}))
    assert r["case_id"] == cid


# ============================================================== 권한

def seeded(store, *responses, name="scenario_2"):
    c, fake, eng = client(store, *responses)
    sc = Scene(c, name)
    return c, fake, eng, sc, sc.case_id("PLAN-001")


def test_승인권자_아니면_409(store):
    c, _, _, sc, cid = seeded(store, ACCEPT)
    sc.play(sc.steps[0])
    d = detail_of(c.post(f"/api/cases/{cid}/decision", json={"actor": "캠페인 담당자", "action": "승인"}))
    assert "승인권자" in d
    assert sc.detail("PLAN-001")["case"]["status"] == "승인 대기"
    assert "등록되지 않은" in detail_of(c.post(f"/api/cases/{cid}/decision", json={"actor": "아무개", "action": "승인"}))
    assert "결정은" in detail_of(c.post(f"/api/cases/{cid}/decision", json={"actor": "그룹 CEO", "action": "보류"}))


def test_회신_대상이_아니면_409(store):
    c, _, _, sc, cid = seeded(store, ACCEPT)
    rid = sc.detail("PLAN-001")["requests"][0]["id"]
    d = detail_of(c.post(f"/api/requests/{rid}/reply", json={"actor": "캠페인 담당자", "text": "가능합니다"}))
    assert "회신" in d and "물류" in d
    assert ok(c.get(f"/api/requests/{rid}"))["replies"] == []
    r = ok(c.post(f"/api/requests/{rid}/reply", json={"actor": "물류 담당자", "text": "가능합니다", "attachments": 0}))
    assert r["status"] == "승인 대기"


def test_정책_수정_권한_없으면_409_있으면_이력_한건(store):
    c, _, _ = client(store)
    body = {"actor": "캠페인 담당자", "value": 9, "reason": "시험"}
    assert "정책" in detail_of(c.put("/api/policy/escalation.after_days", json=body))
    assert ok(c.get("/api/policy/history")) == []
    ok(c.put("/api/policy/escalation.after_days", json={**body, "actor": "Masil 대표"}))
    h = ok(c.get("/api/policy/history", params={"key": "escalation.after_days"}))
    assert len(h) == 1 and h[0]["actor"] == "Masil 대표" and h[0]["after"] == 9 and h[0]["before"] == 2 and h[0]["at"]
    assert "양수" in detail_of(c.put("/api/policy/escalation.after_days", json={**body, "actor": "Masil 대표", "value": -1}))
    assert "알 수 없는" in detail_of(c.put("/api/policy/없는.키", json={**body, "actor": "Masil 대표"}))


def test_정책_조회는_값_출처_설명_덮어쓴_값을_준다(store):
    c, _, _ = client(store)
    rows = {r["key"]: r for r in ok(c.get("/api/policy"))}
    r = rows["escalation.after_days"]
    assert r["value"] == policy.get("escalation.after_days") and r["source"] and r["description"] and r["overridden"] is False
    ok(c.put("/api/policy/escalation.after_days", json={"actor": "그룹 CEO", "value": 7, "reason": "시험"}))
    r = {r["key"]: r for r in ok(c.get("/api/policy"))}["escalation.after_days"]
    assert r["value"] == 7 and r["overridden"] is True and r["file_value"] != 7


@pytest.mark.usefixtures("legacy_scenes")
def test_정책_수정은_다음_판정에_반영된다(store):
    c, _, _ = client(store)
    sc = Scene(c, "scenario_1")
    before = sc.detail("PLAN-019")["rule"]["approvers"]
    assert "Masil 대표" in before
    ok(c.put("/api/policy/approval.total_limit_krw", json={"actor": "Masil 대표", "value": 10**9, "reason": "시험"}))
    r = ok(c.post("/api/sync", json={"actor": "캠페인 담당자"}))
    assert any(a["action"] == "권한이동" for a in r["actions"])
    assert "Masil 대표" not in sc.detail("PLAN-019")["rule"]["approvers"]
    assert len(ok(c.get("/api/policy/history"))) == 1


def test_사람_확인은_담당_또는_올려_받은_역할만_처리한다(store):
    c, _, eng, sc, cid = seeded(store, ACCEPT, ACCEPT)
    rid = sc.detail("PLAN-001")["requests"][0]["id"]
    store.set_request_status(rid, "사람 확인", "시험", "시험")
    hc = ok(c.get("/api/human-checks"))
    assert [(x["request_id"], x["case_id"], x["dept"]) for x in hc] == [(rid, cid, "물류")]
    body = {"actor": "물류 담당자", "text": "가능합니다"}
    assert "처리할 수 없음" in detail_of(c.post(f"/api/requests/{rid}/resolve", json=body))
    # 부서 회신 입구로는 사람 확인 요청을 처리할 수 없다
    assert "사람 확인" in detail_of(c.post(f"/api/requests/{rid}/reply", json=body))
    r = ok(c.post(f"/api/requests/{rid}/resolve", json={**body, "actor": "캠페인 담당자"}))
    assert r["needs_human"] is False and ok(c.get(f"/api/requests/{rid}"))["status"] == "처리됨"
    assert ok(c.get("/api/human-checks")) == []


# ============================================================== 모드

def test_모드_전환은_권한자만_하고_운영에서는_시연_동작이_막힌다(store):
    c, _, _, sc, cid = seeded(store, ACCEPT)
    assert ok(c.get("/api/mode")) == {"mode": "시연"}
    assert "모드" in detail_of(c.put("/api/mode", json={"actor": "캠페인 담당자", "mode": "운영"}))
    ok(c.put("/api/mode", json={"actor": "Masil 대표", "mode": "운영"}))
    assert ok(c.get("/api/mode")) == {"mode": "운영"}
    assert "운영 모드" in detail_of(c.post("/api/clock", json={"date": "2026-12-31"}))
    assert "시연 모드" in detail_of(c.post("/api/demo/reset", json={"scenario": "scenario_1"}))
    assert "운영 모드" in detail_of(c.post("/api/demo/play", json={"step": sc.steps[0]}))
    assert "운영 모드" in detail_of(c.post("/api/demo/run", json={"scenario": "scenario_2", "upto": 1}))
    # 운영의 기준일은 저장소 시계(실제 오늘)이고 기한 점검은 열려 있다
    assert ok(c.get("/api/clock")) == {"date": date.today().isoformat(), "mode": "운영"}
    assert isinstance(ok(c.post("/api/deadlines/check")), list)
    # 운영에서는 역할 이름이 아니라 사람 이름만 받는다
    assert "등록되지 않은" in detail_of(c.post(f"/api/cases/{cid}/decision", json={"actor": "CEO", "action": "승인"}))
    # 시연으로 되돌리면 다시 열린다
    ok(c.put("/api/mode", json={"actor": "Masil 대표", "mode": "시연"}))
    ok(c.post("/api/demo/reset", json={"scenario": "scenario_1"}))


def test_기준일_뒤로_409(store):
    c, _, _ = client(store)
    ok(c.post("/api/demo/reset", json={"scenario": "scenario_1"}))
    today = date.fromisoformat(ok(c.get("/api/clock"))["date"])
    ok(c.post("/api/clock", json={"date": date.fromordinal(today.toordinal() + 3).isoformat()}))
    assert "뒤로" in detail_of(c.post("/api/clock", json={"date": today.isoformat()}))


def test_시연_파일_목록과_없는_시연은_404(store):
    c, _, _ = client(store)
    names = {s["name"] for s in ok(c.get("/api/demo/scenarios"))}
    assert {"scenario_1", "scenario_2", "scenario_2_reject", "scenario_2_sales", "scenario_3", "scenario_1_escalate", "scenario_3_reject", "scenario_2_exception"} <= names
    s = next(x for x in ok(c.get("/api/demo/scenarios")) if x["name"] == "scenario_1")
    assert s["title"] and s["script"] and "description" in s
    assert "시연 파일" in detail_of(c.post("/api/demo/reset", json={"scenario": "없는장면"}), 404)


def test_대본_재생은_한_단계씩_또는_앞에서부터(store, tmp_path):
    c, _, _ = client(store, ACCEPT)
    sc = Scene(c, "scenario_1")
    r = ok(c.post("/api/demo/play", json={"step": sc.steps[0]}))
    assert r["action"] == "회신" and r["status"] == "승인 대기"
    other = open_db(tmp_path / "b.db")
    try:
        c2, _, _ = client(other, ACCEPT)
        ok(c2.post("/api/demo/reset", json={"scenario": "scenario_1"}))
        out = ok(c2.post("/api/demo/run", json={"scenario": "scenario_1", "upto": 1}))
        assert len(out) == 1 and out[0]["action"] == "회신"
    finally:
        other.close()


# ============================================================== 등록부

PLAN = {"plan_id": "PLAN-화면", "campaign_id": "CMP-0005", "influencer_id": "INF-002", "channel": "라이브",
        "requested_budget_krw": 5_000_000, "expected_gmv_krw": 40_000_000,
        "settlement_date": "2026-09-14", "contract_deadline": "2026-09-11"}


def test_화면_등록_기안은_바로_판정된다(store):
    c, _, _ = client(store, ACCEPT)
    r = ok(c.post("/api/plans", json={"actor": "캠페인 담당자", "fields": PLAN}), 201)
    assert r["plan_id"] == "PLAN-화면" and r["case_id"] and r["open_error"] is None
    plan = ok(c.get("/api/plans/PLAN-화면"))
    assert plan["origin"] == "시연" and plan["requested_budget_krw"] == 5_000_000  # 최종 수정 M6: 시연 모드에서 등록한 행은 시연 출처
    d = ok(c.get(f"/api/cases/{r['case_id']}"))
    assert d["case"]["status"] == "회신 대기" and d["rule"]["approvers"]
    assert d["facts"]["volume"]["units"] is None  # 원본 표본이 없어 담당자 입력 필요
    assert [x["plan_id"] for x in ok(c.get("/api/plans"))] == ["PLAN-화면"]


def test_기안_등록에서_사건_열기를_끌_수_있고_중복_등록과_틀린_항목은_거부(store):
    c, _, _ = client(store)
    r = ok(c.post("/api/plans", json={"actor": "캠페인 담당자", "fields": PLAN, "open_case": False}), 201)
    assert r["case_id"] is None and ok(c.get("/api/cases")) == []
    ok(c.post("/api/plans/PLAN-화면/open", json={"actor": "캠페인 담당자"}))
    assert len(ok(c.get("/api/cases"))) == 1
    assert "이미" in detail_of(c.post("/api/plans", json={"actor": "캠페인 담당자", "fields": PLAN}))  # 같은 기안 ID: 409
    d = detail_of(c.post("/api/plans", json={"actor": "캠페인 담당자", "fields": {**PLAN, "plan_id": "PLAN-두번째",
                                                                               "settlement_date": "내일"}}), 422)
    assert "YYYY-MM-DD" in d
    assert "등록되지 않은" in detail_of(c.post("/api/plans", json={"actor": "아무개", "fields": {**PLAN, "plan_id": "P3"}}))


def test_빠진_항목이_있는_기안은_등록은_되고_사건_열기_오류를_알린다(store):
    c, _, _ = client(store)
    fields = {k: v for k, v in PLAN.items() if k != "contract_deadline"}
    r = ok(c.post("/api/plans", json={"actor": "캠페인 담당자", "fields": fields}), 201)
    assert r["case_id"] is None and "비어 있는 항목" in r["open_error"]
    assert ok(c.get("/api/plans/PLAN-화면"))["plan_id"] == "PLAN-화면"


def test_기안_수정은_재판정하고_받은_승인을_무효로_한다(store):
    c, _, _, sc, cid = seeded(store, ACCEPT, SCM_PART)
    sc.play(sc.steps[0]); sc.play(sc.steps[1])  # CEO만 분할 승인
    before = sc.detail("PLAN-001")
    assert before["rule"]["approved_roles"] == ["CEO"]
    amount = before["facts"]["amount_krw"]
    r = ok(c.put("/api/plans/PLAN-001", json={"actor": "캠페인 담당자", "fields": {"requested_budget_krw": amount + 1000}}))
    assert any(a["action"] == "재승인" for a in r["actions"])
    d = sc.detail("PLAN-001")
    assert d["case"]["status"] == "재승인 대기" and d["rule"]["approved_roles"] == []
    assert d["facts"]["amount_krw"] == amount + 1000
    assert ok(c.get("/api/plans/PLAN-001"))["requested_budget_krw"] == amount + 1000
    assert "고칠 수 없는" in detail_of(c.put("/api/plans/PLAN-001", json={"actor": "캠페인 담당자",
                                                                       "fields": {"plan_id": "PLAN-X"}}), 422)
    assert "비어 있음" in detail_of(c.put("/api/plans/PLAN-001", json={"actor": "캠페인 담당자", "fields": {}}), 422)


CONTRACT = {"influencer_code": "INF-화면", "influencer_name": "화면 인플루언서", "annual_fixed_krw": 300_000_000,
            "performance_fee_text": "성과 피 5%", "notice_deadline": "2026-12-01", "expiry_date": "2027-01-31",
            "auto_renew": True}


def test_화면_등록_계약은_갱신_검토_건이_열린다_수정하면_재판정(store):
    c, _, _ = client(store)
    r = ok(c.post("/api/contracts", json={"actor": "계약 담당자", "fields": CONTRACT}), 201)
    assert r["contract_id"] and r["case_id"] and r["open_error"] is None
    row = ok(c.get(f"/api/contracts/{r['contract_id']}"))
    assert row["origin"] == "시연" and row["auto_renew"] is True  # 최종 수정 M6: 시연 모드에서 등록한 행은 시연 출처 and len(ok(c.get("/api/contracts"))) == 1
    d = ok(c.get(f"/api/cases/{r['case_id']}"))
    assert d["case"]["kind"] == "계약" and d["case"]["status"] == "승인 대기"
    assert d["rule"]["approvers"][0] == "Masil 대표"  # 연 고정 피가 한도 이하
    limit = policy.get("approval.contract_limit_krw")
    r2 = ok(c.put(f"/api/contracts/{r['contract_id']}", json={"actor": "계약 담당자",
                                                              "fields": {"annual_fixed_krw": limit + 1}}))
    assert any(a["action"] == "권한이동" for a in r2["actions"])
    assert ok(c.get(f"/api/cases/{r['case_id']}"))["rule"]["approvers"][0] == "CEO"
    assert "정수" in detail_of(c.put(f"/api/contracts/{r['contract_id']}", json={"actor": "계약 담당자",
                                                                              "fields": {"annual_fixed_krw": "많이"}}), 422)
    detail_of(c.get("/api/contracts/9999"), 404)


def test_가져오기_실행은_결과_개수를_준다(store):
    c, _, _ = client(store)
    r = ok(c.post("/api/import/plans", json={"actor": "캠페인 담당자"}))
    assert r["added"] == 25 and r["updated"] == 0 and r["unchanged"] == 0 and r["skipped"] == [] and r["warnings"] == []
    again = ok(c.post("/api/import/plans", json={"actor": "캠페인 담당자"}))
    assert again["added"] == 0 and again["unchanged"] == 25
    k = ok(c.post("/api/import/contracts", json={"actor": "계약 담당자"}))
    assert k["count"] == len(loader.contract_notices()) == len(k["contract_ids"])
    assert len(ok(c.get("/api/plans"))) == 25 and len(ok(c.get("/api/contracts"))) == k["count"]
    assert isinstance(r["actions"], list)  # 가져온 뒤 열린 건을 등록부에 맞춰 다시 판정한 조치


def test_화면에서_고친_기안은_가져오기가_건너뛰고_이유를_준다(store):
    c, _, _ = client(store)
    ok(c.post("/api/import/plans", json={"actor": "캠페인 담당자"}))
    store.set_mode("운영")  # 최종 수정 M6: 시연 모드에서는 가져온 행을 고칠 수 없으므로 운영 모드에서 고친다
    ok(c.put("/api/plans/PLAN-001", json={"actor": "캠페인 담당자", "fields": {"requested_budget_krw": 1_234_567}}))
    r = ok(c.post("/api/import/plans", json={"actor": "캠페인 담당자"}))
    assert [x["plan_id"] for x in r["skipped"]] == ["PLAN-001"] and "덮어쓰지 않음" in r["skipped"][0]["reason"]


def test_가져오기_원본이_깨지면_409_한국어(store, data_copy):
    c, _, _ = client(store)
    f = data_copy / "02_masil" / "marketing" / "mkt_budget_plan_ms.csv"
    f.write_text("엉뚱,열\n1,2\n", encoding="utf-8")
    loader._read.cache_clear()
    assert detail_of(c.post("/api/import/plans", json={"actor": "캠페인 담당자"}))
    loader._read.cache_clear()


# ============================================================== 2차: 판매 실적·계속·취소

def hold_state(store, monkeypatch):
    """판매율이 하한 미만이라 2차 보류가 된 건(엔진 시험의 준비 함수를 그대로 쓴다)."""
    from test_flow_escalation import hold_case
    eng, cid, _ = hold_case(store, monkeypatch)
    return TestClient(create_app(store, eng)), cid


def test_판매_실적_입력_검증과_권한(store, monkeypatch):
    from test_flow_sellthrough import locked
    eng, cid = locked(store, monkeypatch)
    c = TestClient(create_app(store, eng))
    assert "캠페인 담당" in detail_of(c.post(f"/api/cases/{cid}/sales", json={"actor": "물류 담당자", "orders": 9, "returns": 1}))
    assert "보다 클 수 없음" in detail_of(c.post(f"/api/cases/{cid}/sales", json={"actor": "캠페인 담당자", "orders": 5, "returns": 6}))
    assert "0 이상" in detail_of(c.post(f"/api/cases/{cid}/sales", json={"actor": "캠페인 담당자", "orders": -1, "returns": 0}))
    r = ok(c.post(f"/api/cases/{cid}/sales", json={"actor": "캠페인 담당자", "orders": 900, "returns": 100}))
    assert r["sales"]["net"] == 800 and r["status"] == "2차 승인 대기"
    p = ok(c.get(f"/api/cases/{cid}/phase2"))
    assert p["gate"]["open"] is True and p["sales"]["net"] == 800 and p["sellthrough"]["outcome"] == "조절"


def test_판매율_보류는_담당이_2차_계속으로_판단한다(store, monkeypatch):
    c, cid = hold_state(store, monkeypatch)
    body = {"actor": "물류 담당자", "qty": 300, "reason": "수요가 남아 있음"}
    assert "판단" in detail_of(c.post(f"/api/cases/{cid}/phase2/continue", json=body))
    assert "1 이상" in detail_of(c.post(f"/api/cases/{cid}/phase2/continue", json={**body, "actor": "캠페인 담당자", "qty": 0}))
    r = ok(c.post(f"/api/cases/{cid}/phase2/continue", json={**body, "actor": "캠페인 담당자"}))
    assert r["choice"] == "2차 계속" and r["status"] == "2차 승인 대기" and r["qty_after"] == 300
    assert "판단할 수 있음" in detail_of(c.post(f"/api/cases/{cid}/phase2/cancel", json={"actor": "캠페인 담당자", "reason": "취소"}))
    d = ok(c.get(f"/api/cases/{cid}"))
    assert d["phase2"]["decision"]["choice"] == "2차 계속" and d["phase2"]["sellthrough"]["outcome"] == "보류"


def test_판매율_보류는_담당이_2차_취소로_판단한다(store, monkeypatch):
    c, cid = hold_state(store, monkeypatch)
    assert "이유" in detail_of(c.post(f"/api/cases/{cid}/phase2/cancel", json={"actor": "캠페인 담당자", "reason": " "}))
    r = ok(c.post(f"/api/cases/{cid}/phase2/cancel", json={"actor": "캠페인 담당자", "reason": "수요 부족"}))
    assert r["choice"] == "2차 취소" and r["status"] == "완료"  # 수정 회차 2 C
    assert ok(c.get(f"/api/cases/{cid}"))["phase2"] is None


# ============================================================== 나머지 엔진 입구

def test_1차_수량_조정_공지_통보_발송_권한은_엔진이_판정(store):
    c, _, _, sc, cid = seeded(store, ACCEPT, SCM_PART)
    sc.play(sc.steps[0])
    assert "캠페인 담당" in detail_of(c.post(f"/api/cases/{cid}/adjust-phase1", json={"actor": "그룹 CEO", "qty": 100}))
    assert "공지" in detail_of(c.post(f"/api/cases/{cid}/announce", json={"actor": "그룹 CEO"}))
    assert "계약 담당" in detail_of(c.post(f"/api/cases/{cid}/send-notice", json={"actor": "캠페인 담당자"}))
    assert "승인 뒤에만" in detail_of(c.post(f"/api/cases/{cid}/announce", json={"actor": "캠페인 담당자"}))
    assert "늘릴 수 없음" in detail_of(c.post(f"/api/cases/{cid}/adjust-phase1", json={"actor": "캠페인 담당자", "qty": 10**8}))


def test_장면3_통보_발송과_상대_회신(store):
    c, _, _ = client(store, "통보 초안 문장입니다.", ACCEPT)
    sc = Scene(c, "scenario_3")
    sc.run(upto=2)  # 기준일 7/12, 7/17: 확정 기한까지 승인 없음 → 기본 거부 → 통보 초안
    d = sc.detail("INF-001")
    assert d["case"]["status"] == "통보 초안" and d["facts"]["notice"]["text"] == "통보 초안 문장입니다."
    cid = sc.case_id("INF-001")
    assert "계약 담당" in detail_of(c.post(f"/api/cases/{cid}/send-notice", json={"actor": "캠페인 담당자"}))
    r = sc.play(sc.steps[2])
    assert r["status"] == "상대 회신 대기"
    r = sc.play(sc.steps[3])
    assert r["status"] == "합의"


def test_기한_점검과_실행_점검과_동기화(store):
    c, _, _ = client(store)
    sc = Scene(c, "scenario_1")
    assert isinstance(ok(c.post("/api/deadlines/check")), list)
    assert isinstance(ok(c.post("/api/sync", json={"actor": "캠페인 담당자"}))["actions"], list)
    r = ok(c.get("/api/execution-check", params={"influencer_id": "INF-002", "day": "2026-09-14"}))
    assert set(r) >= {"allowed", "expiry", "renewal_confirmed", "reason"}
    assert "등록되지 않은" in detail_of(c.post("/api/sync", json={"actor": "아무개"}))


def test_리뷰와_반품_입력(store):
    c, _, _, sc, cid = seeded(store, ACCEPT, SCM_PART, *REVIEWS)
    for s in sc.steps[:6]:
        sc.play(s)
    r = ok(c.post(f"/api/cases/{cid}/reviews", json={"reviews": [{"product": "상품", "text": "색이 영상과 달라요"}]}))
    assert r["gate"]["open"] is False
    assert "0 이상" in detail_of(c.post(f"/api/cases/{cid}/returns", json={"change_of_mind": -1, "color": 0}))
    r = ok(c.post(f"/api/cases/{cid}/returns", json={"change_of_mind": 0, "color": 0}))
    assert "gate" in r


def test_브리핑은_요청할_때만_AI를_부른다(store):
    c, fake, _, sc, cid = seeded(store, ACCEPT, BRIEF_A, COUNTER_A)
    sc.play(sc.steps[0])
    n = len(fake.calls)
    assert ok(c.get(f"/api/cases/{cid}"))["briefing"] is None and len(fake.calls) == n
    r = ok(c.post(f"/api/cases/{cid}/briefing", json={"actor": "그룹 CEO"}))
    assert r["briefing"]["text"] == BRIEF_A and r["counterpoints"]["text"] == COUNTER_A
    assert ok(c.get(f"/api/cases/{cid}"))["briefing"]["stale"] is False and len(fake.calls) == n + 2


def test_할일과_캘린더와_건_목록(store):
    c, _, _, sc, cid = seeded(store, ACCEPT)
    cal = ok(c.get("/api/calendar"))
    assert cal and all({"date", "kind", "label"} <= set(e) for e in cal) and [e["date"] for e in cal] == sorted(e["date"] for e in cal)
    todo = ok(c.get("/api/todo/물류 담당자"))
    assert todo["role"] == "물류" and todo["회신 대기"][0]["request_id"]
    cases = ok(c.get("/api/cases", params={"kind": "기안"}))
    assert [x["ref_id"] for x in cases] == ["PLAN-001"] and cases[0]["status"] == "회신 대기"
    assert ok(c.get("/api/cases", params={"kind": "계약"})) == []
    assert ok(c.get("/api/cases", params={"status": "없는상태"})) == []
    reqs = ok(c.get("/api/requests", params={"dept": "물류"}))
    assert len(reqs) == 1 and reqs[0]["case_id"] == cid and reqs[0]["status"] == "대기"


# ============================================================== 현금·AI 비용·기록

def test_현금_일별_잔액_하회_구간_공식_전망_차이(store):
    c, _, _ = client(store)
    r = ok(c.get("/api/cash"))
    assert r["days"] and {"date", "inflow", "outflow", "closing"} <= set(r["days"][0])
    assert all(isinstance(d["closing"], int) for d in r["days"])
    assert r["windows"] and {"start", "end"} <= set(r["windows"][0]) and isinstance(r["covenant_min_krw"], int)
    g = r["official_forecast_gap"]
    assert g["official_min"] > g["defined_min"] and g["causes"]


def test_AI_비용_사용액과_미정산_예약(store):
    c, _, _ = client(store)
    r = ok(c.get("/api/ai/usage"))
    assert r["spent_usd"] == 0 and r["pending_reservations"] == [] and r["calls"] == []
    assert r["total_cap_usd"] == policy.get("ai.total_cap_usd") and r["daily_cap_usd"] == policy.get("ai.daily_cap_usd")
    assert r["mode"] in ("fake", "real")
    store.add_ai_call(None, "시험", policy.get("ai.reply_model"), 1000, 1000)
    r = ok(c.get("/api/ai/usage"))
    assert r["spent_usd"] > 0 and len(r["calls"]) == 1 and r["calls"][0]["kind"] == "시험"


def test_기록_조회는_사건과_종류로_거른다(store):
    c, _, _, sc, cid = seeded(store, ACCEPT)
    sc.play(sc.steps[0])
    allev = ok(c.get("/api/events"))
    one = ok(c.get("/api/events", params={"case_id": cid, "kind": "상태변경"}))
    assert one and all(e["case_id"] == cid and e["kind"] == "상태변경" for e in one) and len(allev) > len(one)
    assert ok(c.get("/api/events", params={"limit": 2})) == allev[-2:]


# ============================================================== 정적 파일

def test_frontend_dist가_있으면_루트에_정적_파일(store, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html><body>화면</body></html>", encoding="utf-8")
    c, _, _ = client(store, static_dir=dist)
    assert "화면" in c.get("/").text
    assert ok(c.get("/healthz")) == "ok" and ok(c.get("/api/people"))
    assert c.get("/api/없는길").status_code == 404


def test_frontend_dist가_없어도_API는_동작한다(store, tmp_path):
    c, _, _ = client(store, static_dir=tmp_path / "없음")
    assert c.get("/").status_code == 404
    assert ok(c.get("/healthz")) == "ok"


def test_기본_앱은_환경변수로_DB_사람_목록_시연_폴더를_정한다(tmp_path, monkeypatch):
    from app.api.main import build_app
    monkeypatch.setenv("AXWAR_DB", str(tmp_path / "env.db"))
    monkeypatch.setenv("AXWAR_AI", "fake")
    monkeypatch.setenv("AXWAR_FRONTEND_DIST", str(tmp_path / "없음"))
    app = build_app()
    c = TestClient(app)
    assert ok(c.get("/healthz")) == "ok" and (tmp_path / "env.db").exists()
    assert {p["name"] for p in ok(c.get("/api/people"))} == set(scenarios.load_people().people)


def test_시연_초기화는_운영에서_연_사건을_지우지_않는다(store):
    c, _, _ = client(store, ACCEPT)
    ok(c.put("/api/mode", json={"actor": "Masil 대표", "mode": "운영"}))
    r = ok(c.post("/api/plans", json={"actor": "캠페인 담당자", "fields": PLAN}), 201)
    ops = r["case_id"]
    assert ok(c.get(f"/api/cases/{ops}"))["case"]["origin"] == "운영"
    assert "시연 모드에서만" in detail_of(c.post("/api/demo/reset", json={"scenario": "scenario_1"}))
    ok(c.put("/api/mode", json={"actor": "Masil 대표", "mode": "시연"}))
    ok(c.post("/api/demo/reset", json={"scenario": "scenario_1"}))
    cases = {x["id"]: x for x in ok(c.get("/api/cases"))}
    assert ops in cases and cases[ops]["origin"] == "운영" and cases[ops]["ref_id"] == "PLAN-화면"
    assert [x["origin"] for x in cases.values() if x["id"] != ops] == ["시연"]
    assert ok(c.get(f"/api/cases/{ops}"))["requests"]


# ---------------------------------------------------------------- 수정 회차 2: 상부 상신

def test_상신_API_1차와_2차(store):
    c, _, _ = client(store, ACCEPT, SCM_PART)
    sc = Scene(c, "scenario_2_sales")
    sc.play(sc.steps[0])  # 물류 회신 -> 1차 승인 대기(CEO·이사회)
    cid = sc.case_id("PLAN-001")
    body = {"actor": "그룹 CEO", "stage": "1차", "opinion": "승인 권고", "reason": "금액이 커서 이사회 확인 요청"}
    assert "승인권자" in detail_of(c.post(f"/api/cases/{cid}/escalate", json={**body, "actor": "물류 담당자"}))
    detail_of(c.post(f"/api/cases/{cid}/escalate", json={**body, "opinion": "몰라요"}))
    detail_of(c.post(f"/api/cases/{cid}/escalate", json={**body, "reason": " "}))
    r = ok(c.post(f"/api/cases/{cid}/escalate", json=body))
    assert r["to"] == "이사회" and r["required_roles"] == ["이사회"] and r["stage"] == "1차"
    assert "승인권자가 아님" in detail_of(c.post(f"/api/cases/{cid}/decision", json={"actor": "그룹 CEO", "action": "승인"}))
    d = ok(c.get(f"/api/cases/{cid}?viewer=이사회"))
    assert d["escalations"][0]["reason"] == body["reason"] and d["viewer"]["can_escalate"] is False  # 맨 위
    todo = ok(c.get("/api/todo/이사회"))["승인 대기"][0]
    assert todo["상신"][0]["opinion"] == "승인 권고"
    assert "맨 위" in detail_of(c.post(f"/api/cases/{cid}/escalate", json={**body, "actor": "이사회"}))
    detail_of(c.post("/api/cases/9999/escalate", json=body), 404)


def test_상신_API_2차_승인_단계(store):
    c, _, _ = client(store, ACCEPT, SCM_PART)
    sc = Scene(c, "scenario_2_sales")
    sale = next(i for i, x in enumerate(sc.steps) if x["action"] == "판매")
    sc.run(upto=sale + 1)
    cid = sc.case_id("PLAN-001")
    body = {"actor": "Masil 대표", "stage": "2차", "opinion": "반대 권고", "reason": "물량이 커서 CEO 확인 요청"}
    r = ok(c.post(f"/api/cases/{cid}/escalate", json=body))
    assert r["to"] == "CEO" and r["pending"] == ["CEO", "그룹"]
    assert "2차 승인권자" in detail_of(c.post(f"/api/cases/{cid}/phase2/decision", json={"actor": "Masil 대표", "action": "승인"}))
    assert "보고 체계" in detail_of(c.post(f"/api/cases/{cid}/escalate", json={**body, "actor": "그룹 재무"}))
    d = ok(c.get(f"/api/cases/{cid}?viewer=그룹 CEO"))
    assert d["viewer"]["can_decide_phase2"] is True and d["escalations"][0]["stage"] == "2차"
    assert d["phase2"]["deadline"] == "2026-08-28" and d["phase2"]["plan"]["date"] == "2026-08-28"


def test_조건_API가_새_역할_항목을_가정으로_보인다(store):
    c, _, _ = client(store)
    keys = {r["key"] for r in ok(c.get("/api/assumptions"))}
    assert {"roles.campaign", "roles.contract", "roles.logistics", "roles.cs", "volume.input_lead_days"} <= keys


def test_없는_건은_이유와_할_일을_알려준다(store):
    c, _, _ = client(store)
    for r in (c.get("/api/cases/999"), c.post("/api/cases/999/decision", json={"actor": "Masil 대표", "action": "승인"})):
        assert r.status_code == 404
        text = r.json()["detail"]
        assert "찾을 수 없어요" in text and "처음으로 돌아갔을 수 있어요" in text
        assert "없는 사건" not in text
