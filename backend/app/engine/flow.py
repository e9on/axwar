"""이벤트 엔진(설계 7.2·7.3·7.4): 기준일 이동 시 기한 점검, 회신 저장 → AI 해석 → 규칙 → 상태 변경 → 작업 생성.

- 엔진은 등록부(DB)의 기안·계약만 본다. 장면 숫자·ID·날짜·문구는 없다(시연 파일과 테스트에만).
- 오늘 = store.get_clock()(운영은 실제 오늘, 시연은 시연 시계). advance는 시연 전용, 운영은 check_deadlines.
- 권한은 역할로 판정한다(보는 사람 → 역할은 사람 목록 파일). 승인권자는 rules.approver가 정한다.
- AI 판정은 ai_judgments(store.add_judgment)에, 비용은 제공자(BudgetedProvider)가 ai_calls에 남긴다.
- 부서 요청은 목적(purpose)을 달고, 회신이 수용으로 해석되면 목적별 처리기(_handlers)가 사실을 바꾼다.
  11b는 처리기(안전재고 사용·통보 회신 등)와 분할안 계산을 더하면 된다.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

from app.ai import judge
from app.ai.providers import Provider, make_provider
from app.calc import volume as volume_calc
from app.calc.campaign import return_count_rate
from app.calc.cash import Window, breach_windows, forecast_window, simulate_cash
from app.calc.indicators import CHANGE_OF_MIND, key_indicators
from app.data import loader
from app.engine import scenarios
from app.rules.approver import decide_contract, decide_plan, diff_approver
from app.rules.deadline import deadline_actions
from app.rules.models import ApproverDecision, ContractFacts, PlanFacts, RuleHit
from app.rules.split import GateResult, phase2_gate
from app.store.db import CLOCK_LOCKED, MODE_OPERATION, Store

KIND_PLAN, KIND_CONTRACT = "기안", "계약"

# 상태(설계 7.3 캠페인 확대 건, 7.4 전속계약 건)
S_DRAFT, S_WAIT_REPLY, S_WAIT_APPROVAL = "기안", "회신 대기", "승인 대기"
S_APPROVED, S_SPLIT_APPROVED, S_REJECTED = "승인", "분할 승인", "거절"
S_DEFAULT_DENY, S_HOLD = "기본 거부", "확정 보류"
S_PHASE1, S_PHASE2_LOCK, S_PHASE2_HOLD, S_DONE = "1차 집행", "2차 잠금", "2차 보류", "완료"
S_REVIEW, S_RENEW_OK, S_CHANGE_OK, S_AGREED = "검토", "갱신 승인", "조건변경 승인", "합의"
OPEN = {KIND_PLAN: (S_WAIT_REPLY, S_WAIT_APPROVAL), KIND_CONTRACT: (S_REVIEW, S_WAIT_APPROVAL)}
TERMINAL = {KIND_PLAN: (S_REJECTED, S_HOLD, S_DONE), KIND_CONTRACT: (S_REJECTED, S_AGREED)}
RENEWAL_CONFIRMED = (S_RENEW_OK, S_CHANGE_OK, S_AGREED)

# 요청 상태와 목적
R_WAIT, R_HUMAN, R_DONE = "대기", "사람 확인", "처리됨"
P_LOGISTICS, P_CONTENT = "물류 처리 능력", "콘텐츠 수정"

# 역할
LOGISTICS, CS, CAMPAIGN, CONTRACT_OWNER = "물류", "CS", "캠페인 담당", "계약 담당"
OWNER = {KIND_PLAN: CAMPAIGN, KIND_CONTRACT: CONTRACT_OWNER}
# 승인권자 표기(rules.approver) → 승인하는 역할. 보고만 받는 표기는 승인 대상이 아니다.
APPROVER_ROLE = {"이사회 의결": "이사회", "그룹 확인": "그룹"}
REPORT_ONLY = {"그룹 보고": "그룹"}

DECISIONS = scenarios.DECISIONS
D_APPROVE, D_SPLIT, D_REJECT = DECISIONS
COLOR_RETURN = "색상불만"  # 원본 반품 사유 값
COLOR_REVIEW = "색상불일치"  # 리뷰 해석 사유 값
NO_VOLUME = "추정 불가 — 담당자 입력 필요"
ALLOC_HOLD, ALLOC_FULL, ALLOC_PARTIAL = "보류", "전량", "조건부"
EV_WARN, EV_REPORT = "조기경고", "그룹보고"
RAW_KEEP = 500  # AI 원문은 이 글자 수까지만 판정 기록에 남긴다
OBSERVE_NOTE = "2차는 반품 관찰 뒤 열림"


def _d(s: str) -> date:
    return date.fromisoformat(s)


def _md(d: date) -> str:
    return f"{d.month}/{d.day}"


def _hits(hits) -> list[dict]:
    return [{"rule_id": h.rule_id, "text": h.text, "source": h.source, "badge": h.badge} for h in hits]


def _decision(f: dict) -> ApproverDecision:
    return ApproverDecision(tuple(f["approvers"]), tuple(RuleHit(**h) for h in f["approver_hits"]))


def _role(label: str) -> str:
    return APPROVER_ROLE.get(label, label)


def _required_roles(f: dict) -> list[str]:
    out: list[str] = []
    for label in f["approvers"]:
        if label not in REPORT_ONLY and _role(label) not in out:
            out.append(_role(label))
    return out


def _pending_roles(f: dict) -> list[str]:
    done = set(f.get("approved_roles", []))
    return [r for r in _required_roles(f) if r not in done]


class Engine:
    def __init__(self, store: Store, provider: Provider | None = None, demo_dir: str | Path | None = None,
                 people: scenarios.People | None = None):
        """provider를 주면 모든 AI 작업에 쓴다(테스트). 안 주면 작업마다 make_provider(task, ledger=store)."""
        self.store = store
        self._fixed = provider
        self._providers: dict[str, Provider] = {}
        self.demo_dir = Path(demo_dir) if demo_dir is not None else None
        if people is None:
            people = scenarios.load_people(self.demo_dir / "people.json" if self.demo_dir is not None else None)
        self.people = people
        self._handlers = {P_LOGISTICS: self._on_logistics, P_CONTENT: self._on_content_fix}

    # ---------------------------------------------------------------- 기반

    def _provider(self, task: str) -> Provider:
        if self._fixed is not None:
            return self._fixed
        if task not in self._providers:
            self._providers[task] = make_provider(task, ledger=self.store)
        return self._providers[task]

    def _today(self) -> date:
        return self.store.get_clock()

    @staticmethod
    def _windows() -> list[Window]:
        w = forecast_window()
        return breach_windows(simulate_cash(w.start, w.end))

    def _task_once(self, case_id: int, dept: str, title: str, due: date, detail: str = "") -> int:
        for t in self.store.list_tasks(case_id):
            if (t["dept"], t["title"], t["detail"]) == (dept, title, detail):
                return t["id"]
        return self.store.add_task(case_id, dept, title, due, detail)

    def _request_once(self, case_id: int, dept: str, text: str, attach: bool, purpose: str) -> int:
        for r in self.store.list_requests(case_id):
            if r["purpose"] == purpose and r["status"] != R_DONE:
                return r["id"]
        return self.store.add_request(case_id, dept, text, attach, purpose=purpose)

    def _find_case(self, kind: str, ref_id: str) -> dict | None:
        rows = [c for c in self.store.list_cases(kind) if c["ref_id"] == ref_id]
        return rows[-1] if rows else None

    def role_of(self, person: str) -> str:
        return self.people.role_of(person)

    # ---------------------------------------------------------------- 기안·계약 판정

    @staticmethod
    def _plan_total(plan: dict) -> int:
        """기안 총액 = 같은 기안 문서(원본 파일)의 요청액 합계. 화면 등록 기안(문서 없음)은 자기 금액."""
        if plan["source_file"]:
            return sum(r["requested_budget_krw"] for r in loader.read_table(plan["source_file"]))
        return plan["requested_budget_krw"]

    @staticmethod
    def _volume(plan: dict) -> dict:
        """원본 표본이 있는 기안만 물량 공식(calc.volume)으로 계산. 없으면 담당자 입력 필요."""
        if plan["source_file"] == loader.PLAN_SOURCE:
            vols = {v.plan_id: v for v in volume_calc.all_plan_volumes()}
            v = vols.get(plan["plan_id"])
            if v is not None:
                load = volume_calc.daily_load(plan["plan_id"])
                peak = max(load, key=lambda d: (load[d], -d.toordinal()))
                return {"units": round(v.plan_units), "peak_units": round(load[peak]), "peak_day": peak.isoformat(),
                        "low_confidence": v.low_confidence, "product_line": v.product_line,
                        "note": "계산: 과거 실판매량 × 확대 배율(설계 4.5)"}
        return {"units": None, "peak_units": None, "peak_day": None, "low_confidence": None,
                "product_line": None, "note": NO_VOLUME}

    def _plan_decision(self, plan: dict, windows: list[Window]):
        missing = [k for k in ("requested_budget_krw", "settlement_date", "contract_deadline") if plan[k] is None]
        if missing:
            raise ValueError(f"기안 {plan['plan_id']}에 비어 있는 항목: {missing}")
        ind = key_indicators(plan["influencer_id"] or "")
        total = self._plan_total(plan)
        pf = PlanFacts(plan["plan_id"], plan["campaign_id"] or "", plan["influencer_id"] or "",
                       plan["requested_budget_krw"], total, _d(plan["settlement_date"]),
                       _d(plan["contract_deadline"]), "확대", ind.good)
        return decide_plan(pf, windows), ind, total

    def _contract_decision(self, c: dict, windows: list[Window]):
        ind = key_indicators(c["influencer_code"])
        cf = ContractFacts(c["influencer_code"], c["annual_fixed_krw"], _d(c["notice_deadline"]),
                           _d(c["expiry_date"]), "갱신", ind.good)
        return decide_contract(cf, windows), ind

    def _logistics_text(self, plan: dict, vol: dict) -> str:
        d1 = _md(_d(plan["settlement_date"]))
        ask = "날짜별 ① 평소 안정적으로 처리하는 양 ② 최대 처리량(야근 포함)을 회신해 주세요."
        if vol["units"] is None:
            return f"{plan['plan_id']} 집행일 {d1}. 물량 {NO_VOLUME}(원본 표본이 없는 기안). {ask}"
        text = (f"{plan['plan_id']} 집행일 {d1}부터 예상 물량 총 {vol['units']:,}개"
                f"(하루 최대 {vol['peak_units']:,}개, {_md(_d(vol['peak_day']))}). {ask}")
        if vol["low_confidence"]:
            text += " (표본 쏠림으로 물량 추정 신뢰도 낮음)"
        return text

    def open_plan(self, plan_id: str, actor: str = "시스템") -> int:
        """등록부의 기안으로 사건을 연다(이미 있으면 그 사건). 물류에 처리 능력 요청을 보내고 회신 대기."""
        found = self._find_case(KIND_PLAN, plan_id)
        if found is not None:
            return found["id"]
        plan = self.store.get_plan(plan_id)
        dec, ind, total = self._plan_decision(plan, self._windows())
        vol = self._volume(plan)
        facts = {
            "plan_id": plan_id, "campaign_id": plan["campaign_id"], "influencer_id": plan["influencer_id"],
            "channel": plan["channel"], "amount_krw": plan["requested_budget_krw"], "plan_total_krw": total,
            "expected_gmv_krw": plan["expected_gmv_krw"], "settlement_date": plan["settlement_date"],
            "deadline": plan["contract_deadline"], "direction": "확대",
            "indicator_good": ind.good, "indicator_hits": _hits(ind.hits),
            "approvers": list(dec.approvers), "approver_hits": _hits(dec.hits), "approved_roles": [],
            "volume": vol, "allocation": ALLOC_HOLD, "warned": False, "phase1": None, "phase2": None,
        }
        cid = self.store.create_case(KIND_PLAN, plan_id, facts, S_DRAFT)
        if vol["units"] is None:
            self._task_once(cid, CAMPAIGN, "물량 입력", _d(plan["contract_deadline"]),
                            f"{plan_id}: {NO_VOLUME}. 입력 전에는 물류·재고 할당 판정을 보류한다")
        self.store.add_request(cid, LOGISTICS, self._logistics_text(plan, vol), False, purpose=P_LOGISTICS)
        self.store.set_status(cid, S_WAIT_REPLY, actor, "물류 처리 능력 회신 요청")
        return cid

    def open_contract(self, influencer_code: str, actor: str = "시스템") -> int:
        """등록부의 전속계약으로 갱신 검토 사건을 연다(이미 있으면 그 사건). 승인 대기."""
        found = self._find_case(KIND_CONTRACT, influencer_code)
        if found is not None:
            return found["id"]
        c = scenarios.registry_contract(self.store, influencer_code)
        if c is None:
            raise KeyError(f"등록부에 없는 전속계약: {influencer_code}")
        dec, ind = self._contract_decision(c, self._windows())
        facts = {
            "contract_row_id": c["id"], "influencer_code": influencer_code, "influencer_name": c["influencer_name"],
            "annual_fixed_krw": c["annual_fixed_krw"], "deadline": c["notice_deadline"], "expiry": c["expiry_date"],
            "auto_renew": c["auto_renew"], "direction": "갱신",
            "indicator_good": ind.good, "indicator_hits": _hits(ind.hits),
            "approvers": list(dec.approvers), "approver_hits": _hits(dec.hits), "approved_roles": [], "warned": False,
        }
        cid = self.store.create_case(KIND_CONTRACT, influencer_code, facts, S_REVIEW)
        self.store.set_status(cid, S_WAIT_APPROVAL, actor, "승인권자에게 갱신 여부 승인 요청")
        return cid

    # ---------------------------------------------------------------- 시연

    def seed(self, scenario: str) -> list[int]:
        """시연 파일을 읽어 검증한 뒤(실패하면 아무것도 지우지 않음) 시연 데이터를 초기화하고 등록·사건을 연다."""
        if self.store.get_mode() == MODE_OPERATION:
            raise PermissionError("시연 데이터는 시연 모드에서만 불러올 수 있음")
        sc = scenarios.load(scenario, self.demo_dir)
        scenarios.check_refs(self.store, sc)
        self.store.reset(scenarios.SEED_ACTOR)
        for pid in sc.plans:
            scenarios.register_plan(self.store, pid)
        for code in sc.contracts:
            scenarios.register_contract(self.store, code)
        ids = [self.open_plan(pid, scenarios.SEED_ACTOR) for pid in sc.plans]
        ids += [self.open_contract(code, scenarios.SEED_ACTOR) for code in sc.contracts]
        for r in sc.requests:
            cid = self._case_for(r)
            self.store.add_request(cid, r["dept"], r["text"], r.get("attach_required", False),
                                   purpose=r.get("purpose", ""))
        self.store.add_event(None, "시연불러오기", scenarios.SEED_ACTOR, {"scenario": scenario, "cases": ids})
        return ids

    def _case_for(self, item: dict) -> int:
        kind, ref = (KIND_PLAN, item["plan"]) if "plan" in item else (KIND_CONTRACT, item["contract"])
        found = self._find_case(kind, ref)
        if found is None:
            raise KeyError(f"사건 없음: {kind} {ref}")
        return found["id"]

    def _request_for(self, case_id: int, dept: str) -> int:
        """그 부서의 아직 처리되지 않은 마지막 요청(없으면 마지막 요청 — 중복 회신은 reply가 무시)."""
        rows = [r for r in self.store.list_requests(case_id) if r["dept"] == dept]
        if not rows:
            raise ValueError(f"사건 {case_id}에 {dept} 요청이 없음")
        open_rows = [r for r in rows if r["status"] != R_DONE]
        return (open_rows or rows)[-1]["id"]

    def play(self, step: dict) -> dict:
        """대본 한 단계를 실행한다(시연 조작판과 테스트가 같이 쓴다)."""
        moved: list[dict] = []
        if "date" in step:
            moved = self.advance(_d(step["date"]))
        action = step["action"]
        if action == "기준일":
            return {"action": action, "date": step["date"], "actions": moved}
        cid = self._case_for(step)
        if action == "회신":
            out = self.reply(self._request_for(cid, step["dept"]), step["text"], step.get("attachments", 0))
        elif action == "결정":
            out = self.decide(cid, step["actor"], step["decision"], step.get("comment", ""))
        elif action == "리뷰":
            g = self.add_reviews(cid, [(p, t) for p, t in step["reviews"]])
            out = {"case_id": cid, "status": self.store.get_case(cid)["status"], "gate": asdict(g)}
        else:
            g = self.add_returns(cid, step["change_of_mind"], step["color"])
            out = {"case_id": cid, "status": self.store.get_case(cid)["status"], "gate": asdict(g)}
        return {"action": action, "actions": moved, **out}

    def run_script(self, scenario: str, upto: int | None = None) -> list[dict]:
        sc = scenarios.load(scenario, self.demo_dir)
        return [self.play(s) for s in sc.script[:upto]]

    # ---------------------------------------------------------------- 기준일·기한

    def advance(self, to: date) -> list[dict]:
        """시연 시계를 하루씩 옮기며 날마다 기한(조기 경고·기본 거부)과 승인권자를 다시 본다. 운영 모드면 PermissionError."""
        if self.store.get_mode() == MODE_OPERATION:
            raise PermissionError(CLOCK_LOCKED)
        cur = self._today()
        if to < cur:
            raise ValueError(f"기준일은 뒤로 돌릴 수 없음: {cur} → {to}")
        cache: dict = {"windows": self._windows()}
        actions: list[dict] = []
        if to == cur:
            return self._daily(cur, cache)
        d = cur
        while d < to:
            d += timedelta(days=1)
            self.store.set_clock(d)
            actions += self._daily(d, cache)
        return actions

    def check_deadlines(self) -> list[dict]:
        """오늘(운영은 실제 오늘) 기준으로 기한·승인권자를 점검한다. 여러 번 불러도 같은 조치를 두 번 하지 않는다."""
        return self._daily(self._today(), {"windows": self._windows()})

    def _daily(self, d: date, cache: dict) -> list[dict]:
        out: list[dict] = []
        for case in self.store.list_cases():
            if case["status"] not in OPEN[case["kind"]]:
                continue
            out += self._recheck_approver(case, cache)
            case = self.store.get_case(case["id"])
            acts = deadline_actions(_d(case["facts"]["deadline"]), d, approved=False)
            if "기본거부" in acts:
                out.append(self._default_deny(case, d))
            elif "조기경고" in acts and not case["facts"].get("warned"):
                w = self._warn(case, d)
                if w:
                    out.append(w)
        return out

    def _recheck_approver(self, case: dict, cache: dict) -> list[dict]:
        """등록부·정책·하회 구간으로 승인권자를 다시 정하고, 바뀌면 권한 이동을 남긴다(설계 4.2)."""
        key = ("decision", case["id"])
        if key not in cache:
            if case["kind"] == KIND_PLAN:
                cache[key] = self._plan_decision(self.store.get_plan(case["ref_id"]), cache["windows"])[0]
            else:
                c = self.store.get_contract(case["facts"]["contract_row_id"])
                cache[key] = self._contract_decision(c, cache["windows"])[0]
        new = cache[key]
        f = case["facts"]
        at = _d(f["settlement_date"] if case["kind"] == KIND_PLAN else f["deadline"])
        change = diff_approver(_decision(f), new, at)
        if change is None:
            return []
        self.store.add_approver_change(case["id"], change)
        f["approvers"], f["approver_hits"] = list(new.approvers), _hits(new.hits)
        f["approved_roles"] = [r for r in f.get("approved_roles", []) if r in _required_roles(f)]
        self.store.update_facts(case["id"], f, "시스템", "승인권자 변경")
        return [{"date": self._today().isoformat(), "case_id": case["id"], "action": "권한이동",
                 "before": list(change.before), "after": list(change.after), "reason": change.reason}]

    def _warn(self, case: dict, d: date) -> dict | None:
        f = case["facts"]
        pending = _pending_roles(f)
        if not pending:
            return None
        chain = self.people.escalation
        lowest = min(pending, key=lambda r: chain.index(r) if r in chain else len(chain))
        target = self.people.above(lowest)
        deadline = _d(f["deadline"])
        text = f"{case['ref_id']} 확정 기한 {_md(deadline)} 전 미승인(승인권자 {'·'.join(pending)})"
        self.store.add_event(case["id"], EV_WARN, "시스템", {"target": target, "pending": pending, "text": text,
                                                         "deadline": f["deadline"]})
        f["warned"] = True
        self.store.update_facts(case["id"], f, "시스템", "조기 경고")
        return {"date": d.isoformat(), "case_id": case["id"], "action": "조기경고", "target": target, "text": text}

    def _default_deny(self, case: dict, d: date) -> dict:
        """기한까지 승인 없음 → 기본 거부(설계 3장 2번·4.3). 기안은 확정 보류(철회)."""
        deadline = _md(_d(case["facts"]["deadline"]))
        self.store.set_status(case["id"], S_DEFAULT_DENY, "시스템", f"확정 기한 {deadline}까지 승인 없음 — 기본 거부")
        status = S_DEFAULT_DENY
        if case["kind"] == KIND_PLAN:
            self.store.set_status(case["id"], S_HOLD, "시스템", "확정 보류(철회)")
            status = S_HOLD
            self._task_once(case["id"], CAMPAIGN, "확정 보류(철회) 처리", d,
                            f"{case['ref_id']}: 기한 {deadline}까지 승인이 없어 확정하지 않음. 상대측에 보류·철회를 알림")
        return {"date": d.isoformat(), "case_id": case["id"], "action": "기본거부", "status": status}

    # ---------------------------------------------------------------- 회신

    def reply(self, request_id: int, text: str, attachments: int = 0) -> dict:
        """회신 저장 → AI 해석 → (사람 확인 | 목적별 처리 → 상태 변경). 이미 처리된 요청이면 무시."""
        req = self.store.get_request(request_id)
        case = self.store.get_case(req["case_id"])
        base = {"request_id": request_id, "case_id": case["id"]}
        if req["status"] == R_DONE or case["status"] in TERMINAL[case["kind"]]:
            reason = "이미 처리된 요청" if req["status"] == R_DONE else "이미 끝난 건"
            return {**base, "ignored": True, "reason": reason, "needs_human": False, "changed": False,
                    "status": case["status"], "judgment": None}
        self.store.add_reply(request_id, text, attachments)
        j = judge.interpret_reply(self._provider("reply"), req["dept"], req["text"], text, self._today())
        result = {**asdict(j), "raw": j.raw[:RAW_KEEP]}
        needs_human = j.needs_human
        notes = []
        if req["attach_required"] and attachments <= 0:
            needs_human = True
            notes.append("필수 첨부 없음")
        self.store.add_judgment(case["id"], "회신해석", j.model, f"{req['dept']} 회신: {text}", result,
                                needs_human, j.confidence)
        if needs_human:
            why = "; ".join(notes + [f"AI 해석 {j.stance}"])
            self.store.set_request_status(request_id, R_HUMAN, "AI", why)
            self._task_once(case["id"], OWNER[case["kind"]], "회신 사람 확인", self._today(),
                            f"{req['dept']} 회신 '{text}' — {why}. 사람이 확인해 주세요")
            return {**base, "ignored": False, "needs_human": True, "changed": False,
                    "status": self.store.get_case(case["id"])["status"], "judgment": result}
        handler = self._handlers.get(req["purpose"])
        if handler is not None:
            handler(case["id"], req, j)
        self.store.set_request_status(request_id, R_DONE, "AI", f"AI 해석 {j.stance}")
        changed = self._after_requests(case["id"])
        return {**base, "ignored": False, "needs_human": False, "changed": changed,
                "status": self.store.get_case(case["id"])["status"], "judgment": result}

    def _after_requests(self, case_id: int) -> bool:
        case = self.store.get_case(case_id)
        if case["status"] != S_WAIT_REPLY:
            return False
        if any(r["status"] != R_DONE for r in self.store.list_requests(case_id)):
            return False
        self.store.set_status(case_id, S_WAIT_APPROVAL, "시스템", "부서 회신 완료, 승인권자 판단 대기")
        return True

    def _on_logistics(self, case_id: int, req: dict, j: judge.ReplyJudgment) -> None:
        f = self.store.get_case(case_id)["facts"]
        f["logistics"] = {"request_id": req["id"], "stance": j.stance, "qty_limit": j.qty_limit,
                          "next_date": j.next_date.isoformat() if j.next_date else None}
        if f["volume"]["units"] is None:
            f["allocation"] = ALLOC_HOLD  # 물량 입력 전에는 할당 판정 보류
        else:
            f["allocation"] = ALLOC_FULL if j.stance == "수용" else ALLOC_PARTIAL
        self.store.update_facts(case_id, f, "AI", "물류 회신 반영")

    def _on_content_fix(self, case_id: int, req: dict, j: judge.ReplyJudgment) -> None:
        f = self.store.get_case(case_id)["facts"]
        f["content_fix_confirmed"] = True
        self.store.update_facts(case_id, f, "AI", "콘텐츠 수정 확인(첨부 포함)")

    # ---------------------------------------------------------------- 결정

    def decide(self, case_id: int, actor: str, action: str, comment: str = "") -> dict:
        """승인권자의 결정. 승인권자가 아니면 PermissionError, 끝난 건이면 상태 그대로."""
        if action not in DECISIONS:
            raise ValueError(f"결정은 {', '.join(DECISIONS)} 중 하나: {action!r}")
        role = self.people.role_of(actor)
        case = self.store.get_case(case_id)
        f = case["facts"]
        required = _required_roles(f)
        if role not in required:
            raise PermissionError(f"{actor}({role})는 이 건의 승인권자가 아님 — 승인권자: {'·'.join(required)}")
        base = {"case_id": case_id, "actor": actor, "role": role, "action": action}
        if case["status"] not in OPEN[case["kind"]]:
            return {**base, "changed": False, "status": case["status"], "message": "이미 끝난 건이라 상태 그대로"}
        if action == D_REJECT:
            self.store.add_approval(case_id, (role,), action, actor, comment)
            self.store.set_status(case_id, S_REJECTED, actor, comment or "승인권자 거절")
            return {**base, "changed": True, "status": S_REJECTED}
        if case["status"] == S_WAIT_REPLY:
            raise ValueError("부서 회신을 기다리는 중이라 아직 승인할 수 없음")
        if action == D_SPLIT and not f.get("split"):
            raise ValueError("분할안이 없어 분할 승인할 수 없음")
        if role in f.get("approved_roles", []):
            return {**base, "changed": False, "status": case["status"], "message": "이미 승인함"}
        self.store.add_approval(case_id, (role,), action, actor, comment)
        f["approved_roles"] = [*f.get("approved_roles", []), role]
        if action == D_SPLIT:
            f["split_chosen"] = True
        self.store.update_facts(case_id, f, actor, f"{role} {action}")
        pending = _pending_roles(f)
        if pending:
            return {**base, "changed": True, "status": case["status"], "pending": pending}
        status = self._finalize(case_id, actor)
        return {**base, "changed": True, "status": status}

    def _finalize(self, case_id: int, actor: str) -> str:
        case = self.store.get_case(case_id)
        f = case["facts"]
        if case["kind"] == KIND_CONTRACT:
            self.store.set_status(case_id, S_RENEW_OK, actor, "승인권자 전원 승인")
            self._report(case)
            return S_RENEW_OK
        split = f.get("split") if f.get("split_chosen") else None
        if split:
            first = S_SPLIT_APPROVED
            f["phase1"] = {"qty": split["phase1_qty"], "date": split["phase1_date"]}
            f["phase2"] = ({"qty": split["phase2_qty"], "date": split["phase2_date"]}
                           if split["phase2_qty"] > 0 else None)
        else:
            first = S_APPROVED
            f["phase1"] = {"qty": f["volume"]["units"], "date": f["settlement_date"]}
            f["phase2"] = None
        self.store.update_facts(case_id, f, "시스템", "집행 수량 확정")
        self.store.set_status(case_id, first, actor, "승인권자 전원 승인")
        self._report(case)
        d1 = _d(f["phase1"]["date"])
        qty = f["phase1"]["qty"]
        qty_text = f"{qty:,}개" if qty is not None else f"수량 미정({NO_VOLUME})"
        self._task_once(case_id, LOGISTICS, "물류 출고", d1, f"{case['ref_id']} {_md(d1)}부터 1차 {qty_text} 출고")
        self._task_once(case_id, CS, "CS 대비", d1, f"{case['ref_id']} {_md(d1)}부터 1차 {qty_text} — 반품·문의 대비")
        self.store.set_status(case_id, S_PHASE1, "시스템", "1차 집행 시작")
        if f["phase2"]:
            self.store.set_status(case_id, S_PHASE2_LOCK, "시스템", OBSERVE_NOTE)
            return S_PHASE2_LOCK
        return S_PHASE1

    def _report(self, case: dict) -> None:
        for label in case["facts"]["approvers"]:
            if label in REPORT_ONLY:
                self.store.add_event(case["id"], EV_REPORT, "시스템",
                                     {"target": REPORT_ONLY[label], "text": f"{case['ref_id']} 승인 보고"})

    # ---------------------------------------------------------------- 리뷰·반품·2차

    def add_reviews(self, case_id: int, reviews: list[tuple[str, str]]) -> GateResult:
        """모의 리뷰를 AI로 해석한다. 색상불일치면 캠페인 담당에게 콘텐츠 수정 요청(첨부 필수), 2차는 잠금 유지."""
        case = self.store.get_case(case_id)
        owner = OWNER[case["kind"]]
        color = human = 0
        for product, text in reviews:
            self.store.add_review(case_id, product, text)
            j = judge.interpret_review(self._provider("review"), product, text)
            self.store.add_judgment(case_id, "리뷰해석", j.model, f"{product} 리뷰: {text}",
                                    {**asdict(j), "raw": j.raw[:RAW_KEEP]}, j.needs_human, j.confidence)
            color += int(j.reason == COLOR_REVIEW or j.content_gap)
            human += int(j.needs_human)
        f = self.store.get_case(case_id)["facts"]
        rev = f.get("reviews") or {"total": 0, "color": 0}
        rev = {"total": rev["total"] + len(reviews), "color": rev["color"] + color}
        f["reviews"] = rev
        if color and not f.get("content_fix_confirmed"):
            f["color_review_flagged"] = True
        self.store.update_facts(case_id, f, "AI", "리뷰 해석 반영")
        if f.get("color_review_flagged") and not f.get("content_fix_confirmed"):
            self._request_once(case_id, owner,
                               f"{case['ref_id']} 색상불일치 리뷰 {rev['color']}/{rev['total']}건 — 영상·상세페이지 색 표현을 "
                               "수정하고 수정본과 원본 대비 비교 자료를 첨부해 회신해 주세요", True, P_CONTENT)
        if human:
            self._task_once(case_id, owner, "리뷰 사람 확인", self._today(), f"AI가 확신하지 못한 리뷰 {human}건")
        return self._gate(self.store.get_case(case_id))

    def add_returns(self, case_id: int, change_of_mind: int, color: int) -> GateResult:
        """시연용 모의 반품(1차 기준 건수). 통계 기준(기준선 = 과거 건수 반품률)을 넘으면 2차 자동 보류."""
        if change_of_mind < 0 or color < 0:
            raise ValueError("반품 건수는 0 이상")
        f = self.store.get_case(case_id)["facts"]
        f["returns"] = {"change_of_mind": change_of_mind, "color": color, "date": self._today().isoformat()}
        self.store.update_facts(case_id, f, "시스템", "모의 반품 반영")
        case = self.store.get_case(case_id)
        g = self._gate(case)
        if g.auto_stopped and case["status"] == S_PHASE2_LOCK:
            self.store.set_status(case_id, S_PHASE2_HOLD, "시스템", "; ".join(g.reasons))
        return g

    def _renewal_confirmed(self, influencer_code: str) -> bool:
        return any(c["ref_id"] == influencer_code and c["status"] in RENEWAL_CONFIRMED
                   for c in self.store.list_cases(KIND_CONTRACT))

    def _gate(self, case: dict) -> GateResult:
        f = case["facts"]
        review_actions = (("콘텐츠 수정 요청", "사람 확인")
                          if f.get("color_review_flagged") and not f.get("content_fix_confirmed") else ())
        p2 = f.get("phase2")
        if not p2:
            return GateResult(False, False, ("2차 집행 없음",), review_actions)
        p1 = f.get("phase1") or {}
        inf = f.get("influencer_id") or ""
        contract = scenarios.registry_contract(self.store, inf)
        end = _d(contract["expiry_date"]) if contract else date.max
        renewal = True if contract is None else self._renewal_confirmed(inf)
        p1_date = _d(p1["date"]) if p1.get("date") else self._today()
        r = f.get("returns") or {}
        return phase2_gate(
            phase1_orders=p1.get("qty") or 0,
            change_of_mind_returns=r.get("change_of_mind", 0), color_returns=r.get("color", 0),
            baseline_change_of_mind=return_count_rate(inf, CHANGE_OF_MIND),
            baseline_color=return_count_rate(inf, COLOR_RETURN),
            days_since_phase1=(self._today() - p1_date).days,
            color_review_flagged=bool(f.get("color_review_flagged")),
            content_fix_confirmed=bool(f.get("content_fix_confirmed")),
            renewal_confirmed=renewal,
            phase2_date=_d(p2["date"]) if p2.get("date") else date.max,
            contract_end=end,
        )

    # ---------------------------------------------------------------- 화면용 읽기

    @staticmethod
    def _item(c: dict) -> dict:
        return {"case_id": c["id"], "kind": c["kind"], "ref_id": c["ref_id"], "status": c["status"],
                "deadline": c["facts"].get("deadline")}

    def todo(self, person: str) -> dict:
        """사람별 할 일(설계 6.2): 승인 대기, 기한 임박, 회신 대기, 작업, 권한 이동, 알림."""
        role = self.people.role_of(person)
        out: dict = {"person": person, "role": role, "승인 대기": [], "기한 임박": [], "회신 대기": [],
                     "작업": [], "권한 이동": [], "알림": []}
        cases = {c["id"]: c for c in self.store.list_cases()}
        for c in cases.values():
            if c["status"] == S_WAIT_APPROVAL and role in _pending_roles(c["facts"]):
                out["승인 대기"].append(self._item(c))
            for ch in self.store.get_approver_changes(c["id"]):
                before = {_role(x) for x in ch.before if x not in REPORT_ONLY}
                after = {_role(x) for x in ch.after if x not in REPORT_ONLY}
                if role in before and role not in after:
                    out["권한 이동"].append({**self._item(c), "reason": ch.reason})
        for e in self.store.events(kind=EV_WARN):
            c = cases.get(e["case_id"])
            if c and e["detail"]["target"] == role and c["status"] in OPEN[c["kind"]]:
                out["기한 임박"].append({**self._item(c), "text": e["detail"]["text"]})
        for e in self.store.events(kind=EV_REPORT):
            c = cases.get(e["case_id"])
            if c and e["detail"]["target"] == role:
                out["알림"].append({**self._item(c), "text": e["detail"]["text"]})
        for r in self.store.all_requests(dept=role):
            if r["status"] != R_DONE and r["case_id"] in cases:
                out["회신 대기"].append({**self._item(cases[r["case_id"]]), "request_id": r["id"], "text": r["text"],
                                      "request_status": r["status"], "attach_required": r["attach_required"]})
        for t in self.store.all_tasks(dept=role):
            if t["status"] == "대기" and t["case_id"] in cases:
                out["작업"].append({**self._item(cases[t["case_id"]]), "task_id": t["id"], "title": t["title"],
                                  "detail": t["detail"], "due": t["due"]})
        return out

    def calendar(self) -> list[dict]:
        """캘린더(설계 6.2): 하회 구간, 확정·통보 기한, 집행일, 2차 집행일, 계약 만료, 작업 기한. 날짜순."""
        out: list[dict] = []

        def add(day: str, kind: str, label: str, case_id=None, roles=(), end=None):
            out.append({"date": day, "end": end, "kind": kind, "label": label, "case_id": case_id, "roles": list(roles)})

        for w in self._windows():
            add(w.start.isoformat(), "하회 구간", f"현금 하회 구간 {_md(w.start)}~{_md(w.end)}", end=w.end.isoformat())
        with_case = set()
        for c in self.store.list_cases():
            f = c["facts"]
            pending = _pending_roles(f) if c["status"] in OPEN[c["kind"]] else []
            if c["kind"] == KIND_PLAN:
                add(f["deadline"], "확정 기한", f"{c['ref_id']} 확정 기한", c["id"], pending)
                add(f["settlement_date"], "집행일", f"{c['ref_id']} 집행일", c["id"], [CAMPAIGN])
                if f.get("phase2") and f["phase2"].get("date"):
                    add(f["phase2"]["date"], "2차 집행일", f"{c['ref_id']} 2차 집행일", c["id"], [CAMPAIGN])
            else:
                with_case.add(f["contract_row_id"])
                add(f["deadline"], "통보 기한", f"{c['ref_id']} 해지·조건변경 통보 기한", c["id"], pending)
                add(f["expiry"], "계약 만료", f"{c['ref_id']} 계약 만료", c["id"], [CONTRACT_OWNER])
        for k in self.store.list_contracts():
            if k["id"] not in with_case:
                add(k["notice_deadline"], "통보 기한", f"{k['influencer_code']} 해지·조건변경 통보 기한", None, [CONTRACT_OWNER])
                add(k["expiry_date"], "계약 만료", f"{k['influencer_code']} 계약 만료", None, [CONTRACT_OWNER])
        for t in self.store.all_tasks():
            if t["status"] == "대기":
                add(t["due"], "작업", t["title"], t["case_id"], [t["dept"]])
        out.sort(key=lambda e: (e["date"], e["kind"]))
        return out
