"""PR #36 검토 반영: 반품 기준 근거·이름, 상태별 권한 표 시험, 2차 viewer 보완, 해석 실패 표시, 권한 읽기, 시연 진행 상태."""
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from app import policy
from app.ai.providers import FakeProvider
from app.calc import campaign
from app.engine import scenarios
from app.engine.flow import CHANGE_OF_MIND, COLOR_RETURN, Engine
from app.rules import split
from app.store.db import open_db

sys.path.insert(0, str(Path(__file__).parent))
from test_api import Scene, client, detail_of, ok  # noqa: E402
from test_flow_11b import ACCEPT, SCM_PART  # noqa: E402
from test_flow_escalation import after_days, hold_case, stale_events  # noqa: E402
from test_flow_sellthrough import ACTOR  # noqa: E402
from test_task25 import CANCEL, CONT, EXC, RET, REVIEW, SALES, _blocked, _scene, _v  # noqa: E402


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


# ---- M1. 반품 기준 근거 ----

def test_근거_원본_목록은_기준선_계산이_실제로_읽는_파일과_같다(store, monkeypatch):
    eng, cid = _scene(store, "scenario_2_exception", 9)
    inf = store.get_case(cid)["facts"]["influencer_id"]
    read: list[str] = []
    real = campaign.read_table
    monkeypatch.setattr(campaign, "read_table", lambda rel: (read.append(rel), real(rel))[1])
    campaign.return_count_rate(inf, CHANGE_OF_MIND)
    monkeypatch.undo()
    assert read, "기준선 계산이 읽은 파일을 잡아야 함"
    for item in eng.phase2_view(cid)["returns_check"]["items"]:
        assert set(item["detail"]["sources"]) == set(read) == set(campaign.RETURN_RATE_SOURCES)
    assert any(s.endswith("m_campaign_ms.csv") for s in read)


def test_건에_저장된_값은_원본_CSV가_아니라_건_기록으로_표시한다(store):
    eng, cid = _scene(store, "scenario_2_exception", 9)
    for item in eng.phase2_view(cid)["returns_check"]["items"]:
        labels = [i["label"] for i in item["detail"]["inputs"]]
        assert any("1차 집행 수량" in x and "건 기록" in x for x in labels)
        assert any("반품 건수" in x and "건 기록" in x for x in labels)
        assert not any("1차 주문 수" in x for x in labels)


# ---- M2. 이름 바로잡기 ----

def test_반품률_분모는_1차_집행_수량이고_실제_주문_수는_따로_온다(store):
    eng, cid = _scene(store, "scenario_2_exception", 7)
    rc = eng.phase2_view(cid)["returns_check"]
    f = store.get_case(cid)["facts"]
    assert "orders" not in rc and rc["phase1_qty"] == f["phase1"]["qty"]
    assert all("orders" not in i and i["phase1_qty"] == rc["phase1_qty"] for i in rc["items"])
    assert rc["sales_orders"] is None  # 판매 실적 입력 전
    assert "1차 집행 수량" in rc["items"][0]["detail"]["formula"]
    eng2, cid2 = _scene(store, "scenario_2_exception", 11)
    sales = store.get_case(cid2)["facts"].get("sales")
    rc2 = eng2.phase2_view(cid2)["returns_check"]
    assert sales and rc2["sales_orders"] == sales["orders"] and rc2["phase1_qty"] != rc2["sales_orders"]


def test_관찰_기간_보정_문장은_판정을_미룬다고_밝힌다(store):
    eng, cid = _scene(store, "scenario_2_exception", 9)
    adj = eng.phase2_view(cid)["returns_check"]["observation"]["adjustment"]
    assert "미룸" in adj and "보정 없음" in adj and "1차 집행 수량" in adj


# ---- M3. 상태 x 사람 x 동작 표 시험 ----

CALLS = {
    CONT: lambda e, c, w: e.continue_phase2(c, w, 1, "시험 사유"),
    CANCEL: lambda e, c, w: e.cancel_phase2(c, w, "시험 사유"),
    EXC: lambda e, c, w: e.approve_phase2_exception(c, w, 1, "시험 사유"),
    SALES: lambda e, c, w: e.record_phase1_sales(c, w, 10, 0),
    REVIEW: lambda e, c, w: e.add_reviews(c, [("립", "좋아요")], actor=w),
    RET: lambda e, c, w: e.add_returns(c, 0, 0, actor=w),
}


def _who(eng, with_roles):
    seen: dict[str, str] = {}
    for name, role in eng.people.people.items():
        seen.setdefault(role, name)
    out = list(seen.values())
    return out + sorted(set(eng.people.people.values()) - set(out)) if with_roles else out


def _check_table(store, eng, cid, label):
    """viewer.actions·blocked가 실제 엔진 메서드 결과와 같다: 성공이면 actions에, 막히면 blocked에 같은 문장으로.
    (호출은 시험용 올바른 입력으로 하고 호출마다 DB를 되돌린다.)"""
    snap0 = store._db.serialize()
    for who in _who(eng, store.get_mode() != "운영"):
        v = _v(eng, cid, who)
        assert set(v["actions"]) | set(_blocked(v)) == set(CALLS), (label, who)
        assert not set(v["actions"]) & set(_blocked(v))
        for act, call in CALLS.items():
            snap = store._db.serialize()
            try:
                call(eng, cid, who)
            except (PermissionError, ValueError) as e:
                assert _blocked(v).get(act) == str(e), (label, who, act, str(e))
            else:
                assert act in v["actions"], (label, who, act)
            finally:
                store._db.deserialize(snap)
    assert store._db.serialize() == snap0, label


def test_2차_관찰_권한_표_시험_반품_보류와_예외_승인_뒤(store):
    for upto in (7, 9, 10):
        eng, cid = _scene(store, "scenario_2_exception", upto)
        _check_table(store, eng, cid, f"예외 시나리오 {upto}단계")
        store.reset()


def test_2차_관찰_권한_표_시험_판매율_보류_방치_올림_이미_판단함(store, monkeypatch):
    eng, cid, made = hold_case(store, monkeypatch)
    _check_table(store, eng, cid, "판매율 보류")
    eng.advance(made + timedelta(days=after_days()))
    target = stale_events(store, cid)[0]["detail"]["target"]
    who = next(n for n, r in eng.people.people.items() if r == target)
    assert CANCEL in _v(eng, cid, who)["actions"] or CONT in _v(eng, cid, who)["actions"]
    _check_table(store, eng, cid, "방치 올림 뒤")
    eng.cancel_phase2(cid, who, "올려 받아 취소")
    _check_table(store, eng, cid, "취소로 판단한 뒤")


def test_2차_관찰_권한_표_시험_계속으로_이미_판단한_건과_운영_모드(store, monkeypatch):
    eng, cid, _ = hold_case(store, monkeypatch)
    eng.continue_phase2(cid, ACTOR, 1, "계속")
    _check_table(store, eng, cid, "계속 판단 뒤")


def test_2차_관찰_권한_표_시험_운영_모드(store):
    eng2, cid2 = _scene(store, "scenario_2_exception", 9)
    eng2.set_mode("Masil 대표", "운영")
    _check_table(store, eng2, cid2, "운영 모드")


# ---- L1. 반품 사유·관찰 완료 판정 한 곳 ----

def test_반품_사유_목록과_관찰_완료_판정을_게이트와_화면이_같이_읽는다(store):
    eng, cid = _scene(store, "scenario_2_exception", 9)
    assert set(split.RETURN_KEYS) == {CHANGE_OF_MIND, COLOR_RETURN}
    assert [i["label"] for i in eng.phase2_view(cid)["returns_check"]["items"]] == list(split.RETURN_KEYS)
    elapsed = eng.phase2_view(cid)["returns_check"]["observation"]["elapsed_days"]
    for required in (elapsed - 1, elapsed, elapsed + 1):  # 경계 양쪽에서 화면 done과 게이트 사유가 같다
        policy.set_overrides({"split.return_observe_days": (required, "시험", "시험")})
        v = eng.phase2_view(cid)
        in_gate = any(r.startswith("관찰 ") for r in v["gate"]["reasons"])
        assert v["returns_check"]["observation"]["done"] is (not in_gate) is split.observation_done(elapsed, required)


# ---- L2. 2차 관찰 viewer에 2차 승인·거절 ----

def test_2차_관찰_viewer의_2차_승인_거절은_건_상세와_같다(store):
    eng, cid = _scene(store, "scenario_2_exception", 10)
    sc = scenarios.load("scenario_2_exception")
    for s in sc.script[10:]:
        if store.get_case(cid)["status"] == "2차 승인 대기":
            break
        eng.play(s)
    assert store.get_case(cid)["status"] == "2차 승인 대기"
    seen = set()
    for who in _who(eng, True):
        pv, dv = _v(eng, cid, who), eng.case_detail(cid, viewer=who)["viewer"]
        assert pv["actions_phase2"] == dv["actions_phase2"] and pv["blocked_phase2"] == dv["blocked_phase2"]
        assert pv["can_decide_phase2"] == dv["can_decide_phase2"]
        seen |= set(pv["actions_phase2"])
    assert seen, "2차 승인권자는 한 명 이상 결정할 수 있어야 함"
    eng2, cid2 = _scene(store, "scenario_2_exception", 9)
    assert _v(eng2, cid2, "Masil 대표")["actions_phase2"] == []


# ---- L3. 등록되지 않은 viewer ----

def test_등록되지_않은_viewer면_viewer_부분만_오류_표시(store):
    eng, cid = _scene(store, "scenario_2_exception", 9)
    p = eng.phase2_view(cid, viewer="없는 사람")
    assert p["viewer"]["error"] == "등록되지 않은 사람: 없는 사람"
    assert p["viewer"]["actions"] == [] and p["viewer"]["blocked"] == [] and p["viewer"]["role"] is None
    assert p["returns_check"]["items"] and "error" not in _v(eng, cid, "Masil 대표")
    eng.set_mode("Masil 대표", "운영")  # 운영 모드에서 역할 이름을 사람 대신 쓰는 것도 같다
    role_name = "캠페인 담당"
    assert role_name not in eng.people.people and "error" in eng.phase2_view(cid, viewer=role_name)["viewer"]


def test_API는_등록되지_않은_viewer에도_200(store):
    c, _, _ = client(store, ACCEPT, SCM_PART)
    sc = Scene(c, "scenario_2_exception")
    for s in sc.steps[:11]:
        sc.play(s)
    cid = sc.case_id("PLAN-001")
    d = ok(c.get(f"/api/cases/{cid}/phase2", params={"viewer": "없는 사람"}))
    assert d["viewer"]["error"] and d["returns_check"]["items"]


# ---- L4. 해석 저장 실패 표시 ----

def test_해석에_실패한_리뷰는_옛_리뷰와_다르게_실패로_표시한다(store, monkeypatch):
    eng, cid = _scene(store, "scenario_2_sales", 8)
    old = store.add_review(cid, "립", "옛 리뷰")  # 해석 기록도 실패 기록도 없는 옛 저장
    from app.ai import judge

    def boom(*a, **k):
        raise RuntimeError("공급자 연결 실패")

    monkeypatch.setattr(judge, "interpret_review", boom)
    eng.add_reviews(cid, [("립", "새 리뷰")])  # 실패해도 리뷰 입력은 받는다
    monkeypatch.undo()
    rv = {r["text"]: r for r in eng.phase2_view(cid)["reviews"]}
    assert rv["옛 리뷰"]["judgment"] is None and rv["옛 리뷰"]["id"] == old
    bad = rv["새 리뷰"]["judgment"]
    assert bad["ok"] is False and "공급자 연결 실패" in bad["error"]
    assert any("리뷰 사람 확인" in str(t) for t in store.list_tasks(cid))  # 해석 못 한 리뷰는 사람이 확인
    assert [r["judgment"] for r in eng.case_detail(cid)["reviews"]][-1]["ok"] is False


# ---- L5. review_id 없는 옛 해석은 다른 리뷰에 붙지 않는다 ----

def test_review_id가_없는_옛_해석_기록이_있어도_리뷰에_잘못_붙지_않는다(store):
    eng, cid = _scene(store, "scenario_2_sales", 8)
    rid = store.add_review(cid, "립", "옛 리뷰")
    store.add_judgment(cid, "리뷰해석", "fake", "립 리뷰: 옛 리뷰", {"reason": "만족", "sentiment": "긍정"}, False, 0.9)
    rv = eng.phase2_view(cid)["reviews"]
    assert [r for r in rv if r["id"] == rid][0]["judgment"] is None


# ---- A1. 권한 읽기 ----

ADMIN = ("registry", "policy", "mode", "review", "return")


def _admin_calls(eng, cid):
    return {
        "registry": lambda w: eng.require_registry_editor(w),
        "policy": lambda w: eng.change_policy(w, "없는.정책.키", 1, "시험"),
        "mode": lambda w: eng.set_mode(w, "없는 모드"),
        "review": lambda w: eng.add_reviews(cid, None, actor=w),
        "return": lambda w: eng.add_returns(cid, -1, 0, actor=w),
    }


def _same_as_engine(eng, cid, people):
    calls = _admin_calls(eng, cid)
    for p in people:
        assert set(p["admin"]) == set(ADMIN)
        for key in ADMIN:
            a = p["admin"][key]
            try:
                calls[key](p["name"])
            except PermissionError as e:
                assert a == {"allowed": False, "reason": str(e)}, (p["name"], key)
            except (ValueError, TypeError):  # 권한은 통과하고 시험용 잘못된 입력에서 멈춤
                assert a == {"allowed": True, "reason": None}, (p["name"], key)


def test_사람마다_할_수_있는_관리_작업을_엔진_검사와_같게_준다(store):
    c, _, eng = client(store, ACCEPT, SCM_PART)
    sc = Scene(c, "scenario_2_sales")
    for s in sc.steps[:10]:
        sc.play(s)
    cid = sc.case_id("PLAN-001")
    people = ok(c.get("/api/permissions"))
    assert ok(c.get("/api/people")) == [{"name": p["name"], "role": p["role"]} for p in people]  # 사람 목록은 그대로
    assert {p["name"] for p in people} == set(eng.people.people) and all(p["role"] for p in people)
    _same_as_engine(eng, cid, people)
    assert any(p["admin"]["policy"]["allowed"] for p in people) and any(not p["admin"]["policy"]["allowed"] for p in people)
    ok(c.put("/api/mode", json={"actor": next(p["name"] for p in people if p["admin"]["mode"]["allowed"]), "mode": "운영"}))
    people = ok(c.get("/api/permissions"))  # 운영 모드에서는 리뷰·반품 입력이 정책 역할만
    _same_as_engine(eng, cid, people)
    assert any(not p["admin"]["review"]["allowed"] for p in people)


def test_person_조회로_한_사람만_받을_수_있다(store):
    c, _, eng = client(store, ACCEPT, SCM_PART)
    name = next(iter(eng.people.people))
    d = ok(c.get("/api/permissions", params={"person": name}))
    assert [p["name"] for p in d] == [name] and set(d[0]["admin"]) == set(ADMIN)
    assert "등록되지 않은 사람" in detail_of(c.get("/api/permissions", params={"person": "없는 사람"}), 404)


# ---- A2. 시연 진행 상태 ----

def _dplay(c, step):
    return ok(c.post("/api/demo/play", json={"step": step}))


def _state(c):
    return ok(c.get("/api/demo/state"))


def test_시연_진행_상태_초기화_재생_끝까지(store):
    c, _, _ = client(store, ACCEPT, SCM_PART)
    assert _state(c)["scenario"] is None
    sc = Scene(c, "scenario_1")
    steps = sc.steps
    st = _state(c)
    assert st["scenario"] == "scenario_1" and st["done"] == 0 and st["total"] == len(steps) and st["finished"] is False
    assert st["next_step"] == steps[0] and st["title"]
    _dplay(c, steps[0])
    assert _state(c)["done"] == 1 and _state(c)["next_step"] == steps[1]
    _dplay(c, steps[1])
    assert _state(c)["done"] == 2
    ok(c.post("/api/demo/reset", json={"scenario": "scenario_2_reject"}))  # 초기화하면 처음으로
    st = _state(c)
    assert st["scenario"] == "scenario_2_reject" and st["done"] == 0


def test_run은_처음부터가_기본이고_from_step으로_남은_단계만_돈다(store):
    c, _, _ = client(store, ACCEPT, SCM_PART)
    sc = Scene(c, "scenario_1")
    n = len(sc.steps)
    _dplay(c, sc.steps[0])
    _dplay(c, sc.steps[1])
    out = ok(c.post("/api/demo/run", json={"scenario": "scenario_1", "from_step": 2}))
    assert len(out) == n - 2 and _state(c)["done"] == n and _state(c)["finished"] is True
    assert _state(c)["next_step"] is None
    assert _state(c)["done"] == n


def test_from_step이_없으면_기존처럼_처음부터_돌고_진행_위치가_맞는다(store):
    c, _, eng = client(store, ACCEPT, SCM_PART)
    ok(c.post("/api/demo/reset", json={"scenario": "scenario_1"}))
    out = ok(c.post("/api/demo/run", json={"scenario": "scenario_1", "upto": 2}))
    assert len(out) == 2 and _state(c)["done"] == 2
    out = ok(c.post("/api/demo/run", json={"scenario": "scenario_1", "from_step": 2, "upto": 3}))
    assert len(out) == 1 and _state(c)["done"] == 3
    bad = detail_of(c.post("/api/demo/run", json={"scenario": "scenario_1", "from_step": 0}))
    assert "3단계" in bad and _state(c)["done"] == 3
    other = detail_of(c.post("/api/demo/run", json={"scenario": "scenario_3", "from_step": 3}))
    assert "scenario_1" in other
    assert c.post("/api/demo/run", json={"scenario": "scenario_1", "from_step": -1}).status_code == 422


def test_진행_상태는_저장돼_엔진을_다시_만들어도_남고_운영_모드에서는_거부(store):
    c, _, eng = client(store, ACCEPT, SCM_PART)
    sc = Scene(c, "scenario_1")
    _dplay(c, sc.steps[0])
    assert Engine(store).demo_state()["done"] == 1
    eng.set_mode("Masil 대표", "운영")
    assert "운영 모드" in detail_of(c.get("/api/demo/state"))
