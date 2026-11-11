"""SQLite 저장소 테스트. 모든 DB는 tmp_path 아래에 만든다."""
import sqlite3
from datetime import date, timedelta

import pytest

from app import config, policy
from app.calc.cash import sim_start
from app.rules.models import ApproverChange, RuleHit
from app.store.db import Store, open_db


@pytest.fixture
def store(tmp_path):
    s = open_db(tmp_path / "t.db")
    yield s
    s.close()


# ---- 사건·이벤트 ----

def test_상태를_바꾸면_이벤트가_남는다(store):
    cid = store.create_case("campaign_plan", "PLAN-X", {"amount": 123, "due": date(2030, 1, 2)}, "접수")
    store.set_status(cid, "승인대기", "담당자", "검토 시작")
    assert store.get_case(cid)["status"] == "승인대기"
    ev = store.events(cid)
    assert [e["kind"] for e in ev] == ["사건생성", "상태변경"]
    assert ev[1]["actor"] == "담당자" and ev[1]["detail"] == {"from": "접수", "to": "승인대기", "note": "검토 시작"}


def test_사건_사실은_그대로_저장된다(store):
    cid = store.create_case("k", "r", {"amount": 18962703, "name": "한글"}, "접수")
    c = store.get_case(cid)
    assert c["facts"] == {"amount": 18962703, "name": "한글"} and c["kind"] == "k" and c["ref_id"] == "r"


def test_없는_사건은_KeyError(store):
    with pytest.raises(KeyError):
        store.get_case(999)
    with pytest.raises(KeyError):
        store.set_status(999, "x", "a", "")


def test_작업_요청_회신_리뷰를_저장하고_읽는다(store):
    cid = store.create_case("k", "r", {}, "접수")
    tid = store.add_task(cid, "물류", "출고 확인", date(2030, 3, 4))
    rid = store.add_request(cid, "CS", "문의 현황", True)
    pid = store.add_reply(rid, "가능합니다", 2)
    vid = store.add_review(cid, "립밤", "색이 달라요")
    assert store.list_tasks(cid)[0]["id"] == tid and store.list_tasks(cid)[0]["due"] == "2030-03-04"
    assert store.list_requests(cid)[0]["attach_required"] is True
    assert store.list_replies(rid)[0]["id"] == pid and store.list_replies(rid)[0]["attachments"] == 2
    assert store.list_reviews(cid)[0]["id"] == vid
    assert tid and rid and pid and vid


def test_외래키가_켜져_있다(store):
    with pytest.raises(sqlite3.IntegrityError):
        store.add_task(999, "물류", "x", date(2030, 1, 1))


def test_권한이동_기록을_읽는다(store):
    cid = store.create_case("k", "r", {}, "접수")
    ch = ApproverChange(("마케팅팀",), ("Masil 대표", "그룹 보고"), "금액 변경",
                        (RuleHit("R1", "건별 초과", "정책", "계산"),), date(2030, 1, 2))
    store.add_approver_change(cid, ch)
    assert store.get_approver_changes(cid) == [ch]


def test_스키마_버전과_열린_DB_다시_열기(tmp_path):
    p = tmp_path / "v.db"
    s = open_db(p)
    s.create_case("k", "r", {}, "접수")
    s.close()
    s2 = open_db(p)
    assert s2.schema_version() == 1 and s2.get_case(1)["ref_id"] == "r"
    s2.close()


def test_DB_폴더가_없으면_만든다(tmp_path):
    s = open_db(tmp_path / "a" / "b" / "x.db")
    assert (tmp_path / "a" / "b" / "x.db").exists()
    s.close()


def test_DB_위치_기본값은_환경변수와_backend_var(monkeypatch, tmp_path):
    monkeypatch.setenv("AXWAR_DB", str(tmp_path / "e.db"))
    assert config.db_path() == tmp_path / "e.db"
    monkeypatch.delenv("AXWAR_DB")
    assert config.db_path().parts[-3:] == ("backend", "var", "axwar.db")


# ---- 시계와 모드 ----

def test_시계_기본값은_데이터_기준일(store):
    assert store.get_mode() == "시연"
    assert store.get_clock() == sim_start()
    assert sim_start() == date(2026, 7, 1)  # 현재 데이터 기준일(값은 여기서만 확인)


def test_시연_시계는_앞으로만_간다(store):
    store.set_clock(sim_start() + timedelta(days=3))
    assert store.get_clock() == sim_start() + timedelta(days=3)
    with pytest.raises(ValueError):
        store.set_clock(sim_start())


def test_시계는_다시_열어도_남는다(tmp_path):
    p = tmp_path / "c.db"
    s = open_db(p)
    s.set_clock(sim_start() + timedelta(days=5))
    s.close()
    s2 = open_db(p)
    assert s2.get_clock() == sim_start() + timedelta(days=5)
    s2.close()


def test_운영모드에서는_시계를_못바꾼다(tmp_path):
    fixed = date(2031, 5, 6)
    s = open_db(tmp_path / "o.db", today=lambda: fixed)
    s.set_mode("운영")
    assert s.get_clock() == fixed
    with pytest.raises(PermissionError, match="운영 모드에서는 날짜를 바꿀 수 없음"):
        s.set_clock(fixed + timedelta(days=1))
    with pytest.raises(PermissionError, match="운영 모드에서는 날짜를 바꿀 수 없음"):
        s.reset()
    s.set_mode("시연")
    assert s.get_clock() == sim_start()
    s.close()


def test_모르는_모드는_거절(store):
    with pytest.raises(ValueError):
        store.set_mode("이상한모드")


def test_초기화하면_시연데이터만_비고_시계는_기준일(store):
    cid = store.create_case("k", "r", {}, "접수")
    rid = store.add_request(cid, "CS", "x", False)
    store.add_reply(rid, "답", 0)
    store.add_task(cid, "물류", "t", date(2030, 1, 1))
    store.add_review(cid, "p", "t")
    store.set_clock(sim_start() + timedelta(days=9))
    store.add_ai_call(cid, "review", "claude-haiku-5-5", 10, 5, 0.9)
    store.add_contract({"influencer_code": "INF-T", "influencer_name": "시연", "annual_fixed_krw": 1,
                        "notice_deadline": "2030-01-01", "expiry_date": "2030-02-01"}, "a", origin="시연")
    store.add_contract({"influencer_code": "INF-U", "influencer_name": "화면", "annual_fixed_krw": 2,
                        "notice_deadline": "2030-01-01", "expiry_date": "2030-02-01"}, "a")
    store.import_contracts_from_notice(config.data_root() / "02_masil/marketing/inf001_exclusive_contract_notice.md")
    store.import_plans_from_source()
    store.change_policy("deadline.early_warning_days", 9, "담당자", "시험")
    before = store.spent(None)
    store.reset()
    assert store.get_clock() == sim_start()
    assert store.events(None) != [] and all(e["case_id"] is None for e in store.events(None))
    with pytest.raises(KeyError):
        store.get_case(cid)
    assert store.list_tasks(cid) == [] and store.list_reviews(cid) == []
    codes = {c["influencer_code"] for c in store.list_contracts()}
    assert codes == {"INF-U", "INF-001"}
    assert len(store.list_plans()) == 25
    assert len(store.policy_history()) == 1
    assert store.spent(None) == before


# ---- 등록부와 가져오기 ----

NOTICE = config.data_root() / "02_masil/marketing/inf001_exclusive_contract_notice.md"


def test_전속계약_통보문을_읽는다(store):
    ids = store.import_contracts_from_notice(NOTICE)
    assert len(ids) == 1
    c = store.get_contract(ids[0])
    assert c["influencer_code"] == "INF-001" and c["influencer_name"] == "혜인"
    assert c["annual_fixed_krw"] == 2_800_000_000
    assert c["expiry_date"] == "2026-08-31" and c["notice_deadline"] == "2026-07-17"
    assert c["auto_renew"] is True and c["origin"] == "가져오기" and "성과 피" in c["performance_fee_text"]
    assert c["source_doc"].endswith("inf001_exclusive_contract_notice.md")


def test_통보문을_두번_가져와도_한_건(store):
    store.import_contracts_from_notice(NOTICE)
    store.import_contracts_from_notice(NOTICE)
    assert len(store.list_contracts()) == 1
    assert len(store.import_all_contract_notices()) == 1 and len(store.list_contracts()) == 1


def test_화면에서_고친_계약은_다시_가져와도_유지(store):
    cid = store.import_contracts_from_notice(NOTICE)[0]
    store.update_contract(cid, {"annual_fixed_krw": 1}, "담당자")
    store.import_contracts_from_notice(NOTICE)
    c = store.get_contract(cid)
    assert c["annual_fixed_krw"] == 1 and c["origin"] == "화면"


def test_계약_수정은_허용된_열만_이벤트를_남긴다(store):
    cid = store.import_contracts_from_notice(NOTICE)[0]
    with pytest.raises(ValueError):
        store.update_contract(cid, {"origin": "시연"}, "담당자")
    store.update_contract(cid, {"auto_renew": False}, "담당자")
    ev = [e for e in store.events(None) if e["kind"] == "계약수정"]
    assert ev and ev[-1]["actor"] == "담당자" and ev[-1]["detail"]["changes"]["auto_renew"] == {"before": True, "after": False}


def test_기안을_가져온다(store):
    assert store.import_plans_from_source() == 0
    plans = store.list_plans()
    assert len(plans) == 25
    p = store.get_plan("PLAN-001")
    assert p["campaign_id"] == "CMP-0003" and p["requested_budget_krw"] == 18962703
    assert p["settlement_date"] == "2026-07-27" and p["contract_deadline"] == "2026-07-17"
    assert p["origin"] == "가져오기" and p["influencer_id"] and p["source_file"].endswith("mkt_budget_plan_ms.csv")


def test_기안을_두번_가져와도_중복없음(store):
    store.import_plans_from_source()
    assert store.import_plans_from_source() == 0
    assert len(store.list_plans()) == 25


def test_화면에서_고친_기안은_다시_가져와도_유지(store):
    store.import_plans_from_source()
    pid = store.get_plan("PLAN-001")["id"]
    store.update_plan(pid, {"requested_budget_krw": 5}, "담당자")
    assert store.import_plans_from_source() == 1  # 건너뛴 수
    p = store.get_plan("PLAN-001")
    assert p["requested_budget_krw"] == 5 and p["origin"] == "화면"


def test_화면에서_기안을_등록한다(store):
    pid = store.add_plan({"plan_id": "NEW-1", "campaign_id": "C", "requested_budget_krw": 7,
                          "settlement_date": "2030-01-02", "contract_deadline": "2030-01-01"}, "담당자")
    assert store.get_plan("NEW-1")["id"] == pid and store.get_plan("NEW-1")["origin"] == "화면"
    with pytest.raises(sqlite3.IntegrityError):
        store.add_plan({"plan_id": "NEW-1"}, "담당자")
    assert any(e["kind"] == "기안등록" for e in store.events(None))


# ---- 정책 변경 ----

def test_정책을_바꾸면_이력이_남고_규칙이_새값을_쓴다(store):
    from app.rules.deadline import deadline_actions
    dl = date(2030, 1, 20)
    day = dl - timedelta(days=policy.get("deadline.early_warning_days") + 2)
    assert deadline_actions(dl, day, approved=False) == []
    before = policy.get("deadline.early_warning_days")
    store.change_policy("deadline.early_warning_days", before + 5, "담당자", "여유 필요")
    assert deadline_actions(dl, day, approved=False) == ["조기경고"]
    h = store.policy_history("deadline.early_warning_days")
    assert len(h) == 1 and (h[0]["before"], h[0]["after"], h[0]["actor"], h[0]["reason"]) == (before, before + 5, "담당자", "여유 필요")
    assert h[0]["at"] and "설정 화면 변경" in policy.entry("deadline.early_warning_days")[1]
    assert store.policy_history("split.stop_z") == []


def test_정책_변경은_다시_열면_적용된다(tmp_path):
    p = tmp_path / "p.db"
    s = open_db(p)
    base = policy.get("deadline.early_warning_days")
    s.change_policy("deadline.early_warning_days", base + 2, "a", "r")
    s.close()
    policy.clear_overrides()
    assert policy.get("deadline.early_warning_days") == base
    s2 = open_db(p)
    assert policy.get("deadline.early_warning_days") == base + 2
    s2.close()


def test_잘못된_정책값은_거절(store):
    base = policy.get("deadline.early_warning_days")
    for key, bad in (("deadline.early_warning_days", -1), ("deadline.early_warning_days", "x"),
                     ("ai.effort", " "), ("없는.항목", 1)):
        with pytest.raises(ValueError):
            store.change_policy(key, bad, "a", "r")
    assert store.policy_history() == [] and policy.get("deadline.early_warning_days") == base


def test_정책_파일은_고치지_않는다(store):
    before = policy.DEFAULT_PATH.read_bytes()
    store.change_policy("deadline.early_warning_days", policy.get("deadline.early_warning_days") + 1, "a", "r")
    assert policy.DEFAULT_PATH.read_bytes() == before


# ---- AI 비용 장부 ----

def test_비용장부는_재시작해도_남는다(tmp_path):
    p = tmp_path / "l.db"
    s = open_db(p)
    day = date(2030, 1, 2)
    s.record("claude-haiku-5-5", 1000, 100, 0.00015, day)
    s.close()
    s2 = open_db(p)
    assert s2.spent(None) == pytest.approx(0.00015) and s2.spent(day) == pytest.approx(0.00015)
    assert s2.spent(day + timedelta(days=1)) == 0
    s2.close()


def test_AI_호출_기록_열(store):
    cid = store.create_case("k", "r", {}, "접수")
    store.add_ai_call(cid, "review", "claude-haiku-5-5", 1000, 100, 0.8, summary="색상불일치")
    store.add_ai_call(None, "writer", "claude-haiku-5-5", 10, 10, None)
    rows = store.ai_calls()
    assert rows[0]["case_id"] == cid and rows[0]["confidence"] == 0.8 and rows[0]["summary"] == "색상불일치"
    assert rows[0]["usd"] == pytest.approx(0.00015) and rows[1]["case_id"] is None
    assert rows[0]["ts"] and rows[0]["day"]


def test_예약하고_정산하면_실제_비용만_남는다(store):
    day = date(2030, 1, 2)
    rid = store.reserve(0.5, day, 1.0, 1.0)
    assert store.spent(None) == pytest.approx(0.5)
    store.settle(rid, "claude-haiku-5-5", 1000, 100, 0.00015)
    assert store.spent(None) == pytest.approx(0.00015)
    rid2 = store.reserve(0.5, day, 1.0, 1.0)
    store.release(rid2)
    assert store.spent(None) == pytest.approx(0.00015)


def test_예약이_한도를_넘으면_거절(store):
    from app.ai.providers import BudgetExceeded
    day = date(2030, 1, 2)
    store.reserve(0.6, day, 1.0, 1.0)
    with pytest.raises(BudgetExceeded):
        store.reserve(0.5, day, 1.0, 1.0)
    with pytest.raises(BudgetExceeded):
        store.reserve(0.1, day, 10.0, 0.6)


@pytest.mark.parametrize("kind", ["db", "memory"])
def test_동시호출에도_한도를_넘지_않는다(kind, tmp_path):
    import threading
    from app.ai.providers import BudgetExceeded, MemoryCostLedger
    ledger = open_db(tmp_path / "th.db") if kind == "db" else MemoryCostLedger()
    day = date(2030, 1, 2)
    ok, no = [], []

    def work():
        try:
            ok.append(ledger.reserve(0.001, day, 0.0035, 1.0))
        except BudgetExceeded:
            no.append(1)

    threads = [threading.Thread(target=work) for _ in range(20)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(ok) == 3 and len(no) == 17
    assert ledger.spent(None) <= 0.0035


def test_두_연결이_같은_파일을_써도_한도를_넘지_않는다(tmp_path):
    import threading
    from app.ai.providers import BudgetExceeded
    p = tmp_path / "two.db"
    stores = [open_db(p), open_db(p)]
    day = date(2030, 1, 2)
    ok = []

    def work(i):
        try:
            ok.append(stores[i % 2].reserve(0.001, day, 0.0035, 1.0))
        except BudgetExceeded:
            pass

    threads = [threading.Thread(target=work, args=(i,)) for i in range(20)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(ok) == 3
    [s.close() for s in stores]


def test_예산_제공자가_DB_장부에_기록한다(store):
    from app.ai.providers import BudgetedProvider, Completion

    class Inner:
        model = "claude-haiku-5-5"

        def complete(self, system, user):
            return Completion("ok", 1000, 100, self.model)

    day = date(2030, 1, 2)
    BudgetedProvider(Inner(), store, today=lambda: day).complete("s", "u")
    assert store.spent(day) == pytest.approx(0.00015)
    assert [r["model"] for r in store.ai_calls()] == ["claude-haiku-5-5"]
