"""Task 25: 2차 관찰 화면이 짐작하던 것을 서버가 준다 — 2차 결정 권한(actions·blocked), 반품 기준 숫자, 리뷰↔AI 해석 연결."""
import sys
from pathlib import Path

import pytest

from app import policy
from app.ai.providers import FakeProvider
from app.calc.campaign import return_count_rate
from app.engine import scenarios
from app.engine.flow import CHANGE_OF_MIND, COLOR_RETURN, Engine
from app.rules.split import return_stop_threshold
from app.store.db import open_db

sys.path.insert(0, str(Path(__file__).parent))
from test_flow_11b import ACCEPT, COLOR, SCM_PART  # noqa: E402
from test_flow_escalation import hold_case  # noqa: E402
from test_flow_sellthrough import ACTOR  # noqa: E402

CONT, CANCEL, EXC, SALES, REVIEW, RET = "2차 계속", "2차 취소", "예외 승인", "판매 실적 입력", "리뷰 입력", "반품 입력"


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


def _scene(store, name, upto):
    eng = Engine(store, provider=FakeProvider([ACCEPT, SCM_PART]))
    (cid,) = eng.seed(name)
    sc = scenarios.load(name)
    for s in sc.script[:upto]:
        eng.play(s)
    return eng, cid


def _v(eng, cid, who):
    return eng.phase2_view(cid, viewer=who)["viewer"]


def _blocked(v):
    return {b["action"]: b["reason"] for b in v["blocked"]}


# ---- 1. 2차 결정 권한 ----

def test_반품_보류_건에서_캠페인_담당은_취소만_최고_승인권자는_예외_승인만(store):
    eng, cid = _scene(store, "scenario_2_exception", 9)
    assert store.get_case(cid)["status"] == "2차 보류"
    v = _v(eng, cid, "캠페인 담당자")
    assert CANCEL in v["actions"] and EXC not in v["actions"] and CONT not in v["actions"]
    assert "최고 역할" in _blocked(v)[EXC] and "판매율" in _blocked(v)[CONT]
    top = _v(eng, cid, "Masil 대표")
    assert EXC in top["actions"] and CANCEL not in top["actions"]
    assert "캠페인 담당" in _blocked(top)[CANCEL]
    low = _v(eng, cid, "마케팅팀장")
    assert low["actions"] == [] or set(low["actions"]) <= {REVIEW, RET}
    assert EXC in _blocked(low) and CANCEL in _blocked(low)
    assert v["person"] == "캠페인 담당자" and v["role"] == "캠페인 담당"


def test_actions_blocked는_각_엔진_메서드와_같은_결과(store):
    eng, cid = _scene(store, "scenario_2_exception", 9)
    for who in ("캠페인 담당자", "Masil 대표", "마케팅팀장", "그룹 CEO"):
        v = _v(eng, cid, who)
        for act, call in ((CANCEL, lambda w=who: eng.cancel_phase2(cid, w, "")),
                          (EXC, lambda w=who: eng.approve_phase2_exception(cid, w, 1, ""))):
            try:
                call()
            except PermissionError as e:  # 빈 이유는 권한 검사 뒤에 거절되므로 권한 거절만 가려낸다
                assert act in _blocked(v) and str(e) == _blocked(v)[act]
            except ValueError:
                assert act in v["actions"]
    assert store.get_case(cid)["status"] == "2차 보류"  # 한 번도 저장하지 않음


def test_판매율_보류에서는_계속이_담당에게_열리고_예외_승인은_막힘(store, monkeypatch):
    eng, cid, _ = hold_case(store, monkeypatch)
    v = _v(eng, cid, ACTOR)
    assert {CONT, CANCEL} <= set(v["actions"]) and EXC in _blocked(v) and "판매율" in _blocked(v)[EXC]
    assert SALES in _blocked(v)  # 이미 판매율로 판정한 건
    assert CONT in _blocked(_v(eng, cid, "물류 담당자"))


def test_반품_보류_사유가_남아_있으면_계속은_막힌다(store, monkeypatch):
    eng, cid, _ = hold_case(store, monkeypatch)
    eng.add_returns(cid, 900, 900)  # 반품 기준 초과 사유가 남은 판매율 보류
    r = _blocked(_v(eng, cid, ACTOR))[CONT]
    with pytest.raises(ValueError) as e:
        eng.continue_phase2(cid, ACTOR, 1, "사유")
    assert str(e.value) == r


def test_판매_실적_입력은_캠페인_담당에게만_열린다(store):
    eng, cid = _scene(store, "scenario_2_sales", 8)
    assert eng.store.get_case(cid)["facts"].get("sales") is None
    assert SALES in _v(eng, cid, "캠페인 담당자")["actions"]
    b = _blocked(_v(eng, cid, "물류 담당자"))
    assert "캠페인 담당" in b[SALES]
    with pytest.raises(PermissionError) as e:
        eng.record_phase1_sales(cid, "물류 담당자", 10, 0)
    assert str(e.value) == b[SALES]


def test_리뷰_반품_입력은_운영_모드에서_정책_역할만(store):
    eng, cid = _scene(store, "scenario_2_sales", 8)
    assert {REVIEW, RET} <= set(_v(eng, cid, "물류 담당자")["actions"])  # 시연 모드는 누구나
    eng.set_mode("Masil 대표", "운영")
    low = _blocked(_v(eng, cid, "물류 담당자"))
    assert REVIEW in low and RET in low
    with pytest.raises(PermissionError) as e:
        eng.add_reviews(cid, [("립", "좋아요")], actor="물류 담당자")
    assert str(e.value) == low[REVIEW]
    allowed = policy.get("admin.review_inputters").split(",")[0].strip()
    who = next(p for p, r in eng.people.people.items() if r == allowed)
    assert REVIEW in _v(eng, cid, who)["actions"]


def test_viewer_없으면_actions를_주지_않고_읽기는_저장하지_않는다(store):
    eng, cid = _scene(store, "scenario_2_exception", 9)
    assert eng.phase2_view(cid)["viewer"] is None
    snap = (store.get_case(cid)["facts"], store.events(cid), store.get_case(cid)["status"], store.list_tasks(cid))
    for who in ("캠페인 담당자", "Masil 대표"):
        eng.phase2_view(cid, viewer=who)
    assert (store.get_case(cid)["facts"], store.events(cid), store.get_case(cid)["status"], store.list_tasks(cid)) == snap


def test_건_상세의_phase2에도_viewer_결정_권한이_들어간다(store):
    eng, cid = _scene(store, "scenario_2_exception", 9)
    d = eng.case_detail(cid, viewer="Masil 대표")
    assert EXC in d["phase2"]["viewer"]["actions"]
    assert eng.case_detail(cid)["phase2"]["viewer"] is None


# ---- 2. 반품 기준 ----

def test_반품_기준_숫자는_계산_함수와_2차_보류_사유와_일치(store):
    eng, cid = _scene(store, "scenario_2_exception", 9)
    p2 = eng.phase2_view(cid)
    rc = p2["returns_check"]
    f = store.get_case(cid)["facts"]
    n = f["phase1"]["qty"]
    items = {i["label"]: i for i in rc["items"]}
    assert set(items) == {"단순변심", "색상불만"} and rc["phase1_qty"] == n and rc["entered"] is True
    inf = f["influencer_id"]
    for label, key, reason in (("단순변심", "change_of_mind", CHANGE_OF_MIND), ("색상불만", "color", COLOR_RETURN)):
        i = items[label]
        base = return_count_rate(inf, reason)
        assert i["baseline"] == base
        assert i["limit"] == return_stop_threshold(base, n)
        assert i["count"] == f["returns"][key] and i["rate"] == f["returns"][key] / n and i["unit"] == "ratio"
        assert i["over"] == (i["rate"] > i["limit"])
    over = [i for i in items.values() if i["over"]]
    assert over, "시연 대본은 기준 초과로 2차 보류가 됨"
    reasons = p2["gate"]["reasons"]
    for i in over:  # 보류 사유 문장과 같은 값
        assert f"{i['label']} 반품률 {i['rate']:.1%}이 기준 {i['limit']:.1%} 초과" in reasons
    assert not [i for i in items.values() if not i["over"] and any(r.startswith(i["label"]) for r in reasons)]


def test_반품_기준_근거_detail은_근거_API_모양이고_관찰_기간_정보가_있다(store):
    eng, cid = _scene(store, "scenario_2_exception", 9)
    rc = eng.phase2_view(cid)["returns_check"]
    d = rc["items"][0]["detail"]
    assert set(d) == {"formula", "inputs", "sources", "policies"} and d["formula"] and d["inputs"] and d["sources"]
    assert {"split.stop_z"} <= {p["key"] for p in d["policies"]} and all(p["source"] for p in d["policies"])
    obs = rc["observation"]
    assert obs["required_days"] == policy.get("split.return_observe_days")
    assert obs["elapsed_days"] >= 0 and isinstance(obs["done"], bool) and obs["adjustment"]
    assert rc["z"] == policy.get("split.stop_z")


def test_반품을_아직_입력하지_않았으면_건수_0이고_entered는_False(store):
    eng, cid = _scene(store, "scenario_2_exception", 7)
    rc = eng.phase2_view(cid)["returns_check"]
    assert rc["entered"] is False and all(i["count"] == 0 and i["over"] is False for i in rc["items"])


def test_예외_승인을_받은_건은_초과여도_보류_사유에서_빠졌음을_알린다(store):
    eng, cid = _scene(store, "scenario_2_exception", 10)
    rc = eng.phase2_view(cid)["returns_check"]
    assert rc["exception_applied"] is True and any(i["over"] for i in rc["items"])
    assert not [r for r in eng.phase2_view(cid)["gate"]["reasons"] if "반품률" in r]


# ---- 3. 리뷰 ↔ AI 해석 ----

def test_같은_글_리뷰_둘이_각자_해석에_연결된다(store):
    eng = Engine(store, provider=FakeProvider([ACCEPT, SCM_PART, COLOR, '{"reason": "기타", "sentiment": "긍정", "content_gap": false, "confidence": 0.7}']))
    (cid,) = eng.seed("scenario_2_sales")
    for s in scenarios.load("scenario_2_sales").script[:8]:
        eng.play(s)
    eng.add_reviews(cid, [("립", "색이 달라요")])
    eng.add_reviews(cid, [("립", "색이 달라요")])
    rv = eng.phase2_view(cid)["reviews"]
    assert len(rv) == 2 and rv[0]["text"] == rv[1]["text"]
    a, b = rv[0]["judgment"], rv[1]["judgment"]
    assert a["id"] != b["id"] and a["reason"] == "색상불일치" and a["sentiment"] == "부정" and a["content_gap"] is True
    assert b["reason"] != a["reason"] and b["confidence"] == 0.7 and a["model"] and a["needs_human"] is False
    assert set(a) == {"ok", "id", "reason", "sentiment", "content_gap", "confidence", "needs_human", "model"} and a["ok"] is True
    assert [r["judgment"]["id"] for r in eng.case_detail(cid)["reviews"]] == [a["id"], b["id"]]


def test_옛_리뷰는_해석이_null(store):
    eng, cid = _scene(store, "scenario_2_sales", 8)
    rid = store.add_review(cid, "립", "옛 리뷰")  # 해석 기록에 review_id가 없는 옛 저장
    rv = eng.phase2_view(cid)["reviews"]
    assert [r["id"] for r in rv][-1] == rid and rv[-1]["judgment"] is None


# ---- API ----

def test_phase2_API가_viewer를_받아_actions_blocked_returns_check_reviews를_준다(store):
    from test_api import Scene, client, ok
    c, _, _ = client(store, ACCEPT, SCM_PART)
    sc = Scene(c, "scenario_2_exception")
    for s in sc.steps[:9]:
        sc.play(s)
    cid = sc.case_id("PLAN-001")
    d = ok(c.get(f"/api/cases/{cid}/phase2", params={"viewer": "Masil 대표"}))
    assert EXC in d["viewer"]["actions"] and {b["action"] for b in d["viewer"]["blocked"]} >= {CANCEL, CONT}
    assert d["returns_check"]["items"][0]["detail"]["formula"] and d["reviews"] == []
    assert ok(c.get(f"/api/cases/{cid}/phase2"))["viewer"] is None
