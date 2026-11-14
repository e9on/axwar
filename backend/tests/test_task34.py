"""Task 34: 시연을 날짜로 진행 — 바깥 사건(회신·리뷰·반품·판매)은 도착일에 저절로, 결정은 시연자 몫. 장면 1은 PLAN-014."""
import json
from datetime import date

import pytest

from app import config, policy
from app.api.main import create_app
from app.engine import scenarios
from app.engine.flow import Engine
from app.store.db import open_db
from fastapi.testclient import TestClient

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from test_api import detail_of, ok  # noqa: E402

OUTSIDE = ("회신", "리뷰", "반품", "판매")


@pytest.fixture
def store(tmp_path):
    s = open_db(tmp_path / "t.db")
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _clean_policy():
    policy.set_overrides({})
    yield
    policy.set_overrides({})


def fake_client(store):
    """가짜 AI 모드(키 없는 시연): 대본의 ai 필드가 회신 해석이 된다."""
    eng = Engine(store)
    return TestClient(create_app(store, eng)), eng


def reset(c, name):
    ok(c.post("/api/demo/reset", json={"scenario": name}))


def adv(c, d):
    return ok(c.post("/api/demo/advance", json={"date": d}))


def case(c, ref):
    return next(x for x in ok(c.get("/api/cases")) if x["ref_id"] == ref)


ALL = sorted(p.stem for p in config.demo_dir().glob("scenario_*.json"))


# ---- 대본 형식 ----

def test_모든_장면은_바깥_사건에_도착일이_있고_날짜가_순서대로이며_한_줄_요약이_있다():
    for n in ALL:
        sc = scenarios.load(n)
        assert sc.summary and len(sc.summary) < 80, n
        last = None
        for s in sc.script:
            if s["action"] in OUTSIDE:
                assert "date" in s, (n, s["action"])
            if "date" in s:
                assert last is None or s["date"] >= last, (n, s)
                last = s["date"]


def test_장면_1은_PLAN_014이고_결정에는_날짜가_없다():
    sc = scenarios.load("scenario_1")
    assert sc.plans == ("PLAN-014",) and not sc.demo_plans
    assert [s["action"] for s in sc.script if "date" not in s] == ["결정"]
    assert sc.script[0]["date"] < "2026-07-20"
    assert sc.script[-1] == {"action": "기준일", "date": "2026-07-20"}


def test_바깥_사건의_date와_summary_형식을_검증한다(tmp_path):
    d = tmp_path / "demo"
    d.mkdir()
    base = {"title": "t", "description": "d", "plans": ["PLAN-014"], "contracts": [], "requests": []}
    step = {"action": "회신", "plan": "PLAN-014", "dept": "물류", "text": "t"}

    def w(name, **kw):
        (d / f"{name}.json").write_text(json.dumps({**base, "script": [step], **kw}, ensure_ascii=False), encoding="utf-8")

    w("s1", summary=3)
    with pytest.raises(ValueError, match="summary"):
        scenarios.load("s1", d)
    w("s2", script=[{**step, "date": "7월 3일"}])
    with pytest.raises(ValueError, match="date"):
        scenarios.load("s2", d)
    w("s3", summary="짧은 요약", script=[{**step, "date": "2026-07-03"}])
    sc = scenarios.load("s3", d)
    assert sc.summary == "짧은 요약"
    w("s4")
    assert scenarios.load("s4", d).summary == ""  # 요약은 선택


# ---- 날짜로 진행 ----

def test_날짜를_넘기면_회신이_저절로_오고_결정은_마지막_승인일에_멈춰_시연자가_눌러_7월_20일_1차_집행까지(store):
    c, eng = fake_client(store)
    reset(c, "scenario_1")
    st = ok(c.get("/api/demo/state"))
    assert st["waiting"]["action"] == "결정" and st["waiting"]["ready"] is False and st["next_date"] == "2026-07-03"
    out = adv(c, "2026-07-02")
    assert out["applied"] == [] and out["next_date"] == "2026-07-03"
    out = adv(c, "2026-07-03")
    assert len(out["applied"]) == 1 and "물류 회신" in out["applied"][0] and "7/3" in out["applied"][0]
    # 승인할 수 있게 됐지만 시연은 마지막 승인일(7/16)까지 멈추지 않는다 — 할 일에는 이미 있다
    assert out["waiting"]["actor"] == "Masil 대표" and out["waiting"]["ready"] is False and out["waiting"]["due"] == "2026-07-16"
    assert "Masil 대표" in out["waiting"]["text"] and "PLAN-014" in out["waiting"]["text"] and "승인" in out["waiting"]["text"]
    assert out["next_date"] == "2026-07-16"
    assert case(c, "PLAN-014")["status"] == "승인 대기"  # 결정은 적용하지 않았다
    assert [x["ref_id"] for x in ok(c.get("/api/todo/Masil 대표"))["승인 대기"]] == ["PLAN-014"]
    out = adv(c, "2026-07-10")
    assert out["waiting"]["ready"] is False and case(c, "PLAN-014")["status"] == "승인 대기"
    out = adv(c, "2026-07-16")  # 마지막 승인일: 여기서 멈춘다
    assert out["applied"] == [] and out["waiting"]["actor"] == "Masil 대표" and out["waiting"]["ready"] is True
    assert out["next_date"] == "2026-07-20"
    ok(c.post("/api/demo/play", json={"step": out["waiting"]["step"]}))  # 시연자가 결정
    assert case(c, "PLAN-014")["status"] == "1차 집행"
    st = ok(c.get("/api/demo/state"))
    assert st["waiting"] is None and st["next_date"] == "2026-07-20" and st["finished"] is False
    out = adv(c, "2026-07-20")
    assert out["date"] == "2026-07-20" and out["waiting"] is None and out["next_date"] is None
    st = ok(c.get("/api/demo/state"))
    assert st["finished"] is True and st["done"] == st["total"] and len(st["arrived"]) == 1
    f = store.get_case(case(c, "PLAN-014")["id"])["facts"]
    assert f["phase1"]["date"] == "2026-07-20" and f["phase1"]["qty"] > 0


def test_날짜를_한꺼번에_넘기면_도착일_순서로_적용하고_결정은_건드리지_않는다(store):
    c, _ = fake_client(store)
    reset(c, "scenario_2")
    out = adv(c, "2026-07-03")
    assert len(out["applied"]) == 1 and "물류 회신" in out["applied"][0]
    assert out["waiting"]["actor"] == "그룹 CEO" and out["next_date"] == "2026-07-04"
    for _ in range(2):  # 그룹 CEO, 이사회가 분할 승인
        ok(c.post("/api/demo/play", json={"step": ok(c.get("/api/demo/state"))["waiting"]["step"]}))
    out = adv(c, "2026-07-04")  # SCM이 일부만 허용하면 받은 승인이 무효가 되어 재승인은 시연자 몫
    assert [a.split()[0] for a in out["applied"]] == ["7/4"]
    assert out["waiting"]["action"] == "결정" and out["waiting"]["actor"] == "그룹 CEO"
    assert out["waiting"]["ready"] is False and out["waiting"]["due"] == "2026-07-13"  # 마지막 승인일까지는 멈추지 않는다
    assert case(c, "PLAN-001")["status"] == "재승인 대기"
    out = adv(c, "2026-08-24")  # 재승인 없이 날짜가 넘어가도 리뷰(8/10)·반품(8/24)은 도착일 순서로 들어오고, 기한 규칙은 그대로 돈다
    assert [a.split()[0] for a in out["applied"]] == ["8/10", "8/24"]
    assert case(c, "PLAN-001")["status"] != "1차 집행"
    assert adv(c, "2026-08-24")["applied"] == []  # 같은 날을 다시 눌러도 같은 사건을 두 번 넣지 않는다


def test_아직_받을_수_없는_사건은_건너뛰고_다음에_다시_시도한다(store):
    c, _ = fake_client(store)
    reset(c, "scenario_3")
    out = adv(c, "2026-07-20")  # 발송(시연자 몫) 전이라 인플루언서 측 회신을 받을 요청이 아직 없음
    assert out["skipped"] and "인플루언서 측" in out["skipped"][0]
    assert out["waiting"]["action"] == "발송"


def test_뒤로는_못_가고_운영_모드와_진행_없음은_거부(store):
    c, eng = fake_client(store)
    assert "시연 장면" in detail_of(c.post("/api/demo/advance", json={"date": "2026-07-05"}))
    reset(c, "scenario_1")
    adv(c, "2026-07-05")
    assert "뒤로" in detail_of(c.post("/api/demo/advance", json={"date": "2026-07-04"}))
    assert c.post("/api/demo/advance", json={"date": "내일"}).status_code == 422
    eng.set_mode("Masil 대표", "운영")
    assert detail_of(c.post("/api/demo/advance", json={"date": "2026-07-06"}))


def test_run은_결정까지_끝까지_자동으로_돈다_시험용(store):
    c, _ = fake_client(store)
    reset(c, "scenario_1")
    out = ok(c.post("/api/demo/run", json={"scenario": "scenario_1"}))
    assert len(out) == 3 and case(c, "PLAN-014")["status"] == "1차 집행"
    st = ok(c.get("/api/demo/state"))
    assert st["finished"] and st["waiting"] is None


def test_직접_누른_결정도_다음_결정으로_넘어간다(store):
    c, _ = fake_client(store)
    reset(c, "scenario_2")
    adv(c, "2026-07-02")
    cid = case(c, "PLAN-001")["id"]
    ok(c.post(f"/api/cases/{cid}/decision", json={"actor": "그룹 CEO", "action": "분할승인", "comment": "직접"}))
    assert ok(c.get("/api/demo/state"))["waiting"]["actor"] == "이사회"


def test_결정_날짜가_있는_상신_변형도_PLAN_014_기반_7월로_끝까지_돈다(store):
    c, _ = fake_client(store)
    reset(c, "scenario_1_escalate")
    ok(c.post("/api/demo/run", json={"scenario": "scenario_1_escalate"}))
    assert case(c, "DEMO-PLAN-001")["status"] == "1차 집행"
    assert store.get_clock() < date(2026, 8, 1)


def test_장면_1_PLAN_014의_엔진_판정(store):
    """승인권자는 Masil 대표 한 명(그룹은 보고만), 재고 여유가 충분해 SCM에 묻지 않고 분할도 없다. 집행일 7/20, 확정 기한 8/14."""
    c, eng = fake_client(store)
    reset(c, "scenario_1")
    cid = case(c, "PLAN-014")["id"]
    f = store.get_case(cid)["facts"]
    assert f["approvers"] == ["Masil 대표", "그룹 보고"] and f["settlement_date"] == "2026-07-20" and f["deadline"] == "2026-08-14"
    adv(c, "2026-07-03")
    f = store.get_case(cid)["facts"]
    assert f["split"] is None and f["stock"]["shortage"] is False
    assert [r["dept"] for r in store.list_requests(cid)] == ["물류"]  # SCM 요청 없음
    cal = ok(c.get("/api/calendar"))
    kinds = {(e["kind"], e["date"]) for e in cal if e.get("case_id") in (cid, None)}
    assert ("집행일", "2026-07-20") in kinds and ("확정 기한", "2026-08-14") in kinds


def test_승인을_미루면_1차_집행일_기준으로_경고하고_기본_거부한다(store):
    c, _ = fake_client(store)
    reset(c, "scenario_1")
    adv(c, "2026-07-03")
    out = adv(c, "2026-07-16")  # 마지막 승인일(집행일 7/20의 기본 거부 실행일 7/17 전날): 아직 승인 대기, 알림만
    assert case(c, "PLAN-014")["status"] == "승인 대기" and any(a.get("action") == "마감알림" for a in out["actions"])
    out = adv(c, "2026-07-17")
    assert case(c, "PLAN-014")["status"] == "확정 보류"
    assert any(a.get("action") == "기본거부" for a in out["actions"])


def test_진행_상태는_장면_건들의_지금_상태를_결과로_준다(store):
    c, _ = fake_client(store)
    reset(c, "scenario_1")
    assert ok(c.get("/api/demo/state"))["outcome"] == ["PLAN-014 회신 대기"]
    ok(c.post("/api/demo/run", json={"scenario": "scenario_1"}))
    assert ok(c.get("/api/demo/state"))["outcome"] == ["PLAN-014 1차 집행"]


def test_화면에서_통보를_발송하면_시연이_발송을_더_기다리지_않는다(store):
    c, _ = fake_client(store)
    reset(c, "scenario_3")
    out = adv(c, "2026-07-14")
    assert out["waiting"]["action"] == "발송" and out["waiting"]["ready"]
    ok(c.post(f"/api/cases/{case(c, 'INF-001')['id']}/send-notice", json={"actor": "계약 담당자"}))
    assert ok(c.get("/api/demo/state"))["waiting"] is None


def test_화면에서_상신하면_시연이_다음_결정을_기다린다(store):
    c, _ = fake_client(store)
    reset(c, "scenario_1_escalate")
    out = adv(c, "2026-07-08")
    assert out["waiting"]["action"] == "상신" and out["waiting"]["ready"]
    ok(c.post(f"/api/cases/{case(c, 'DEMO-PLAN-001')['id']}/escalate",
              json={"actor": "마케팅팀장", "stage": "1차", "opinion": "승인 권고", "reason": "대표 확인"}))
    w = ok(c.get("/api/demo/state"))["waiting"]
    assert w["action"] == "결정" and w["actor"] == "Masil 대표"


# ---- 1차 결재 기한: 확정 기한과 1차 집행일 중 이른 날 기준(사용자 결정 2026-11-14)

def test_집행일이_확정_기한보다_앞이면_결재_기한은_집행일_기준(store):
    c, _ = fake_client(store)
    reset(c, "scenario_1")  # PLAN-014: 집행 7/20, 확정 기한 8/14
    cid = case(c, "PLAN-014")["id"]
    d = ok(c.get(f"/api/cases/{cid}?viewer=Masil 대표"))
    assert d["deadline"] == "2026-08-14"  # 확정 기한 표시는 그대로
    assert (d["deny_date"], d["approval_deadline"]) == ("2026-07-17", "2026-07-16")
    adv(c, "2026-07-17")
    assert case(c, "PLAN-014")["status"] == "확정 보류"


def test_확정_기한이_집행일보다_앞이면_결재_기한은_그대로(store):
    c, _ = fake_client(store)
    reset(c, "scenario_2")  # PLAN-001: 집행 7/27, 확정 기한 7/17
    cid = case(c, "PLAN-001")["id"]
    d = ok(c.get(f"/api/cases/{cid}?viewer=그룹 CEO"))
    assert (d["deadline"], d["deny_date"], d["approval_deadline"]) == ("2026-07-17", "2026-07-14", "2026-07-13")


def test_일정에는_승인할_수_있게_된_날부터_마지막_승인일까지_승인_기간이_보인다(store):
    c, _ = fake_client(store)
    reset(c, "scenario_1")
    periods = lambda: [e for e in ok(c.get("/api/calendar")) if e["kind"] == "승인 기간"]
    assert periods() == []  # 회신 대기: 아직 승인할 수 없다
    adv(c, "2026-07-05")
    [p] = periods()
    assert (p["date"], p["end"], p["roles"]) == ("2026-07-03", "2026-07-16", ["Masil 대표"])
    assert "PLAN-014" in p["label"] and "7/3~7/16" in p["label"]
    ok(c.post("/api/demo/play", json={"step": ok(c.get("/api/demo/state"))["waiting"]["step"]}))
    assert periods() == []  # 승인하면 사라진다
