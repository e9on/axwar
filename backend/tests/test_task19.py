"""Task 19: 키 없이(가짜 AI 모드) 시연 대본이 끝까지 돌기 + 할 일·건 목록 항목 이름."""
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.ai.providers import FakeProvider
from app.api.main import create_app
from app.engine import scenarios
from app.engine.flow import Engine
from app.store.db import open_db

ALL = ["scenario_1", "scenario_1_escalate", "scenario_2", "scenario_2_exception", "scenario_2_reject",
       "scenario_2_sales", "scenario_3", "scenario_3_reject"]


@pytest.fixture
def store(tmp_path):
    s = open_db(tmp_path / "t.db")
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _fake_mode(monkeypatch):
    monkeypatch.delenv("AXWAR_AI", raising=False)  # 기본 = 가짜 AI


def run_fake(store, name):
    eng = Engine(store)  # 고정 응답 공급자 없이 기본 공급자
    ids = eng.seed(name)
    out = eng.run_script(name)
    return eng, ids, out


def test_모든_대본_파일의_회신_단계에_ai_해석이_있다():
    for name in ALL:
        for s in scenarios.load(name).script:
            if s["action"] == "회신":
                assert set(s["ai"]) >= {"stance", "qty_limit", "next_date", "needs_human"}, (name, s)


# 대본별 끝 상태(기존 대본 시험이 고정 응답으로 확인하는 값과 같다)
END = {
    "scenario_1": "1차 집행", "scenario_1_escalate": "1차 집행", "scenario_2": "2차 보류",
    "scenario_2_reject": "1차 차단", "scenario_2_sales": "완료", "scenario_2_exception": "완료",
    "scenario_3_reject": "상대 회신 대기",
}


@pytest.mark.parametrize("name", sorted(END))
def test_가짜_AI로_대본이_끝까지_돌고_끝_상태가_기존_시험과_같다(store, name):
    eng, ids, out = run_fake(store, name)
    assert store.get_case(ids[0])["status"] == END[name]
    j = [x for x in store.list_judgments(ids[0]) if x["kind"] == "회신해석"]
    assert (j or name == "scenario_3_reject") and all("fake" in x["model"] and "대본" in x["model"] for x in j)  # 대본 지정 해석임이 드러난다


def test_가짜_AI_장면1_승인권자와_해석(store):
    eng, (cid,), out = run_fake(store, "scenario_1")
    assert store.get_case(cid)["facts"]["approvers"] == ["Masil 대표", "그룹 보고"]
    assert out[1]["judgment"]["stance"] == "수용" and out[1]["needs_human"] is False


def test_가짜_AI_장면2_수량과_리뷰(store):
    eng, (cid,), out = run_fake(store, "scenario_2")
    f = store.get_case(cid)["facts"]
    assert out[3]["judgment"]["stance"] == "조건부수용" and out[3]["judgment"]["qty_limit"] == 3000
    assert f["announce"]["qty"] == 3000 and f["reviews"] == {"total": 10, "color": 3}
    assert f["scm"]["state"] == "일부 허용"


def test_가짜_AI_예외승인_2차_수량(store):
    eng, (cid,), out = run_fake(store, "scenario_2_exception")
    assert store.get_case(cid)["facts"]["phase2"] == {"qty": 4700, "date": "2026-08-28", "amount_krw": 606285}
    assert store.get_clock() == date(2026, 9, 2)


def test_가짜_AI_장면3_정보부족은_사람_확인(store):
    eng, ids, out = run_fake(store, "scenario_3")
    contract = ids[3]
    assert store.get_case(contract)["status"] == "사람 확인"
    assert out[3]["needs_human"] is True and out[3]["judgment"]["stance"] == "정보부족"


def test_API로_가짜_AI_대본_실행(store):
    c = TestClient(create_app(store, Engine(store)))
    assert c.post("/api/demo/reset", json={"scenario": "scenario_1"}).status_code == 200
    r = c.post("/api/demo/run", json={"scenario": "scenario_1"})
    assert r.status_code == 200, r.text
    assert [x["status"] for x in r.json()] == ["승인 대기", "승인 대기", "1차 집행"]


def test_ai_필드는_가짜_모드에서만_쓰고_실제_모드에서는_무시한다(store, monkeypatch):
    eng = Engine(store, provider=FakeProvider([]))  # 고정 공급자를 주면 그 공급자가 해석(ai 필드 무시)
    assert eng._reply_override({"ai": {"stance": "거절"}}) is None
    monkeypatch.setenv("AXWAR_AI", "real")
    assert Engine(store)._reply_override({"ai": {"stance": "수용"}}) is None


def test_fake_키워드_해석은_허용을_수용으로_본다():
    from app.ai.providers import _fake_reply
    def j(text):
        return json.loads(_fake_reply("회신: " + text))
    assert j("전량 허용합니다. 안전재고를 사용해도 좋습니다.")["stance"] == "수용"
    assert j("안전재고는 쓸 수 없습니다. 거절합니다.")["stance"] == "거절"
    assert j("허용하지 않습니다. 불가합니다.")["stance"] == "거절"  # 불가가 먼저 이긴다
    assert j("허용하지 않습니다.")["stance"] == "거절"
    assert j("내부 논의 후 회신드리겠습니다.")["stance"] == "정보부족"


# ---- 형식 검증

BASE = {"title": "t", "description": "d", "plans": ["PLAN-019"], "contracts": [], "requests": []}


def load_step(tmp_path, step):
    (tmp_path / "x.json").write_text(json.dumps({**BASE, "script": [{"plan": "PLAN-019", "action": "회신", "dept": "물류",
                                                                    "text": "가능", **step}]}, ensure_ascii=False), encoding="utf-8")
    return scenarios.load("x", tmp_path)


def test_ai_형식_검증(tmp_path):
    good = {"stance": "수용", "qty_limit": None, "next_date": None, "needs_human": False}
    assert load_step(tmp_path, {"ai": good}).script[0]["ai"] == good
    load_step(tmp_path, {})  # ai는 선택
    for bad in ({**good, "stance": "몰라"}, {**good, "qty_limit": -1}, {**good, "qty_limit": "3000"},
                {**good, "next_date": "9/1"}, {**good, "needs_human": "아니오"}, {"stance": "수용"},
                {**good, "extra": 1}, "수용"):
        with pytest.raises(ValueError, match="ai"):
            load_step(tmp_path, {"ai": bad})


# ---- 항목 이름

def titles(eng, store, ref):
    cid = next(c["id"] for c in store.list_cases() if c["ref_id"] == ref)
    return cid


def test_원본_기안과_전속계약의_항목_이름(store):
    eng = Engine(store, provider=FakeProvider([]))
    eng.seed("scenario_3")
    by = {c["ref_id"]: c for c in store.list_cases()}
    assert eng._item(by["PLAN-001"])["title"] == "혜인 기초 캠페인3 · 혜인"
    assert eng._item(by["INF-001"])["title"] == "혜인 전속계약"
    assert eng.todo("그룹 CEO")["승인 대기"][0]["title"]


def test_시연_기안_이름은_base_기안_캠페인과_시연용_표시(store):
    eng = Engine(store, provider=FakeProvider([]))
    (cid,) = eng.seed("scenario_1_escalate")
    demo = eng._item(store.get_case(cid))["title"]
    base = eng.seed("scenario_1")[0]  # 새 시연 준비(이전 건은 지워짐)
    plain = eng._item(store.get_case(base))["title"]
    assert demo == plain + " (시연용)"


def test_PLAN_019_이름(store):
    eng = Engine(store, provider=FakeProvider([]))
    (cid,) = eng.seed("scenario_1")
    t = eng._item(store.get_case(cid))["title"]
    assert t == "초혜핏 선케어 캠페인2 · 초혜핏"  # CMP-0005 / INF-002


def test_화면_등록_기안은_등록부_이름_없으면_ref_id(store):
    store.add_plan({"plan_id": "NEW-1", "campaign_id": "CMP-0005", "influencer_id": "INF-002", "channel": "자사몰",
                    "requested_budget_krw": 3000000, "expected_gmv_krw": 30000000,
                    "settlement_date": "2026-10-01", "contract_deadline": "2026-09-11"}, "캠페인 담당자")
    store.add_plan({"plan_id": "NEW-2", "campaign_id": "CMP-없음", "influencer_id": "INF-없음", "channel": "자사몰",
                    "requested_budget_krw": 3000000, "expected_gmv_krw": 30000000,
                    "settlement_date": "2026-10-01", "contract_deadline": "2026-09-11"}, "캠페인 담당자")
    eng = Engine(store, provider=FakeProvider([]))
    c1, c2 = eng.open_plan("NEW-1"), eng.open_plan("NEW-2")
    t1 = eng._item(store.get_case(c1))["title"]
    assert t1 != "NEW-1" and "시연용" not in t1 and "초혜핏" in t1
    assert eng._item(store.get_case(c2))["title"] == "NEW-2"


def test_API_목록과_상세에도_title(store):
    eng = Engine(store, provider=FakeProvider([]))
    ids = eng.seed("scenario_3")
    c = TestClient(create_app(store, eng))
    rows = {r["ref_id"]: r for r in c.get("/api/cases").json()}
    assert rows["INF-001"]["title"] == "혜인 전속계약" and rows["PLAN-001"]["title"]
    d = c.get(f"/api/cases/{ids[3]}").json()
    assert d["case"]["title"] == "혜인 전속계약"
