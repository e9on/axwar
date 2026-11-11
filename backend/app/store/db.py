"""SQLite 저장소: 사건·작업·회신·리뷰 기록, 계약·기안 등록부, 정책 변경 이력, AI 비용 장부, 운영/시연 시계.

- 연결 하나를 락으로 보호해 여러 스레드가 함께 쓴다. 한도 예약처럼 읽고 쓰는 묶음은 BEGIN IMMEDIATE로 감싸
  같은 파일을 여는 다른 연결(프로세스)과도 겹치지 않게 한다.
- 시연 시계·실행 모드는 settings 테이블에 둔다. reset은 origin="시연" 데이터만 지운다
  (가져오기·화면 등록부, 정책 변경 이력, AI 비용 장부는 지속 데이터라 남는다).
- 날짜는 ISO 문자열로 저장한다.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from app import config, policy
from app.ai.providers import TOKENS_PER_PRICE_UNIT, check_caps, utc_today
from app.calc.cash import sim_start
from app.data import loader
from app.rules.models import ApproverChange, RuleHit

SCHEMA_VERSION = 2
MODE_OPERATION, MODE_DEMO = "운영", "시연"
MODES = (MODE_OPERATION, MODE_DEMO)
ORIGINS = ("가져오기", "화면", "시연")
CLOCK_LOCKED = "운영 모드에서는 날짜를 바꿀 수 없음"
logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE schema_version (version INTEGER NOT NULL);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE cases (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, ref_id TEXT NOT NULL, facts TEXT NOT NULL,
  status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE approvals (
  id INTEGER PRIMARY KEY, case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  approvers TEXT NOT NULL, decision TEXT NOT NULL, actor TEXT NOT NULL, note TEXT NOT NULL, decided_at TEXT NOT NULL);
CREATE TABLE tasks (
  id INTEGER PRIMARY KEY, case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  dept TEXT NOT NULL, title TEXT NOT NULL, due TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE requests (
  id INTEGER PRIMARY KEY, case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  dept TEXT NOT NULL, text TEXT NOT NULL, attach_required INTEGER NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE replies (
  id INTEGER PRIMARY KEY, request_id INTEGER NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
  text TEXT NOT NULL, attachments INTEGER NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE reviews (
  id INTEGER PRIMARY KEY, case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  product TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE approver_changes (
  id INTEGER PRIMARY KEY, case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  before TEXT NOT NULL, after TEXT NOT NULL, reason TEXT NOT NULL, hits TEXT NOT NULL, at TEXT NOT NULL);
CREATE TABLE events (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, sim_date TEXT NOT NULL,
  case_id INTEGER REFERENCES cases(id) ON DELETE CASCADE,
  kind TEXT NOT NULL, actor TEXT NOT NULL, detail TEXT NOT NULL);
CREATE TABLE ai_calls (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, day TEXT NOT NULL,
  case_id INTEGER REFERENCES cases(id) ON DELETE SET NULL,
  kind TEXT NOT NULL, model TEXT NOT NULL, in_tok INTEGER NOT NULL, out_tok INTEGER NOT NULL,
  usd REAL NOT NULL, confidence REAL, summary TEXT NOT NULL, state TEXT NOT NULL);
CREATE TABLE contracts (
  id INTEGER PRIMARY KEY, influencer_code TEXT NOT NULL, influencer_name TEXT NOT NULL,
  annual_fixed_krw INTEGER NOT NULL, performance_fee_text TEXT NOT NULL,
  notice_deadline TEXT NOT NULL, expiry_date TEXT NOT NULL, auto_renew INTEGER NOT NULL,
  source_doc TEXT NOT NULL, origin TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE UNIQUE INDEX contracts_source ON contracts(source_doc) WHERE source_doc != '';
CREATE TABLE plans (
  id INTEGER PRIMARY KEY, plan_id TEXT NOT NULL UNIQUE, campaign_id TEXT, influencer_id TEXT, channel TEXT,
  requested_budget_krw INTEGER, expected_gmv_krw INTEGER, settlement_date TEXT, contract_deadline TEXT,
  raw TEXT NOT NULL, source_file TEXT NOT NULL, origin TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE policy_changes (
  id INTEGER PRIMARY KEY, key TEXT NOT NULL, before TEXT NOT NULL, after TEXT NOT NULL,
  actor TEXT NOT NULL, at TEXT NOT NULL, reason TEXT NOT NULL);
"""



def _migrate_1_to_2(db: sqlite3.Connection) -> None:
    """버전 2: AI 판정 기록(ai_judgments, 비용 장부 행 연결), 요청의 목적·상태, 작업 상세."""
    db.execute("CREATE TABLE ai_judgments ("
               "id INTEGER PRIMARY KEY, ts TEXT NOT NULL, sim_date TEXT NOT NULL, "
               "case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE, "
               "kind TEXT NOT NULL, model TEXT NOT NULL, input_summary TEXT NOT NULL, result TEXT NOT NULL, "
               "needs_human INTEGER NOT NULL, confidence REAL, "
               "ledger_id INTEGER REFERENCES ai_calls(id) ON DELETE SET NULL)")
    db.execute("ALTER TABLE requests ADD COLUMN purpose TEXT NOT NULL DEFAULT ''")
    db.execute("ALTER TABLE requests ADD COLUMN status TEXT NOT NULL DEFAULT '대기'")
    db.execute("ALTER TABLE tasks ADD COLUMN detail TEXT NOT NULL DEFAULT ''")


# 마이그레이션: 버전 N을 N+1로 올리는 함수. 새 DB도 버전 1 스키마를 만든 뒤 차례로 올린다(길을 하나만 둔다).
_MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {1: _migrate_1_to_2}

_CONTRACT_FIELDS = ("influencer_code", "influencer_name", "annual_fixed_krw", "performance_fee_text",
                    "notice_deadline", "expiry_date", "auto_renew", "source_doc")
_PLAN_FIELDS = ("plan_id", "campaign_id", "influencer_id", "channel", "requested_budget_krw", "expected_gmv_krw",
                "settlement_date", "contract_deadline", "source_file")
# 화면에서 고칠 수 있는 열. 식별 열(source_doc, plan_id, source_file)은 뺀다(고치면 다시 가져올 때 중복이 생김).
_CONTRACT_EDITABLE = tuple(f for f in _CONTRACT_FIELDS if f != "source_doc")
_PLAN_EDITABLE = tuple(f for f in _PLAN_FIELDS if f not in ("plan_id", "source_file"))
_BOOL_COLUMNS = {"auto_renew"}
_INT_COLUMNS = {"annual_fixed_krw", "requested_budget_krw", "expected_gmv_krw"}
_DATE_COLUMNS = {"notice_deadline", "expiry_date", "settlement_date", "contract_deadline"}


@dataclass(frozen=True)
class SkippedPlan:
    plan_id: str
    reason: str
    source_changed: list[str]  # 원본 파일 값이 등록부 값과 달라진 열(화면 수정 때문에 반영되지 못함)


@dataclass
class PlanImportResult:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: list[SkippedPlan] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _clean(fields: dict) -> dict:
    """등록부 값 검증: 금액은 정수, 날짜는 ISO 문자열 또는 date, 자동 갱신은 bool. 날짜는 ISO 문자열로 바꿔 돌려준다."""
    out = {}
    for k, v in fields.items():
        if v is None:
            out[k] = v
        elif k in _INT_COLUMNS:
            if isinstance(v, bool) or not isinstance(v, int):
                raise ValueError(f"{k}는 정수여야 함: {v!r}")
            out[k] = v
        elif k in _DATE_COLUMNS:
            try:
                if isinstance(v, date):
                    out[k] = v.isoformat()
                elif isinstance(v, str) and len(v) == len(date.min.isoformat()):
                    out[k] = date.fromisoformat(v).isoformat()
                else:
                    raise ValueError
            except ValueError:
                raise ValueError(f"{k}는 YYYY-MM-DD 날짜여야 함: {v!r}") from None
        elif k in _BOOL_COLUMNS:
            if not isinstance(v, bool):
                raise ValueError(f"{k}는 참/거짓이어야 함: {v!r}")
            out[k] = v
        else:
            out[k] = v
    return out


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=lambda o: o.isoformat() if isinstance(o, date) else str(o))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _db_value(field: str, value):
    return int(value) if field in _BOOL_COLUMNS else value


class Store:
    """저장소. AI 비용 장부(CostLedger)도 겸한다."""

    def __init__(self, path: str | Path, today: Callable[[], date] = date.today):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._today = today
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None, timeout=30)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._migrate()
        self._apply_policy_overrides()
        self._expire_stale_reservations()

    # ---- 기반 ----

    @contextmanager
    def _tx(self):
        """쓰기 묶음: 다른 연결과 겹치지 않게 BEGIN IMMEDIATE."""
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield self._db
                self._db.execute("COMMIT")
            except BaseException:
                try:
                    self._db.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise

    def _all(self, sql: str, *args) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    def _one(self, sql: str, *args):
        with self._lock:
            return self._db.execute(sql, args).fetchone()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _migrate(self) -> None:
        with self._tx() as db:
            has = db.execute("SELECT name FROM sqlite_master WHERE name='schema_version'").fetchone()
            if not has:
                for stmt in _SCHEMA.split(";\n"):
                    if stmt.strip():
                        db.execute(stmt)
                db.execute("INSERT INTO schema_version VALUES (1)")
            version = db.execute("SELECT version FROM schema_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError(f"DB 스키마 버전 {version}이 이 프로그램({SCHEMA_VERSION})보다 새로움")
            while version < SCHEMA_VERSION:
                _MIGRATIONS[version](db)
                version += 1
                db.execute("UPDATE schema_version SET version=?", (version,))

    def schema_version(self) -> int:
        return self._one("SELECT version FROM schema_version")[0]

    def _event(self, db, case_id: int | None, kind: str, actor: str, detail: dict) -> None:
        db.execute("INSERT INTO events (ts, sim_date, case_id, kind, actor, detail) VALUES (?,?,?,?,?,?)",
                   (_now(), self._clock(db).isoformat(), case_id, kind, actor, _json(detail)))

    # ---- 설정·모드·시계 ----

    @staticmethod
    def _setting(db, key: str) -> str | None:
        row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def _mode(self, db) -> str:
        return self._setting(db, "mode") or MODE_DEMO  # 지금은 시연 데이터로 쓰므로 기본은 시연

    def get_mode(self) -> str:
        with self._lock:
            return self._mode(self._db)

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"알 수 없는 실행 모드: {mode!r} ({' 또는 '.join(MODES)})")
        with self._tx() as db:
            db.execute("INSERT INTO settings (key, value) VALUES ('mode', ?) "
                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (mode,))

    def _clock(self, db) -> date:
        if self._mode(db) == MODE_OPERATION:
            return self._today()
        saved = self._setting(db, "demo_clock")
        return date.fromisoformat(saved) if saved else sim_start()

    def get_clock(self) -> date:
        """운영: 실제 오늘. 시연: 저장된 시연 시계(없으면 데이터 기준일 = 자금일보 마지막 날 + 1일)."""
        with self._lock:
            return self._clock(self._db)

    def set_clock(self, d: date) -> None:
        with self._tx() as db:
            if self._mode(db) == MODE_OPERATION:
                raise PermissionError(CLOCK_LOCKED)
            if d < self._clock(db):
                raise ValueError("시연 시계는 뒤로 돌릴 수 없음")
            db.execute("INSERT INTO settings (key, value) VALUES ('demo_clock', ?) "
                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (d.isoformat(),))

    def reset(self, actor: str = "시스템") -> None:
        """시연 데이터(사건·작업·회신·리뷰·사건 이벤트·시연 등록부 행)를 지우고 시계를 기준일로 되돌린다."""
        with self._tx() as db:
            if self._mode(db) == MODE_OPERATION:
                raise PermissionError(CLOCK_LOCKED)
            db.execute("DELETE FROM cases")  # 딸린 작업·요청·회신·리뷰·승인·권한이동·AI 판정·사건 이벤트는 CASCADE
            db.execute("DELETE FROM contracts WHERE origin='시연'")
            db.execute("DELETE FROM plans WHERE origin='시연'")
            db.execute("DELETE FROM settings WHERE key='demo_clock'")
            self._event(db, None, "초기화", actor, {})

    # ---- 사건 ----

    def create_case(self, kind: str, ref_id: str, facts: dict, status: str) -> int:
        with self._tx() as db:
            now = _now()
            cur = db.execute("INSERT INTO cases (kind, ref_id, facts, status, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                             (kind, ref_id, _json(facts), status, now, now))
            self._event(db, cur.lastrowid, "사건생성", "시스템", {"kind": kind, "ref_id": ref_id, "status": status})
            return cur.lastrowid

    def get_case(self, case_id: int) -> dict:
        row = self._one("SELECT * FROM cases WHERE id=?", case_id)
        if row is None:
            raise KeyError(f"없는 사건: {case_id}")
        return {**dict(row), "facts": json.loads(row["facts"])}

    def set_status(self, case_id: int, status: str, actor: str, note: str) -> None:
        with self._tx() as db:
            row = db.execute("SELECT status FROM cases WHERE id=?", (case_id,)).fetchone()
            if row is None:
                raise KeyError(f"없는 사건: {case_id}")
            db.execute("UPDATE cases SET status=?, updated_at=? WHERE id=?", (status, _now(), case_id))
            self._event(db, case_id, "상태변경", actor, {"from": row[0], "to": status, "note": note})

    def add_approval(self, case_id: int, approvers: tuple[str, ...], decision: str, actor: str, note: str = "") -> int:
        with self._tx() as db:
            cur = db.execute("INSERT INTO approvals (case_id, approvers, decision, actor, note, decided_at) VALUES (?,?,?,?,?,?)",
                             (case_id, _json(list(approvers)), decision, actor, note, _now()))
            self._event(db, case_id, "승인기록", actor, {"decision": decision, "approvers": list(approvers)})
            return cur.lastrowid

    def add_task(self, case_id: int, dept: str, title: str, due: date, detail: str = "") -> int:
        with self._tx() as db:
            cur = db.execute("INSERT INTO tasks (case_id, dept, title, due, status, created_at, detail) "
                             "VALUES (?,?,?,?,?,?,?)", (case_id, dept, title, due.isoformat(), "대기", _now(), detail))
            self._event(db, case_id, "작업생성", "시스템",
                        {"dept": dept, "title": title, "due": due.isoformat(), "detail": detail})
            return cur.lastrowid

    def set_task_status(self, task_id: int, status: str, actor: str) -> None:
        """작업 상태를 바꾼다(대기 → 완료 등). 바꾼 사람과 함께 이벤트로 남긴다."""
        with self._tx() as db:
            row = db.execute("SELECT case_id, title FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row is None:
                raise KeyError(f"작업 없음: {task_id}")
            db.execute("UPDATE tasks SET status=? WHERE id=?", (status, task_id))
            self._event(db, row["case_id"], "작업상태", actor,
                        {"task_id": task_id, "title": row["title"], "status": status})

    def all_tasks(self, dept: str | None = None) -> list[dict]:
        """모든 사건의 작업(dept가 있으면 그 부서만)."""
        rows = (self._all("SELECT * FROM tasks ORDER BY id") if dept is None
                else self._all("SELECT * FROM tasks WHERE dept=? ORDER BY id", dept))
        return [dict(r) for r in rows]

    def add_request(self, case_id: int, dept: str, text: str, attach_required: bool, purpose: str = "") -> int:
        with self._tx() as db:
            cur = db.execute("INSERT INTO requests (case_id, dept, text, attach_required, created_at, purpose) "
                             "VALUES (?,?,?,?,?,?)", (case_id, dept, text, int(attach_required), _now(), purpose))
            self._event(db, case_id, "요청생성", "시스템",
                        {"dept": dept, "attach_required": attach_required, "purpose": purpose})
            return cur.lastrowid

    @staticmethod
    def _request_dict(row) -> dict:
        return {**dict(row), "attach_required": bool(row["attach_required"])}

    def get_request(self, request_id: int) -> dict:
        row = self._one("SELECT * FROM requests WHERE id=?", request_id)
        if row is None:
            raise KeyError(f"없는 요청: {request_id}")
        return self._request_dict(row)

    def all_requests(self, dept: str | None = None) -> list[dict]:
        rows = (self._all("SELECT * FROM requests ORDER BY id") if dept is None
                else self._all("SELECT * FROM requests WHERE dept=? ORDER BY id", dept))
        return [self._request_dict(r) for r in rows]

    def set_request_status(self, request_id: int, status: str, actor: str, note: str) -> None:
        with self._tx() as db:
            row = db.execute("SELECT case_id, status FROM requests WHERE id=?", (request_id,)).fetchone()
            if row is None:
                raise KeyError(f"없는 요청: {request_id}")
            db.execute("UPDATE requests SET status=? WHERE id=?", (status, request_id))
            self._event(db, row["case_id"], "요청상태", actor,
                        {"request_id": request_id, "from": row["status"], "to": status, "note": note})

    def update_facts(self, case_id: int, facts: dict, actor: str, note: str) -> None:
        """사건 사실을 통째로 바꾼다. 바뀐 키를 이벤트로 남긴다."""
        with self._tx() as db:
            row = db.execute("SELECT facts FROM cases WHERE id=?", (case_id,)).fetchone()
            if row is None:
                raise KeyError(f"없는 사건: {case_id}")
            old = json.loads(row[0])
            new = json.loads(_json(facts))
            keys = sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k))
            db.execute("UPDATE cases SET facts=?, updated_at=? WHERE id=?", (_json(new), _now(), case_id))
            self._event(db, case_id, "사실변경", actor, {"keys": keys, "note": note})

    def list_cases(self, kind: str | None = None) -> list[dict]:
        rows = (self._all("SELECT * FROM cases ORDER BY id") if kind is None
                else self._all("SELECT * FROM cases WHERE kind=? ORDER BY id", kind))
        return [{**dict(r), "facts": json.loads(r["facts"])} for r in rows]

    def list_approvals(self, case_id: int) -> list[dict]:
        return [{**dict(r), "approvers": json.loads(r["approvers"])}
                for r in self._all("SELECT * FROM approvals WHERE case_id=? ORDER BY id", case_id)]

    # ---- AI 판정 기록(비용 장부 ai_calls와 별개) ----

    def add_judgment(self, case_id: int, kind: str, model: str, input_summary: str, result: dict,
                     needs_human: bool, confidence: float | None, ledger_id: int | None = None) -> int:
        """ledger_id는 같은 호출의 비용 장부(ai_calls) 행. 가짜 AI·실패면 None."""
        with self._tx() as db:
            cur = db.execute("INSERT INTO ai_judgments (ts, sim_date, case_id, kind, model, input_summary, result, "
                             "needs_human, confidence, ledger_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                             (_now(), self._clock(db).isoformat(), case_id, kind, model, input_summary, _json(result),
                              int(needs_human), confidence, ledger_id))
            self._event(db, case_id, "AI판정", "AI",
                        {"judgment_id": cur.lastrowid, "kind": kind, "model": model, "needs_human": needs_human})
            return cur.lastrowid

    def list_judgments(self, case_id: int | None = None) -> list[dict]:
        rows = (self._all("SELECT * FROM ai_judgments ORDER BY id") if case_id is None
                else self._all("SELECT * FROM ai_judgments WHERE case_id=? ORDER BY id", case_id))
        return [{**dict(r), "result": json.loads(r["result"]), "needs_human": bool(r["needs_human"])} for r in rows]

    def add_reply(self, request_id: int, text: str, attachments: int) -> int:
        with self._tx() as db:
            row = db.execute("SELECT case_id FROM requests WHERE id=?", (request_id,)).fetchone()
            if row is None:
                raise KeyError(f"없는 요청: {request_id}")
            cur = db.execute("INSERT INTO replies (request_id, text, attachments, created_at) VALUES (?,?,?,?)",
                             (request_id, text, attachments, _now()))
            self._event(db, row[0], "회신접수", "부서", {"request_id": request_id, "attachments": attachments})
            return cur.lastrowid

    def add_review(self, case_id: int, product: str, text: str) -> int:
        with self._tx() as db:
            cur = db.execute("INSERT INTO reviews (case_id, product, text, created_at) VALUES (?,?,?,?)",
                             (case_id, product, text, _now()))
            self._event(db, case_id, "리뷰접수", "시스템", {"product": product})
            return cur.lastrowid

    def add_approver_change(self, case_id: int, change: ApproverChange) -> None:
        hits = [{"rule_id": h.rule_id, "text": h.text, "source": h.source, "badge": h.badge} for h in change.hits]
        with self._tx() as db:
            db.execute("INSERT INTO approver_changes (case_id, before, after, reason, hits, at) VALUES (?,?,?,?,?,?)",
                       (case_id, _json(list(change.before)), _json(list(change.after)), change.reason, _json(hits),
                        change.at.isoformat()))
            self._event(db, case_id, "권한이동", "시스템",
                        {"before": list(change.before), "after": list(change.after), "reason": change.reason})

    def get_approver_changes(self, case_id: int) -> list[ApproverChange]:
        return [ApproverChange(tuple(json.loads(r["before"])), tuple(json.loads(r["after"])), r["reason"],
                               tuple(RuleHit(**h) for h in json.loads(r["hits"])), date.fromisoformat(r["at"]))
                for r in self._all("SELECT * FROM approver_changes WHERE case_id=? ORDER BY id", case_id)]

    def list_tasks(self, case_id: int) -> list[dict]:
        return [dict(r) for r in self._all("SELECT * FROM tasks WHERE case_id=? ORDER BY id", case_id)]

    def list_requests(self, case_id: int) -> list[dict]:
        return [self._request_dict(r) for r in self._all("SELECT * FROM requests WHERE case_id=? ORDER BY id", case_id)]

    def list_replies(self, request_id: int) -> list[dict]:
        return [dict(r) for r in self._all("SELECT * FROM replies WHERE request_id=? ORDER BY id", request_id)]

    def list_reviews(self, case_id: int) -> list[dict]:
        return [dict(r) for r in self._all("SELECT * FROM reviews WHERE case_id=? ORDER BY id", case_id)]

    def add_event(self, case_id: int | None, kind: str, actor: str, detail: dict) -> None:
        """엔진이 남기는 알림성 이벤트(조기 경고·보고 등)."""
        with self._tx() as db:
            self._event(db, case_id, kind, actor, detail)

    def events(self, case_id: int | None = None, kind: str | None = None) -> list[dict]:
        """case_id가 있으면 그 사건의 이벤트, None이면 전체(사건 없는 등록부·정책 이벤트 포함). kind로 종류를 거른다."""
        sql, args = "SELECT * FROM events WHERE 1=1", []
        if case_id is not None:
            sql, args = sql + " AND case_id=?", [*args, case_id]
        if kind is not None:
            sql, args = sql + " AND kind=?", [*args, kind]
        rows = self._all(sql + " ORDER BY id", *args)
        return [{**dict(r), "detail": json.loads(r["detail"])} for r in rows]

    # ---- 등록부(계약·기안) ----

    @staticmethod
    def _contract_dict(row) -> dict:
        return {**dict(row), "auto_renew": bool(row["auto_renew"])}

    def get_contract(self, contract_id: int) -> dict:
        row = self._one("SELECT * FROM contracts WHERE id=?", contract_id)
        if row is None:
            raise KeyError(f"없는 계약: {contract_id}")
        return self._contract_dict(row)

    def list_contracts(self) -> list[dict]:
        return [self._contract_dict(r) for r in self._all("SELECT * FROM contracts ORDER BY id")]

    def add_contract(self, fields: dict, actor: str, origin: str = "화면") -> int:
        if origin not in ORIGINS:
            raise ValueError(f"알 수 없는 출처 구분: {origin!r}")
        extra = set(fields) - set(_CONTRACT_FIELDS)
        if extra:
            raise ValueError(f"계약에 없는 항목: {sorted(extra)}")
        row = {"performance_fee_text": "", "auto_renew": False, "source_doc": "", **_clean(fields)}
        missing = [f for f in _CONTRACT_FIELDS if f not in row]
        if missing:
            raise ValueError(f"계약 항목 누락: {missing}")
        with self._tx() as db:
            cur = self._insert_contract(db, row, origin)
            self._event(db, None, "계약등록", actor, {"contract_id": cur, "origin": origin,
                                                    "influencer_code": row["influencer_code"]})
            return cur

    @staticmethod
    def _insert_contract(db, row: dict, origin: str) -> int:
        now = _now()
        cur = db.execute(
            f"INSERT INTO contracts ({', '.join(_CONTRACT_FIELDS)}, origin, created_at, updated_at) "
            f"VALUES ({', '.join('?' * len(_CONTRACT_FIELDS))}, ?, ?, ?)",
            (*[_db_value(f, row[f]) for f in _CONTRACT_FIELDS], origin, now, now))
        return cur.lastrowid

    def update_contract(self, contract_id: int, fields: dict, actor: str) -> None:
        self._update_row("contracts", "계약", _CONTRACT_EDITABLE, contract_id, fields, actor, "계약수정")

    def update_plan(self, plan_row_id: int, fields: dict, actor: str) -> None:
        self._update_row("plans", "기안", _PLAN_EDITABLE, plan_row_id, fields, actor, "기안수정")

    def _update_row(self, table: str, label: str, allowed: tuple[str, ...], row_id: int, fields: dict, actor: str,
                    event_kind: str) -> None:
        """허용된 열만 고치고 출처를 "화면"으로 바꾼다(시연 행은 시연 유지). 변경 전후를 이벤트로 남긴다."""
        bad = set(fields) - set(allowed)
        if bad or not fields:
            raise ValueError(f"{label}에서 고칠 수 없는 항목: {sorted(bad) or '(비어 있음)'}")
        fields = _clean(fields)
        with self._tx() as db:
            old = db.execute(f"SELECT * FROM {table} WHERE id=?", (row_id,)).fetchone()
            if old is None:
                raise KeyError(f"없는 {label}: {row_id}")
            changes = {k: {"before": bool(old[k]) if k in _BOOL_COLUMNS else old[k], "after": v}
                       for k, v in fields.items()}
            sets = ", ".join(f"{k}=?" for k in fields)
            # 시연 행은 시연으로 둔다(초기화로 지워지게). 그 밖은 '화면'으로 바꿔 다시 가져와도 덮어쓰지 않게.
            db.execute(f"UPDATE {table} SET {sets}, "
                       f"origin=CASE WHEN origin='시연' THEN '시연' ELSE '화면' END, updated_at=? WHERE id=?",
                       (*[_db_value(k, v) for k, v in fields.items()], _now(), row_id))
            self._event(db, None, event_kind, actor, {"id": row_id, "changes": changes})

    def import_contracts_from_notice(self, path: str | Path) -> list[int]:
        """전속계약 통보문 한 건을 등록부에 넣는다(같은 문서는 갱신, 화면에서 고친 행은 건너뜀). 해당 행의 id 목록."""
        return [self._upsert_notice(loader.parse_contract_notice(path))]

    def import_all_contract_notices(self) -> list[int]:
        """데이터 폴더의 모든 전속계약 통보문을 가져온다."""
        return [self._upsert_notice(n) for n in loader.contract_notices().values()]

    def _upsert_notice(self, n: loader.ContractNotice) -> int:
        values = {"influencer_code": n.influencer_code, "influencer_name": n.influencer_name,
                  "annual_fixed_krw": n.annual_fixed_krw, "performance_fee_text": n.performance_fee_text,
                  "notice_deadline": n.notice_deadline.isoformat(), "expiry_date": n.expiry.isoformat(),
                  "auto_renew": n.auto_renew, "source_doc": n.source_file}
        with self._tx() as db:
            old = db.execute("SELECT * FROM contracts WHERE source_doc=?", (n.source_file,)).fetchone()
            if old is None:
                new_id = self._insert_contract(db, values, "가져오기")
                self._event(db, None, "계약등록", "가져오기", {"contract_id": new_id, "source_doc": n.source_file})
                return new_id
            if old["origin"] == "가져오기":
                changes = {f: {"before": bool(old[f]) if f in _BOOL_COLUMNS else old[f], "after": values[f]}
                           for f in _CONTRACT_FIELDS if (bool(old[f]) if f in _BOOL_COLUMNS else old[f]) != values[f]}
                if changes:
                    sets = ", ".join(f"{f}=?" for f in _CONTRACT_FIELDS)
                    db.execute(f"UPDATE contracts SET {sets}, updated_at=? WHERE id=?",
                               (*[_db_value(f, values[f]) for f in _CONTRACT_FIELDS], _now(), old["id"]))
                    self._event(db, None, "계약가져오기", "가져오기",
                                {"contract_id": old["id"], "source_doc": n.source_file, "changes": changes})
            return old["id"]

    def get_plan(self, plan_id: str) -> dict:
        row = self._one("SELECT * FROM plans WHERE plan_id=?", plan_id)
        if row is None:
            raise KeyError(f"없는 기안: {plan_id}")
        return {**dict(row), "raw": json.loads(row["raw"])}

    def list_plans(self) -> list[dict]:
        return [{**dict(r), "raw": json.loads(r["raw"])} for r in self._all("SELECT * FROM plans ORDER BY id")]

    def add_plan(self, fields: dict, actor: str, origin: str = "화면") -> int:
        if origin not in ORIGINS:
            raise ValueError(f"알 수 없는 출처 구분: {origin!r}")
        extra = set(fields) - set(_PLAN_FIELDS)
        if extra or "plan_id" not in fields:
            raise ValueError(f"기안 항목 오류: 없는 항목 {sorted(extra)} 또는 plan_id 누락")
        row = {**{f: None for f in _PLAN_FIELDS}, "source_file": "", **_clean(fields)}
        with self._tx() as db:
            new_id = self._insert_plan(db, row, fields, origin)
            self._event(db, None, "기안등록", actor, {"plan_id": fields["plan_id"], "origin": origin})
            return new_id

    @staticmethod
    def _insert_plan(db, row: dict, raw, origin: str) -> int:
        now = _now()
        cur = db.execute(
            f"INSERT INTO plans ({', '.join(_PLAN_FIELDS)}, raw, origin, created_at, updated_at) "
            f"VALUES ({', '.join('?' * len(_PLAN_FIELDS))}, ?, ?, ?, ?)",
            (*[row[f] for f in _PLAN_FIELDS], _json(raw), origin, now, now))
        return cur.lastrowid

    def import_plans_from_source(self) -> PlanImportResult:
        """캠페인 기안 원본 파일을 등록부에 넣는다. 기안 ID 기준으로 갱신하며(중복 없음),
        화면에서 고친 행은 덮어쓰지 않고 건너뛴다(어느 열의 원본 값이 달라졌는지 함께 알림).
        추가·갱신·변경 없음 수와 건너뛴 기안을 돌려주고, 한 번의 가져오기를 이벤트 하나로 남긴다."""
        rows = loader.plan_rows()
        campaigns = {r["campaign_id"]: r for r in loader.campaign_master_rows()}
        result = PlanImportResult()
        changes: dict[str, dict] = {}
        with self._tx() as db:
            for r in rows:
                camp = campaigns.get(r["campaign_id"])
                if camp is None:
                    result.warnings.append(f"{r['plan_id']}: 캠페인 마스터에 {r['campaign_id']}가 없어 인플루언서·채널을 비워 둠")
                    camp = {}
                vals = {"plan_id": r["plan_id"], "campaign_id": r["campaign_id"],
                        "influencer_id": camp.get("influencer_id"), "channel": camp.get("sales_channel"),
                        "requested_budget_krw": r["requested_budget_krw"], "expected_gmv_krw": r["expected_gmv_krw"],
                        "settlement_date": r["settlement_date"].isoformat(),
                        "contract_deadline": r["contract_deadline"].isoformat(), "source_file": loader.PLAN_SOURCE}
                old = db.execute("SELECT * FROM plans WHERE plan_id=?", (r["plan_id"],)).fetchone()
                if old is None:
                    self._insert_plan(db, vals, r, "가져오기")
                    result.added += 1
                    continue
                diff = {f: {"before": old[f], "after": vals[f]} for f in _PLAN_FIELDS if old[f] != vals[f]}
                new_raw = json.loads(_json(r))
                if old["origin"] == "화면":
                    # 마지막으로 가져온 원본(raw)과 지금 원본을 비교해, 반영되지 못한 원본 변경 열을 알려 준다
                    prev_raw = json.loads(old["raw"])
                    result.skipped.append(SkippedPlan(r["plan_id"], "화면에서 고친 기안이라 덮어쓰지 않음",
                                                      [c for c in new_raw if prev_raw.get(c) != new_raw[c]]))
                elif not diff and json.loads(old["raw"]) == new_raw:
                    result.unchanged += 1
                else:
                    sets = ", ".join(f"{f}=?" for f in _PLAN_FIELDS)
                    db.execute(f"UPDATE plans SET {sets}, raw=?, updated_at=? WHERE id=?",
                               (*[vals[f] for f in _PLAN_FIELDS], _json(r), _now(), old["id"]))
                    result.updated += 1
                    changes[r["plan_id"]] = diff
            self._event(db, None, "기안가져오기", "가져오기",
                        {"added": result.added, "updated": result.updated, "unchanged": result.unchanged,
                         "skipped": [x.plan_id for x in result.skipped], "changes": changes})
        return result

    # ---- 정책 변경 ----

    def _apply_policy_overrides(self) -> None:
        """저장된 덮어쓰기를 적용한다. 나중에 무효가 된 값(예: 단가표에서 빠진 모델)은 건너뛰고 이벤트로 남겨
        저장소가 열리지 못하는 일이 없게 한다."""
        latest: dict[str, tuple] = {}
        for r in self._all("SELECT * FROM policy_changes ORDER BY id"):
            latest[r["key"]] = (json.loads(r["after"]), r["actor"], r["at"], r["id"])
        ignored = []
        for key, (value, _, _, change_id) in list(latest.items()):
            try:
                policy.validate(key, value)
            except ValueError as e:
                ignored.append({"key": key, "change_id": change_id, "error": str(e)})
                del latest[key]
        policy.set_overrides({k: v[:3] for k, v in latest.items()})
        if ignored:
            logger.error("무효가 된 정책 덮어쓰기를 건너뜀: %s", ignored)
            with self._tx() as db:  # 같은 이력은 한 번만 이벤트로 남긴다
                seen = set(json.loads(self._setting(db, "ignored_policy_changes") or "[]"))
                fresh = [i for i in ignored if i["change_id"] not in seen]
                if fresh:
                    self._event(db, None, "정책덮어쓰기무시", "시스템", {"ignored": fresh})
                    db.execute("INSERT INTO settings (key, value) VALUES ('ignored_policy_changes', ?) "
                               "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                               (json.dumps(sorted(seen | {i["change_id"] for i in fresh})),))

    def change_policy(self, key: str, new_value, actor: str, reason: str) -> None:
        """값을 검증(app.policy)하고 이력에 남긴 뒤 덮어쓰기로 적용한다. 정책 파일은 고치지 않는다."""
        value = policy.validate(key, new_value)
        if not actor.strip():
            raise ValueError("바꾼 사람이 비어 있음")
        before = policy.get(key)
        with self._tx() as db:
            db.execute("INSERT INTO policy_changes (key, before, after, actor, at, reason) VALUES (?,?,?,?,?,?)",
                       (key, _json(before), _json(value), actor, _now(), reason))
            self._event(db, None, "정책변경", actor, {"key": key, "before": before, "after": value, "reason": reason})
        self._apply_policy_overrides()

    def policy_history(self, key: str | None = None) -> list[dict]:
        rows = (self._all("SELECT * FROM policy_changes ORDER BY id") if key is None
                else self._all("SELECT * FROM policy_changes WHERE key=? ORDER BY id", key))
        return [{**dict(r), "before": json.loads(r["before"]), "after": json.loads(r["after"])} for r in rows]

    # ---- AI 비용 장부(CostLedger) ----

    @staticmethod
    def _insert_call(db, state: str, day: date, case_id, kind, model, in_tok, out_tok, usd, confidence, summary) -> int:
        cur = db.execute("INSERT INTO ai_calls (ts, day, case_id, kind, model, in_tok, out_tok, usd, confidence, summary, state) "
                         "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (_now(), day.isoformat(), case_id, kind, model, in_tok, out_tok, usd, confidence, summary, state))
        return cur.lastrowid

    def spent(self, day: date | None = None) -> float:
        """쓴 돈(USD) = 정산된 비용 + 예약분(미정산 포함, 예상 비용). day가 있으면 그날만(UTC 날짜)."""
        row = (self._one("SELECT COALESCE(SUM(usd), 0) FROM ai_calls") if day is None
               else self._one("SELECT COALESCE(SUM(usd), 0) FROM ai_calls WHERE day=?", day.isoformat()))
        return row[0]

    def record(self, model: str, in_tok: int, out_tok: int, usd: float, day: date) -> None:
        with self._tx() as db:
            self._insert_call(db, "정산", day, None, "", model, in_tok, out_tok, usd, None, "")

    def add_ai_call(self, case_id: int | None, kind: str, model: str, in_tok: int, out_tok: int,
                    confidence: float | None = None, summary: str = "", usd: float | None = None,
                    day: date | None = None) -> None:
        """AI 호출 한 건을 기록한다. usd를 안 주면 정책 단가표로 계산, day를 안 주면 UTC 오늘."""
        if usd is None:
            _, price_in, price_out = policy.model_price(model)
            usd = (in_tok * price_in + out_tok * price_out) / TOKENS_PER_PRICE_UNIT
        with self._tx() as db:
            self._insert_call(db, "정산", day or utc_today(), case_id, kind, model, in_tok, out_tok, usd, confidence, summary)

    def ai_calls(self, case_id: int | None = None) -> list[dict]:
        """정산된 호출과 미정산(이전 프로세스가 남긴 예약, 예상 비용) 호출. 진행 중인 예약은 pending_reservations."""
        base = "SELECT * FROM ai_calls WHERE state IN ('정산', '미정산')"
        rows = (self._all(base + " ORDER BY id") if case_id is None
                else self._all(base + " AND case_id=? ORDER BY id", case_id))
        return [dict(r) for r in rows]

    def pending_reservations(self) -> list[dict]:
        """아직 정산·반환되지 않은 예약(created = 예약 시각, usd = 예상 비용)."""
        return [{"id": r["id"], "created": r["ts"], "day": r["day"], "usd": r["usd"]}
                for r in self._all("SELECT * FROM ai_calls WHERE state='예약' ORDER BY id")]

    def _expire_stale_reservations(self) -> None:
        """열 때 정책 시간(ai.reservation_stale_seconds)보다 오래된 예약을 '미정산'으로 바꿔 보이게 한다.
        비용은 예상 비용 그대로 집계에 남긴다(보수적)."""
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=policy.get("ai.reservation_stale_seconds"))
                  ).isoformat(timespec="seconds")
        with self._tx() as db:
            stale = db.execute("SELECT id, usd FROM ai_calls WHERE state='예약' AND ts < ?", (cutoff,)).fetchall()
            if not stale:
                return
            db.execute("UPDATE ai_calls SET state='미정산', summary='정산되지 않은 예약(예상 비용으로 집계)' "
                       "WHERE state='예약' AND ts < ?", (cutoff,))
            self._event(db, None, "미정산예약", "시스템", {"ids": [r["id"] for r in stale], "usd": sum(r["usd"] for r in stale)})

    def note_settle_failure(self, reservation_id: int, error: BaseException) -> None:
        """호출은 성공했지만 정산이 실패한 사실을 이벤트로 남긴다(예약은 예상 비용으로 남음)."""
        with self._tx() as db:
            self._event(db, None, "정산실패", "시스템", {"reservation_id": reservation_id, "error": str(error)})

    def reserve(self, estimate_usd: float, day: date, total_cap: float, daily_cap: float) -> int:
        """한도 확인과 예약을 한 묶음(BEGIN IMMEDIATE)으로. 넘으면 BudgetExceeded."""
        with self._tx() as db:
            total = db.execute("SELECT COALESCE(SUM(usd), 0) FROM ai_calls").fetchone()[0]
            today = db.execute("SELECT COALESCE(SUM(usd), 0) FROM ai_calls WHERE day=?", (day.isoformat(),)).fetchone()[0]
            check_caps(total, today, estimate_usd, total_cap, daily_cap)
            return self._insert_call(db, "예약", day, None, "", "", 0, 0, estimate_usd, None, "")

    def settle(self, reservation_id: int, model: str, in_tok: int, out_tok: int, usd: float) -> None:
        with self._tx() as db:
            cur = db.execute("UPDATE ai_calls SET model=?, in_tok=?, out_tok=?, usd=?, state='정산', summary='', ts=? "
                             "WHERE id=? AND state IN ('예약', '미정산')", (model, in_tok, out_tok, usd, _now(), reservation_id))
            if cur.rowcount == 0:
                raise KeyError(f"없는 예약: {reservation_id}")

    def release(self, reservation_id: int) -> None:
        with self._tx() as db:
            db.execute("DELETE FROM ai_calls WHERE id=? AND state IN ('예약', '미정산')", (reservation_id,))


def open_db(path: str | Path | None = None, today: Callable[[], date] = date.today) -> Store:
    """DB를 연다(폴더·테이블이 없으면 만든다). path를 안 주면 config.db_path()."""
    return Store(config.db_path() if path is None else path, today=today)
