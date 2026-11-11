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
    r = store.import_plans_from_source()
    assert r.added == 25 and r.skipped == []
    plans = store.list_plans()
    assert len(plans) == 25
    p = store.get_plan("PLAN-001")
    assert p["campaign_id"] == "CMP-0003" and p["requested_budget_krw"] == 18962703
    assert p["settlement_date"] == "2026-07-27" and p["contract_deadline"] == "2026-07-17"
    assert p["origin"] == "가져오기" and p["influencer_id"] and p["source_file"].endswith("mkt_budget_plan_ms.csv")


def test_기안을_두번_가져와도_중복없음(store):
    store.import_plans_from_source()
    assert store.import_plans_from_source().added == 0
    assert len(store.list_plans()) == 25


def test_화면에서_고친_기안은_다시_가져와도_유지(store):
    store.import_plans_from_source()
    pid = store.get_plan("PLAN-001")["id"]
    store.update_plan(pid, {"requested_budget_krw": 5}, "담당자")
    assert [x.plan_id for x in store.import_plans_from_source().skipped] == ["PLAN-001"]
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


# ======================= 수정 회차 1 =======================

def _plan_csv(data_copy, plan_id, column, value):
    import csv
    from app.data import loader
    path = data_copy / "02_masil/marketing/mkt_budget_plan_ms.csv"
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    head = lines[0].split("|")
    out = [lines[0]]
    for ln in lines[1:]:
        cells = ln.split("|")
        if cells[0] == plan_id:
            cells[head.index(column)] = str(value)
        out.append("|".join(cells))
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    loader._read.cache_clear()


# ---- 기안 가져오기 결과 ----

def test_기안_가져오기_결과는_추가_갱신_변경없음_건너뜀을_센다(store):
    r = store.import_plans_from_source()
    assert (r.added, r.updated, r.unchanged, r.skipped) == (25, 0, 0, [])
    r2 = store.import_plans_from_source()
    assert (r2.added, r2.updated, r2.unchanged, r2.skipped) == (0, 0, 25, [])


def test_원본이_바뀌면_갱신되고_이벤트에_무엇이_바뀌었는지_남는다(store, data_copy):
    store.import_plans_from_source()
    _plan_csv(data_copy, "PLAN-001", "requested_budget_krw", 777)
    r = store.import_plans_from_source()
    assert (r.added, r.updated, r.unchanged) == (0, 1, 24)
    assert store.get_plan("PLAN-001")["requested_budget_krw"] == 777
    ev = [e for e in store.events(None) if e["kind"] == "기안가져오기"]
    last = ev[-1]["detail"]
    assert last["added"] == 0 and last["updated"] == 1 and last["unchanged"] == 24
    assert last["changes"] == {"PLAN-001": {"requested_budget_krw": {"before": 18962703, "after": 777}}}


def test_화면에서_고친_기안은_건너뛰고_이유와_바뀐_열을_알려준다(store, data_copy):
    store.import_plans_from_source()
    store.update_plan(store.get_plan("PLAN-001")["id"], {"requested_budget_krw": 5}, "담당자")
    _plan_csv(data_copy, "PLAN-001", "expected_gmv_krw", 999)
    r = store.import_plans_from_source()
    assert [s.plan_id for s in r.skipped] == ["PLAN-001"]
    assert "화면" in r.skipped[0].reason and r.skipped[0].source_changed == ["expected_gmv_krw"]
    assert store.get_plan("PLAN-001")["requested_budget_krw"] == 5
    assert r.updated == 0 and r.unchanged == 24


def test_캠페인_마스터에_없는_기안은_경고로_알린다(store, data_copy):
    path = data_copy / "02_masil/master/m_campaign_ms.csv"
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    path.write_text("\n".join(ln for ln in lines if not ln.startswith("CMP-0003|")) + "\n", encoding="utf-8")
    from app.data import loader
    loader._read.cache_clear()
    r = store.import_plans_from_source()
    assert r.added == 25 and any("PLAN-001" in w and "CMP-0003" in w for w in r.warnings)
    assert store.get_plan("PLAN-001")["influencer_id"] is None


def test_계약_원본이_바뀌면_가져오기_이벤트가_남는다(store, tmp_path):
    src = tmp_path / "inf001_exclusive_contract_notice.md"
    text = NOTICE.read_text(encoding="utf-8")
    src.write_text(text, encoding="utf-8")
    cid = store.import_contracts_from_notice(src)[0]
    src.write_text(text.replace("연 28억원", "연 30억원"), encoding="utf-8")
    assert store.import_contracts_from_notice(src)[0] == cid
    assert store.get_contract(cid)["annual_fixed_krw"] == 3_000_000_000
    ev = [e for e in store.events(None) if e["kind"] == "계약가져오기"]
    assert ev[-1]["detail"]["changes"]["annual_fixed_krw"] == {"before": 2_800_000_000, "after": 3_000_000_000}


def test_다른_폴더의_같은_이름_통보문은_다른_계약(store, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    text = NOTICE.read_text(encoding="utf-8")
    (a / "n_exclusive_contract_notice.md").write_text(text, encoding="utf-8")
    (b / "n_exclusive_contract_notice.md").write_text(text.replace("INF-001", "INF-002"), encoding="utf-8")
    assert store.import_contracts_from_notice(a / "n_exclusive_contract_notice.md") != \
        store.import_contracts_from_notice(b / "n_exclusive_contract_notice.md")


# ---- 등록부 값 검증·식별 열 ----

def test_식별_열은_고칠_수_없다(store):
    cid = store.import_contracts_from_notice(NOTICE)[0]
    store.import_plans_from_source()
    pid = store.get_plan("PLAN-001")["id"]
    for col in ("source_doc",):
        with pytest.raises(ValueError):
            store.update_contract(cid, {col: "x"}, "a")
    for col in ("plan_id", "source_file"):
        with pytest.raises(ValueError):
            store.update_plan(pid, {col: "x"}, "a")


def test_등록부_값_형식을_검증한다(store):
    base = {"influencer_code": "INF-V", "influencer_name": "n", "annual_fixed_krw": 1,
            "notice_deadline": "2030-01-01", "expiry_date": "2030-02-01"}
    for bad in ({"annual_fixed_krw": "28억"}, {"annual_fixed_krw": True}, {"annual_fixed_krw": 1.5},
                {"notice_deadline": "내일"}, {"expiry_date": "2030/02/01"}, {"auto_renew": "예"}):
        with pytest.raises(ValueError):
            store.add_contract({**base, **bad}, "a")
    cid = store.add_contract({**base, "notice_deadline": date(2030, 1, 5)}, "a")
    assert store.get_contract(cid)["notice_deadline"] == "2030-01-05"
    with pytest.raises(ValueError):
        store.update_contract(cid, {"annual_fixed_krw": "x"}, "a")
    with pytest.raises(ValueError):
        store.add_plan({"plan_id": "P-V", "requested_budget_krw": "많이"}, "a")
    with pytest.raises(ValueError):
        store.add_plan({"plan_id": "P-V", "settlement_date": "어제"}, "a")


# ---- reset 기록 ----

def test_초기화는_누가_했는지_이벤트로_남긴다(store):
    store.reset("담당자")
    ev = [e for e in store.events(None) if e["kind"] == "초기화"]
    assert ev and ev[-1]["actor"] == "담당자"


# ---- 정산 실패·남은 예약 ----

def test_존재하지_않는_예약을_정산하면_오류(store):
    with pytest.raises(KeyError):
        store.settle(999, "claude-haiku-5-5", 1, 1, 0.1)


def test_정산_실패는_이벤트로_남는다(store):
    store.note_settle_failure(7, RuntimeError("database is locked"))
    ev = [e for e in store.events(None) if e["kind"] == "정산실패"]
    assert ev and ev[-1]["detail"]["reservation_id"] == 7 and "database is locked" in ev[-1]["detail"]["error"]


def test_COMMIT이_실패해도_연결이_갇히지_않는다(store):
    class Wrap:
        def __init__(self, real):
            self.real, self.fail = real, True

        def execute(self, sql, *a):
            if sql == "COMMIT" and self.fail:
                self.fail = False
                raise sqlite3.OperationalError("disk I/O error")
            return self.real.execute(sql, *a)

        def __getattr__(self, name):
            return getattr(self.real, name)

    real = store._db
    store._db = Wrap(real)
    with pytest.raises(sqlite3.OperationalError):
        store.create_case("k", "x", {}, "접수")
    cid = store.create_case("k", "y", {}, "접수")  # 이전 실패가 연결을 막지 않는다
    assert store.get_case(cid)["ref_id"] == "y"
    with pytest.raises(KeyError):
        store.get_case(cid - 1)  # 실패한 쓰기는 반영되지 않았다


def _age(store, rid, seconds):
    from datetime import datetime, timedelta, timezone
    old = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat(timespec="seconds")
    store._db.execute("UPDATE ai_calls SET ts=? WHERE id=?", (old, rid))


def test_예약_조회와_오래된_예약_정리(tmp_path):
    p = tmp_path / "r.db"
    s = open_db(p)
    day = date(2030, 1, 2)
    stale = s.reserve(0.2, day, 1.0, 1.0)
    fresh = s.reserve(0.1, day, 1.0, 1.0)
    _age(s, stale, policy.get("ai.reservation_stale_seconds") + 60)
    pend = s.pending_reservations()
    assert {r["id"] for r in pend} == {stale, fresh} and all(r["created"] for r in pend)
    s.close()
    s2 = open_db(p)  # 다시 열 때 오래된 예약은 '미정산'으로 바뀌어 보인다
    assert [r["id"] for r in s2.pending_reservations()] == [fresh]
    rows = {r["id"]: r for r in s2.ai_calls()}
    assert rows[stale]["state"] == "미정산" and rows[stale]["usd"] == pytest.approx(0.2)
    assert s2.spent(None) == pytest.approx(0.3)  # 예상 비용으로 계속 집계(보수적)
    assert any(e["kind"] == "미정산예약" for e in s2.events(None))
    s2.close()


# ---- 느린 틈에서도 한도를 지키는 동시 호출 ----

class GapLock:
    """락을 놓은 직후 잠깐 쉬는 락: 락을 나눠 잡는 잘못된 구현에서 다른 스레드가 반드시 그 틈에 끼어들게 한다."""

    def __init__(self, inner=None):
        import threading
        self._inner = inner or threading.Lock()

    def __enter__(self):
        self._inner.acquire()
        return self

    def __exit__(self, *exc):
        import time
        self._inner.release()
        time.sleep(0.02)



def _barrier_run(ledger, n, estimate, total_cap):
    import threading
    from app.ai.providers import BudgetExceeded
    barrier = threading.Barrier(n)
    day = date(2030, 1, 2)
    ok = []

    def work():
        barrier.wait()
        try:
            ok.append(ledger.reserve(estimate, day, total_cap, 100.0))
        except BudgetExceeded:
            pass

    threads = [threading.Thread(target=work) for _ in range(n)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    return ok


@pytest.mark.parametrize("kind", ["db", "memory"])
def test_틈이_있어도_동시_예약이_한도를_넘지_않는다(kind, tmp_path, monkeypatch):
    import time
    from app.ai import providers
    from app.ai.providers import MemoryCostLedger
    from app.store import db as dbmod
    orig = providers.check_caps

    def slow(*a, **k):
        orig(*a, **k)
        time.sleep(0.02)  # 확인과 기록 사이에 틈을 만든다

    monkeypatch.setattr(providers, "check_caps", slow)
    monkeypatch.setattr(dbmod, "check_caps", slow)
    ledger = open_db(tmp_path / "s.db") if kind == "db" else MemoryCostLedger()
    ledger._lock = GapLock(ledger._lock)
    ok = _barrier_run(ledger, 20, 0.001, 0.0035)
    assert len(ok) == 3 and ledger.spent(None) <= 0.0035


def test_두_연결도_틈이_있어도_한도를_넘지_않는다(tmp_path, monkeypatch):
    import threading
    import time
    from app.ai import providers
    from app.ai.providers import BudgetExceeded
    from app.store import db as dbmod
    orig = providers.check_caps

    def slow(*a, **k):
        orig(*a, **k)
        time.sleep(0.02)

    monkeypatch.setattr(dbmod, "check_caps", slow)
    p = tmp_path / "two2.db"
    stores = [open_db(p), open_db(p)]
    barrier = threading.Barrier(20)
    ok = []

    def work(i):
        barrier.wait()
        try:
            ok.append(stores[i % 2].reserve(0.001, date(2030, 1, 2), 0.0035, 100.0))
        except BudgetExceeded:
            pass

    threads = [threading.Thread(target=work, args=(i,)) for i in range(20)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(ok) == 3
    [s.close() for s in stores]


def test_저장된_정책이_무효가_되어도_저장소는_열린다(tmp_path):
    p = tmp_path / "bad.db"
    s = open_db(p)
    s.change_policy("deadline.early_warning_days", 9, "a", "r")
    s._db.execute("UPDATE policy_changes SET after='-5'")  # 나중에 무효가 된 값
    s.close()
    s2 = open_db(p)
    assert policy.get("deadline.early_warning_days") != -5
    assert any(e["kind"] == "정책덮어쓰기무시" for e in s2.events(None))
    s2.close()


def test_무효_정책_덮어쓰기_경고는_같은_이력당_한_번만(tmp_path):
    p = tmp_path / "bad2.db"
    s = open_db(p)
    s.change_policy("deadline.early_warning_days", 9, "a", "r")
    s._db.execute("UPDATE policy_changes SET after='-5'")
    s.close()
    for _ in range(3):
        open_db(p).close()
    s3 = open_db(p)
    assert len([e for e in s3.events(None) if e["kind"] == "정책덮어쓰기무시"]) == 1
    s3.close()
