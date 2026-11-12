"""HTTP API(Task 12). 엔진(app.engine.flow)과 저장소(app.store.db)를 JSON으로 연다. 규칙·권한 판정은 엔진이 하고 여기는 연결만 한다.

- 인증은 아직 없다: 요청 본문의 actor(보는 사람 이름)로 엔진이 역할을 판별한다.
- 오류는 {"detail": "한국어 문장"}: 없는 id 404, 권한·상태 위반 409, 등록부 값 오류·형식 오류 422.
- create_app(store, engine, static_dir=None)로 만든다(시험은 임시 DB·FakeProvider를 넣는다). 실제 실행은 build_app()이
  환경변수(AXWAR_DB·AXWAR_PEOPLE·AXWAR_DEMO_DIR·AXWAR_AI·AXWAR_FRONTEND_DIST)로 구성한다:
  uvicorn app.api.main:build_app --factory
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StrictInt
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import config, policy
from app.ai.providers import utc_today
from app.calc.cash import breach_windows, covenant_min_krw, forecast_window, official_forecast_gap, simulate_cash
from app.engine import scenarios
from app.engine.flow import R_HUMAN, Engine
from app.store.db import Store, open_db

PEOPLE_FILE = "people"  # 시연 폴더에서 장면이 아닌 파일(사람 목록)
logger = logging.getLogger(__name__)
CALL_LIMIT = 50  # AI 호출 내역 기본 표시 개수(화면 목록 길이 — 정책 기준 아님)


# ---------------------------------------------------------------- 요청 본문

class Who(BaseModel):
    actor: str


class Decision(Who):
    action: str
    comment: str = ""


class Escalation(Who):
    stage: str = "1차"
    opinion: str
    reason: str


class Reply(Who):
    text: str
    attachments: StrictInt = Field(0, ge=0)


class ReviewItem(BaseModel):
    product: str
    text: str


class Reviews(BaseModel):
    reviews: list[ReviewItem]
    actor: str | None = None  # 없으면 시연 대본 재생: 시연 모드에서만. 운영에서는 입력 권한 역할의 사람이 필요


class Returns(BaseModel):
    change_of_mind: StrictInt
    color: StrictInt
    actor: str | None = None  # Reviews와 같음


class Sales(Who):
    orders: StrictInt
    returns: StrictInt


class Qty(Who):
    qty: StrictInt


class Announce(Who):
    qty: StrictInt | None = None


class Notice(Who):
    text: str | None = None


class Continue(Qty):
    reason: str


class Cancel(Who):
    reason: str


class Clock(BaseModel):
    date: date


class Mode(Who):
    mode: str


class Register(Who):
    fields: dict[str, Any]
    open_case: bool = True


class Edit(Who):
    fields: dict[str, Any]


class PolicyChange(Who):
    value: Any
    reason: str = ""


class Seed(BaseModel):
    scenario: str


class Run(Seed):
    upto: StrictInt | None = None


class Step(BaseModel):
    step: dict[str, Any]


# ---------------------------------------------------------------- 오류 문장

def _validation_text(e: RequestValidationError) -> str:
    parts = []
    for err in e.errors():
        where = ".".join(str(x) for x in err["loc"] if x != "body") or "요청"
        parts.append(f"{where}: " + ("빠져 있음" if err["type"] == "missing" else "값 형식이 올바르지 않음"))
    return "요청 형식이 올바르지 않음 — " + "; ".join(parts)


def _bad_input(fn):
    """등록부 값 오류(ValueError)는 충돌이 아니라 입력 오류(422)로."""
    try:
        return fn()
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


def _policy_row(key: str) -> dict:
    value, effective_source, _ = policy.entry(key)
    file_value, source, description = policy.base_entry(key)
    return {"key": key, "value": value, "source": source, "description": description,
            "overridden": policy.is_overridden(key), "file_value": file_value, "effective_source": effective_source}


def create_app(store: Store, engine: Engine, static_dir: str | Path | None = None) -> FastAPI:
    app = FastAPI(title="Masil 승인·집행 API")

    # ------------------------------------------------------------ 오류 처리
    @app.exception_handler(KeyError)
    async def _not_found(_: Request, e: KeyError):
        return JSONResponse({"detail": str(e.args[0]) if e.args else "찾을 수 없음"}, 404)

    @app.exception_handler(FileNotFoundError)
    async def _no_file(_: Request, e: FileNotFoundError):
        return JSONResponse({"detail": str(e)}, 404)

    @app.exception_handler(PermissionError)
    async def _forbidden(_: Request, e: PermissionError):
        return JSONResponse({"detail": str(e)}, 409)

    @app.exception_handler(ValueError)
    async def _conflict(_: Request, e: ValueError):
        return JSONResponse({"detail": str(e)}, 409)

    @app.exception_handler(sqlite3.IntegrityError)
    async def _dup(_: Request, e: sqlite3.IntegrityError):
        return JSONResponse({"detail": "이미 등록된 항목이라 저장할 수 없음"}, 409)

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, e: RequestValidationError):
        return JSONResponse({"detail": _validation_text(e)}, 422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, e: StarletteHTTPException):
        text = {404: "찾을 수 없는 주소", 405: "허용되지 않는 요청 방식"}.get(e.status_code)
        return JSONResponse({"detail": text or str(e.detail)}, e.status_code)

    @app.middleware("http")
    async def _daily_check(request: Request, call_next):
        """운영 모드에서는 API 요청이 들어올 때 오늘의 일일 점검이 아직 안 돌았으면 먼저 한 번 돌린다(멱등, H5)."""
        if request.url.path.startswith("/api/"):
            try:
                await run_in_threadpool(engine.ensure_daily_check)
            except Exception:  # 점검이 실패해도 요청은 받는다(다음 요청에서 다시 시도, 로그로 남김)
                logger.exception("일일 점검 실패")
        return await call_next(request)

    # ------------------------------------------------------------ 기본·읽기
    @app.get("/healthz")
    def healthz():
        return "ok"

    @app.get("/api/people")
    def people():
        return [{"name": n, "role": r} for n, r in engine.people.people.items()]

    @app.get("/api/todo/{person}")
    def todo(person: str):
        try:
            engine.role_of(person)
        except PermissionError as e:
            raise HTTPException(404, str(e)) from None
        return engine.todo(person)

    @app.get("/api/calendar")
    def calendar():
        return engine.calendar()

    @app.get("/api/cases")
    def cases(kind: str | None = None, status: str | None = None):
        return [{"id": c["id"], "kind": c["kind"], "ref_id": c["ref_id"], "status": c["status"],
                 **engine.deadline_view(c["facts"].get("deadline")), "origin": c["origin"]}
                for c in store.list_cases(kind) if status is None or c["status"] == status]

    @app.get("/api/cases/{case_id}")
    def case_detail(case_id: int, viewer: str | None = None):
        return engine.case_detail(case_id, viewer)

    @app.get("/api/cases/{case_id}/phase2")
    def phase2(case_id: int):
        store.get_case(case_id)
        return engine.phase2_view(case_id)

    @app.get("/api/events")
    def events(case_id: int | None = None, kind: str | None = None, limit: int | None = Query(None, ge=1)):
        rows = store.events(case_id, kind)
        return rows[-limit:] if limit else rows

    @app.get("/api/assumptions")
    def assumptions():
        rows = [_policy_row(k) for k in policy.keys()]
        return [r for r in rows if r["source"].startswith("가정")]

    @app.get("/api/cash")
    def cash():
        w = forecast_window()
        days = simulate_cash(w.start, w.end)
        return {"start": w.start, "end": w.end, "days": [{"date": d.day, "inflow": d.inflow, "outflow": d.outflow, "closing": d.closing} for d in days],
                "windows": [asdict(x) for x in breach_windows(days)], "covenant_min_krw": covenant_min_krw(),
                "official_forecast_gap": official_forecast_gap()}

    @app.get("/api/execution-check")
    def execution_check(influencer_id: str, day: date):
        return engine.execution_check(influencer_id, day)

    @app.get("/api/ai/usage")
    def ai_usage(limit: int = CALL_LIMIT):
        calls = store.ai_calls()
        by_kind: dict[str, dict] = {}
        for c in calls:
            row = by_kind.setdefault(c["kind"], {"count": 0, "usd": 0.0})
            row["count"] += 1
            row["usd"] += c["usd"]
        return {"mode": config.ai_mode(), "spent_usd": store.spent(), "spent_today_usd": store.spent(utc_today()),
                "total_cap_usd": policy.get("ai.total_cap_usd"), "daily_cap_usd": policy.get("ai.daily_cap_usd"),
                "pending_reservations": store.pending_reservations(), "calls_total": len(calls),
                "by_kind": by_kind, "calls": calls[-limit:] if limit else calls}

    # ------------------------------------------------------------ 결정·집행
    @app.post("/api/cases/{case_id}/decision")
    def decision(case_id: int, body: Decision):
        return engine.decide(case_id, body.actor, body.action, body.comment)

    @app.post("/api/cases/{case_id}/briefing")
    def briefing(case_id: int, body: Who):
        return engine.write_briefing(case_id, body.actor)

    @app.post("/api/cases/{case_id}/adjust-phase1")
    def adjust_phase1(case_id: int, body: Qty):
        return engine.adjust_phase1(case_id, body.actor, body.qty)

    @app.post("/api/cases/{case_id}/announce")
    def announce(case_id: int, body: Announce):
        return engine.announce(case_id, body.actor, body.qty)

    @app.post("/api/cases/{case_id}/send-notice")
    def send_notice(case_id: int, body: Notice):
        return engine.send_notice(case_id, body.actor, body.text)

    @app.post("/api/cases/{case_id}/reviews")
    def reviews(case_id: int, body: Reviews):
        store.get_case(case_id)
        g = engine.add_reviews(case_id, [(r.product, r.text) for r in body.reviews], body.actor)
        return {"case_id": case_id, "status": store.get_case(case_id)["status"], "gate": asdict(g)}

    @app.post("/api/cases/{case_id}/returns")
    def returns(case_id: int, body: Returns):
        store.get_case(case_id)
        g = engine.add_returns(case_id, body.change_of_mind, body.color, body.actor)
        return {"case_id": case_id, "status": store.get_case(case_id)["status"], "gate": asdict(g)}

    @app.post("/api/cases/{case_id}/sales")
    def sales(case_id: int, body: Sales):
        return engine.record_phase1_sales(case_id, body.actor, body.orders, body.returns)

    @app.post("/api/cases/{case_id}/escalate")
    def escalate(case_id: int, body: Escalation):
        """승인권자가 권한을 넘는다고 보고 상급자에게 올린다(상신). stage: 1차·2차, opinion: 승인 권고·반대 권고."""
        store.get_case(case_id)
        return engine.escalate(case_id, body.actor, body.stage, body.opinion, body.reason)

    @app.post("/api/cases/{case_id}/phase2/decision")
    def phase2_decision(case_id: int, body: Decision):
        """2차 승인 대기 건의 2차 결정(action: 승인·거절)."""
        return engine.decide_phase2(case_id, body.actor, body.action, body.comment)

    @app.post("/api/cases/{case_id}/phase2/continue")
    def phase2_continue(case_id: int, body: Continue):
        return engine.continue_phase2(case_id, body.actor, body.qty, body.reason)

    @app.post("/api/cases/{case_id}/phase2/exception")
    def phase2_exception(case_id: int, body: Continue):
        """반품 자동 보류 건의 예외 승인(2차 승인권자 중 최고 역할이 이유를 적어 수량은 계획 2차 이하로)."""
        return engine.approve_phase2_exception(case_id, body.actor, body.qty, body.reason)

    @app.post("/api/cases/{case_id}/phase2/cancel")
    def phase2_cancel(case_id: int, body: Cancel):
        return engine.cancel_phase2(case_id, body.actor, body.reason)

    # ------------------------------------------------------------ 부서 요청·회신
    def request_row(r: dict) -> dict:
        case = store.get_case(r["case_id"])
        return {**r, "request_id": r["id"], "ref_id": case["ref_id"], "case_status": case["status"]}

    @app.get("/api/requests")
    def requests(dept: str | None = None, status: str | None = None):
        return [request_row(r) for r in store.all_requests(dept) if status is None or r["status"] == status]

    @app.get("/api/requests/{request_id}")
    def request_one(request_id: int):
        return {**request_row(store.get_request(request_id)), "replies": store.list_replies(request_id)}

    @app.get("/api/human-checks")
    def human_checks():
        return [request_row(r) for r in store.all_requests() if r["status"] == R_HUMAN]

    @app.post("/api/requests/{request_id}/reply")
    def reply(request_id: int, body: Reply):
        return engine.submit_reply(request_id, body.actor, body.text, body.attachments)

    @app.post("/api/requests/{request_id}/resolve")
    def resolve(request_id: int, body: Reply):
        return engine.resolve_human_check(request_id, body.actor, body.text, body.attachments)

    # ------------------------------------------------------------ 기준일·모드
    @app.get("/api/clock")
    def clock_get():
        return {"date": store.get_clock().isoformat(), "mode": store.get_mode()}

    @app.post("/api/clock")
    def clock_set(body: Clock):
        actions = engine.advance(body.date)
        return {"date": store.get_clock().isoformat(), "mode": store.get_mode(), "actions": actions}

    @app.post("/api/deadlines/check")
    def deadlines_check():
        return engine.check_deadlines()

    @app.post("/api/sync")
    def sync(body: Who):
        engine.require_registry_editor(body.actor)
        return {"actions": engine.sync(body.actor)}

    @app.get("/api/mode")
    def mode_get():
        return {"mode": store.get_mode()}

    @app.put("/api/mode")
    def mode_set(body: Mode):
        engine.set_mode(body.actor, body.mode)
        return {"mode": store.get_mode()}

    # ------------------------------------------------------------ 정책
    @app.get("/api/policy")
    def policy_list():
        return [_policy_row(k) for k in policy.keys()]

    @app.get("/api/policy/history")
    def policy_history(key: str | None = None):
        return store.policy_history(key)

    @app.put("/api/policy/{key}")
    def policy_change(key: str, body: PolicyChange):
        engine.change_policy(body.actor, key, body.value, body.reason)
        return _policy_row(key)

    # ------------------------------------------------------------ 등록부: 기안
    @app.get("/api/plans")
    def plans():
        return store.list_plans()

    @app.get("/api/plans/{plan_id}")
    def plan_one(plan_id: str):
        return store.get_plan(plan_id)

    def open_result(opener, *args) -> tuple[int | None, str | None]:
        try:
            return opener(*args), None
        except ValueError as e:  # 등록은 됐으나 판정할 항목이 비어 있음 등
            return None, str(e)

    @app.post("/api/plans", status_code=201)
    def plan_add(body: Register):
        _bad_input(lambda: engine.add_plan(body.fields, body.actor))
        plan_id = body.fields["plan_id"]
        case_id, err = open_result(engine.open_plan, plan_id, body.actor) if body.open_case else (None, None)
        return {"plan_id": plan_id, "case_id": case_id, "open_error": err}

    @app.put("/api/plans/{plan_id}")
    def plan_edit(plan_id: str, body: Edit):
        return {"plan_id": plan_id, "actions": _bad_input(lambda: engine.update_plan(plan_id, body.fields, body.actor))}

    @app.post("/api/plans/{plan_id}/open")
    def plan_open(plan_id: str, body: Who):
        engine.require_registry_editor(body.actor)
        return {"plan_id": plan_id, "case_id": engine.open_plan(plan_id, body.actor)}

    # ------------------------------------------------------------ 등록부: 계약
    @app.get("/api/contracts")
    def contracts():
        return store.list_contracts()

    @app.get("/api/contracts/{contract_id}")
    def contract_one(contract_id: int):
        return store.get_contract(contract_id)

    @app.post("/api/contracts", status_code=201)
    def contract_add(body: Register):
        contract_id = _bad_input(lambda: engine.add_contract(body.fields, body.actor))
        code = body.fields["influencer_code"]
        case_id, err = open_result(engine.open_contract, code, body.actor) if body.open_case else (None, None)
        return {"contract_id": contract_id, "influencer_code": code, "case_id": case_id, "open_error": err}

    @app.put("/api/contracts/{contract_id}")
    def contract_edit(contract_id: int, body: Edit):
        return {"contract_id": contract_id,
                "actions": _bad_input(lambda: engine.update_contract(contract_id, body.fields, body.actor))}

    @app.post("/api/contracts/{influencer_code}/open")
    def contract_open(influencer_code: str, body: Who):
        engine.require_registry_editor(body.actor)
        return {"influencer_code": influencer_code, "case_id": engine.open_contract(influencer_code, body.actor)}

    # ------------------------------------------------------------ 가져오기
    @app.post("/api/import/plans")
    def import_plans(body: Who):
        engine.require_registry_editor(body.actor)
        r = store.import_plans_from_source()
        return {**asdict(r), "actions": engine.sync(body.actor)}

    @app.post("/api/import/contracts")
    def import_contracts(body: Who):
        engine.require_registry_editor(body.actor)
        ids = store.import_all_contract_notices()
        return {"count": len(ids), "contract_ids": ids, "actions": engine.sync(body.actor)}

    # ------------------------------------------------------------ 시연(시연 모드에서만)
    demo_dir = engine.demo_dir or config.demo_dir()

    @app.get("/api/demo/scenarios")
    def demo_scenarios():
        names = sorted(p.stem for p in Path(demo_dir).glob("*.json") if p.stem != PEOPLE_FILE)
        out = []
        for n in names:
            sc = scenarios.load(n, demo_dir)
            out.append({"name": n, "title": sc.title, "description": sc.description, "plans": list(sc.plans),
                        "contracts": list(sc.contracts), "script": list(sc.script)})
        return out

    @app.post("/api/demo/reset")
    def demo_reset(body: Seed):
        ids = engine.seed(body.scenario)
        return {"scenario": body.scenario, "case_ids": ids, "date": store.get_clock().isoformat()}

    @app.post("/api/demo/play")
    def demo_play(body: Step):
        step = body.step
        action = step.get("action")
        if action not in scenarios.ACTION_FIELDS:
            raise HTTPException(422, f"알 수 없는 행동 {action!r} ({', '.join(scenarios.ACTION_FIELDS)})")
        missing = [f for f in scenarios.ACTION_FIELDS[action] if f not in step]
        if missing or (action in scenarios.TARGETED and ("plan" in step) == ("contract" in step)):
            raise HTTPException(422, f"대본 단계({action})에 필요한 항목이 없음: {missing or ['plan 또는 contract']}")
        return engine.play(step)

    @app.post("/api/demo/run")
    def demo_run(body: Run):
        return engine.run_script(body.scenario, body.upto)

    # ------------------------------------------------------------ 정적 파일(API 경로 뒤에 둔다)
    dist = Path(static_dir) if static_dir is not None else config.frontend_dist()
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")
    return app


def build_app() -> FastAPI:
    """환경변수로 구성한 실제 앱. uvicorn app.api.main:build_app --factory"""
    store = open_db()
    wanted = config.default_mode()
    if wanted is not None and not store.has_mode_setting():
        store.set_mode(wanted)  # 배포(AXWAR_MODE=운영)에서 처음 한 번만. 저장된 모드가 있으면 그대로 둔다
    engine = Engine(store, demo_dir=config.demo_dir(), people=scenarios.load_people())
    try:
        engine.ensure_daily_check()  # 서버를 켤 때 오늘 점검이 안 돌았으면 한 번
    except Exception:
        logger.exception("서버 시작 점검 실패")
    return create_app(store, engine)
