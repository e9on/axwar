"""이벤트 엔진(Task 11a). Provider는 FakeProvider로 응답을 고정한다. 설계 8장 숫자는 테스트에만 둔다."""
import json
import shutil
from datetime import date, timedelta

import pytest

from app import config, policy
from app.ai.providers import BudgetedProvider, FakeProvider
from app.engine import flow, scenarios
from app.calc import inventory
from app.engine.flow import Engine, _decide_by
from app.store.db import MODE_OPERATION, open_db

# 이 파일의 대부분은 승인·기한·등록부 흐름(11a)을 본다. 사용자 결정 2(모든 건이 재고 장부를 거침) 뒤에는 시연 데이터의 라인 여유가 0이라
# 물류 회신만 해도 SCM 요청이 생기므로, 재고를 보는 시험(REAL_LEDGER)만 빼고 재고가 충분한 장부로 둔다. 재고 흐름은 test_flow_11b.py가 본다.
REAL_LEDGER = ("test_장면1_정상", "test_대본을_끝까지_실행하면_1차_집행", "test_리뷰_색상불일치면_콘텐츠_수정_요청과_첨부필수",
               "test_모의_반품은_사실에_쌓이고_2차가_없으면_열리지_않는다", "test_끝난_건은_등록부가_바뀌어도_그대로_경고만_한번")


@pytest.fixture(autouse=True)
def _ample_stock(request, monkeypatch):
    if request.node.name not in REAL_LEDGER:
        monkeypatch.setattr(inventory, "line_spare", lambda category, day: 10**9)

ACCEPT = json.dumps({"stance": "수용", "qty_limit": None, "next_date": None, "needs_human": False,
                     "confidence": 0.9}, ensure_ascii=False)
COLOR = json.dumps({"reason": "색상불일치", "sentiment": "부정", "content_gap": True, "confidence": 0.9},
                   ensure_ascii=False)
HAPPY = json.dumps({"reason": "만족", "sentiment": "긍정", "content_gap": False, "confidence": 0.9},
                   ensure_ascii=False)


@pytest.fixture
def store(tmp_path):
    s = open_db(tmp_path / "t.db")
    yield s
    s.close()


def make(store, *responses, **kw):
    fake = FakeProvider(list(responses))
    return Engine(store, provider=fake, **kw), fake


def seeded(store, *responses):
    eng, fake = make(store, *responses)
    cid = eng.seed("scenario_1")[0]
    return eng, fake, cid


def steps():
    return scenarios.load("scenario_1").script


def statuses(store, cid):
    return [e["detail"]["to"] for e in store.events(cid, kind="상태변경")]


# ---- 지시서·개정 11a 필수 ----

@pytest.mark.usefixtures("legacy_scenes")
def test_장면1_정상(store):
    eng, fake = make(store, ACCEPT, ACCEPT)
    ids = eng.seed("scenario_1")
    assert len(ids) == 1
    c = store.get_case(ids[0])
    f = c["facts"]
    assert c["kind"] == "기안" and c["ref_id"] == "PLAN-019" and c["status"] == "회신 대기"
    assert f["campaign_id"] == "CMP-0005" and f["influencer_id"] == "INF-002"
    assert f["amount_krw"] == 4807921 and f["settlement_date"] == "2026-09-14" and f["deadline"] == "2026-09-11"
    assert f["plan_total_krw"] == 180803272
    # 총액 1억 초과 → Masil 대표 + 그룹 보고, 지표 반대 아님
    assert f["approvers"] == ["Masil 대표", "그룹 보고"] and f["indicator_good"] is True
    rule_ids = [h["rule_id"] for h in f["approver_hits"]]
    assert "plan_total_over_limit" in rule_ids and "indicator_opposite" not in rule_ids
    assert store.get_plan("PLAN-019")["origin"] == "시연"
    reqs = store.list_requests(c["id"])
    assert [(r["dept"], r["purpose"], r["status"]) for r in reqs] == [("물류", "물류 처리 능력", "대기")]
    assert eng.todo("물류 담당자")["회신 대기"][0]["request_id"] == reqs[0]["id"]

    r1 = eng.play(steps()[0])  # 물류 "전량 가능"
    assert r1["needs_human"] is False and r1["status"] == "승인 대기"
    assert r1["judgment"]["stance"] == "수용"
    assert store.get_request(reqs[0]["id"])["status"] == "처리됨"
    assert [x["case_id"] for x in eng.todo("Masil 대표")["승인 대기"]] == [c["id"]]

    # 사용자 결정 2(2026-11-11): 처리량 숫자 없는 "전량 가능"도 재고 장부를 돌린다. 9/14 선케어 라인은 안전재고 위 여유가 0이라 SCM 요청이 생긴다.
    f = store.get_case(c["id"])["facts"]
    assert f["stock"]["spare"] == 0 and f["stock"]["shortage"] is True and f["stock"]["capacity"] is None
    assert f["stock"]["day_qty"] == f["stock"]["share"] == f["stock"]["want"] > 0
    scm = [r for r in store.list_requests(c["id"]) if r["dept"] == "SCM"]
    assert [(r["purpose"], r["status"]) for r in scm] == [("안전재고 사용", "대기")]
    with pytest.raises(ValueError, match="분할 승인만"):  # SCM이 답하기 전에는 분할 없는 승인이 안 된다
        eng.decide(c["id"], "Masil 대표", "승인")
    r_scm = eng.play(steps()[1])  # SCM "전량 허용"
    assert r_scm["needs_human"] is False and store.get_case(c["id"])["facts"]["scm"]["state"] == "전량 허용"
    assert store.get_case(c["id"])["status"] == "승인 대기" and store.events(c["id"], kind="재승인알림") == []

    r2 = eng.play(steps()[2])  # 대표 승인
    assert r2["status"] == "1차 집행" and r2["changed"] is True
    tasks = [t for t in store.list_tasks(c["id"]) if t["dept"] in ("물류", "CS")]  # SCM 발주 조정 요청은 따로 센다
    assert sorted((t["dept"], t["title"]) for t in tasks) == [("CS", "CS 대비"), ("물류", "물류 출고")]
    assert all(t["due"] == "2026-09-14" for t in tasks)
    f = store.get_case(c["id"])["facts"]
    assert f["phase1"] == {"qty": f["stock"]["day_qty"], "date": "2026-09-14"} and f["phase2"] is None  # 집행일 하루 수량 단위
    assert statuses(store, c["id"]) == ["회신 대기", "승인 대기", "승인", "1차 집행"]  # SCM 전량 허용은 분할안이 그대로라 재승인 없음
    assert [a["approvers"] for a in store.list_approvals(c["id"])] == [["Masil 대표"]]
    assert eng.todo("그룹 재무")["알림"][0]["case_id"] == c["id"]  # 그룹 보고
    assert eng.todo("Masil 대표")["승인 대기"] == []
    assert len(fake.calls) == 2


@pytest.mark.usefixtures("legacy_scenes")
def test_대본을_끝까지_실행하면_1차_집행(store):
    eng, _ = make(store, ACCEPT, ACCEPT)
    eng.seed("scenario_1")
    results = eng.run_script("scenario_1")
    assert [r["status"] for r in results] == ["승인 대기", "승인 대기", "1차 집행"]


def test_승인권자가_아니면_거절하고_상태_그대로(store):
    eng, _, cid = seeded(store, ACCEPT)
    eng.play(steps()[0])
    with pytest.raises(PermissionError):
        eng.decide(cid, "물류 담당자", "승인")
    with pytest.raises(PermissionError):
        eng.decide(cid, "모르는 사람", "승인")
    with pytest.raises(PermissionError):
        eng.decide(cid, "그룹 재무", "승인")  # 그룹 보고는 보고만 받는다
    assert store.get_case(cid)["status"] == "승인 대기"
    assert store.list_tasks(cid) == [] and store.list_approvals(cid) == []


def test_같은_승인을_두번_눌러도_작업은_한번(store):
    eng, _, cid = seeded(store, ACCEPT)
    eng.play(steps()[0])
    first = eng.decide(cid, "Masil 대표", "승인")
    second = eng.decide(cid, "Masil 대표", "승인")
    assert first["changed"] is True and second["changed"] is False
    assert second["status"] == "1차 집행" and second["message"] == "결정 단계가 지난 건이라 상태 그대로"
    assert len(store.list_tasks(cid)) == 3 and len(store.list_approvals(cid)) == 1
    assert len(store.events(kind="그룹보고")) == 1


def test_같은_회신을_두번_저장해도_한번만_처리(store):
    eng, fake, cid = seeded(store, ACCEPT)
    rid = store.list_requests(cid)[0]["id"]
    a = eng.reply(rid, "전량 가능합니다")
    b = eng.reply(rid, "전량 가능합니다")
    assert a["ignored"] is False and b["ignored"] is True
    assert len(store.list_replies(rid)) == 1 and len(fake.calls) == 1
    assert len(store.list_judgments(cid)) == 1
    assert store.get_case(cid)["status"] == "승인 대기"
    assert statuses(store, cid).count("승인 대기") == 1


def test_기준일을_뒤로_돌리면_거절(store):
    eng, _, _ = seeded(store, ACCEPT)
    d0 = store.get_clock()
    eng.advance(d0 + timedelta(days=3))
    with pytest.raises(ValueError):
        eng.advance(d0 + timedelta(days=1))
    assert store.get_clock() == d0 + timedelta(days=3)


def test_AI가_실패해도_상태는_안바뀌고_사람확인(store):
    eng, _, cid = seeded(store, RuntimeError("연결 끊김"), ACCEPT)
    rid = store.list_requests(cid)[0]["id"]
    r = eng.reply(rid, "전량 가능합니다")
    assert r["needs_human"] is True and r["ignored"] is False and r["status"] == "회신 대기"
    assert store.get_case(cid)["status"] == "회신 대기"
    assert store.get_request(rid)["status"] == "사람 확인"
    j = store.list_judgments(cid)[0]
    assert j["needs_human"] is True and j["result"]["raw"] == "RuntimeError"
    assert [(t["dept"], t["title"]) for t in store.list_tasks(cid)] == [("캠페인 담당", "회신 사람 확인")]
    # 다시 회신이 오면 처리한다(사람 확인 상태는 처리 끝이 아님)
    r2 = eng.reply(rid, "전량 가능합니다")
    assert r2["needs_human"] is False and r2["status"] == "승인 대기"


def test_운영모드에서는_advance_불가(store):
    eng, _, _ = seeded(store, ACCEPT)
    store.set_mode(MODE_OPERATION)
    with pytest.raises(PermissionError):
        eng.advance(store.get_clock() + timedelta(days=1))
    with pytest.raises(PermissionError):
        eng.seed("scenario_1")


def test_시연파일에_없는_기안ID면_오류(store, tmp_path):
    demo = tmp_path / "demo"
    demo.mkdir()
    shutil.copy(config.demo_dir() / "people.json", demo / "people.json")
    (demo / "bad.json").write_text(json.dumps({"title": "t", "description": "d", "plans": ["PLAN-999"],
                                                "contracts": [], "requests": [], "script": []}), encoding="utf-8")
    keep = store.create_case("기안", "남아야 함", {}, "회신 대기")
    eng = Engine(store, provider=FakeProvider([]), demo_dir=demo)
    with pytest.raises(ValueError, match="PLAN-999"):
        eng.seed("bad")
    assert store.get_case(keep)["ref_id"] == "남아야 함"  # 검증이 먼저라 초기화하지 않았다


def test_화면등록_기안은_물량_추정불가(store):
    store.add_plan({"plan_id": "NEW-1", "campaign_id": "CMP-0005", "influencer_id": "INF-002", "channel": "자사몰",
                    "requested_budget_krw": 3000000, "expected_gmv_krw": 30000000,
                    "settlement_date": "2026-10-01", "contract_deadline": "2026-09-25"}, "캠페인 담당자", origin="화면")
    eng, _ = make(store, ACCEPT)
    cid = eng.open_plan("NEW-1")
    f = store.get_case(cid)["facts"]
    assert f["volume"]["units"] is None and f["volume"]["note"] == "추정 불가 — 담당자 입력 필요"
    assert f["allocation"] == "보류"
    assert f["plan_total_krw"] == 3000000 and f["approvers"] == ["마케팅팀"]
    assert ("캠페인 담당", "물량 입력") in [(t["dept"], t["title"]) for t in store.list_tasks(cid)]
    rid = store.list_requests(cid)[0]["id"]
    assert "추정 불가" in store.get_request(rid)["text"]
    eng.reply(rid, "가능합니다")
    assert store.get_case(cid)["facts"]["allocation"] == "보류"  # 입력 전에는 할당 판정 보류


def test_AI판정은_ai_judgments에_비용은_ai_calls에(store):
    provider = BudgetedProvider(FakeProvider([ACCEPT], model="claude-haiku-5-5"), store)
    eng = Engine(store, provider=provider)
    cid = eng.seed("scenario_1")[0]
    eng.reply(store.list_requests(cid)[0]["id"], "전량 가능합니다")
    js = store.list_judgments(cid)
    assert len(js) == 1 and js[0]["kind"] == "회신해석" and js[0]["model"] == "claude-haiku-5-5"
    assert js[0]["result"]["stance"] == "수용" and js[0]["confidence"] == 0.9
    calls = store.ai_calls()
    assert len(calls) == 1 and calls[0]["model"] == "claude-haiku-5-5" and calls[0]["state"] == "정산"
    assert "수용" not in calls[0]["summary"]


# ---- 추가: 제공자·기한·권한 이동·캘린더·리뷰·반품 ----

def test_제공자를_안주면_작업별로_저장소_장부와_만든다(store, monkeypatch):
    made = []

    def fake_make(task, ledger=None):
        made.append((task, ledger))
        return FakeProvider([ACCEPT])

    monkeypatch.setattr(flow, "make_provider", fake_make)
    eng = Engine(store)
    cid = eng.seed("scenario_1")[0]
    eng.reply(store.list_requests(cid)[0]["id"], "전량 가능합니다")
    assert made == [("reply", store)]


def test_기한_전_조기경고는_남은_승인권자_본인에게_한번만(store):
    eng, _, cid = seeded(store, ACCEPT)
    eng.play(steps()[0])
    early = policy.get("deadline.early_warning_days")
    deadline = date.fromisoformat(_decide_by(store.get_case(cid)["facts"])[0])  # 결재 기한(확정 기한과 1차 집행일 중 이른 날)
    buffer = policy.get("deadline.buffer_days")
    run = deadline - timedelta(days=buffer)  # 기본 거부 실행일: 조기 경고 창은 여기서 센다
    acts = eng.advance(run - timedelta(days=early))
    assert [a["action"] for a in acts] == ["조기경고"] and acts[0]["targets"] == ["Masil 대표"]
    eng.advance(run - timedelta(days=1))
    assert len(store.events(cid, kind="조기경고")) == 1
    assert [x["case_id"] for x in eng.todo("Masil 대표")["기한 임박"]] == [cid]
    assert eng.todo("그룹 CEO")["기한 임박"] == []  # 상급자에게는 가지 않는다(사용자 결정 2026-11-12)
    assert [x["case_id"] for x in eng.todo("Masil 대표")["승인 대기"]] == [cid]
    assert store.get_case(cid)["status"] == "승인 대기"


def test_기한까지_승인이_없으면_기본거부_확정보류(store):
    eng, _, cid = seeded(store, ACCEPT)
    eng.play(steps()[0])
    deadline = date.fromisoformat(store.get_case(cid)["facts"]["deadline"])
    acts = eng.advance(deadline)
    assert "기본거부" in [a["action"] for a in acts]
    assert store.get_case(cid)["status"] == "확정 보류"
    assert statuses(store, cid)[-2:] == ["기본 거부", "확정 보류"]
    assert ("캠페인 담당", "확정 보류(철회) 처리") in [(t["dept"], t["title"]) for t in store.list_tasks(cid)]
    after = eng.decide(cid, "Masil 대표", "승인")  # 끝난 건은 상태 그대로
    assert after["changed"] is False and after["status"] == "확정 보류"
    eng.advance(deadline + timedelta(days=2))
    assert len(store.events(cid, kind="상태변경")) == len(statuses(store, cid))  # 다시 처리하지 않음
    assert statuses(store, cid).count("기본 거부") == 1


def test_정책이_바뀌어_결재권자가_바뀌면_권한이동을_남긴다(store):
    eng, _, cid = seeded(store, ACCEPT)
    store.change_policy("approval.total_limit_krw", 1000000000, "관리자", "시험")
    eng.advance(store.get_clock() + timedelta(days=1))
    ch = store.get_approver_changes(cid)
    assert len(ch) == 1 and ch[0].before == ("Masil 대표", "그룹 보고") and ch[0].after == ("마케팅팀",)
    assert store.get_case(cid)["facts"]["approvers"] == ["마케팅팀"]
    assert [x["case_id"] for x in eng.todo("Masil 대표")["권한 이동"]] == [cid]
    eng.advance(store.get_clock() + timedelta(days=1))
    assert len(store.get_approver_changes(cid)) == 1  # 같은 변경을 다시 남기지 않음


def test_회신대기_중에는_승인할_수_없고_거절은_가능(store):
    eng, _, cid = seeded(store, ACCEPT)
    with pytest.raises(ValueError, match="회신"):
        eng.decide(cid, "Masil 대표", "승인")
    assert store.get_case(cid)["status"] == "회신 대기"
    r = eng.decide(cid, "Masil 대표", "거절", "보류 판단")
    # 최종 수정 L2: 거절된 기안도 기본 거부와 같이 캠페인 담당의 '확정 보류(철회) 처리' 작업이 생긴다(상대측에 알릴 일이 같음)
    assert r["status"] == "거절" and [(t["dept"], t["title"]) for t in store.list_tasks(cid)] == [("캠페인 담당", "확정 보류(철회) 처리")]


def test_분할승인은_분할안이_있어야_하고_있으면_2차_잠금(store):
    eng, _, cid = seeded(store, ACCEPT)
    eng.play(steps()[0])
    with pytest.raises(ValueError, match="분할안"):
        eng.decide(cid, "Masil 대표", "분할승인")
    f = store.get_case(cid)["facts"]
    d1 = date.fromisoformat(f["settlement_date"])
    f["split"] = {"phase1_qty": 100, "phase1_date": d1.isoformat(), "phase2_qty": 50,
                  "phase2_date": (d1 + timedelta(days=30)).isoformat()}
    store.update_facts(cid, f, "시험", "분할안")
    r = eng.decide(cid, "Masil 대표", "분할승인")
    assert r["status"] == "2차 잠금"
    assert statuses(store, cid)[-3:] == ["분할 승인", "1차 집행", "2차 잠금"]
    f = store.get_case(cid)["facts"]
    assert f["phase1"]["qty"] == 100 and f["phase2"]["qty"] == 50
    assert any("100" in t["detail"] for t in store.list_tasks(cid) if t["title"] == "물류 출고")


@pytest.mark.usefixtures("legacy_scenes")
def test_캘린더에_기한_집행일_하회구간(store):
    eng, _, cid = seeded(store, ACCEPT)
    cal = eng.calendar()
    kinds = {(e["kind"], e["date"]) for e in cal}
    assert ("확정 기한", "2026-09-11") in kinds and ("집행일", "2026-09-14") in kinds
    win = [e for e in cal if e["kind"] == "하회 구간"]
    assert [(e["date"], e["end"]) for e in win] == [("2026-07-21", "2026-08-22")]
    dl = next(e for e in cal if e["kind"] == "확정 기한")
    assert dl["case_id"] == cid and dl["roles"] == ["Masil 대표"]
    assert [e["date"] for e in cal] == sorted(e["date"] for e in cal)


def test_리뷰_색상불일치면_콘텐츠_수정_요청과_첨부필수(store):
    eng, _, cid = seeded(store, ACCEPT, ACCEPT, COLOR, HAPPY, ACCEPT, ACCEPT)
    eng.run_script("scenario_1")
    g = eng.add_reviews(cid, [("선케어", "영상에서 본 색이랑 실제 색이 달라요"), ("선케어", "만족해요")])
    assert g.open is False and "콘텐츠 수정 요청" in g.actions
    assert len(store.list_reviews(cid)) == 2
    assert [j["kind"] for j in store.list_judgments(cid)].count("리뷰해석") == 2
    req = [r for r in store.list_requests(cid) if r["purpose"] == "콘텐츠 수정"]
    assert len(req) == 1 and req[0]["dept"] == "캠페인 담당" and req[0]["attach_required"] is True
    # 첨부 없이 완료라고만 하면 사람 확인
    r = eng.reply(req[0]["id"], "수정했습니다", attachments=0)
    assert r["needs_human"] is True and store.get_case(cid)["facts"].get("content_fix_confirmed") is not True
    r = eng.reply(req[0]["id"], "수정본과 원본 비교 자료 첨부합니다", attachments=2)
    assert r["needs_human"] is False and store.get_case(cid)["facts"]["content_fix_confirmed"] is True


def test_모의_반품은_사실에_쌓이고_2차가_없으면_열리지_않는다(store):
    eng, _, cid = seeded(store, ACCEPT, ACCEPT)
    eng.run_script("scenario_1")
    g = eng.add_returns(cid, 10, 5)
    assert g.open is False and "2차 집행 없음" in g.reasons
    assert store.get_case(cid)["facts"]["returns"]["change_of_mind"] == 10
    assert store.get_case(cid)["status"] == "1차 집행"


def test_2차_잠금에서_반품률이_기준을_넘으면_자동_보류(store):
    eng, _, cid = seeded(store, ACCEPT)
    f = store.get_case(cid)["facts"]
    today = store.get_clock()
    f["phase1"] = {"qty": 3000, "date": today.isoformat()}
    f["phase2"] = {"qty": 1000, "date": (today + timedelta(days=40)).isoformat()}
    store.update_facts(cid, f, "시험", "2차 준비")
    store.set_status(cid, "2차 잠금", "시험", "")
    g = eng.add_returns(cid, 0, 600)
    assert g.auto_stopped is True and "2차 자동 보류" in g.actions
    assert store.get_case(cid)["status"] == "2차 보류"


def test_여러_승인권자는_모두_승인해야_하고_같은_역할의_재승인은_무시(store):
    """하회 구간 안 집행 + 지표 반대 기안(설계 2.3 PLAN-001): CEO·이사회·이사회 의결 → CEO와 이사회가 모두 승인해야 집행."""
    scenarios.register_plan(store, "PLAN-001")
    eng, _ = make(store, ACCEPT)
    cid = eng.open_plan("PLAN-001")
    f = store.get_case(cid)["facts"]
    assert f["approvers"] == ["CEO", "이사회", "이사회 의결"] and f["indicator_good"] is False
    eng.reply(store.list_requests(cid)[0]["id"], "가능합니다")
    r = eng.decide(cid, "그룹 CEO", "승인")
    assert r["status"] == "승인 대기" and r["pending"] == ["이사회"]
    again = eng.decide(cid, "그룹 CEO", "승인")
    assert again["changed"] is False and len(store.list_approvals(cid)) == 1
    assert store.list_tasks(cid) == []
    assert eng.decide(cid, "이사회", "승인")["status"] == "1차 집행"
    assert len(store.list_tasks(cid)) == 3


def test_AI판정은_같은_호출의_비용_행을_가리킨다(store):
    provider = BudgetedProvider(FakeProvider([ACCEPT], model="claude-haiku-5-5"), store)
    eng = Engine(store, provider=provider)
    cid = eng.seed("scenario_1")[0]
    eng.reply(store.list_requests(cid)[0]["id"], "전량 가능합니다")
    assert store.list_judgments(cid)[0]["ledger_id"] == store.ai_calls()[0]["id"]


def test_가짜_AI면_비용_행이_없다(store):
    eng, _, cid = seeded(store, ACCEPT)
    eng.reply(store.list_requests(cid)[0]["id"], "전량 가능합니다")
    assert store.list_judgments(cid)[0]["ledger_id"] is None


def test_지표_반대_판정은_기안별_빨강만_쓴다(store):
    eng, _, cid = seeded(store, ACCEPT)
    f = store.get_case(cid)["facts"]
    assert f["indicator_good"] is True and f["indicator_excluded"] == ["forecast_gap"]
    assert "forecast_gap" not in [h["rule_id"] for h in f["indicator_hits"]]
    scenarios.register_plan(store, "PLAN-001")
    f2 = store.get_case(eng.open_plan("PLAN-001"))["facts"]
    assert f2["indicator_good"] is False and "indicator_opposite" in [h["rule_id"] for h in f2["approver_hits"]]
    assert [h["rule_id"] for h in f2["indicator_hits"]] == ["coupon_stacking", "slow_payment_channel",
                                                            "spend_concentration"]


# ---- 수정 회차 1: 등록부가 원천(I1), 재판정 뒤 확정(I2), 동시성(M1), 역할 이름(M4), 경고 대상(M5) ----

def _plan001_partly_approved(store):
    scenarios.register_plan(store, "PLAN-001")
    eng, _ = make(store, ACCEPT)
    cid = eng.open_plan("PLAN-001")
    eng.reply(store.list_requests(cid)[0]["id"], "가능합니다")
    eng.decide(cid, "그룹 CEO", "승인")
    return eng, cid


def test_등록부에서_집행일을_바꾸면_사실_이유문장_기한_승인권자가_새값으로(store):
    """재현: PLAN-001 집행일 7/27→9/30, 기한 7/17→9/25. 하회 구간 밖이 되어 Masil 대표 + 그룹 보고 + 그룹 확인."""
    eng, cid = _plan001_partly_approved(store)
    eng.update_plan("PLAN-001", {"settlement_date": "2026-09-30", "contract_deadline": "2026-09-25"}, "캠페인 담당자")
    c = store.get_case(cid)
    f = c["facts"]
    assert f["settlement_date"] == "2026-09-30" and f["deadline"] == "2026-09-25"
    assert f["approvers"] == ["Masil 대표", "그룹 보고", "그룹 확인"]
    reason = store.get_approver_changes(cid)[-1].reason
    assert reason.startswith("집행일 9/30 기준으로") and "7/27 기준" not in reason
    new_part, old_part = reason.split("더는 적용되지 않는 근거:")
    assert "7/27" not in new_part and "7/27" in old_part  # 옛 날짜는 해제된 근거로만
    # 이미 받은 승인은 무효, 재승인 대기. 이전 승인자(CEO)에게 무엇이 바뀌었는지 알림
    assert c["status"] == "재승인 대기" and f["approved_roles"] == []
    note = store.events(cid, kind="재승인알림")
    assert [e["detail"]["target"] for e in note] == ["CEO"]
    assert "집행일 7/27→9/30" in note[0]["detail"]["text"]
    assert [x["case_id"] for x in eng.todo("그룹 CEO")["알림"]] == [cid]
    # 옛 기한(7/17)에는 기본 거부가 일어나지 않는다
    eng.advance(date(2026, 7, 17))
    assert store.get_case(cid)["status"] == "재승인 대기"
    assert [x["case_id"] for x in eng.todo("Masil 대표")["승인 대기"]] == [cid]
    with pytest.raises(PermissionError):
        eng.decide(cid, "그룹 CEO", "승인")  # 더는 승인권자가 아님
    assert eng.decide(cid, "Masil 대표", "승인")["pending"] == ["그룹"]
    assert eng.decide(cid, "그룹 재무", "승인")["status"] == "1차 집행"
    assert {t["due"] for t in store.list_tasks(cid)} == {"2026-09-30"}


def test_새_기한에_기본거부된다(store):
    eng, cid = _plan001_partly_approved(store)
    eng.update_plan("PLAN-001", {"settlement_date": "2026-09-30", "contract_deadline": "2026-09-25"}, "캠페인 담당자")
    eng.advance(date(2026, 9, 21))  # 새 기한 9/25의 3일 전(9/22)이 기본 거부 실행일
    assert store.get_case(cid)["status"] == "재승인 대기"
    eng.advance(date(2026, 9, 22))
    assert store.get_case(cid)["status"] == "확정 보류"


def test_금액만_바뀌어도_받은_승인은_무효(store):
    eng, cid = _plan001_partly_approved(store)
    amount = store.get_case(cid)["facts"]["amount_krw"]
    eng.update_plan("PLAN-001", {"requested_budget_krw": amount + 1}, "캠페인 담당자")
    c = store.get_case(cid)
    assert c["facts"]["amount_krw"] == amount + 1 and c["status"] == "재승인 대기"
    assert c["facts"]["approvers"] == ["CEO", "이사회", "이사회 의결"]  # 구성은 그대로
    assert "요청액" in store.events(cid, kind="재승인알림")[0]["detail"]["text"]


@pytest.mark.usefixtures("legacy_scenes")
def test_승인_전_등록부_변경은_사실만_바꾸고_상태는_그대로(store):
    eng, _, cid = seeded(store, ACCEPT)
    eng.update_plan("PLAN-019", {"settlement_date": "2026-09-20"}, "캠페인 담당자")
    c = store.get_case(cid)
    assert c["facts"]["settlement_date"] == "2026-09-20" and c["status"] == "회신 대기"
    assert store.events(cid, kind="재승인알림") == []


@pytest.mark.usefixtures("legacy_scenes")
def test_끝난_건은_등록부가_바뀌어도_그대로_경고만_한번(store):
    eng, _, cid = seeded(store, ACCEPT, ACCEPT)
    eng.run_script("scenario_1")
    eng.update_plan("PLAN-019", {"settlement_date": "2026-09-20"}, "캠페인 담당자")
    eng.sync()
    eng.advance(store.get_clock() + timedelta(days=1))
    c = store.get_case(cid)
    assert c["status"] == "1차 집행" and c["facts"]["settlement_date"] == "2026-09-14"
    warn = store.events(cid, kind="등록부변경경고")
    assert len(warn) == 1 and "settlement_date" in warn[0]["detail"]["changes"]


@pytest.mark.usefixtures("legacy_scenes")
def test_가져오기로_바뀐_등록부도_다음_점검에서_반영(store):
    eng, _, cid = seeded(store, ACCEPT)
    store.update_plan(store.get_plan("PLAN-019")["id"], {"settlement_date": "2026-09-20"}, "다른 경로")
    eng.check_deadlines()
    assert store.get_case(cid)["facts"]["settlement_date"] == "2026-09-20"


def test_필요한_역할이_모두_승인했으면_재판정에서_바로_확정(store):
    """남은 승인 역할이 없는 승인 대기 사건은 멈추거나 기한에 기본 거부되지 않고 확정된다(I2)."""
    eng, _, cid = seeded(store, ACCEPT)
    eng.play(steps()[0])
    f = store.get_case(cid)["facts"]
    f["approved_roles"] = ["Masil 대표"]  # 승인은 받았는데 확정되지 않은 상태(재판정으로 생길 수 있음)
    store.update_facts(cid, f, "시험", "")
    acts = eng.advance(store.get_clock() + timedelta(days=1))
    assert store.get_case(cid)["status"] == "1차 집행"
    assert "확정" in [a["action"] for a in acts]
    assert len(store.list_tasks(cid)) == 3


def test_동시에_같은_승인을_눌러도_작업은_한번(store):
    import threading
    eng, _, cid = seeded(store, ACCEPT)
    eng.play(steps()[0])
    barrier = threading.Barrier(5)
    errors = []

    def press():
        barrier.wait()
        try:
            eng.decide(cid, "Masil 대표", "승인")
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=press) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [] and len(store.list_tasks(cid)) == 3 and len(store.list_approvals(cid)) == 1


def test_운영모드에서는_역할_이름으로_사람을_대신할_수_없다(store):
    eng, _ = make(store)
    assert eng.role_of("CEO") == "CEO" and eng.role_of("그룹 CEO") == "CEO"
    store.set_mode(MODE_OPERATION)
    assert eng.role_of("그룹 CEO") == "CEO"
    with pytest.raises(PermissionError):
        eng.role_of("CEO")


def test_경고_뒤_승인권자가_바뀌면_새_대상에게_다시_경고(store):
    eng, _, cid = seeded(store, ACCEPT)
    eng.play(steps()[0])
    deadline = date.fromisoformat(_decide_by(store.get_case(cid)["facts"])[0])
    eng.advance(deadline - timedelta(days=policy.get("deadline.early_warning_days")))
    store.change_policy("approval.total_limit_krw", 1000000000, "관리자", "시험")
    acts = eng.advance(store.get_clock() + timedelta(days=1))
    assert [a.get("targets") for a in acts if a["action"] == "조기경고"] == [["마케팅팀"]]
    assert [x["case_id"] for x in eng.todo("마케팅팀장")["기한 임박"]] == [cid]
    assert eng.todo("Masil 대표")["기한 임박"] == []  # 승인권자에서 빠진 역할의 경고는 내려감
