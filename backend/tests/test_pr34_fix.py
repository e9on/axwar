"""PR #34 검토 반영: 기한 지난 건의 가능한 결정, 2차 결재선 이유, 회신별 사람 확인, 단위, 순위 없음 등."""
import json
import threading
import time
from datetime import date

import pytest

from app.ai import providers
from app.ai.providers import FakeProvider
from app.calc import evidence as evidence_calc
from app.engine import scenarios
from app.engine.flow import Engine
from app.rules.deadline import deny_date
from app.store.db import open_db

ACCEPT = json.dumps({"stance": "수용", "qty_limit": None, "next_date": None, "needs_human": False,
                     "confidence": 0.9}, ensure_ascii=False)
UNSURE = json.dumps({"stance": "정보부족", "qty_limit": None, "next_date": None, "needs_human": True,
                     "confidence": 0.3}, ensure_ascii=False)


@pytest.fixture(autouse=True)
def _fake_mode(monkeypatch):
    monkeypatch.delenv("AXWAR_AI", raising=False)


@pytest.fixture
def store(tmp_path):
    s = open_db(tmp_path / "t.db")
    yield s
    s.close()


def _eng(store, *responses):
    return Engine(store, provider=FakeProvider(list(responses) or [ACCEPT] * 6))


def _phase2_wait(store):
    eng = Engine(store)
    cid = eng.seed("scenario_2_exception")[0]
    eng.run_script("scenario_2_exception", upto=12)
    assert store.get_case(cid)["status"] == "2차 승인 대기"
    return eng, cid


# ---- M1 기한이 지난 건 ----

@pytest.mark.usefixtures("legacy_scenes")
def test_기본_거부_실행일이_지난_1차_건은_결정_목록이_비고_이유가_있다(store):
    eng = _eng(store)
    cid = eng.seed("scenario_1")[0]
    eng.run_script("scenario_1", upto=2)
    v = eng.case_detail(cid, viewer="Masil 대표")["viewer"]
    assert "승인" in v["actions"] or "분할승인" in v["actions"]
    f = store.get_case(cid)["facts"]
    store.set_clock(deny_date(date.fromisoformat(f["deadline"])))  # 하루 점검이 아직 돌지 않은 채 날짜만 도달
    v = eng.case_detail(cid, viewer="Masil 대표")["viewer"]
    assert v["actions"] == [] and v["can_decide"] is False
    assert v["blocked"] and all("기한이 지나 기본 거부" in b["reason"] for b in v["blocked"])
    assert {"승인", "분할승인", "거절"} >= {b["action"] for b in v["blocked"]}
    # decide의 실제 동작과 맞다: 결정이 아니라 기본 거부
    out = eng.decide(cid, "Masil 대표", "승인")
    assert out["changed"] is False and "기본 거부" in out["message"]


def test_2차_기본_거부_실행일이_지난_건은_2차_결정_목록이_빈다(store):
    eng, cid = _phase2_wait(store)
    v = eng.case_detail(cid, viewer="Masil 대표")["viewer"]
    assert v["actions_phase2"] == ["승인", "거절"] and v["blocked_phase2"] == []
    f = store.get_case(cid)["facts"]
    store.set_clock(deny_date(date.fromisoformat(f["phase2_deadline"])))
    v = eng.case_detail(cid, viewer="Masil 대표")["viewer"]
    assert v["actions_phase2"] == [] and v["can_decide_phase2"] is False
    assert v["blocked_phase2"] and all("기한이 지나 기본 거부" in b["reason"] for b in v["blocked_phase2"])


# ---- M2 2차 결재선 이유 ----

def test_2차_상신_뒤_phase2_hits도_상신이_앞이고_detail이_없다(store):
    eng, cid = _phase2_wait(store)
    before = eng.case_detail(cid)["phase2"]["hits"]
    assert before and all("detail" not in h and not h.get("superseded") for h in before)
    eng.escalate(cid, "Masil 대표", "2차", "승인 권고", "금액이 커서 CEO 확인이 필요하다고 판단")
    for hits in (eng.case_detail(cid)["phase2"]["hits"], eng.phase2_view(cid)["hits"]):
        assert hits[0]["rule_id"] == "escalation" and "detail" not in hits[0]
        assert len(hits) > 1 and all(h["superseded"] is True for h in hits[1:])
        assert all("detail" not in h for h in hits)


# ---- M3 회신별 사람 확인 ----

def test_처리한_회신이_또_사람_확인이면_확인됨이_아니다(store):
    eng = _eng(store, UNSURE, UNSURE)
    cid = eng.seed("scenario_1")[0]
    req = store.list_requests(cid)[0]
    eng.reply(req["id"], "검토해 보겠습니다", 0)
    eng.resolve_human_check(req["id"], "캠페인 담당자", "더 검토하겠습니다", 0)
    assert store.get_request(req["id"])["status"] == "사람 확인"
    rs = eng.case_detail(cid)["requests"][0]["replies"]
    assert len(rs) == 2
    for r in rs:
        assert r["judgment"]["human_confirmed"] is False and r["judgment"]["confirmed_by"] is None


def test_확인자는_그_회신_뒤에_처리한_회신에서_찾는다(store):
    eng = _eng(store, UNSURE, UNSURE, ACCEPT)
    cid = eng.seed("scenario_1")[0]
    req = store.list_requests(cid)[0]
    eng.reply(req["id"], "검토해 보겠습니다", 0)
    eng.resolve_human_check(req["id"], "캠페인 담당자", "더 검토하겠습니다", 0)
    eng.resolve_human_check(req["id"], "캠페인 담당자", "진행하겠습니다", 0)
    rs = eng.case_detail(cid)["requests"][0]["replies"]
    j = [r["judgment"] for r in rs]
    assert [x["human_confirmed"] for x in j] == [True, False, True]
    assert j[0]["confirmed_by"] == "캠페인 담당자"
    assert j[1]["confirmed_by"] is None
    assert j[2]["confirmed_by"] == "캠페인 담당자"


# ---- L1 viewer도 등록부 동기 뒤 사실로 판정(저장은 하지 않음) ----

def test_viewer_판정은_등록부를_먼저_맞춘_사실로(store):
    eng = _eng(store)
    cid = eng.seed("scenario_1")[0]
    eng.run_script("scenario_1", upto=2)
    plan_id = store.get_case(cid)["ref_id"]
    row = store.get_plan(plan_id)
    new_day = "2026-09-12"
    assert row["settlement_date"] != new_day
    store.update_plan(row["id"], {"settlement_date": new_day}, "시험")  # 엔진을 거치지 않은 등록부 변경
    assert eng.case_detail(cid)["facts"]["settlement_date"] != new_day  # viewer 없는 읽기는 읽기 전용
    d = eng.case_detail(cid, viewer="Masil 대표")
    assert d["facts"]["settlement_date"] != new_day  # viewer를 줘도 저장은 그대로(Task 23: 읽기는 저장 값을 바꾸지 않음)
    assert store.get_case(cid)["facts"]["settlement_date"] != new_day


# ---- L2 분할 미리보기 금액 ----

def test_분할_미리보기가_2차_수량이_있는_확정_값과_같다(store):
    eng = Engine(store)
    cid = eng.seed("scenario_2")[0]
    eng.run_script("scenario_2", upto=4)
    f = store.get_case(cid)["facts"]
    assert f["split"]["phase2_qty"] > 0
    f["volume"] = {**f["volume"], "units": None}  # 물량을 모르는 건: 금액 분모가 1차+2차 수량
    store.update_facts(cid, f, "시험", "물량 모름")
    sp = eng.case_detail(cid, viewer="그룹 CEO")["viewer"]["split_preview"]
    assert sp and sp["phase2_qty"] > 0
    for s in scenarios.load("scenario_2").script[4:6]:
        eng.play(s)  # 남은 분할 승인
    f = store.get_case(cid)["facts"]
    assert f["phase2"] and f["phase2"]["qty"] == sp["phase2_qty"]
    assert f["phase2"]["amount_krw"] == sp["phase2_amount_krw"]
    assert sp["phase1_amount_krw"] == eng._plan_amount_of(f, f["phase1"]["qty"])


# ---- L3 blocked에는 정말 막힌 것만 ----

def test_분할안이_없는_건과_계약에는_분할승인이_없다(store):
    eng = Engine(store)
    ids = eng.seed("scenario_3")
    contract = next(i for i in ids if store.get_case(i)["kind"] == "계약")
    role = eng.case_detail(contract)["rule"]["pending_roles"][0]
    v = eng.case_detail(contract, viewer=role)["viewer"]
    assert "분할승인" not in v["actions"] and all(b["action"] != "분할승인" for b in v["blocked"])
    eng2 = _eng(store)
    scenarios.register_plan(store, "PLAN-001")
    pid = eng2.open_plan("PLAN-001")
    assert not store.get_case(pid)["facts"].get("split")
    role = eng2.case_detail(pid)["rule"]["pending_roles"][0]
    v = eng2.case_detail(pid, viewer=role)["viewer"]
    assert all(b["action"] != "분할승인" for b in v["blocked"])


# ---- L4 2차 승인한 사람의 거절 ----

def test_2차에서_이미_승인한_사람은_거절만_보인다_decide와_같다(store):
    eng, cid = _phase2_wait(store)
    eng.decide_phase2(cid, "Masil 대표", "승인")
    v = eng.case_detail(cid, viewer="Masil 대표")["viewer"]
    assert v["actions_phase2"] == ["거절"] and v["can_decide_phase2"] is True
    out = eng.decide_phase2(cid, "Masil 대표", "거절", "다시 보니 반대")
    assert out["changed"] is True


# ---- L5 대본 해석 공급자는 잠금 안에서만 ----

def test_play는_잠금을_잡은_뒤에야_대본_공급자를_둔다(store):
    eng = Engine(store)
    eng.seed("scenario_1")
    step = scenarios.load("scenario_1").script[0]
    seen = {}
    with eng._lock:
        t = threading.Thread(target=lambda: eng.play(step))
        t.start()
        time.sleep(0.3)
        seen["script_reply"] = eng._script_reply  # 다른 호출이 잠금을 쥔 동안 공유 상태가 바뀌면 안 된다
    t.join(10)
    assert seen["script_reply"] is None


# ---- L6 키워드 해석 ----

@pytest.mark.parametrize("text", ["3,000개까지 허용합니다", "3000개까지 가능합니다"])
def test_N개까지_허용은_일부_허용으로(text):
    out = json.loads(providers._fake_reply("SCM 회신: " + text))
    assert out["stance"] == "조건부수용" and out["qty_limit"] == 3000 and out["needs_human"] is False


def test_수량_없는_허용은_그대로_수용():
    out = json.loads(providers._fake_reply("SCM 회신: 허용합니다"))
    assert out["stance"] == "수용" and out["qty_limit"] is None


# ---- L7 단위 ----

def test_HHI는_score_추세는_diff_단위(store):
    eng = _eng(store)
    scenarios.register_plan(store, "PLAN-001")
    cid = eng.open_plan("PLAN-001")
    sig = {s["key"]: s for s in eng.case_evidence(cid)["signals"]}
    assert sig["spend_concentration"]["unit"] == "score"
    assert sig["trend"]["unit"] == "diff"
    assert sig["forecast_gap"]["unit"] == "multiple"


def test_핵심_지표_입력값에도_단위(store):
    eng = _eng(store)
    scenarios.register_plan(store, "PLAN-001")
    cid = eng.open_plan("PLAN-001")
    ki = {k["key"]: k for k in eng.case_evidence(cid)["key_indicators"]}
    ins = {i["label"]: i for i in ki["spend_share"]["detail"]["inputs"]}
    assert ins["광고비 비중(%)"]["unit"] == "percent"
    ins = {i["label"]: i for i in ki["real_roas"]["detail"]["inputs"]}
    assert ins["실질 ROAS"]["unit"] == "multiple"


# ---- L8 기안이 없는 인플루언서 ----

def test_기안이_없는_인플루언서는_요청_비중_순위가_없다(monkeypatch):
    ranking = evidence_calc.influencer_ranking()
    target = ranking[0].influencer_id
    shares = {k: v for k, v in evidence_calc.request_shares().items() if k != target}
    monkeypatch.setattr(evidence_calc, "request_shares", lambda: shares)
    ki = {k["key"]: k for k in evidence_calc.key_indicators(target)}
    assert ki["request_share"]["rank"] is None and ki["request_share"]["of"] is None
    assert "기안" in ki["request_share"]["rank_reason"]
    assert ki["allocation_inversion"]["value"] is False


# ---- L9 없어진 정책 키 ----

def test_없어진_정책_키는_500이_아니라_표시():
    d = evidence_calc.resolve_detail({"formula": "f", "inputs": [], "sources": [], "policy_keys": ["no.such.key"]})
    assert d["policies"][0]["key"] == "no.such.key" and d["policies"][0]["missing"] is True
    assert "없어진 정책 항목" in d["policies"][0]["description"]


def test_건_근거는_없어진_정책_키가_있어도_열린다(store):
    eng = _eng(store)
    scenarios.register_plan(store, "PLAN-001")
    cid = eng.open_plan("PLAN-001")
    f = store.get_case(cid)["facts"]
    det = f["approver_hits"][0]["detail"]
    det["policy_keys"] = [*det["policy_keys"], "no.such.key"]
    store.update_facts(cid, f, "시험", "정책 키 없앰")
    hits = eng.case_evidence(cid)["rule"]["approver_hits"]
    assert any(p.get("missing") for p in hits[0]["detail"]["policies"])


# ---- L10 상신이 여러 번 ----

@pytest.mark.usefixtures("legacy_scenes")
def test_상신이_둘이면_마지막_상신이_맨_앞(store):
    eng = Engine(store)
    cid = eng.seed("scenario_1_escalate")[0]
    eng.run_script("scenario_1_escalate", upto=3)  # 마케팅팀장 -> Masil 대표 상신
    eng.escalate(cid, "Masil 대표", "1차", "반대 권고", "CEO 확인이 필요하다고 판단")
    hits = eng.case_evidence(cid)["rule"]["approver_hits"]
    assert hits[0]["rule_id"] == "escalation" and "Masil 대표" in hits[0]["text"] and "CEO" in hits[0]["text"]
    assert not hits[0].get("superseded")
    assert hits[1]["rule_id"] == "escalation" and "마케팅팀장" in hits[1]["text"] and hits[1]["superseded"] is True
    d = eng.case_detail(cid)["rule"]["hits"]
    assert d[0]["rule_id"] == "escalation" and "CEO" in d[0]["text"]


# ---- 열린 건과 단계 ----

def test_건_상세에_open과_stage_회신_대기에서_1차_집행까지(store):
    eng = _eng(store)
    cid = eng.seed("scenario_1")[0]
    c = eng.case_detail(cid)["case"]
    assert c["open"] is True and c["stage"] == "회신 대기"
    eng.run_script("scenario_1")
    c = eng.case_detail(cid)["case"]
    assert c["open"] is False and c["stage"] == "1차 집행"


def test_건_상세의_stage_2차_승인_대기(store):
    eng, cid = _phase2_wait(store)
    c = eng.case_detail(cid)["case"]
    assert c["open"] is False and c["stage"] == "2차 승인 대기"


def test_건_상세의_stage_1차_승인_대기(store):
    eng = Engine(store)
    cid = eng.seed("scenario_1_escalate")[0]
    eng.run_script("scenario_1_escalate", upto=2)
    c = eng.case_detail(cid)["case"]
    assert c["open"] is True and c["stage"] == "1차 승인 대기"
