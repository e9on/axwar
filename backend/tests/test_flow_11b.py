"""시연 장면 2·3 전체 흐름(Task 11b). 장면 값은 시연 파일(backend/demo)에, 설계 8장 숫자는 이 테스트에만 둔다.

Provider는 FakeProvider로 응답을 순서대로 고정한다(회신·리뷰·통보 초안 순서가 대본 순서와 같다).
"""
import json
from datetime import date, timedelta

import pytest

from app import policy
from app.ai.providers import FakeProvider
from app.calc import inventory, volume
from app.calc.campaign import return_count_rate
from app.engine import scenarios
from app.engine.flow import Engine
from app.rules.split import return_stop_threshold
from app.store.db import open_db


def _j(**kw):
    base = {"stance": "수용", "qty_limit": None, "next_date": None, "needs_human": False, "confidence": 0.9}
    base.update(kw)
    return json.dumps(base, ensure_ascii=False)


ACCEPT = _j()
SCM_PART = _j(stance="조건부수용", qty_limit=3000)
SCM_FULL = _j()
SCM_REFUSE = _j(stance="거절", qty_limit=0, needs_human=True)
SCM_VAGUE = _j(stance="조건부수용", qty_limit=None)
LACK = _j(stance="정보부족", needs_human=True)
COLOR = json.dumps({"reason": "색상불일치", "sentiment": "부정", "content_gap": True, "confidence": 0.9},
                   ensure_ascii=False)
HAPPY = json.dumps({"reason": "만족", "sentiment": "긍정", "content_gap": False, "confidence": 0.9},
                   ensure_ascii=False)
REVIEWS = [COLOR] * 3 + [HAPPY] * 7  # 장면 2 대본의 리뷰 10건(색상불일치 3건)
NOTICE = "조건변경 통보 초안입니다. 성과 피 기준은 공제 후 순액으로 바꾸는 안을 제안드립니다."

EXPIRY = date(2026, 8, 31)  # 설계 2.1: 혜인 계약 만료


@pytest.fixture
def store(tmp_path):
    s = open_db(tmp_path / "t.db")
    yield s
    s.close()


def make(store, *responses):
    fake = FakeProvider(list(responses))
    return Engine(store, provider=fake), fake


def steps(name):
    return scenarios.load(name).script


def statuses(store, cid):
    return [e["detail"]["to"] for e in store.events(cid, kind="상태변경")]


def scm_request(store, cid):
    return [r for r in store.list_requests(cid) if r["dept"] == "SCM"][0]


def tasks(store, cid):
    return [(t["dept"], t["title"]) for t in store.list_tasks(cid)]


def scene2(store, *responses, name="scenario_2"):
    eng, fake = make(store, *responses)
    cid = eng.seed(name)[0]
    return eng, fake, cid, steps(name)


def to_scm_reply(eng, store, cid, st, text):
    """물류 회신 + 첫 분할 승인(CEO·이사회) 뒤 SCM이 text로 답한다."""
    eng.play(st[0]); eng.play(st[1]); eng.play(st[2])
    return eng.reply(scm_request(store, cid)["id"], text)


# ============================================================== 장면 2 — SCM 일부 허용

def test_장면2_조건변경_SCM_일부허용(store):
    eng, fake, cid, st = scene2(store, ACCEPT, SCM_PART, *REVIEWS)
    f = store.get_case(cid)["facts"]
    # 규칙 판정: 집행일 7/27이 하회 구간 → CEO·이사회, 지표 반대(🔴 근거) → 이사회 의결 추가
    assert f["settlement_date"] == "2026-07-27" and f["deadline"] == "2026-07-17"
    assert f["approvers"] == ["CEO", "이사회", "이사회 의결"]
    rule_ids = [h["rule_id"] for h in f["approver_hits"]]
    assert "covenant_window" in rule_ids and "indicator_opposite" in rule_ids
    assert {"coupon_stacking", "slow_payment_channel", "spend_concentration"} <= {h["rule_id"] for h in f["indicator_hits"]}
    # 계약은 등록부에만(사건 없음), 갱신 미확정
    assert store.list_cases("계약") == [] and store.list_contracts()[0]["expiry_date"] == "2026-08-31"

    # ---- 물류 회신 "평소 하루 20,000개, 최대 26,000개" → 7/27 물류는 넉넉, 재고 장부 여유 0 → SCM 요청
    r = eng.play(st[0])
    assert r["needs_human"] is False and r["status"] == "승인 대기"
    f = store.get_case(cid)["facts"]
    s = f["stock"]
    assert (s["stable"], s["maximum"], s["capacity"]) == (20000, 26000, 20000)
    assert abs(s["want"] - 16000) < 10 and s["share"] == s["want"]  # 7/27 혜인 라이브 약 16,000개, 물류 몫 전부
    assert s["want"] < s["capacity"]  # 물류는 넉넉
    assert (s["line"], s["line_stock"], s["safety_min"], s["spare"]) == ("기초", 20185, 48868, 0)  # 설계 4.5 확인값
    assert s["shortage"] is True and s["need"] == s["share"]
    scm = scm_request(store, cid)
    assert scm["purpose"] == "안전재고 사용" and scm["status"] == "대기"
    days = s["need"] / inventory.line_daily_sale("기초")
    assert f"약 {days:.1f}일 일찍 품절" in scm["text"] and "4%" in scm["text"]
    assert [x["case_id"] for x in eng.todo("SCM 담당자")["회신 대기"]] == [cid]
    # 첫 분할안: SCM이 필요한 양을 모두 허용한다고 본 안 — 1차 = 물류 몫, 2차 = 나머지, 2차 집행일 8/24
    sp = f["split"]
    assert sp["phase1_qty"] == s["share"] and sp["phase1_date"] == "2026-07-27" and sp["phase2_date"] == "2026-08-24"
    assert sp["phase1_qty"] + sp["phase2_qty"] == f["volume"]["units"]

    # ---- 승인권자가 먼저 분할 승인(SCM 회신을 기다리는 동안 확정은 보류)
    assert eng.play(st[1])["status"] == "승인 대기"
    r = eng.play(st[2])
    assert r["changed"] is True and r["status"] == "승인 대기" and r["waiting_for"] == ["SCM 회신"]
    assert store.get_case(cid)["facts"]["phase1"] is None
    assert [t for t in tasks(store, cid) if t[0] in ("물류", "CS")] == []  # 출고·CS 작업은 확정 뒤에

    # ---- SCM "3,000개까지 허용" → 1차 3,000 → 분할안이 달라져 재승인 대기
    r = eng.play(st[3])
    assert r["status"] == "재승인 대기" and r["needs_human"] is False
    f = store.get_case(cid)["facts"]
    assert f["split"]["phase1_qty"] == 3000 and f["split"]["phase1_date"] == "2026-07-27"
    assert f["split"]["phase2_qty"] == f["volume"]["units"] - 3000 and f["split"]["phase2_date"] == "2026-08-24"
    assert f["scm"]["state"] == "일부 허용" and f["scm"]["allow"] == 3000
    assert f["approved_roles"] == []
    alerts = [e["detail"]["text"] for e in store.events(cid, kind="재승인알림")]
    assert len(alerts) == 2 and all("SCM 일부 허용 3,000개" in a and "분할안 변경" in a for a in alerts)
    assert [x["case_id"] for x in eng.todo("그룹 CEO")["승인 대기"]] == [cid]
    assert "SCM 일부 허용 3,000개" in eng.todo("그룹 CEO")["알림"][0]["text"]
    assert store.get_request(scm["id"])["status"] == "처리됨"

    # ---- CEO·이사회 재승인 → 분할 승인 → 1차 집행 → 2차 잠금
    assert eng.play(st[4])["status"] == "재승인 대기"
    r = eng.play(st[5])
    assert r["status"] == "2차 잠금"
    assert statuses(store, cid) == ["회신 대기", "승인 대기", "재승인 대기", "분할 승인", "1차 집행", "2차 잠금"]
    f = store.get_case(cid)["facts"]
    assert f["phase1"] == {"qty": 3000, "date": "2026-07-27"}
    assert f["phase2"] == {"qty": f["volume"]["units"] - 3000, "date": "2026-08-24"}
    assert sorted(t for t in tasks(store, cid) if t[0] in ("물류", "CS")) == [("CS", "CS 대비"), ("물류", "물류 출고")]
    # 2차 집행일 8/24는 하회 구간(7/21~8/22) 밖 → 2차 승인권자 Masil 대표로 이동, 권한 이동 1건
    ch = store.get_approver_changes(cid)
    assert len(ch) == 1 and ch[0].after[0] == "Masil 대표" and ch[0].before == ("CEO", "이사회", "이사회 의결")
    assert ch[0].at == date(2026, 8, 24) and "8/24" in ch[0].reason
    assert f["phase2_approvers"] == ["Masil 대표", "그룹 보고", "그룹 확인"]
    assert f["approvers"] == ["CEO", "이사회", "이사회 의결"]  # 1차 승인권자는 그대로
    assert [x["case_id"] for x in eng.todo("그룹 CEO")["권한 이동"]] == [cid]

    # ---- 캠페인 담당자 공지 → 예약·잠금, 마케팅팀 측정 요청(라이브 전용 코드·검색량)
    r = eng.play(st[6])
    assert r["changed"] is True
    f = store.get_case(cid)["facts"]
    assert f["announce"]["qty"] == 3000 and f["announce"]["reserved"] is True
    assert f["announce"]["overflow_demand"] == f["stock"]["want"] - 3000  # 넘친 수요는 품절, 2차 근거로 기록
    measure = [t for t in store.list_tasks(cid) if t["title"] == "측정 요청"]
    assert len(measure) == 1 and measure[0]["dept"] == "마케팅팀"
    assert "라이브 전용 코드" in measure[0]["detail"] and "검색량" in measure[0]["detail"]
    assert [x["title"] for x in eng.todo("마케팅팀장")["작업"]] == ["측정 요청"]
    # 같은 화면의 다른 부서 영향: 재고 과잉 색조 립·쿠션 → SCM 발주 조정 요청
    orders = [t for t in store.list_tasks(cid) if t["title"] == "발주 조정 요청"]
    assert len(orders) == 2 and all(t["dept"] == "SCM" for t in orders)
    assert sorted(t["detail"].split(" ")[0] for t in orders) == ["SKU-3001", "SKU-3002"]

    # ---- 기준일 8/10: 모의 리뷰 10건 중 색상불일치 3건 → 콘텐츠 수정 요청(첨부 필수), 2차 잠금 유지
    r = eng.play(st[7])
    assert store.get_clock() == date(2026, 8, 10)
    assert store.get_case(cid)["status"] == "2차 잠금"
    f = store.get_case(cid)["facts"]
    assert f["reviews"] == {"total": 10, "color": 3}
    fix = [x for x in store.list_requests(cid) if x["purpose"] == "콘텐츠 수정"]
    assert len(fix) == 1 and fix[0]["dept"] == "캠페인 담당" and fix[0]["attach_required"] is True
    assert "콘텐츠 수정 요청" in r["gate"]["actions"] and r["gate"]["open"] is False

    # ---- 기준일 8/24: 모의 반품 색상불만 = 1차의 5% → 통계 기준(약 4.3%) 초과 → 2차 자동 보류
    r = eng.play(st[8])
    assert store.get_clock() == date(2026, 8, 24)
    base = return_count_rate("INF-001", "색상불만")
    limit = return_stop_threshold(base, 3000)
    assert round(limit, 3) == 0.043 and 150 / 3000 > limit
    assert store.get_case(cid)["status"] == "2차 보류" and r["gate"]["auto_stopped"] is True
    assert "2차 자동 보류" in r["gate"]["actions"]
    assert any("색상불만 반품률 5.0%" in x and "4.3%" in x for x in r["gate"]["reasons"])
    assert not any("단순변심" in x and "초과" in x for x in r["gate"]["reasons"])  # 단순변심은 기준 이내
    assert len(fake.calls) == 12  # 물류·SCM 회신 2 + 리뷰 10


def test_설계_8장_장면2_날짜는_기존_함수_결과와_같다(store):
    """2차 개시일·관찰 종료일은 엔진이 기존 함수로 계산한 값이며 설계 8장 숫자와 같다."""
    eng, _, cid, st = scene2(store, ACCEPT, SCM_PART)
    eng.play(st[0])
    s = store.get_case(cid)["facts"]["split"]
    assert s["phase2_date"] == "2026-08-24"  # max(입고 다음 날 8/20, 하회 구간 끝 다음 날 8/23, 1차 + 28일 8/24)
    assert (date.fromisoformat(s["phase1_date"]) + timedelta(days=policy.get("split.return_observe_days"))
            == date(2026, 8, 24))
    assert inventory.line_restock_date("기초") + timedelta(days=1) == date(2026, 8, 20)
    # 7/27 25건 합계 18,064개 중 혜인 라이브가 약 16,000개 — 설계 4.5 확인값
    day = date(2026, 7, 27)
    assert round(sum(volume.total_daily_load(day, day)[day].values())) == 18064


# ============================================================== 장면 2 — SCM 거절

def run_to_refusal(store, *extra):
    eng, fake, cid, st = scene2(store, ACCEPT, SCM_REFUSE, *extra, name="scenario_2_reject")
    for i in range(4):
        eng.play(st[i])
    return eng, fake, cid, st


def test_장면2_SCM_거절(store):
    eng, fake, cid, st = scene2(store, ACCEPT, SCM_REFUSE, name="scenario_2_reject")
    eng.play(st[0]); eng.play(st[1]); eng.play(st[2])
    approved_split = store.get_case(cid)["facts"]["split"]
    # SCM "거절"은 애매한 회신이 아니라 SCM의 결정이다 → 사람 확인 없이 처리
    r = eng.play(st[3])
    assert r["needs_human"] is False and r["status"] == "재승인 대기"
    f = store.get_case(cid)["facts"]
    assert f["scm"]["state"] == "거절" and f["scm"]["allow"] == 0
    # 1차는 입고 다음 날 8/20으로 연기, 수량은 그대로(물류 몫)
    assert f["phase1_date"] == "2026-08-20" and f["split"]["phase1_date"] == "2026-08-20"
    assert f["split"]["phase1_qty"] == approved_split["phase1_qty"]
    assert f["settlement_date"] == "2026-07-27"  # 등록부 집행일은 그대로 — 연기는 별도 키
    # 8/20도 하회 구간(7/21~8/22) 안이라 승인권자 CEO 유지, 권한 이동 없음
    assert f["approvers"] == ["CEO", "이사회", "이사회 의결"] and store.get_approver_changes(cid) == []
    assert [x["case_id"] for x in eng.todo("그룹 CEO")["승인 대기"]] == [cid]
    assert any("1차 날짜" in e["detail"]["text"] and "SCM 거절" in e["detail"]["text"]
               for e in store.events(cid, kind="재승인알림"))
    # 2차 관찰 끝(8/20 + 28일 = 9/17)이 계약 만료(8/31) 뒤, 갱신 미확정 → 날짜를 정할 수 없다
    assert f["split"]["phase2_date"] is None
    assert any(h["rule_id"] == "split_expiry" for h in f["split"]["hits"])
    end = date.fromisoformat(f["split"]["phase1_date"]) + timedelta(days=policy.get("split.return_observe_days"))
    assert end == date(2026, 9, 17) and end > EXPIRY

    eng.play(st[4])
    eng.play(st[5])
    assert store.get_case(cid)["status"] == "2차 차단"
    assert statuses(store, cid)[-3:] == ["1차 집행", "2차 잠금", "2차 차단"]
    f = store.get_case(cid)["facts"]
    assert f["phase1"]["date"] == "2026-08-20" and f["phase2"]["date"] is None
    assert all(t["due"] == "2026-08-20" for t in store.list_tasks(cid) if t["title"] in ("물류 출고", "CS 대비"))
    g = eng.phase2_status(cid)
    assert g.blocked and not g.open and any("계약 만료 뒤" in x for x in g.reasons)

    # N2: 기준일을 옮겨 점검이 여러 번 돌아도 연기한 1차 날짜가 등록부 값으로 되돌아가지 않는다
    eng.play(st[6])
    assert store.get_clock() == date(2026, 9, 17)
    f = store.get_case(cid)["facts"]
    assert f["phase1_date"] == "2026-08-20" and f["phase1"]["date"] == "2026-08-20" and f["approvers"][0] == "CEO"
    assert store.get_case(cid)["status"] == "2차 차단"
    assert len(fake.calls) == 2


def test_연기한_1차_날짜는_승인_대기_중_점검이_돌아도_유지된다(store):
    eng, _, cid, st = run_to_refusal(store)
    eng.advance(store.get_clock() + timedelta(days=3))  # 재승인 대기 중 점검
    f = store.get_case(cid)["facts"]
    assert f["phase1_date"] == "2026-08-20" and f["settlement_date"] == "2026-07-27"
    assert store.get_case(cid)["status"] == "재승인 대기" and store.events(cid, kind="재승인알림") != []
    assert len(store.events(cid, kind="재승인알림")) == 2  # 점검이 다시 돌아도 알림은 늘지 않는다


def test_등록부_집행일을_고치면_연기는_버려지고_등록부_값이_이긴다(store):
    eng, _, cid, st = run_to_refusal(store)
    eng.update_plan("PLAN-001", {"settlement_date": "2026-09-30", "contract_deadline": "2026-09-25"}, "캠페인 담당자")
    f = store.get_case(cid)["facts"]
    assert f["settlement_date"] == "2026-09-30" and f["phase1_date"] == "2026-09-30" and f["shift"] is None


def test_SCM_거절후_수량만_줄여_진행할_수_없다(store):
    eng, _, cid, _ = run_to_refusal(store)
    before_case = store.get_case(cid)
    before_tasks, before_events = store.list_tasks(cid), len(store.events(cid))
    with pytest.raises(PermissionError, match="SCM"):
        eng.adjust_phase1(cid, "캠페인 담당자", 3000)
    assert store.get_case(cid) == before_case  # 상태·사실 그대로
    assert store.list_tasks(cid) == before_tasks and len(store.events(cid)) == before_events
    # 재승인이 끝난 뒤에도 마찬가지
    eng.decide(cid, "그룹 CEO", "분할승인")
    eng.decide(cid, "이사회", "분할승인")
    with pytest.raises(PermissionError, match="SCM"):
        eng.adjust_phase1(cid, "캠페인 담당자", 3000)
    assert store.get_case(cid)["facts"]["phase1"]["qty"] == before_case["facts"]["split"]["phase1_qty"]


def test_수량_조정은_캠페인_담당만_하고_늘릴_수_없다(store):
    eng, _, cid, st = scene2(store, ACCEPT, SCM_PART)
    eng.play(st[0])
    eng.reply(scm_request(store, cid)["id"], "3,000개까지 허용합니다.")
    with pytest.raises(PermissionError, match="캠페인 담당"):
        eng.adjust_phase1(cid, "그룹 CEO", 2000)
    with pytest.raises(ValueError, match="늘릴 수 없"):
        eng.adjust_phase1(cid, "캠페인 담당자", 3001)
    r = eng.adjust_phase1(cid, "캠페인 담당자", 2000)  # 허용 범위 안에서 줄이는 것은 가능
    assert r["changed"] is True
    f = store.get_case(cid)["facts"]
    assert f["split"]["phase1_qty"] == 2000 and f["split"]["phase2_qty"] == f["volume"]["units"] - 2000


def test_조정으로_분할안이_바뀌면_받은_승인은_무효가_되어_재승인(store):
    eng, _, cid, st = scene2(store, ACCEPT, SCM_PART)
    to_scm_reply(eng, store, cid, st, "3,000개까지 허용합니다.")
    eng.play(st[4])  # CEO 재승인
    assert store.get_case(cid)["facts"]["approved_roles"] == ["CEO"]
    eng.adjust_phase1(cid, "캠페인 담당자", 2000)
    f = store.get_case(cid)["facts"]
    assert f["approved_roles"] == [] and store.get_case(cid)["status"] == "재승인 대기"
    assert any("2,000" in e["detail"]["text"] for e in store.events(cid, kind="재승인알림"))


def test_확정된_뒤에는_수량을_조정할_수_없다(store):
    eng, _, cid, st = scene2(store, ACCEPT, SCM_PART)
    to_scm_reply(eng, store, cid, st, "3,000개까지 허용합니다.")
    eng.play(st[4]); eng.play(st[5])
    assert store.get_case(cid)["status"] == "2차 잠금"
    with pytest.raises(ValueError, match="승인 전"):
        eng.adjust_phase1(cid, "캠페인 담당자", 2000)


# ============================================================== 장면 2 — 그 밖의 SCM 갈래·재고

def test_재고가_충분하면_SCM에_요청하지_않는다(store):
    eng, _ = make(store, ACCEPT)
    eng.seed("scenario_2")
    scenarios.register_plan(store, "PLAN-002")  # 색조 라인(재고 여유 충분)
    cid = eng.open_plan("PLAN-002")
    r = eng.reply(store.list_requests(cid)[0]["id"], "평소 하루 20,000개, 최대 26,000개")
    f = store.get_case(cid)["facts"]
    assert f["stock"]["shortage"] is False and f["stock"]["spare"] >= f["stock"]["share"]
    assert [x for x in store.list_requests(cid) if x["dept"] == "SCM"] == []
    assert f["split"] is None and f["allocation"] == "전량" and r["status"] == "승인 대기"


def test_처리량_숫자_없는_전량가능_회신은_재고를_보지_않는다(store):
    eng, _ = make(store, ACCEPT)
    cid = eng.seed("scenario_2")[0]
    eng.reply(store.list_requests(cid)[0]["id"], "전량 가능합니다.")
    f = store.get_case(cid)["facts"]
    assert f["stock"] is None and f["split"] is None and f["allocation"] == "전량"
    assert [r for r in store.list_requests(cid) if r["dept"] == "SCM"] == []


def test_물류가_최대만_말하면_85퍼센트를_쓰고_근거를_남긴다(store):
    eng, _ = make(store, ACCEPT)
    cid = eng.seed("scenario_2")[0]
    eng.reply(store.list_requests(cid)[0]["id"], "최대 20,000개까지 가능합니다.")
    s = store.get_case(cid)["facts"]["stock"]
    assert s["stable"] is None and s["maximum"] == 20000 and s["capacity"] == 17000
    assert s["capacity_hits"][0]["rule_id"] == "capacity_fallback" and s["capacity_hits"][0]["badge"] == "가정"


def test_SCM이_전량_허용하면_분할안이_그대로라_재승인_없이_확정(store):
    eng, _, cid, st = scene2(store, ACCEPT, SCM_FULL)
    r = to_scm_reply(eng, store, cid, st, "전량 허용합니다.")
    assert r["status"] == "2차 잠금" and store.events(cid, kind="재승인알림") == []
    f = store.get_case(cid)["facts"]
    assert f["scm"]["state"] == "전량 허용" and f["phase1"]["qty"] == f["split"]["phase1_qty"]


def test_SCM이_수량_없이_애매하게_답하면_사람확인(store):
    eng, _, cid, st = scene2(store, ACCEPT, SCM_VAGUE)
    eng.play(st[0])
    r = eng.reply(scm_request(store, cid)["id"], "검토해 보고 알려드릴게요.")
    assert r["needs_human"] is True and r["changed"] is False
    assert scm_request(store, cid)["status"] == "사람 확인"
    assert ("캠페인 담당", "회신 사람 확인") in tasks(store, cid)
    f = store.get_case(cid)["facts"]
    assert f["scm"]["state"] == "요청" and f["split"]["phase1_qty"] == f["stock"]["share"]


def test_사람확인_상태의_SCM_요청이_남아있으면_승인이_끝나도_확정하지_않는다(store):
    eng, _, cid, st = scene2(store, ACCEPT, SCM_VAGUE)
    r = to_scm_reply(eng, store, cid, st, "검토해 보고 알려드릴게요.")
    assert r["needs_human"] is True
    assert store.get_case(cid)["status"] == "승인 대기" and store.get_case(cid)["facts"]["phase1"] is None


def test_재고_부족_건은_분할승인만_가능(store):
    eng, _, cid, st = scene2(store, ACCEPT)
    eng.play(st[0])
    with pytest.raises(ValueError, match="분할 승인만"):
        eng.decide(cid, "그룹 CEO", "승인")
    assert store.get_case(cid)["facts"]["approved_roles"] == []


def test_공지는_캠페인_담당만_1차_수량으로_고정되고_한번만(store):
    eng, _, cid, st = scene2(store, ACCEPT, SCM_PART)
    to_scm_reply(eng, store, cid, st, "3,000개까지 허용합니다.")
    with pytest.raises(ValueError, match="승인 뒤"):
        eng.announce(cid, "캠페인 담당자")
    eng.play(st[4]); eng.play(st[5])
    with pytest.raises(PermissionError):
        eng.announce(cid, "그룹 CEO")
    with pytest.raises(ValueError, match="1차 수량"):
        eng.announce(cid, "캠페인 담당자", qty=2999)
    assert store.get_case(cid)["facts"].get("announce") is None
    assert eng.announce(cid, "캠페인 담당자", qty=3000)["changed"] is True
    assert eng.announce(cid, "캠페인 담당자")["changed"] is False
    assert len([t for t in store.list_tasks(cid) if t["title"] == "측정 요청"]) == 1


def test_예약할_재고가_모자라면_공지를_막는다(store):
    eng, _, cid, st = scene2(store, ACCEPT, SCM_PART)
    to_scm_reply(eng, store, cid, st, "3,000개까지 허용합니다.")
    eng.play(st[4]); eng.play(st[5])
    f = store.get_case(cid)["facts"]
    f["scm"]["allow"] = 2999  # SCM 허용분이 공지 수량보다 모자라는 상황
    store.update_facts(cid, f, "시험", "허용분 조작")
    with pytest.raises(ValueError, match="예약"):
        eng.announce(cid, "캠페인 담당자")
    assert store.get_case(cid)["facts"].get("announce") is None
    assert [t for t in store.list_tasks(cid) if t["title"] == "측정 요청"] == []


def test_갱신이_확정되면_2차_차단이_풀리고_2차_날짜가_정해진다(store):
    eng, _, cid, st = scene2(store, ACCEPT, SCM_REFUSE, name="scenario_2_reject")
    for i in range(6):
        eng.play(st[i])
    assert store.get_case(cid)["status"] == "2차 차단"
    ccid = eng.open_contract("INF-001")
    eng.decide(ccid, "그룹 CEO", "승인")
    eng.decide(ccid, "이사회", "승인")
    assert store.get_case(ccid)["status"] == "갱신 승인"
    eng.advance(store.get_clock() + timedelta(days=1))
    assert store.get_case(cid)["status"] == "2차 잠금"
    p2 = store.get_case(cid)["facts"]["phase2"]
    assert p2["date"] == "2026-09-17" and p2["qty"] > 0


def test_실행_점검은_갱신_미확정이면_만료_뒤를_막는다(store):
    eng, _, cid, st = scene2(store, ACCEPT)
    assert eng.execution_check("INF-001", date(2026, 8, 31))["allowed"] is True
    out = eng.execution_check("INF-001", date(2026, 9, 1))
    assert out["allowed"] is False and "갱신 미확정" in out["reason"]
    assert eng.execution_check("INF-999", date(2030, 1, 1))["allowed"] is True  # 계약이 등록부에 없으면 막지 않음


# ============================================================== 장면 3

def scene3(store, *responses):
    eng, fake = make(store, *responses)
    ids = eng.seed("scenario_3")
    return eng, fake, ids, steps("scenario_3")


def test_장면3_무승인_기본거부(store):
    eng, fake, ids, st = scene3(store, NOTICE, LACK)
    plans, contract = ids[:3], ids[3]
    c = store.get_case(contract)
    assert [store.get_case(p)["ref_id"] for p in plans] == ["PLAN-001", "PLAN-002", "PLAN-003"]
    assert c["kind"] == "계약" and c["ref_id"] == "INF-001" and c["status"] == "승인 대기"
    assert c["facts"]["approvers"] == ["CEO", "이사회", "이사회 의결"]
    assert c["facts"]["annual_fixed_krw"] == 2800000000 and c["facts"]["deadline"] == "2026-07-17"
    assert c["facts"]["expiry"] == "2026-08-31"
    assert all(store.get_case(p)["facts"]["deadline"] == "2026-07-17" for p in plans)

    # ---- 7/12(D-5): 한 단계 위(이사회)에 조기 경고, CEO 할 일에는 승인 대기가 그대로
    eng.play(st[0])
    assert store.get_clock() == date(2026, 7, 12)
    board = eng.todo("이사회")
    assert sorted(x["ref_id"] for x in board["기한 임박"]) == ["INF-001", "PLAN-001", "PLAN-002", "PLAN-003"]
    ceo = eng.todo("그룹 CEO")
    assert ceo["기한 임박"] == [] and [x["case_id"] for x in ceo["승인 대기"]] == [contract]

    # ---- 7/17: 승인 없음 → 계약 기본 거부 + 통보 초안(AI, 순액 기준) + 계약 담당 '통보 발송' 작업, 기안 3건 확정 보류
    eng.play(st[1])
    assert store.get_clock() == date(2026, 7, 17)
    c = store.get_case(contract)
    assert c["status"] == "통보 초안" and statuses(store, contract) == ["승인 대기", "기본 거부", "통보 초안"]
    assert c["facts"]["notice"]["ok"] is True and c["facts"]["notice"]["text"] == NOTICE
    assert [store.get_case(p)["status"] for p in plans] == ["확정 보류"] * 3
    assert all(("캠페인 담당", "확정 보류(철회) 처리") in tasks(store, p) for p in plans)
    send = [t for t in store.list_tasks(contract) if t["title"] == "통보 발송"]
    assert len(send) == 1 and send[0]["dept"] == "계약 담당" and send[0]["status"] == "대기"
    j = [x for x in store.list_judgments(contract) if x["kind"] == "통보초안"]
    assert len(j) == 1 and j[0]["needs_human"] is False and j[0]["result"]["text"] == NOTICE
    sent_to_ai = fake.calls[0][1]
    assert "공제 후" in sent_to_ai and "2,800,000,000" in sent_to_ai  # 순액 기준 재협상안, 현 계약 고정 피 유지
    assert [x["title"] for x in eng.todo("계약 담당자")["작업"]] == ["통보 발송"]

    # ---- 계약 담당이 발송 → 상대 회신 대기
    r = eng.play(st[2])
    c = store.get_case(contract)
    assert r["changed"] is True and c["status"] == "상대 회신 대기"
    assert [t["status"] for t in store.list_tasks(contract) if t["title"] == "통보 발송"] == ["완료"]
    ask = [q for q in store.list_requests(contract) if q["dept"] == "인플루언서 측"]
    assert len(ask) == 1 and ask[0]["purpose"] == "통보 회신" and ask[0]["text"] == NOTICE

    # ---- 인플루언서 측 "내부 논의 후 회신드리겠습니다" → AI 정보부족 → 사람 확인
    r = eng.play(st[3])
    assert r["needs_human"] is True and r["judgment"]["stance"] == "정보부족"
    c = store.get_case(contract)
    assert c["status"] == "사람 확인"
    assert store.get_request(ask[0]["id"])["status"] == "사람 확인"
    assert ("계약 담당", "회신 사람 확인") in tasks(store, contract)

    # ---- 갱신 미확정이라 8/31 이후 집행(2차 포함)은 차단
    assert eng.execution_check("INF-001", EXPIRY)["allowed"] is True
    out = eng.execution_check("INF-001", EXPIRY + timedelta(days=1))
    assert out["allowed"] is False and out["expiry"] == "2026-08-31" and out["renewal_confirmed"] is False
    assert len(fake.calls) == 2


def test_장면3_기본거부_뒤_다시_점검해도_통보_초안은_한번(store):
    eng, fake, ids, st = scene3(store, NOTICE, NOTICE)
    eng.play(st[0]); eng.play(st[1])
    eng.advance(store.get_clock() + timedelta(days=3))
    eng.check_deadlines()
    assert len(fake.calls) == 1
    assert len([t for t in store.list_tasks(ids[3]) if t["title"] == "통보 발송"]) == 1


def test_통보_초안_AI가_실패하면_직접_작성해야_발송(store):
    eng, _, ids, st = scene3(store, RuntimeError("연결 끊김"))
    eng.play(st[0]); eng.play(st[1])
    c = store.get_case(ids[3])
    assert c["status"] == "통보 초안" and c["facts"]["notice"]["ok"] is False
    assert [x for x in store.list_judgments(ids[3]) if x["kind"] == "통보초안"][0]["needs_human"] is True
    with pytest.raises(ValueError, match="초안"):
        eng.send_notice(ids[3], "계약 담당자")
    assert store.get_case(ids[3])["status"] == "통보 초안"
    r = eng.send_notice(ids[3], "계약 담당자", text="사람이 직접 쓴 통보문")
    assert r["changed"] is True and store.get_case(ids[3])["status"] == "상대 회신 대기"
    assert [q for q in store.list_requests(ids[3]) if q["dept"] == "인플루언서 측"][0]["text"] == "사람이 직접 쓴 통보문"


def test_통보_발송은_계약_담당만_두번_눌러도_한번(store):
    eng, _, ids, st = scene3(store, NOTICE)
    eng.play(st[0]); eng.play(st[1])
    with pytest.raises(PermissionError):
        eng.send_notice(ids[3], "그룹 CEO")
    assert store.get_case(ids[3])["status"] == "통보 초안"
    eng.send_notice(ids[3], "계약 담당자")
    again = eng.send_notice(ids[3], "계약 담당자")
    assert again["changed"] is False
    assert len([q for q in store.list_requests(ids[3]) if q["dept"] == "인플루언서 측"]) == 1


def test_기본거부_전에는_통보문을_발송할_수_없다(store):
    eng, _, ids, st = scene3(store, NOTICE)
    with pytest.raises(ValueError, match="통보 초안"):
        eng.send_notice(ids[3], "계약 담당자")  # 아직 승인 대기


def test_상대가_수용하면_합의로_갱신이_확정되어_차단이_풀린다(store):
    eng, _, ids, st = scene3(store, NOTICE, ACCEPT)
    eng.play(st[0]); eng.play(st[1]); eng.play(st[2])
    ask = [q for q in store.list_requests(ids[3]) if q["dept"] == "인플루언서 측"][0]
    r = eng.reply(ask["id"], "제안을 수용합니다.")
    assert r["needs_human"] is False and store.get_case(ids[3])["status"] == "합의"
    assert eng.execution_check("INF-001", date(2026, 12, 31))["allowed"] is True


def test_승인된_계약은_기한이_지나도_기본거부되지_않는다(store):
    eng, fake, ids, st = scene3(store)
    eng.decide(ids[3], "그룹 CEO", "승인")
    eng.decide(ids[3], "이사회", "승인")
    assert store.get_case(ids[3])["status"] == "갱신 승인"
    eng.advance(date(2026, 7, 20))
    assert store.get_case(ids[3])["status"] == "갱신 승인" and fake.calls == []


def test_필요한_승인이_모였으면_SCM_회신을_기다려도_기한에_기본거부되지_않는다(store):
    eng, _, cid, st = scene2(store, ACCEPT)
    eng.play(st[0]); eng.play(st[1]); eng.play(st[2])  # 승인은 모였고 SCM 응답만 남음
    eng.advance(date(2026, 7, 20))  # 확정 기한(7/17) 지남
    assert store.get_case(cid)["status"] == "승인 대기"
    assert store.get_case(cid)["facts"]["approved_roles"] == ["CEO", "이사회"]


def test_승인이_모자라면_SCM_회신을_받아도_기한에_기본거부된다(store):
    eng, _, cid, st = scene2(store, ACCEPT)
    eng.play(st[0]); eng.play(st[1])  # 이사회 승인 없음
    eng.advance(date(2026, 7, 17))
    assert store.get_case(cid)["status"] == "확정 보류"
