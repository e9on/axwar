"""이벤트 엔진(설계 7.2·7.3·7.4): 기준일 이동 시 기한 점검, 회신 저장 → AI 해석 → 규칙 → 상태 변경 → 작업 생성.

- 엔진은 등록부(DB)의 기안·계약만 본다. 장면 숫자·ID·날짜·문구는 없다(시연 파일과 테스트에만).
- 오늘 = store.get_clock()(운영은 실제 오늘, 시연은 시연 시계). advance는 시연 전용, 운영은 check_deadlines.
- 권한은 역할로 판정한다(보는 사람 → 역할은 사람 목록 파일). 승인권자는 rules.approver가 정한다.
- AI 판정은 ai_judgments(store.add_judgment)에, 비용은 제공자(BudgetedProvider)가 ai_calls에 남긴다.
- 부서 요청은 목적(purpose)을 달고, 회신이 수용으로 해석되면 목적별 처리기(_handlers)가 사실을 바꾼다.
  처리기가 사람 확인 사유(문자열)를 돌려주면 사실을 바꾸지 않고 사람 확인으로 넘긴다.
- 물류가 회신하면 모든 건이 재고 장부(calc.inventory)와 같은 퍼센트 배분(rules.allocate)으로 1차 집행일의
  쓸 수 있는 재고를 본다(처리량 숫자가 없으면 처리 능력 제한 없음). 요청 단위는 집행일 하루 수량이다.
  모자라면 SCM에 안전재고 사용을 묻고 수량은 SCM이 정하며, 분할안이 바뀌면 재승인이다.
  SCM 거절·무응답(scm.no_reply_days)은 장부를 앞으로 돌려 여유가 1차 수량 이상 생기는 첫날로 연기하고, 없거나 계약 만료 뒤면 1차 차단.
  등록부 집행일이 바뀌면 재고 점검·분할안을 새 날짜로 다시 돌린다.
- 2차 승인·집행(설계 7.3): 2차 게이트가 모두 풀리고 판매율 판정이 조절·유지(보류 아님)로 끝나면 2차 승인 대기. 승인 기한 =
  2차 집행일 - deadline.buffer_days에 기본 거부(승인은 그 전날까지). 진입일 + phase2.min_approval_days가 그보다 늦으면 집행일을 진입일 + 그 일수 + 여유일로 민다. 조기 경고·방치 올림·기본 거부는 1차와 같은 장치.
  모두 승인 → 2차 집행(물류 출고·CS 대비, 날짜 = 2차 집행일) → 집행일이 지나면 완료. 거절·기본 거부 → 2차 없이 완료(통보 없음).
- 시연·운영 분리(최종 수정 H1): 기준일 이동·일일 점검·대본·할 일·캘린더·재고 장부·갱신 확정은 지금 모드의 사건(origin)만 본다.
  운영 모드는 API 요청이 들어올 때 오늘 점검이 안 돌았으면 먼저 돌린다(ensure_daily_check). 결정·상신도 확정 기한이 지났으면(당일까지 허용) 기본 거부.
- 계약 건 거절·기본 거부는 모두 조건변경 통보 초안으로 이어진다(통보 기한이 지나도록 미발송이면 경고·방치 올림).
- 1차 날짜는 phase1_date(등록부 집행일에서 엔진이 옮긴 날짜 shift 포함), 2차는 STAGES["2차"]에 따로 둔다.
"""
from __future__ import annotations

import functools
import hashlib
import json
import logging
import threading
from dataclasses import asdict, replace
from datetime import date, timedelta
from pathlib import Path

from app import policy
from app.ai import judge, writer
from app.ai.providers import Provider, make_provider
from app.calc import inventory
from app.calc import volume as volume_calc
from app.calc.campaign import return_count_rate
from app.calc.cash import Window, breach_windows, forecast_window, simulate_cash
from app.calc.indicators import contract_indicators, plan_indicators
from app.data import loader
from app.engine import scenarios
from app.rules.allocate import allocate_day, can_announce, stock_alerts, stockout_days_earlier, usable_capacity
from app.rules.approver import decide_contract, decide_plan, diff_approver
from app.rules.capacity import parse_capacity
from app.rules.deadline import approval_deadline, deadline_actions, deny_date, is_lapsed
from app.rules.models import ApproverChange, ApproverDecision, ContractFacts, PlanFacts, RuleHit
from app.rules.split import GateResult, make_split, phase2_gate
from app.store.db import CASE_DEMO, CASE_OPERATION, CLOCK_LOCKED, MODE_OPERATION, Store

KIND_PLAN, KIND_CONTRACT = "기안", "계약"

# 상태(설계 7.3 캠페인 확대 건, 7.4 전속계약 건)
S_DRAFT, S_WAIT_REPLY, S_WAIT_APPROVAL = "기안", "회신 대기", "승인 대기"
S_APPROVED, S_SPLIT_APPROVED, S_REJECTED = "승인", "분할 승인", "거절"
S_DEFAULT_DENY, S_HOLD = "기본 거부", "확정 보류"
S_PHASE1, S_PHASE2_LOCK, S_PHASE2_HOLD, S_DONE = "1차 집행", "2차 잠금", "2차 보류", "완료"
S_PHASE2_WAIT, S_PHASE2_EXEC = "2차 승인 대기", "2차 집행"  # 설계 7.3: 2차 잠금 → 2차 승인 대기 → (2차 집행 →) 완료
S_REVIEW, S_RENEW_OK, S_CHANGE_OK, S_AGREED = "검토", "갱신 승인", "조건변경 승인", "합의"
S_REAPPROVAL = "재승인 대기"  # 받은 승인이 무효가 되어 새로 받아야 함(설계 4.1·4.2 변경 통보)
S_PHASE2_BLOCKED = "2차 차단"  # 갱신 미확정인데 2차 집행일이 계약 만료 뒤(설계 4.6)
S_PHASE1_BLOCKED = "1차 차단"  # SCM 거절 뒤 장부를 돌려도 1차 수량을 받칠 날이 없거나 계약 만료 뒤(사용자 결정 2026-11-11)
S_NOTICE_DRAFT, S_NOTICE_SENT, S_WAIT_PARTNER, S_HUMAN = "통보 초안", "통보 발송", "상대 회신 대기", "사람 확인"
APPROVAL_STATES = (S_WAIT_APPROVAL, S_REAPPROVAL)
OPEN = {KIND_PLAN: (S_WAIT_REPLY, *APPROVAL_STATES), KIND_CONTRACT: (S_REVIEW, *APPROVAL_STATES)}
TERMINAL = {KIND_PLAN: (S_REJECTED, S_HOLD, S_DONE, S_PHASE1_BLOCKED), KIND_CONTRACT: (S_REJECTED, S_AGREED)}
CONTRACT_ENDED = (*TERMINAL[KIND_CONTRACT], S_RENEW_OK)  # 이 상태면 같은 인플루언서의 다음 계약 기간 사건을 새로 열 수 있다(M2)
RENEWAL_CONFIRMED = (S_RENEW_OK, S_CHANGE_OK, S_AGREED)

# 요청 상태와 목적
R_WAIT, R_HUMAN, R_DONE = "대기", "사람 확인", "처리됨"
P_LOGISTICS, P_CONTENT = "물류 처리 능력", "콘텐츠 수정"
P_STOCK, P_NOTICE = "안전재고 사용", "통보 회신"  # SCM의 안전재고 사용 응답 / 인플루언서 측의 통보 회신

# 역할
SCM, MARKETING, PARTNER = "SCM", "마케팅팀", "인플루언서 측"
LIVE = "라이브"  # 원본 판매 채널 값: 라이브 방송 판매는 전용 코드로 효과를 가른다
# 거절이 "애매한 회신"이 아니라 그 부서의 결정인 요청 목적(SCM이 안전재고 사용을 거절하는 것은 정해진 답)
DEFINITIVE_REFUSAL = (P_STOCK,)
# 값이 역할 목록(쉼표로 구분)인 정책 항목: 바꿀 때 모르는 역할을 넣을 수 없다
ROLE_KEYS = ("roles.campaign", "roles.contract", "roles.logistics", "roles.cs")  # 값이 역할 하나인 정책 항목: 사람 목록에 있는 역할이어야 한다
ROLE_LIST_KEYS = ("admin.policy_editors", "admin.review_inputters", "admin.return_inputters", "admin.registry_editors")
# 조건변경 통보 재협상안(설계 5.2): 성과 피 기준을 총매출이 아니라 공제 후 순액으로. 고정 피 금액은 시스템이 정하지 않는다.
NET_BASE = "공제 후 순액"
NET_DEDUCTIONS = ("반품 환불", "쿠폰", "채널 수수료")
# 승인권자 표기(rules.approver) → 승인하는 역할. 보고만 받는 표기는 승인 대상이 아니다.
APPROVER_ROLE = {"이사회 의결": "이사회", "그룹 확인": "그룹"}
REPORT_ONLY = {"그룹 보고": "그룹"}

DECISIONS = scenarios.DECISIONS
D_APPROVE, D_SPLIT, D_REJECT = DECISIONS
CHANGE_OF_MIND, COLOR_RETURN = "단순변심", "색상불만"  # 원본 반품 사유 값
COLOR_REVIEW = "색상불일치"  # 리뷰 해석 사유 값
NO_VOLUME = "추정 불가 — 담당자 입력 필요"
ALLOC_HOLD, ALLOC_FULL, ALLOC_PARTIAL = "보류", "전량", "조건부"
TASK_VOLUME = "물량 입력"  # 원본 표본이 없는 기안의 물량을 담당자가 넣는 작업(제목)
EV_WARN, EV_REPORT, EV_REAPPROVE, EV_DRIFT = "조기경고", "그룹보고", "재승인알림", "등록부변경경고"
EV_SPLIT, EV_STOCK, EV_ANNOUNCE, EV_BLOCK = "분할안변경", "재고부족", "공지", "1차차단"
EV_UNBLOCK = "차단해제"  # 등록부 집행일을 고쳐 1차 차단이 풀림(사용자 결정 2026-11-11)
EV_SELL = "판매율조절"  # 1차 판매 실적(판매율)으로 2차 수량을 조절·보류·품절 기록(추가 결정 8)
EV_DATE = "집행일 변경"  # 1차·2차 집행일이 바뀐 그때 관련자에게(사용자 결정 2026-11-12)
EV_ALARM = "마감 알림"  # 마지막 승인일(기본 거부 전날)에 남은 승인권자 본인에게(사용자 결정 2026-11-12)
EV_STALE = "방치올림"  # 담당이 처리하지 않은 사람 확인·판단을 상급자에게 올림(추가 결정 9)
EV_DECIDE = "판매율판단"  # 판매율 보류 건에 대한 담당의 2차 계속·취소 판단(컨트롤러 판정 10)
STALE_SCM_HUMAN, STALE_PHASE2_HOLD = "SCM 사람 확인", "2차 보류 판단"  # 방치 올림 대상 종류(두 번째는 작업 제목과 같음)
STALE_PHASE2_WAIT = "2차 승인"  # 2차 승인 대기 건의 방치 올림 키
STALE_NOTICE = "통보 발송"  # 통보 기한이 지나도록 통보 초안이 발송되지 않은 계약 건의 방치 올림 키(작업 제목과 같음)
EV_P2_HOLD, EV_P2_EXCEPTION = "2차보류", "2차예외승인"
CHOICE_EXCEPTION = "예외 승인"
EV_P2_WAIT, EV_P2_DECIDE, EV_P2_DONE = "2차승인대기", "2차결정", "2차완료"
P2_REJECT, P2_DENY, P2_EXECUTED = "거절", "기본 거부", "집행"  # phase2_result.result 값
P2_NONE = "2차 없음"  # 2차 취소·판매율 조절 0개로 2차가 없어진 건이 반품 관찰을 마치고 완료될 때의 결과
EV_P2_SHIFT = "2차집행일연기"  # 승인 기간을 확보하려고 2차 집행일을 민 일
EV_UP, EV_UP_VOID = "상신", "상신무효"  # 승인권자가 자기 권한을 넘는다며 상급자에게 올림 / 등록부 변경 등으로 결재선이 다시 정해져 무효
UP_OPINIONS = scenarios.UP_OPINIONS
UP_LABEL = {v: k for k, v in APPROVER_ROLE.items()}  # 역할 -> 승인권자 표기(이사회 -> 이사회 의결)
P2_DECISIONS = (D_APPROVE, D_REJECT)  # 2차 결정은 분할 승인이 없다
CHOICE_CONTINUE, CHOICE_CANCEL = "2차 계속", "2차 취소"
NO_SALES = "1차 판매 실적 미입력"
SELL_ADJUST, SELL_HOLD, SELL_SOLDOUT = "조절", "보류", "품절"
SCM_ASKED, SCM_FULL, SCM_PARTIAL, SCM_REFUSED = "요청", "전량 허용", "일부 허용", "거절"
ORDER_ADJUST, MEASURE = "발주 조정 요청", "측정 요청"
# 사건 사실 ← 등록부 열(등록부가 원천). 바뀌면 사실을 새로 읽고 다시 판정한다.
SYNC_FIELDS = {
    KIND_PLAN: {"amount_krw": "requested_budget_krw", "settlement_date": "settlement_date",
                "deadline": "contract_deadline", "expected_gmv_krw": "expected_gmv_krw",
                "campaign_id": "campaign_id", "influencer_id": "influencer_id", "channel": "channel"},
    KIND_CONTRACT: {"annual_fixed_krw": "annual_fixed_krw", "deadline": "notice_deadline",
                    "expiry": "expiry_date", "auto_renew": "auto_renew"},
}
# 이미 받은 승인을 무효로 만드는 등록부 사실(승인한 내용 자체가 바뀜). 승인권자 구성이 바뀌어도 무효.
# 분할 수량 변경(11b)은 등록부가 아니라 엔진이 바꾸므로 그 자리에서 _invalidate(material=["split"])를 부른다.
MATERIAL = {KIND_PLAN: ("amount_krw", "settlement_date"), KIND_CONTRACT: ("annual_fixed_krw",)}
LABELS = {"amount_krw": "요청액", "settlement_date": "집행일", "phase1_date": "1차 집행일", "deadline": "기한", "expected_gmv_krw": "예상 GMV",
          "plan_total_krw": "기안 총액", "annual_fixed_krw": "연 고정 피", "expiry": "계약 만료", "split": "분할안"}
# 승인 단계: 단계마다 (승인권자, 근거, 받은 승인, 판정 기준 날짜) 사실 키. 11b는 "2차"를 더한다.
# 1차 날짜는 등록부 집행일이 아니라 phase1_date다: SCM 거절로 연기한 날짜(shift)는 등록부를 고치지 않고 별도 키에 둔다.
STAGES = {"1차": ("approvers", "approver_hits", "approved_roles", "phase1_date"),
          "2차": ("phase2_approvers", "phase2_approver_hits", "phase2_approved_roles", "phase2_date")}
RAW_KEEP = 500  # AI 원문은 이 글자 수까지만 판정 기록에 남긴다
OBSERVE_NOTE = "2차는 반품 관찰 뒤 열림"


def _d(s: str) -> date:
    return date.fromisoformat(s)


def _md(d: date) -> str:
    return f"{d.month}/{d.day}"


def _hits(hits) -> list[dict]:
    return [{"rule_id": h.rule_id, "text": h.text, "source": h.source, "badge": h.badge} for h in hits]


def _decision(f: dict, stage: str = "1차") -> ApproverDecision:
    a, h, _, _ = STAGES[stage]
    return ApproverDecision(tuple(f[a]), tuple(RuleHit(**x) for x in f[h]))


def _role(label: str) -> str:
    return APPROVER_ROLE.get(label, label)


def _required_roles(f: dict, stage: str = "1차") -> list[str]:
    out: list[str] = []
    for label in f[STAGES[stage][0]]:
        if label not in REPORT_ONLY and _role(label) not in out:
            out.append(_role(label))
    return out


def _pending_roles(f: dict, stage: str = "1차") -> list[str]:
    done = set(f.get(STAGES[stage][2], []))
    return [r for r in _required_roles(f, stage) if r not in done]


def _show(key: str, v) -> str:
    if isinstance(v, str) and len(v) == len(date.min.isoformat()):
        try:
            return _md(_d(v))
        except ValueError:
            return v
    if isinstance(v, int) and not isinstance(v, bool):
        return f"{v:,}원"
    return str(v)


def _locked(method):
    """엔진의 변경 메서드는 한 번에 하나씩(읽고-판단하고-쓰는 사이에 다른 호출이 끼지 않게)."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


logger = logging.getLogger(__name__)

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
        self._handlers = {P_LOGISTICS: self._on_logistics, P_CONTENT: self._on_content_fix,
                          P_STOCK: self._on_stock, P_NOTICE: self._on_notice}
        self._lock = threading.RLock()
        self._check_roles()

    # ---------------------------------------------------------------- 기반

    # 담당 역할 이름은 코드가 아니라 정책(roles.*)에서 호출 시점에 읽는다
    @property
    def campaign(self) -> str:
        return policy.get("roles.campaign")

    @property
    def contract_owner(self) -> str:
        return policy.get("roles.contract")

    @property
    def logistics(self) -> str:
        return policy.get("roles.logistics")

    @property
    def cs(self) -> str:
        return policy.get("roles.cs")

    def _volume_due(self, deadline: date) -> date:
        """물량 입력 기한 = 마지막 승인일 - volume.input_lead_days(물량이 들어온 뒤 결재할 시간). 오늘보다 이르면 오늘."""
        return max(self._today(), approval_deadline(deadline) - timedelta(days=policy.get("volume.input_lead_days")))

    def _sync_volume_task(self, case_id: int, deadline: date, actor: str) -> None:
        for t in self.store.list_tasks(case_id):
            if t["title"] == TASK_VOLUME and t["status"] != "완료":
                self.store.set_task_due(t["id"], self._volume_due(deadline), actor)

    def _close_volume_tasks(self, case_id: int) -> None:
        for t in self.store.list_tasks(case_id):
            if t["title"] == TASK_VOLUME and t["status"] != "완료":
                self.store.set_task_status(t["id"], "완료", "시스템")

    def _owner(self, kind: str) -> str:
        return self.campaign if kind == KIND_PLAN else self.contract_owner

    def _check_roles(self) -> None:
        """정책의 담당 역할이 사람 목록에 모두 있는지. 저장된 덮어쓰기(DB)가 어긋난 것은 이번 실행에서 적용하지 않고
        경고 이벤트를 남긴다(서버가 못 뜨면 화면에서 고칠 길이 없으므로). 정책 파일 값 자체가 어긋나면 오류."""
        have = set(self.people.people.values())
        for key in ROLE_KEYS:
            if policy.get(key) not in have and policy.is_overridden(key):
                stored, default = policy.get(key), policy.base_entry(key)[0]
                policy.drop_override(key)
                if default in have:
                    text = f"정책 {key}의 저장된 값 '{stored}'이 사람 목록에 없어 기본값 '{default}'으로 시작함"
                    logger.warning(text)
                    self.store.add_event(None, "정책덮어쓰기무시", "시스템", {"key": key, "stored": stored, "default": default, "text": text})
        missing = [f"{k}={policy.get(k)!r}" for k in ROLE_KEYS if policy.get(k) not in have]
        if missing:
            raise ValueError(f"사람 목록에 없는 담당 역할이 정책에 있음: {', '.join(missing)} — 사람 목록의 역할: {', '.join(sorted(have))}")

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

    def _mode_origin(self) -> str:
        """지금 모드가 다루는 사건 출처: 운영 모드는 운영 사건, 시연 모드는 시연 사건(H1: 서로의 사건을 건드리지 않는다)."""
        return CASE_OPERATION if self.store.get_mode() == MODE_OPERATION else CASE_DEMO

    def _cases(self, kind: str | None = None) -> list[dict]:
        """지금 모드의 사건만(기준일 이동·점검·대본·할 일·캘린더·재고 장부·갱신 확정이 모두 이것을 본다)."""
        origin = self._mode_origin()
        return [c for c in self.store.list_cases(kind) if c["origin"] == origin]

    def _find_case(self, kind: str, ref_id: str) -> dict | None:
        rows = [c for c in self._cases(kind) if c["ref_id"] == ref_id]
        return rows[-1] if rows else None

    def _guard_open(self, kind: str, ref_id: str) -> None:
        """운영 모드에서 시연 등록부 행으로는 사건을 열 수 없다(시연 출처 사건은 운영 점검이 보지 않으므로)."""
        if self.store.case_origin(kind, ref_id) != self._mode_origin():
            raise ValueError(f"{ref_id}는 시연 등록부 행이라 운영 모드에서 사건을 열 수 없음")

    def role_of(self, person: str) -> str:
        """보는 사람의 역할. 역할 이름을 사람 대신 받는 것은 시연 모드에서만."""
        return self.people.role_of(person, allow_role_names=self.store.get_mode() != MODE_OPERATION)

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

    def _plan_decision(self, plan: dict, windows: list[Window], on: date | None = None):
        """on = 승인권자 판정에 쓰는 1차 집행일(연기했으면 연기한 날, 없으면 등록부 집행일)."""
        missing = [k for k in ("requested_budget_krw", "settlement_date", "contract_deadline") if plan[k] is None]
        if missing:
            raise ValueError(f"기안 {plan['plan_id']}에 비어 있는 항목: {missing}")
        ind = plan_indicators(plan["plan_id"])
        total = self._plan_total(plan)
        pf = PlanFacts(plan["plan_id"], plan["campaign_id"] or "", plan["influencer_id"] or "",
                       plan["requested_budget_krw"], total, on or _d(plan["settlement_date"]),
                       _d(plan["contract_deadline"]), "확대", ind.good)
        return decide_plan(pf, windows), ind, total

    def _contract_decision(self, c: dict, windows: list[Window]):
        ind = contract_indicators(c["influencer_code"])
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

    @_locked
    def open_plan(self, plan_id: str, actor: str = "시스템") -> int:
        """등록부의 기안으로 사건을 연다(이미 있으면 그 사건). 물류에 처리 능력 요청을 보내고 회신 대기."""
        found = self._find_case(KIND_PLAN, plan_id)
        if found is not None:
            return found["id"]
        plan = self.store.get_plan(plan_id)
        self._guard_open(KIND_PLAN, plan_id)
        dec, ind, total = self._plan_decision(plan, self._windows())
        vol = self._volume(plan)
        facts = {
            "plan_id": plan_id, "campaign_id": plan["campaign_id"], "influencer_id": plan["influencer_id"],
            "channel": plan["channel"], "amount_krw": plan["requested_budget_krw"], "plan_total_krw": total,
            "expected_gmv_krw": plan["expected_gmv_krw"], "settlement_date": plan["settlement_date"],
            "deadline": plan["contract_deadline"], "direction": "확대",
            "indicator_good": ind.good, "indicator_hits": _hits(ind.hits), "indicator_excluded": list(ind.excluded),
            "approvers": list(dec.approvers), "approver_hits": _hits(dec.hits), "approved_roles": [],
            "volume": vol, "allocation": ALLOC_HOLD, "warned_targets": [], "phase1": None, "phase2": None,
            "phase1_date": plan["settlement_date"], "shift": None, "split": None, "stock": None, "scm": None,
            "curve_anchor": plan["settlement_date"],  # 일별 물량 곡선이 놓인 집행일(등록부 집행일을 옮기면 곡선도 같은 만큼 옮김)
        }
        cid = self.store.create_case(KIND_PLAN, plan_id, facts, S_DRAFT)
        if vol["units"] is None:
            self._task_once(cid, self.campaign, TASK_VOLUME, self._volume_due(_d(plan["contract_deadline"])),
                            f"{plan_id}: {NO_VOLUME}. 입력 전에는 물류·재고 할당 판정을 보류한다")
        self.store.add_request(cid, self.logistics, self._logistics_text(plan, vol), False, purpose=P_LOGISTICS)
        self.store.set_status(cid, S_WAIT_REPLY, actor, "물류 처리 능력 회신 요청")
        return cid

    @_locked
    def open_contract(self, influencer_code: str, actor: str = "시스템") -> int:
        """등록부의 전속계약으로 갱신 검토 사건을 연다(이미 있으면 그 사건). 승인 대기."""
        c = scenarios.registry_contract(self.store, influencer_code)
        if c is None:
            raise KeyError(f"등록부에 없는 전속계약: {influencer_code}")
        mine = [x for x in self._cases(KIND_CONTRACT) if x["ref_id"] == influencer_code]
        same_period = [x for x in mine if x["facts"].get("contract_row_id") == c["id"]]
        if same_period:
            return same_period[-1]["id"]
        if mine and mine[-1]["status"] not in CONTRACT_ENDED:
            return mine[-1]["id"]  # 이전 기간 사건이 아직 진행 중이면 그 사건(끝난 뒤에야 다음 기간 사건을 연다)
        self._guard_open(KIND_CONTRACT, influencer_code)
        dec, ind = self._contract_decision(c, self._windows())
        facts = {
            "contract_row_id": c["id"], "influencer_code": influencer_code, "influencer_name": c["influencer_name"],
            "annual_fixed_krw": c["annual_fixed_krw"], "deadline": c["notice_deadline"], "expiry": c["expiry_date"],
            "auto_renew": c["auto_renew"], "direction": "갱신",
            "indicator_good": ind.good, "indicator_hits": _hits(ind.hits), "indicator_excluded": list(ind.excluded),
            "approvers": list(dec.approvers), "approver_hits": _hits(dec.hits), "approved_roles": [], "warned_targets": [],
        }
        cid = self.store.create_case(KIND_CONTRACT, influencer_code, facts, S_REVIEW)
        self.store.set_status(cid, S_WAIT_APPROVAL, actor, "승인권자에게 갱신 여부 승인 요청")
        return cid

    # ---------------------------------------------------------------- 시연

    @_locked
    def seed(self, scenario: str) -> list[int]:
        """시연 파일을 읽어 검증한 뒤(실패하면 아무것도 지우지 않음) 시연 데이터를 초기화하고 등록·사건을 연다."""
        if self.store.get_mode() == MODE_OPERATION:
            raise PermissionError("시연 데이터는 시연 모드에서만 불러올 수 있음")
        sc = scenarios.load(scenario, self.demo_dir)
        scenarios.check_refs(self.store, sc)
        self.store.reset(scenarios.SEED_ACTOR)
        for pid in sc.plans:
            scenarios.register_plan(self.store, pid)
        for code in (*sc.contracts, *sc.register_contracts):  # 등록만 하는 계약은 사건을 열지 않는다
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
        """대본 한 단계를 실행한다(시연 조작판과 테스트가 같이 쓴다). 시연 모드에서만."""
        self._demo_only("대본 재생")
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
            decide = self.decide_phase2 if step.get("stage") == "2차" else self.decide
            out = decide(cid, step["actor"], step["decision"], step.get("comment", ""))
        elif action == "공지":
            out = self.announce(cid, step["actor"])
        elif action == "발송":
            out = self.send_notice(cid, step["actor"])
        elif action == "리뷰":
            g = self.add_reviews(cid, [(p, t) for p, t in step["reviews"]])
            out = {"case_id": cid, "status": self.store.get_case(cid)["status"], "gate": asdict(g)}
        elif action == "상신":
            out = self.escalate(cid, step["actor"], step["stage"], step["opinion"], step["reason"])
        elif action == "예외 승인":
            out = self.approve_phase2_exception(cid, step["actor"], step["qty"], step["reason"])
        elif action == "판매":
            out = self.record_phase1_sales(cid, step["actor"], step["orders"], step["returns"])
        else:
            g = self.add_returns(cid, step["change_of_mind"], step["color"])
            out = {"case_id": cid, "status": self.store.get_case(cid)["status"], "gate": asdict(g)}
        return {"action": action, "actions": moved, **out}

    def _demo_only(self, what: str) -> None:
        if self.store.get_mode() == MODE_OPERATION:
            raise PermissionError(f"운영 모드에서는 {what}을(를) 할 수 없음")

    def run_script(self, scenario: str, upto: int | None = None) -> list[dict]:
        self._demo_only("대본 재생")
        sc = scenarios.load(scenario, self.demo_dir)
        return [self.play(s) for s in sc.script[:upto]]

    # ---------------------------------------------------------------- 정책·모드 (바꿀 수 있는 역할은 정책 admin.policy_editors)

    def _require_policy_editor(self, actor: str, what: str) -> None:
        role = self.role_of(actor)
        editors = [r.strip() for r in policy.get("admin.policy_editors").split(",") if r.strip()]
        if role not in editors:
            raise PermissionError(f"{actor}({role})는 {what}을(를) 바꿀 수 없음 — {'·'.join(editors)}만")

    def _require_inputter(self, actor: str | None, key: str, what: str) -> None:
        """리뷰·반품 입력 권한(수정 회차 1 판정 2). actor가 없으면 시연 대본 재생(시스템)이라 시연 모드에서만.
        운영 모드에서는 정책 항목(key)의 역할만. 시연 모드에서는 등록된 사람이면 된다."""
        operation = self.store.get_mode() == MODE_OPERATION
        if actor is None:
            if operation:
                raise PermissionError(f"운영 모드에서는 시연용 {what} 입력을 할 수 없음 — 담당 역할이 직접 입력해야 함")
            return
        role = self.role_of(actor)
        allowed = [r.strip() for r in policy.get(key).split(",") if r.strip()]
        if operation and role not in allowed:
            raise PermissionError(f"{actor}({role})는 {what}을(를) 입력할 수 없음 — {'·'.join(allowed)}만")

    @_locked
    def change_policy(self, actor: str, key: str, value, reason: str) -> None:
        """정책 값을 바꾼다(검증·이력은 저장소). 편집 역할 목록을 바꿀 때는 모르는 역할을 넣을 수 없다.
        역할 이름(roles.*)을 바꾸면 admin.* 목록에 들어 있는 옛 이름도 같은 변경에서 새 이름으로 바꿔 함께 저장한다."""
        self._require_policy_editor(actor, "정책")
        if key in ROLE_KEYS or key in ROLE_LIST_KEYS:
            value = str(value).strip()  # 검증과 저장에 같은 값을 쓴다
        if key in ROLE_KEYS and value not in set(self.people.people.values()):
            raise ValueError(f"담당 역할은 사람 목록에 있는 역할이어야 함: {value!r}")
        if key in ROLE_LIST_KEYS:
            names = [r.strip() for r in value.split(",") if r.strip()]
            bad = [r for r in names if r not in scenarios.ROLES]
            if not names or bad:
                raise ValueError(f"편집 역할은 알려진 역할이어야 함: {bad or '(비어 있음)'}")
        old = policy.get(key) if key in ROLE_KEYS else None
        follow: list[tuple[str, str]] = []
        if old is not None and old != value and not any(policy.get(k) == old for k in ROLE_KEYS if k != key):
            for lk in policy.keys():
                if lk.startswith("admin.") and isinstance(policy.get(lk), str):
                    items = [r.strip() for r in policy.get(lk).split(",") if r.strip()]
                    if old in items:
                        new_items = list(dict.fromkeys(value if r == old else r for r in items))
                        follow.append((lk, ",".join(new_items)))
        self.store.change_policy(key, value, actor, reason)
        for lk, lv in follow:
            self.store.change_policy(lk, lv, actor, f"{key} 변경에 따라 자동 반영")
        self._check_roles()  # 저장소가 덮어쓰기를 다시 적용했으므로 어긋난 역할 덮어쓰기를 다시 뺀다

    @_locked
    def set_mode(self, actor: str, mode: str) -> None:
        self._require_policy_editor(actor, "실행 모드")
        self.store.set_mode(mode, actor)

    # ---------------------------------------------------------------- 기준일·기한

    @_locked
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

    @_locked
    def check_deadlines(self) -> list[dict]:
        """오늘(운영은 실제 오늘) 기준으로 기한·승인권자를 점검한다. 여러 번 불러도 같은 조치를 두 번 하지 않는다."""
        out = self._daily(self._today(), {"windows": self._windows()})
        if self.store.get_mode() == MODE_OPERATION:
            self.store.set_last_daily_check(self._today())  # 오늘 점검을 마쳤다(H5: 같은 날 요청마다 다시 돌지 않게)
        return out

    def ensure_daily_check(self) -> list[dict]:
        """운영 모드에서 오늘의 일일 점검이 아직 안 돌았으면 한 번 돌린다(요청이 들어올 때·서버 시작 때). 멱등: 마지막 점검일을 저장소에 기록.
        이미 돌았는지는 엔진 잠금 없이 먼저 본다(요청마다 잠금을 기다리지 않게)."""
        def done() -> bool:
            return self.store.get_mode() != MODE_OPERATION or self.store.last_daily_check() == self._today()
        if done():
            return []
        with self._lock:
            return [] if done() else self.check_deadlines()

    def _daily(self, d: date, cache: dict) -> list[dict]:
        out: list[dict] = []
        for case in self._cases():
            out += self._refresh(case["id"], cache)
            out += self._scm_timeout(self.store.get_case(case["id"]), d)
            case = self.store.get_case(case["id"])
            out += self._phase2_refresh(case["id"])
            out += self._escalate_phase2_hold(self.store.get_case(case["id"]), d)
            out += self._phase2_daily(self.store.get_case(case["id"]), d)
            out += self._notice_overdue(self.store.get_case(case["id"]), d)
            if case["status"] not in OPEN[case["kind"]]:
                continue
            # 필요한 승인이 모두 있는데 다른 부서 회신(SCM)만 기다리는 건은 승인된 건이다
            approved = bool(case["facts"].get(STAGES["1차"][2])) and not _pending_roles(case["facts"])
            acts = deadline_actions(_d(case["facts"]["deadline"]), d, approved=approved)
            if approved:
                w = self._warn_scm_human(case, d)
                if w:
                    out.append(w)
            if "기본거부" in acts:
                out.append(self._default_deny(case, d))
            elif "조기경고" in acts:
                w = self._warn(case, d)
                if w:
                    out.append(w)
                if not approved:
                    out += self._alarm(self.store.get_case(case["id"]), d)
            out += self._escalate_scm_human(self.store.get_case(case["id"]), d)
        return out

    # ---------------------------------------------------------------- 등록부 반영·재판정·확정 (한 경로)

    def require_registry_editor(self, actor: str) -> str:
        """기안·계약 등록부를 쓸 수 있는 역할인지(정책 admin.registry_editors). 아니면 PermissionError. 역할을 돌려준다."""
        role = self.role_of(actor)
        editors = [r.strip() for r in policy.get("admin.registry_editors").split(",") if r.strip()]
        if role not in editors:
            raise PermissionError(f"{actor}({role})는 등록부를 바꿀 수 없음 — {'·'.join(editors)}만")
        return role

    def _row_origin_for_new(self) -> str:
        """지금 화면에서 등록하는 등록부 행의 출처: 시연 모드는 시연(초기화 때 지워짐), 운영 모드는 화면."""
        return "화면" if self.store.get_mode() == MODE_OPERATION else "시연"

    def _require_row_editable(self, row: dict) -> None:
        """시연 모드에서는 시연 출처 행만 고친다(운영·가져오기 행을 시연 중에 고쳐 운영 데이터가 바뀌지 않게)."""
        if self.store.get_mode() != MODE_OPERATION and row["origin"] != "시연":
            raise PermissionError("시연 모드에서는 시연 등록부 행만 고칠 수 있음 — 운영 등록부 행은 운영 모드에서 고칠 것")

    @_locked
    def add_plan(self, fields: dict, actor: str) -> int:
        self.require_registry_editor(actor)
        return self.store.add_plan(fields, actor, origin=self._row_origin_for_new())

    @_locked
    def add_contract(self, fields: dict, actor: str) -> int:
        self.require_registry_editor(actor)
        return self.store.add_contract(fields, actor, origin=self._row_origin_for_new())

    @_locked
    def update_plan(self, plan_id: str, fields: dict, actor: str) -> list[dict]:
        """등록부 기안을 고치고(화면 수정) 그 기안의 사건을 바로 다시 판정한다."""
        self.require_registry_editor(actor)
        row = self.store.get_plan(plan_id)
        self._require_row_editable(row)
        self.store.update_plan(row["id"], fields, actor)
        return self._refresh_where(lambda c: c["kind"] == KIND_PLAN and c["ref_id"] == plan_id, actor)

    @_locked
    def update_contract(self, contract_row_id: int, fields: dict, actor: str) -> list[dict]:
        """등록부 계약을 고치고 그 계약의 사건을 바로 다시 판정한다."""
        self.require_registry_editor(actor)
        self._require_row_editable(self.store.get_contract(contract_row_id))
        self.store.update_contract(contract_row_id, fields, actor)
        return self._refresh_where(
            lambda c: c["kind"] == KIND_CONTRACT and c["facts"].get("contract_row_id") == contract_row_id, actor)

    @_locked
    def sync(self, actor: str = "시스템") -> list[dict]:
        """모든 사건을 등록부에 맞춰 다시 판정한다(가져오기 뒤 등). 같은 변경은 두 번 처리하지 않는다."""
        return self._refresh_where(lambda c: True, actor)

    def _refresh_where(self, pick, actor: str) -> list[dict]:
        cache: dict = {"windows": self._windows()}
        out: list[dict] = []
        for c in self._cases():
            if pick(c):
                out += self._refresh(c["id"], cache, actor)
        return out

    @staticmethod
    def _phase1_on(f: dict, registry_date: str) -> str:
        """1차 집행일 = 연기(shift)한 날. 연기한 뒤 등록부 집행일이 바뀌었으면 등록부 값이 이긴다."""
        shift = f.get("shift")
        return shift["to"] if shift and shift["from"] == registry_date else registry_date

    def _registry_now(self, case: dict, cache: dict) -> tuple[dict, ApproverDecision] | None:
        """등록부의 지금 값(사실 키로)과 그 값으로 다시 판정한 승인권자. 등록부 행이 없으면 None."""
        key = ("registry", case["id"])
        if key not in cache:
            try:
                if case["kind"] == KIND_PLAN:
                    row = self.store.get_plan(case["ref_id"])
                    on = self._phase1_on(case["facts"], row["settlement_date"])
                    dec, ind, total = self._plan_decision(row, cache["windows"], _d(on))
                    extra = {"plan_total_krw": total, "phase1_date": on}
                else:
                    row = self.store.get_contract(case["facts"]["contract_row_id"])
                    dec, ind = self._contract_decision(row, cache["windows"])
                    extra = {}
            except KeyError:
                cache[key] = None
                return None
            vals = {fk: row[rk] for fk, rk in SYNC_FIELDS[case["kind"]].items()}
            vals.update(extra, indicator_good=ind.good, indicator_hits=_hits(ind.hits),
                        indicator_excluded=list(ind.excluded))
            cache[key] = (vals, dec)
        return cache[key]

    def _refresh(self, case_id: int, cache: dict, actor: str = "시스템") -> list[dict]:
        """사건 하나를 등록부에 맞추고(등록부가 원천) 승인권자를 다시 판정한 뒤, 필요하면 받은 승인을 무효로 하고
        (재승인 대기), 필요한 승인이 모두 있으면 확정한다. advance·check_deadlines·decide·등록부 변경이 모두 이 길을 쓴다.

        끝난 사건(결정 단계가 지남)은 사실을 바꾸지 않고, 등록부와 달라진 값을 경고 이벤트로 한 번만 남긴다."""
        case = self.store.get_case(case_id)
        now = self._registry_now(case, cache)
        if now is None:
            return []
        vals, new_dec = now
        f = case["facts"]
        changes = {k: {"before": f.get(k), "after": v} for k, v in vals.items() if f.get(k) != v}
        out: list[dict] = []
        reopened = None
        if case["kind"] == KIND_PLAN and case["status"] == S_PHASE1_BLOCKED and "settlement_date" in changes and f.get("logistics"):
            reopened = self._reopen_blocked(case, vals, changes, actor)  # 사용자 결정 7: 집행일을 고치면 재점검
            if reopened is not None and not reopened:
                return []  # 새 날짜에서도 막혀 차단 유지(이유만 갱신)
            case = self.store.get_case(case_id)
            f = case["facts"]
            changes = {k: {"before": f.get(k), "after": v} for k, v in vals.items() if f.get(k) != v}
        if case["status"] not in OPEN[case["kind"]]:
            data = {k: c for k, c in changes.items() if k in SYNC_FIELDS[case["kind"]] or k == "plan_total_krw"}
            last = self.store.events(case_id, kind=EV_DRIFT)
            if data and (not last or last[-1]["detail"]["changes"] != data):
                text = (f"{case['ref_id']}는 {case['status']} 상태라 사건을 바꾸지 않음. 등록부와 다른 값: "
                        + ", ".join(f"{LABELS.get(k, k)} {_show(k, c['before'])}→{_show(k, c['after'])}"
                                    for k, c in data.items()))
                self.store.add_event(case_id, EV_DRIFT, actor, {"changes": data, "text": text})
                out.append({"date": self._today().isoformat(), "case_id": case_id, "action": "등록부변경경고",
                            "text": text})
            return out
        for k, c in changes.items():
            f[k] = c["after"]
        if f.get("shift") and f["shift"]["from"] != vals.get("settlement_date", f["shift"]["from"]):
            f["shift"] = None  # 등록부 집행일이 바뀌었으니 엔진이 옮긴 날짜는 버린다
        a_key, h_key, ok_key, date_key = STAGES["1차"]
        ups = self._active_ups(f, "1차")
        if ups and (list(new_dec.approvers) != ups[0]["base"] or any(k in changes for k in MATERIAL[case["kind"]])):
            self._void_ups(case, f, "1차", "등록부 변경으로 승인권자를 다시 판정", actor)  # 규칙의 결재선이 이긴다(아래 권한 이동 기록)
            ups = []
        change = (None if ups else  # 상신으로 올린 결재선은 규칙 판정과 달라도 되돌리지 않는다
                  diff_approver(_decision(f), new_dec, _d(f[date_key] if date_key in f else f["deadline"])))
        if change is not None:
            self.store.add_approver_change(case_id, change)
            f[a_key], f[h_key] = list(new_dec.approvers), _hits(new_dec.hits)
            out.append({"date": self._today().isoformat(), "case_id": case_id, "action": "권한이동",
                        "before": list(change.before), "after": list(change.after), "reason": change.reason})
        if changes or change is not None:
            self.store.update_facts(case_id, f, actor, "등록부 반영·승인권자 재판정")
        if case["kind"] == KIND_PLAN and "phase1_date" in changes:
            self._notify_date(case_id, "1차", changes["phase1_date"]["before"], changes["phase1_date"]["after"],
                              "등록부 집행일 수정", actor)
        if case["kind"] == KIND_PLAN and "deadline" in changes:
            self._sync_volume_task(case_id, _d(f["deadline"]), actor)  # 확정 기한이 바뀌면 물량 입력 기한도 맞춘다
        if case["kind"] == KIND_PLAN and "settlement_date" in changes and f.get("logistics"):
            self._recheck_stock(case_id)  # 집행일이 바뀌었으니 재고 점검·분할안을 새 날짜로 다시 돌린다
            f = self.store.get_case(case_id)["facts"]
        material = [k for k in MATERIAL[case["kind"]] if k in changes]
        if f.get(ok_key) and (material or change is not None):
            out += self._invalidate(case_id, material, changes, change, actor)
        if reopened:
            out += self._announce_unblock(case_id, reopened, actor)
        return out + self._maybe_finalize(case_id, actor)

    def _reopen_blocked(self, case: dict, vals: dict, changes: dict, actor: str) -> str | None | list:
        """1차 차단된 기안의 등록부 집행일이 바뀌었을 때. 새 날짜가 계약 만료(갱신 미확정) 뒤라 여전히 막히면 차단을 유지하고
        이유 문장만 갱신한다(빈 목록 반환). 아니면 차단을 풀고 승인 대기로 되돌려 지난 날짜(문자열)를 돌려준다.
        뒤의 재점검(재고 장부·SCM)과 받은 승인 무효는 _refresh의 일반 경로가 한다."""
        f = case["facts"]
        old_day = changes["settlement_date"]["before"]
        new_day = _d(vals["phase1_date"])
        end = self._split_end(f)
        if new_day > end:
            reason = (f"등록부 집행일이 {_md(_d(old_day))}→{_md(new_day)}로 바뀌었으나 새 집행일이 계약 만료({_md(end)}) 뒤"
                      "(갱신 미확정)라 1차 차단 유지")
            f.update(vals)
            f["shift"] = None
            f["phase1_blocked"] = {"reason": reason, "at": self._today().isoformat()}
            self.store.update_facts(case["id"], f, actor, f"1차 차단 유지: {reason}")
            text = f"{case['ref_id']} {reason}"
            for role in _required_roles(f):
                self.store.add_event(case["id"], EV_BLOCK, actor, {"target": role, "text": text})
            self._task_once(case["id"], self.campaign, "1차 차단 확인", self._today(), text)
            return []
        f["phase1_blocked"] = None
        self.store.update_facts(case["id"], f, actor, "집행일 변경: 1차 차단 해제")
        self.store.set_status(case["id"], S_WAIT_APPROVAL, actor, "등록부 집행일 변경으로 1차 차단 해제, 재점검")
        return old_day

    def _announce_unblock(self, case_id: int, old_day: str, actor: str) -> list[dict]:
        case = self.store.get_case(case_id)
        f = case["facts"]
        new = _md(_d(f["phase1_date"]))
        if f.get("scm"):
            result = f"안전재고 여유가 모자라 SCM에 다시 요청함(분할안 1차 {f['split']['phase1_qty']:,}개)"
        else:
            result = "재고 장부 여유 충분"
        text = f"{case['ref_id']} 1차 차단 해제: 등록부 집행일 {_md(_d(old_day))}→{new}, 새 날짜로 재점검 — {result}"
        for role in _required_roles(f):
            self.store.add_event(case_id, EV_UNBLOCK, actor, {"target": role, "text": text})
        return [{"date": self._today().isoformat(), "case_id": case_id, "action": "차단해제", "text": text}]

    def _invalidate(self, case_id: int, material: list[str], changes: dict, change, actor: str,
                    extra: tuple[str, ...] = ()) -> list[dict]:
        """받은 승인을 무효로 하고 재승인 대기로 둔다. 이전 승인자에게 무엇이 바뀌었는지 알린다(설계 4.1·4.2)."""
        case = self.store.get_case(case_id)
        f = case["facts"]
        ok_key = STAGES["1차"][2]
        previous = list(f.get(ok_key, []))
        parts = [f"{LABELS.get(k, k)} {_show(k, changes[k]['before'])}→{_show(k, changes[k]['after'])}"
                 for k in material]
        if change is not None:
            parts.append(f"승인권자 {'·'.join(change.before)}→{'·'.join(change.after)}")
        parts.extend(extra)
        text = f"{case['ref_id']} 재승인 필요: " + ", ".join(parts)
        f[ok_key] = []
        f.pop("split_chosen", None)
        f.pop("approved_split", None)
        self.store.update_facts(case_id, f, actor, "받은 승인 무효")
        for role in previous:
            self.store.add_event(case_id, EV_REAPPROVE, actor, {"target": role, "text": text})
        if case["status"] != S_REAPPROVAL:
            self.store.set_status(case_id, S_REAPPROVAL, actor, text)
        return [{"date": self._today().isoformat(), "case_id": case_id, "action": "재승인", "text": text}]

    def _maybe_finalize(self, case_id: int, actor: str) -> list[dict]:
        """승인 단계에서 필요한 역할이 모두 승인했으면 확정한다(남은 역할 없이 멈추지 않게)."""
        case = self.store.get_case(case_id)
        f = case["facts"]
        if (case["status"] in APPROVAL_STATES and f.get(STAGES["1차"][2]) and not _pending_roles(f)
                and not self._stock_open(case_id)):
            status = self._finalize(case_id, actor)
            return [{"date": self._today().isoformat(), "case_id": case_id, "action": "확정", "status": status}]
        return []

    def _warn(self, case: dict, d: date, stage: str = "1차") -> dict | None:
        """조기 경고는 아직 승인하지 않은 승인권자 본인에게 역할마다 한 번(사용자 결정 2026-11-12: 상급자가 아니라 당사자).
        경고 뒤 승인권자가 바뀌면 새로 들어온 승인권자에게도 보낸다.
        회신 대기에도 보낸다(부서 회신이 늦어도 기한은 다가오므로 — 설계 4.3보다 넓힘).
        2차 승인 대기 건도 같은 장치를 쓴다(stage="2차": 기한 phase2_deadline, 대상 기록 phase2_warned_targets)."""
        f = case["facts"]
        first = stage == "1차"
        dkey, wkey = ("deadline", "warned_targets") if first else ("phase2_deadline", "phase2_warned_targets")
        pending = _pending_roles(f, stage)
        targets = [r for r in pending if r not in f.get(wkey, [])]
        if not targets:
            return None
        label = "확정 기한" if first else "2차 집행일"
        text = (f"{case['ref_id']} {label} {_md(_d(f[dkey]))} 전 미승인(마지막 승인일 {_md(approval_deadline(_d(f[dkey])))}, "
                f"승인권자 {'·'.join(pending)})")
        if not first:
            f.setdefault("phase2_warned_on", d.isoformat())  # 방치 올림 기준 시점 = 첫 경고일
        for target in targets:
            detail = {"target": target, "pending": pending, "text": text, "deadline": f[dkey],
                      "approval_deadline": approval_deadline(_d(f[dkey])).isoformat()}
            if not first:
                detail["stage"] = stage
            self.store.add_event(case["id"], EV_WARN, "시스템", detail)
        f[wkey] = [*f.get(wkey, []), *targets]
        self.store.update_facts(case["id"], f, "시스템", "조기 경고")
        return {"date": d.isoformat(), "case_id": case["id"], "action": "조기경고", "targets": targets, "text": text}

    def _notify_date(self, case_id: int, stage: str, before: str | None, after: str | None, reason: str, actor: str) -> None:
        """집행일이 바뀌면 바뀐 그때 캠페인 담당·물류·CS와 그 단계 승인권자에게 알린다. 할 일 알림 칸에는 단계마다 마지막 변경만."""
        if before == after or not after:
            return
        case = self.store.get_case(case_id)
        f = case["facts"]
        roles = [self.campaign, self.logistics, self.cs]
        if f.get(STAGES[stage][0]):
            roles += [r for r in _required_roles(f, stage) if r not in roles]
        label = "1차" if stage == "1차" else "2차"
        was = _md(_d(before)) if before else "미정"
        text = f"{case['ref_id']} {label} 집행일 변경 {was}→{_md(_d(after))} ({reason})"
        self.store.add_event(case_id, EV_DATE, actor, {"targets": roles, "stage": stage, "from": before, "to": after,
                                                       "text": text})

    def _alarm(self, case: dict, d: date, stage: str = "1차") -> list[dict]:
        """마지막 승인일(기본 거부 실행일 전날) 알림: 아직 승인하지 않은 승인권자 본인에게 기한마다 한 번.
        기한이 바뀌면(2차 집행일 연기 등) 새 기한의 전날에 다시 알린다."""
        f = case["facts"]
        dkey, akey = ("deadline", "alarmed_for") if stage == "1차" else ("phase2_deadline", "phase2_alarmed_for")
        pending = _pending_roles(f, stage)
        deadline = _d(f[dkey])
        if not pending or d != approval_deadline(deadline) or f.get(akey) == f[dkey]:
            return []
        label = "" if stage == "1차" else "2차 "
        text = (f"{case['ref_id']} {label}오늘({_md(d)})이 마지막 승인일 — 내일({_md(deny_date(deadline))}) 아침 기본 거부 "
                f"(남은 승인권자 {'·'.join(pending)})")
        self.store.add_event(case["id"], EV_ALARM, "시스템", {"targets": pending, "stage": stage, "deadline": f[dkey],
                                                           "text": text})
        f[akey] = f[dkey]
        self.store.update_facts(case["id"], f, "시스템", "마감 알림")
        return [{"date": d.isoformat(), "case_id": case["id"], "action": "마감알림", "targets": pending, "text": text}]

    def _warn_scm_human(self, case: dict, d: date) -> dict | None:
        """필요한 승인은 모였는데 SCM 회신이 '사람 확인'에 머물러 있으면, 미승인 건과 같은 기한 창(조기 경고일~)에 한 번 경고한다.
        자동 거절은 하지 않는다: 답은 했으나 해석이 애매한 건이라 사람이 처리해야 한다."""
        f = case["facts"]
        if case["kind"] != KIND_PLAN:
            return None
        warned = f.get("scm_human_warned_on") or {}
        fresh = [rid for rid in self._human_stock_ids(case["id"]) if str(rid) not in warned]  # 경고는 요청마다 한 번
        if not fresh:
            return None
        if not deadline_actions(_d(f["deadline"]), d, approved=False):
            return None
        text = f"{case['ref_id']} 확정 기한 {_md(_d(f['deadline']))} 전 SCM 회신 사람 확인 미처리(승인은 모였으나 SCM 회신 해석을 사람이 확인해야 확정됨)"
        self.store.add_event(case["id"], EV_WARN, "시스템", {"target": self.campaign, "pending": [], "text": text,
                                                         "deadline": f["deadline"], "scm_human": True,
                                                         "request_ids": fresh})
        f["scm_human_warned_on"] = {**warned, **{str(rid): d.isoformat() for rid in fresh}}  # 요청별 방치 올림 기준 시점
        self.store.update_facts(case["id"], f, "시스템", "SCM 사람 확인 미처리 경고")
        return {"date": d.isoformat(), "case_id": case["id"], "action": "조기경고", "target": self.campaign, "text": text}

    # ---------------------------------------------------------------- 방치 올림 (추가 결정 9)

    def _escalation_target(self, roles: list[str]) -> str:
        """올릴 곳 = 승인권자 역할 중 보고 체계에서 가장 높은 역할. 마케팅팀뿐이면 바로 위(Masil 대표).
        보고 체계 밖 역할(그룹 등)은 순서에 넣지 않고, 체계 안 역할이 하나도 없으면 마케팅팀으로 본다."""
        chain, skip = self.people.escalation, self.people.escalation_skip
        known = [r for r in roles if r in chain]
        top = max(known, key=chain.index) if known else chain[0]
        while top in skip and chain.index(top) > 0:  # 회의체(이사회)는 올림 대상에서 빼고 그 아래 가장 가까운 역할로
            top = chain[chain.index(top) - 1]
        return self.people.above(top) if top == chain[0] else top

    def _escalate_stale(self, case: dict, key: str, since: date, owner: str, roles: list[str], since_label: str,
                        d: date, what: str) -> dict | None:
        """일반형: 담당(owner)이 key 종류의 일을 since부터 policy escalation.after_days일 넘게 처리하지 않았으면
        roles 중 최고 역할에게 한 번 올린다(할 일 알림 + 이벤트). 올려 받은 역할은 _can_handle로 처리 권한을 얻는다.
        자동 거절·기본 처리는 하지 않는다. 호출하는 쪽이 아직 미처리인지 확인한다."""
        f = case["facts"]
        days = (d - since).days
        if key in f.get("escalated", {}) or days < policy.get("escalation.after_days"):
            return None
        target = self._escalation_target(roles)
        text = (f"{case['ref_id']} {what} — 방치 올림({since_label} 후 {days}일): {owner}가 처리하지 않아 "
                f"{target}에게 올림")
        self.store.add_event(case["id"], EV_STALE, "시스템", {"target": target, "key": key, "owner": owner,
                                                           "since": since.isoformat(), "days": days, "text": text})
        f["escalated"] = {**f.get("escalated", {}), key: {"target": target, "since": since.isoformat(),
                                                          "at": d.isoformat(), "days": days}}
        self.store.update_facts(case["id"], f, "시스템", f"방치 올림: {key}")
        return {"date": d.isoformat(), "case_id": case["id"], "action": EV_STALE, "target": target, "text": text}

    @staticmethod
    def _can_handle(f: dict, key: str, role: str, owner: str) -> bool:
        """담당이거나, 그 일을 올려 받은 역할이면 직접 처리할 수 있다."""
        return role == owner or (f.get("escalated", {}).get(key) or {}).get("target") == role

    def _escalate_scm_human(self, case: dict, d: date) -> list[dict]:
        """사람 확인 요청마다, 그 요청의 경고 뒤 정책 일수가 지나도 그대로면 올린다(올림 기록·처리 권한도 요청별)."""
        f = case["facts"]
        if case["kind"] != KIND_PLAN or case["status"] not in OPEN[KIND_PLAN]:
            return []
        out = []
        for rid in self._human_stock_ids(case["id"]):
            on = (f.get("scm_human_warned_on") or {}).get(str(rid))
            if not on:
                continue
            case = self.store.get_case(case["id"])  # 앞 요청의 올림 기록이 반영된 사실로
            got = self._escalate_stale(case, self._human_key(rid), _d(on), self._owner(KIND_PLAN), _required_roles(f), "경고",
                                       d, "SCM 회신 사람 확인 방치")
            if got:
                out.append(got)
        return out

    def _human_stock_ids(self, case_id: int) -> list[int]:
        return [r["id"] for r in self.store.list_requests(case_id) if r["purpose"] == P_STOCK and r["status"] == R_HUMAN]

    def _human_open(self, case_id: int) -> bool:
        return bool(self._human_stock_ids(case_id))

    @staticmethod
    def _human_key(request_id: int) -> str:
        """SCM 사람 확인의 방치 올림 키: 사람 확인 요청마다 따로(올려 받은 처리 권한도 그 요청에만)."""
        return f"{STALE_SCM_HUMAN}#{request_id}"

    def _hold_task(self, case_id: int) -> dict | None:
        pending = [t for t in self.store.list_tasks(case_id) if t["title"] == STALE_PHASE2_HOLD and t["status"] == "대기"]
        return pending[-1] if pending else None

    def _escalate_phase2_hold(self, case: dict, d: date) -> list[dict]:
        """판매율 하한 미만 2차 보류 판단 작업이 작업 생성일부터 정책 일수가 지나도 그대로면 올린다."""
        f = case["facts"]
        task = self._hold_task(case["id"])
        if case["status"] != S_PHASE2_HOLD or f.get("phase2_decision") or task is None:
            return []
        roles = _required_roles(f, "2차") if f.get(STAGES["2차"][0]) else _required_roles(f)
        got = self._escalate_stale(case, STALE_PHASE2_HOLD, _d(task["due"]), self.campaign, roles, "작업 생성", d,
                                   "2차 보류 판단 방치")
        return [got] if got else []

    @_locked
    def resolve_human_check(self, request_id: int, actor: str, text: str, attachments: int = 0) -> dict:
        """사람 확인에 머문 요청을 사람이 처리한다(회신을 다시 넣어 해석·반영). 담당이거나 방치로 올려 받은 역할만 가능."""
        req = self.store.get_request(request_id)
        case = self.store.get_case(req["case_id"])
        if req["status"] != R_HUMAN:
            raise ValueError("사람 확인 상태인 요청만 처리할 수 있음")
        role = self.role_of(actor)
        key = self._human_key(request_id) if req["purpose"] == P_STOCK else req["purpose"]
        if not self._can_handle(case["facts"], key, role, self._owner(case["kind"])):
            raise PermissionError(f"{actor}({role})는 이 사람 확인을 처리할 수 없음 — {self._owner(case['kind'])}"
                                  "(또는 방치로 올려 받은 사람)만")
        return self.reply(request_id, text, attachments)

    @_locked
    def submit_reply(self, request_id: int, actor: str, text: str, attachments: int = 0) -> dict:
        """사람이 부서 요청에 회신을 낸다(HTTP 입구). 그 요청의 대상 부서 역할만 낼 수 있다(아니면 PermissionError, 저장 안 함).
        사람 확인에 머문 요청은 resolve_human_check로만 처리한다(ValueError)."""
        req = self.store.get_request(request_id)
        role = self.role_of(actor)
        if role != req["dept"]:
            raise PermissionError(f"{actor}({role})는 이 요청에 회신할 수 없음 — 회신 대상: {req['dept']}")
        if req["status"] == R_HUMAN:
            raise ValueError("사람 확인 상태인 요청은 회신이 아니라 사람 확인 처리로만 받을 수 있음")
        return self.reply(request_id, text, attachments)

    def _lapsed_deny(self, case: dict, base: dict) -> dict | None:
        """H5: 결정·상신이 들어왔는데 기본 거부 실행일(확정 기한 - deadline.buffer_days)이 되었거나 지났으면(승인은 그 전날까지)
        기본 거부로 처리하고 그 결과를 돌려준다.
        지금 모드의 사건에만 적용한다(다른 모드의 사건에 이 모드의 시계를 대지 않는다)."""
        today = self._today()
        if case["origin"] != self._mode_origin() or not is_lapsed(_d(case["facts"]["deadline"]), today):
            return None
        res = self._default_deny(case, today)
        deadline = _d(case["facts"]["deadline"])
        return {**base, "changed": False, "status": res["status"],
                "message": f"기본 거부 실행일 {_md(deny_date(deadline))}(확정 기한 {_md(deadline)}의 "
                           f"{policy.get('deadline.buffer_days')}일 전)이 되어 기본 거부로 처리함 — 결정을 받지 않음"}

    def _default_deny(self, case: dict, d: date) -> dict:
        """기한까지 승인 없음 → 기본 거부(설계 3장 2번·4.3). 기안은 확정 보류(철회)."""
        deadline = _md(_d(case["facts"]["deadline"]))
        self.store.set_status(case["id"], S_DEFAULT_DENY, "시스템",
                              f"마지막 승인일 {_md(approval_deadline(_d(case['facts']['deadline'])))}까지 승인 없음 — 확정 기한 {deadline}의 "
                              f"{policy.get('deadline.buffer_days')}일 전 기본 거부")
        status = S_DEFAULT_DENY
        if case["kind"] == KIND_PLAN:
            self.store.set_status(case["id"], S_HOLD, "시스템", "확정 보류(철회)")
            status = S_HOLD
            self._close_volume_tasks(case["id"])  # 확정하지 않으니 남은 물량 입력은 필요 없다
            self._task_once(case["id"], self.campaign, "확정 보류(철회) 처리", d,
                            f"{case['ref_id']}: 기한 {deadline}까지 승인이 없어 확정하지 않음. 상대측에 보류·철회를 알림")
        else:
            status = self._draft_notice(case, d)
        return {"date": d.isoformat(), "case_id": case["id"], "action": "기본거부", "status": status}

    def _notice_overdue(self, case: dict, d: date) -> list[dict]:
        """통보 초안이 통보 기한이 지나도록 발송되지 않았으면 계약 담당에게 경고하고(한 번), 정책 일수가 더 지나면 방치 올림.
        통보가 나가지 않으면 자동 갱신된다(설계 4.3·7.4)."""
        f = case["facts"]
        if case["kind"] != KIND_CONTRACT or case["status"] != S_NOTICE_DRAFT or d <= _d(f["deadline"]):
            return []
        out: list[dict] = []
        if not f.get("notice_overdue_warned_on"):
            text = (f"{case['ref_id']} 통보 기한 {_md(_d(f['deadline']))}이 지났는데 조건변경 통보가 발송되지 않음 — "
                    "통보하지 않으면 계약이 자동 갱신됨")
            self.store.add_event(case["id"], EV_WARN, "시스템", {"target": self.contract_owner, "pending": [], "text": text,
                                                             "deadline": f["deadline"], "notice_overdue": True})
            f["notice_overdue_warned_on"] = d.isoformat()
            self.store.update_facts(case["id"], f, "시스템", "통보 기한 초과 경고")
            out.append({"date": d.isoformat(), "case_id": case["id"], "action": "조기경고", "target": self.contract_owner,
                        "text": text})
        got = self._escalate_stale(self.store.get_case(case["id"]), STALE_NOTICE, _d(f["deadline"]), self.contract_owner,
                                   _required_roles(f), "통보 기한", d, "조건변경 통보 미발송")
        return out + ([got] if got else [])

    # ---------------------------------------------------------------- 회신

    @_locked
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
        if req["purpose"] in DEFINITIVE_REFUSAL and j.stance == "거절":
            needs_human = False  # 그 부서의 거절은 결정이다(해석이 애매한 것이 아님)
        notes = []
        if req["attach_required"] and attachments <= 0:
            needs_human = True
            notes.append("필수 첨부 없음")
        self.store.add_judgment(case["id"], "회신해석", j.model, f"{req['dept']} 회신: {text}", result,
                                needs_human, j.confidence, j.ledger_id)
        handler = self._handlers.get(req["purpose"])
        if not needs_human and handler is not None:
            reason = handler(case["id"], req, j, text)  # 처리기가 사람 확인 사유를 돌려주면 사실을 바꾸지 않은 것
            if reason:
                needs_human = True
                notes.append(reason)
        if needs_human:
            return self._human_check(request_id, req, case, text, notes, j, result, base)
        self.store.set_request_status(request_id, R_DONE, "AI", f"AI 해석 {j.stance}")
        changed = self._after_requests(case["id"])
        changed = bool(self._maybe_finalize(case["id"], "AI")) or changed
        return {**base, "ignored": False, "needs_human": False, "changed": changed,
                "status": self.store.get_case(case["id"])["status"], "judgment": result}

    def _human_check(self, request_id: int, req: dict, case: dict, text: str, notes: list[str], j, result: dict,
                     base: dict) -> dict:
        why = "; ".join(notes + [f"AI 해석 {j.stance}"])
        self.store.set_request_status(request_id, R_HUMAN, "AI", why)
        if req["purpose"] == P_NOTICE:
            self.store.set_status(case["id"], S_HUMAN, "AI", why)
        self._task_once(case["id"], self._owner(case["kind"]), "회신 사람 확인", self._today(),
                        f"{req['dept']} 회신 '{text}' — {why}. 사람이 확인해 주세요")
        return {**base, "ignored": False, "needs_human": True, "changed": False,
                "status": self.store.get_case(case["id"])["status"], "judgment": result}

    def _after_requests(self, case_id: int) -> bool:
        case = self.store.get_case(case_id)
        if case["status"] != S_WAIT_REPLY:
            return False
        # SCM의 안전재고 사용 요청은 승인을 막지 않는다: 승인권자가 먼저 승인하고, SCM 응답이 분할안을 바꾸면 재승인
        if any(r["status"] != R_DONE and r["purpose"] != P_STOCK for r in self.store.list_requests(case_id)):
            return False
        self.store.set_status(case_id, S_WAIT_APPROVAL, "시스템", "부서 회신 완료, 승인권자 판단 대기")
        return True

    def _on_logistics(self, case_id: int, req: dict, j: judge.ReplyJudgment, text: str) -> None:
        f = self.store.get_case(case_id)["facts"]
        stable, maximum = parse_capacity(text)
        f["logistics"] = {"request_id": req["id"], "stance": j.stance, "qty_limit": j.qty_limit,
                          "next_date": j.next_date.isoformat() if j.next_date else None,
                          "stable": stable, "maximum": maximum}
        if f["volume"]["units"] is None:
            f["allocation"] = ALLOC_HOLD  # 물량 입력 전에는 할당 판정 보류
        else:
            f["allocation"] = ALLOC_FULL if j.stance == "수용" else ALLOC_PARTIAL
        self.store.update_facts(case_id, f, "AI", "물류 회신 반영")
        # 모든 건이 재고 장부를 거친다(사용자 결정 2026-11-11). 처리량 숫자가 없으면 처리 능력을 제한 없음(회신 수용 = 요청 수량)으로 본다.
        if f["volume"]["units"] is not None:
            self._check_stock(case_id)

    def _on_content_fix(self, case_id: int, req: dict, j: judge.ReplyJudgment, text: str) -> None:
        f = self.store.get_case(case_id)["facts"]
        f["content_fix_confirmed"] = True
        self.store.update_facts(case_id, f, "AI", "콘텐츠 수정 확인(첨부 포함)")
        self._phase2_refresh(case_id)  # 리뷰 잠금이 풀렸으면 다음은 판매율(이미 판정한 건은 2차 승인 대기로 되돌아감)

    # ---------------------------------------------------------------- 재고 장부·SCM (설계 4.5)

    def _contract_terms(self, influencer_id: str) -> tuple[date, bool]:
        """(계약 만료일, 갱신 확정 여부). 등록부에 계약이 없으면 막지 않는다(만료 없음, 확정으로 본다)."""
        c = scenarios.registry_contract(self.store, influencer_id) if influencer_id else None
        if c is None:
            return date.max, True
        return _d(c["expiry_date"]), self._renewal_confirmed(c)

    def _split_end(self, f: dict) -> date:
        """분할안의 2차 날짜 상한: 갱신이 확정됐으면 제한 없음, 아니면 계약 만료일."""
        end, renewal = self._contract_terms(f.get("influencer_id") or "")
        return date.max if renewal else end

    @staticmethod
    def _split_dict(sp) -> dict:
        return {"phase1_qty": sp.phase1_qty, "phase1_date": sp.phase1_date.isoformat(),
                "phase2_qty": sp.phase2_qty, "phase2_date": sp.phase2_date.isoformat() if sp.phase2_date else None,
                "hits": _hits(sp.hits)}

    def _stock_open(self, case_id: int) -> bool:
        return any(r["purpose"] == P_STOCK and r["status"] != R_DONE for r in self.store.list_requests(case_id))

    def _active_loads(self, day: date) -> tuple[dict[str, int], dict[str, str]]:
        """day에 물량이 있는 진행 중 기안(등록부 사건)의 원하는 양과 기안이 속한 라인.
        등록부 집행일을 옮긴 기안은 일별 물량 곡선도 같은 만큼 옮겨 읽는다(곡선은 원본 집행일에 놓여 있음)."""
        active = {c["ref_id"]: c["facts"] for c in self._cases(KIND_PLAN)
                  if c["status"] not in TERMINAL[KIND_PLAN] and (c["facts"].get("volume") or {}).get("units") is not None}
        loads = volume_calc.total_daily_load(date.min, date.max)
        demand: dict[str, int] = {}
        for pid, f in active.items():
            moved = (_d(f["settlement_date"]) - _d(f.get("curve_anchor") or f["settlement_date"])).days
            q = round(loads.get(day - timedelta(days=moved), {}).get(pid, 0))
            if q > 0:
                demand[pid] = q
        return demand, {pid: active[pid]["volume"]["product_line"] for pid in demand}

    def _check_stock(self, case_id: int) -> None:
        """1차 집행일의 물류 몫(같은 퍼센트 배분)과 재고 장부의 쓸 수 있는 재고를 비교한다. 모든 건이 거친다.
        요청 단위는 집행일 하루 수량(day_qty)이다. 모자라면 SCM에 안전재고 사용을 묻고(수량은 SCM이 정한다),
        SCM이 필요한 양을 모두 허용한다고 본 첫 분할안(1차 = 물류 몫, 2차 = 하루 수량 − 1차)을 만든다."""
        case = self.store.get_case(case_id)
        f, ref = case["facts"], case["ref_id"]
        lg = f["logistics"]
        stable, maximum = lg["stable"], lg["maximum"]
        line, units, d1 = f["volume"]["product_line"], f["volume"]["units"], _d(f["phase1_date"])
        cap, cap_hits = usable_capacity(stable, maximum)  # 숫자가 없으면 None = 처리 능력 제한 없음(회신 수용 = 요청 수량)
        limit = lg.get("qty_limit")
        if cap is None and lg["stance"] == "조건부수용" and isinstance(limit, int) and not isinstance(limit, bool) and limit >= 0:
            # 물류가 이름표 없이 "N개까지"만 답한 조건부 수용: AI가 읽은 수량 제한을 처리 능력으로 쓴다
            cap = limit
            cap_hits = (RuleHit("logistics_qty_limit", f"물류 회신의 수량 제한 {limit:,}개를 처리 능력으로 쓴다(평소·최대 이름표 없음)",
                                "물류 회신(AI 해석)", "가정"),)
        demand, line_of = self._active_loads(d1)
        want = demand.get(ref, 0)
        room = {ln: sum(demand.values()) + 1 for ln in set(line_of.values())}  # 재고 제약 없이 물류 몫만 본다
        share = min(units, allocate_day(d1, demand, line_of, room, cap).shipped.get(ref, 0)) if want else 0
        day_qty = min(units, want)
        spare = inventory.line_spare(line, d1)
        need = max(0, share - spare)
        daily = inventory.line_daily_sale(line)
        restock = inventory.line_restock_date(line)
        f["stock"] = {
            "line": line, "day": d1.isoformat(), "line_stock": inventory.line_stock(line, d1),
            "safety_min": inventory.line_safety_min(line), "spare": spare, "stable": stable, "maximum": maximum,
            "capacity": cap, "capacity_hits": _hits(cap_hits), "want": want, "day_qty": day_qty, "share": share,
            "need": need, "shortage": need > 0, "daily_sale": daily, "restock": restock.isoformat(),
            "days_earlier": stockout_days_earlier(need, daily) if need > 0 and daily > 0 else 0.0,
        }
        f["split"], f["scm"] = None, None
        if share < want:
            f["allocation"] = ALLOC_PARTIAL
        if need <= 0:
            if share < day_qty:  # 재고는 충분하지만 물류 몫이 하루 수량보다 작다: 1차 = 물류 몫, 2차 = 나머지
                f["split"] = self._split_dict(make_split(day_qty, share, spare, d1, restock, self._windows(),
                                                         self._split_end(f)))
            self.store.update_facts(case_id, f, "시스템", "재고 장부 점검: 여유 충분")
            return
        sp = make_split(day_qty, share, spare + need, d1, restock, self._windows(), self._split_end(f))
        f["split"] = self._split_dict(sp)
        f["scm"] = {"state": SCM_ASKED, "need": need, "allow": None, "asked_on": self._today().isoformat()}
        f["allocation"] = ALLOC_PARTIAL
        self.store.update_facts(case_id, f, "시스템", "재고 장부 점검: 안전재고 위 여유 부족")
        s = f["stock"]
        pct = policy.get("scm.stockout_loss_pct")
        ask = (f"{ref} {_md(d1)} 1차 {share:,}개 중 안전재고 위 여유분이 {spare:,}개라 {need:,}개가 모자랍니다. "
               f"안전재고를 쓸 수 있는지, 쓴다면 몇 개까지 허용하는지 회신해 주세요(전량 허용 / 일부 허용(수량) / 거절). "
               f"쓰면 평소 고객 주문이 약 {s['days_earlier']:.1f}일 일찍 품절되고, 쓰지 않아 품절될 때의 손실은 매출의 약 {pct:.0%}로 봅니다. "
               "재고 결정은 SCM 권한이라 시스템은 수량을 정하지 않습니다.")
        self._request_once(case_id, SCM, ask, False, P_STOCK)
        self.store.add_event(case_id, EV_STOCK, "시스템", {"text": ask, "stock": s})
        self._order_adjustments(case_id, d1)

    def _recheck_stock(self, case_id: int) -> None:
        """등록부 집행일이 바뀌면 분할안·재고 점검을 새 날짜로 다시 돌린다. 이전 날짜로 보낸 SCM 요청은 닫고 새로 묻는다.
        (받은 승인이 있으면 무효로 하는 것은 집행일이 승인 사실이라 _refresh의 11a 경로가 한다.)"""
        case = self.store.get_case(case_id)
        f = case["facts"]
        if f["volume"]["units"] is None:
            return
        for r in self.store.list_requests(case_id):
            if r["purpose"] == P_STOCK and r["status"] != R_DONE:
                self.store.set_request_status(r["id"], R_DONE, "시스템", "집행일이 바뀌어 새 날짜로 다시 점검")
        f["allocation"] = ALLOC_FULL if f["logistics"]["stance"] == "수용" else ALLOC_PARTIAL
        self.store.update_facts(case_id, f, "시스템", "집행일 변경: 재고 점검 다시")
        self._check_stock(case_id)

    def _order_adjustments(self, case_id: int, day: date) -> None:
        """재고 과잉 상품은 SCM에 발주 조정을 요청한다(같은 상품은 열린 요청이 있으면 다시 만들지 않는다)."""
        rows = inventory.stock_state(day)
        alerts = stock_alerts({r.sku_id: max(0, round(r.stock)) for r in rows},
                              {r.sku_id: r.weekly_sale for r in rows},
                              {r.sku_id: r.min_weeks for r in rows}, {r.sku_id: r.max_weeks for r in rows})
        by_id = {r.sku_id: r for r in rows}
        open_skus = {t["detail"].split(" ")[0] for t in self.store.all_tasks(dept=SCM)
                     if t["title"] == ORDER_ADJUST and t["status"] == "대기"}
        for sku, kind in alerts:
            if kind != "재고 과잉" or sku in open_skus:
                continue
            r = by_id[sku]
            weeks = max(0, r.stock) / r.weekly_sale
            self.store.add_task(case_id, SCM, ORDER_ADJUST, day,
                                f"{sku} {r.name}: 재고 {weeks:.1f}주분으로 안전재고 최대 {r.max_weeks}주를 넘어 과잉. "
                                "입고 예정 발주를 줄이거나 미루는 것을 검토해 주세요")

    def _on_stock(self, case_id: int, req: dict, j: judge.ReplyJudgment, text: str) -> str | None:
        """SCM 응답: 전량 허용 → 계산대로 / 일부 허용(수량) → 1차 = 허용분과 물류 몫 중 작은 값 / 거절 → 입고 다음 날로 연기.
        수량을 알 수 없거나 해석이 안 되면 사람 확인(사실을 바꾸지 않는다)."""
        f = self.store.get_case(case_id)["facts"]
        need = (f.get("scm") or {}).get("need")
        if need is None:
            return "재고 점검 결과가 없는 건"
        if j.stance == "수용":
            allow = need
        elif j.stance == "조건부수용":
            if not isinstance(j.qty_limit, int) or isinstance(j.qty_limit, bool):
                return "허용 수량을 알 수 없음"
            allow = min(max(j.qty_limit, 0), need)
        elif j.stance == "거절":
            allow = 0
        else:
            return f"해석할 수 없는 SCM 응답({j.stance})"
        self._apply_scm(case_id, allow, text)
        return None

    def _ready_day(self, f: dict, qty: int) -> tuple[date | None, int, str]:
        """SCM 거절 뒤: 입고 다음 날부터 장부를 앞으로 돌려 라인 여유가 qty 이상 생기는 첫날과 그날 여유.
        없거나 계약 만료(갱신 미확정) 뒤면 날짜 None과 차단 이유. 장부 전망은 라인의 마지막 입고일까지(그 뒤는 줄기만 함)."""
        s = f["stock"]
        restock = _d(s["restock"])
        first = restock + timedelta(days=1)
        last = max(inventory.line_last_inbound(s["line"]), first)
        path = inventory.spare_path(s["line"], first, last)
        found = next(((d, q) for d, q in path if q >= qty), None)
        base = f"SCM가 안전재고 사용을 거절했고 입고({_md(restock)}) 다음 날부터 장부를 돌려도"
        if found is None:
            best = max(path, key=lambda x: x[1]) if path else None
            peak = f" (가장 큰 여유 {best[1]:,}개, {_md(best[0])})" if best else ""
            return None, 0, f"{base} {_md(last)}까지 라인 여유가 1차 수량 {qty:,}개 이상인 날이 없어 1차 차단{peak}"
        end = self._split_end(f)
        if found[0] > end:
            return None, found[1], (f"{base} 여유가 생기는 첫날 {_md(found[0])}이 계약 만료({_md(end)}) 뒤"
                                    "(갱신 미확정)라 1차 차단")
        return found[0], found[1], ""

    def _apply_scm(self, case_id: int, allow: int, text: str, actor: str = "AI", no_reply_days: int | None = None) -> None:
        case = self.store.get_case(case_id)
        f = case["facts"]
        s, sc, old = f["stock"], f["scm"], f["split"]
        restock, windows = _d(s["restock"]), self._windows()
        if allow > 0:
            state = SCM_FULL if allow >= sc["need"] else SCM_PARTIAL
            sp = make_split(s["day_qty"], s["share"], s["spare"] + allow,
                            _d(self._phase1_on(f, f["settlement_date"])), restock, windows, self._split_end(f))
            reason = f"SCM {state} {allow:,}개"
        else:
            # 거절·무응답: 수량만 줄여 안전재고를 쓰는 우회는 하지 않는다. 장부를 앞으로 돌려 여유가 1차 수량 이상 생기는 첫날로 연기하고,
            # 그런 날이 없거나 계약 만료 뒤면 1차 차단. 1차 수량은 그날 여유와 물류 몫 중 작은 값.
            state = SCM_REFUSED
            why = f"SCM 무응답 {no_reply_days}일(거절로 처리)" if no_reply_days else "SCM 거절"
            later, spare_then, blocked = self._ready_day(f, s["share"])
            if later is None:
                f["scm"] = {**sc, "state": state, "allow": 0, "reply": text}
                if no_reply_days:
                    f["scm"]["no_reply_days"] = no_reply_days
                self._block_phase1(case_id, f, f"{why} — {blocked}", actor)
                return
            sp = make_split(s["day_qty"], s["share"], spare_then, later, restock, windows, self._split_end(f))
            s["spare"], s["day"] = spare_then, later.isoformat()
            f["shift"] = {"from": f["settlement_date"], "to": later.isoformat(), "reason": why}
            f["phase1_date"] = later.isoformat()
            reason = f"{why} — 1차 날짜를 장부 여유가 생기는 첫날 {_md(later)}로 연기"
        f["split"] = self._split_dict(sp)
        f["scm"] = {**sc, "state": state, "allow": allow, "reply": text}
        if no_reply_days:
            f["scm"]["no_reply_days"] = no_reply_days
        self.store.update_facts(case_id, f, actor, f"SCM 응답 반영: {reason}")
        if state == SCM_REFUSED:
            self._notify_date(case_id, "1차", f["shift"]["from"], f["phase1_date"], why, actor)
        # 받은 승인이 새 분할안과 맞지 않으면 먼저 무효로 한다. 확정(_refresh 끝)이 먼저 돌면 옛 승인으로 새 분할안을 확정해 버린다.
        self._reapprove_if_changed(case_id, old, reason, actor)
        self._refresh(case_id, {"windows": windows})  # 날짜가 바뀌었으면 승인권자를 등록부 길로 다시 판정

    def _block_phase1(self, case_id: int, f: dict, reason: str, actor: str) -> None:
        """1차 차단: 승인권자·캠페인 담당에게 이유를 알린다. 다시 풀려면 집행일·물량을 바꿔 새 기안으로."""
        case = self.store.get_case(case_id)
        f["phase1_blocked"] = {"reason": reason, "at": self._today().isoformat()}
        self.store.update_facts(case_id, f, actor, f"1차 차단: {reason}")
        self.store.set_status(case_id, S_PHASE1_BLOCKED, actor, reason)
        text = f"{case['ref_id']} {reason}"
        for role in _required_roles(f):
            self.store.add_event(case_id, EV_BLOCK, actor, {"target": role, "text": text})
        self._task_once(case_id, self.campaign, "1차 차단 확인", self._today(), text)

    def _scm_timeout(self, case: dict, d: date) -> list[dict]:
        """SCM이 안전재고 사용 요청에 요청 후 scm.no_reply_days일이 지나도 답이 없으면 거절로 처리한다(사용자 결정).
        답은 했지만 사람 확인 중인 요청은 무응답이 아니다."""
        sc = case["facts"].get("scm")
        if case["kind"] != KIND_PLAN or case["status"] not in OPEN[KIND_PLAN] or not sc or sc["state"] != SCM_ASKED:
            return []
        days = policy.get("scm.no_reply_days")
        waiting = [r for r in self.store.list_requests(case["id"]) if r["purpose"] == P_STOCK and r["status"] == R_WAIT]
        if not waiting or (d - _d(sc["asked_on"])).days < days:
            return []
        self.store.set_request_status(waiting[-1]["id"], R_DONE, "시스템", f"SCM 무응답 {days}일 — 거절로 처리")
        self._apply_scm(case["id"], 0, f"무응답 {days}일", "시스템", no_reply_days=days)
        now = self.store.get_case(case["id"])
        return [{"date": d.isoformat(), "case_id": case["id"], "action": "SCM무응답", "status": now["status"],
                 "text": f"{case['ref_id']} SCM 무응답 {days}일 — 거절로 처리"}]

    def _reapprove_if_changed(self, case_id: int, old: dict, reason: str, actor: str) -> list[dict]:
        """분할안이 바뀌었는데 받은 승인이 있으면 무효로 하고 재승인을 받는다(설계 4.5: 처음 승인한 분할안과 달라지면)."""
        f = self.store.get_case(case_id)["facts"]
        new, seen = f["split"], f.get("approved_split") or old
        if new == seen:
            return []  # 분할안이 그대로면 변경 이벤트를 남기지 않는다(SCM 전량 허용 등)
        text = f"분할안 변경: 1차 {seen['phase1_qty']:,}→{new['phase1_qty']:,}개"
        if seen["phase1_date"] != new["phase1_date"]:
            text += f", 1차 날짜 {_md(_d(seen['phase1_date']))}→{_md(_d(new['phase1_date']))}"
        text += f" ({reason})"
        self.store.add_event(case_id, EV_SPLIT, actor, {"text": text, "split": new})
        if f.get(STAGES["1차"][2]) and f.get("approved_split") != new:
            return self._invalidate(case_id, [], {}, None, actor, extra=(text,))
        return []

    @_locked
    def adjust_phase1(self, case_id: int, actor: str, qty: int) -> dict:
        """캠페인 담당이 승인 전 분할안의 1차 수량을 줄인다. SCM이 거절한 건은 수량만 줄여 진행할 수 없다(PermissionError)."""
        role = self.role_of(actor)
        if role != self.campaign:
            raise PermissionError(f"{actor}({role})는 1차 수량을 조정할 수 없음 — {self.campaign}만")
        case = self.store.get_case(case_id)
        f = case["facts"]
        if (f.get("scm") or {}).get("state") == SCM_REFUSED:
            raise PermissionError("SCM이 안전재고 사용을 거절한 건은 수량만 줄여 진행할 수 없음 — 입고 뒤로 연기한 1차 날짜로만 진행")
        if case["status"] not in APPROVAL_STATES or not f.get("split"):
            raise ValueError("승인 전 분할안만 조정할 수 있음")
        old = f["split"]
        if qty <= 0:
            raise ValueError("1차 수량은 1 이상")
        if qty > old["phase1_qty"]:
            raise ValueError(f"1차 수량은 늘릴 수 없음(현재 {old['phase1_qty']:,}개)")
        if qty == old["phase1_qty"]:
            return {"case_id": case_id, "changed": False, "status": case["status"]}
        s = f["stock"]
        sp = make_split(s["day_qty"], qty, qty, _d(old["phase1_date"]), _d(s["restock"]), self._windows(),
                        self._split_end(f))
        f["split"] = self._split_dict(sp)
        self.store.update_facts(case_id, f, actor, f"1차 수량 조정 {old['phase1_qty']:,}→{qty:,}")
        self._reapprove_if_changed(case_id, old, f"{actor}가 1차 수량을 {qty:,}개로 줄임", actor)
        return {"case_id": case_id, "changed": True, "status": self.store.get_case(case_id)["status"]}

    @_locked
    def announce(self, case_id: int, actor: str, qty: int | None = None) -> dict:
        """캠페인 담당이 1차 수량을 소비자에게 공지한다. 시스템은 예약 가능 여부만 확인하고, 공지하면 그 수량을
        재고·물류에서 먼저 떼어 잠근다(공지 수량 고정). 모자라면 공지를 막는다(공지 후 미배송은 소비자 피해)."""
        role = self.role_of(actor)
        if role != self.campaign:
            raise PermissionError(f"{actor}({role})는 공지할 수 없음 — 공지는 {self.campaign}가 한다")
        case = self.store.get_case(case_id)
        f = case["facts"]
        if case["kind"] != KIND_PLAN or not f.get("phase1"):
            raise ValueError("승인 뒤에만 공지할 수 있음")
        base = {"case_id": case_id, "actor": actor}
        if f.get("announce"):
            return {**base, "changed": False, "qty": f["announce"]["qty"], "message": "이미 공지함"}
        if case["status"] in TERMINAL[KIND_PLAN] or self._today() > _d(f["phase1"]["date"]):
            raise ValueError("1차 집행일이 지났거나 끝난 건은 공지할 수 없음")
        fixed = f["phase1"]["qty"]
        if qty is not None and qty != fixed:
            raise ValueError(f"공지 수량은 1차 수량({fixed:,}개)으로 고정")
        d1, s = _d(f["phase1"]["date"]), f.get("stock")
        if s is not None:
            allow = (f.get("scm") or {}).get("allow") or 0
            others = [c["facts"]["announce"] for c in self._cases(KIND_PLAN)
                      if c["id"] != case_id and (c["facts"].get("announce") or {}).get("date") == d1.isoformat()
                      and c["facts"]["announce"]["line"] == s["line"]]
            reserved = sum(a["qty"] for a in others)
            if not can_announce(case["ref_id"], d1, fixed, {case["ref_id"]: s["line"]}, {s["line"]: s["spare"] + allow},
                                s["capacity"], {s["line"]: reserved}, reserved):
                raise ValueError(f"공지할 수 없음: {fixed:,}개를 예약할 재고·물류가 모자람")
        f["announce"] = {"qty": fixed, "date": d1.isoformat(), "by": actor, "reserved": True,
                         "line": s["line"] if s else None,
                         "overflow_demand": max(0, s["want"] - fixed) if s else None}
        self.store.update_facts(case_id, f, actor, f"1차 {fixed:,}개 공지·예약")
        self.store.add_event(case_id, EV_ANNOUNCE, actor, f["announce"])
        if f.get("channel") == LIVE:
            self._task_once(case_id, MARKETING, MEASURE, d1,
                            f"{case['ref_id']} 1차 {fixed:,}개 한정 공지({_md(d1)}): 라이브 전용 코드로 판매를 구분하고 "
                            "방송 전후 검색량을 비교해 효과를 측정해 주세요")
        return {**base, "changed": True, "qty": fixed, "date": d1.isoformat()}

    # ---------------------------------------------------------------- 전속계약 기본 거부 → 통보 (설계 7.4)

    def _draft_notice(self, case: dict, d: date) -> str:
        """기본 거부된 계약: 순액 기준 재협상안으로 조건변경 통보 초안(AI)을 만들고 계약 담당에게 발송 작업을 낸다."""
        f = case["facts"]
        reg = self.store.get_contract(f["contract_row_id"])
        contract = {"인플루언서": f["influencer_name"], "연 고정 피(원)": f["annual_fixed_krw"],
                    "성과 피 조건": reg.get("performance_fee_text") or "", "계약 만료": f["expiry"],
                    "해지·조건변경 통보 기한": f["deadline"]}
        proposal = {"fixed_fee_krw": f["annual_fixed_krw"], "performance_base": NET_BASE,
                    "deductions": list(NET_DEDUCTIONS)}
        t = writer.notice_draft(self._provider("writer"), contract, proposal)
        f["notice"] = {"text": t.text, "ok": t.ok, "model": t.model, "proposal": proposal}
        self.store.update_facts(case["id"], f, "AI", "조건변경 통보 초안")
        self.store.add_judgment(case["id"], "통보초안", t.model, "순액 기준 조건변경 통보 초안",
                                {"text": t.text, "ok": t.ok}, not t.ok, None, t.ledger_id)
        self.store.set_status(case["id"], S_NOTICE_DRAFT, "AI", "조건변경 통보 초안 생성" if t.ok else "AI 초안 실패")
        note = "통보 초안을 확인하고 발송해 주세요" if t.ok else "AI 초안이 실패했으니 통보문을 직접 작성해 발송해 주세요"
        deadline = _d(f["deadline"])
        self._task_once(case["id"], self.contract_owner, "통보 발송", deadline if d <= deadline else d,
                        f"{case['ref_id']}: {note}(통보 기한 {_md(deadline)}까지)")
        return S_NOTICE_DRAFT

    @_locked
    def send_notice(self, case_id: int, actor: str, text: str | None = None) -> dict:
        """계약 담당이 통보문을 발송한다(초안이 없으면 text를 직접 줘야 한다). 상대 회신을 기다린다."""
        role = self.role_of(actor)
        case = self.store.get_case(case_id)
        f = case["facts"]
        if not self._can_handle(f, STALE_NOTICE, role, self.contract_owner):
            raise PermissionError(f"{actor}({role})는 통보를 발송할 수 없음 — {self.contract_owner}(또는 방치로 올려 받은 사람)만")
        base = {"case_id": case_id, "actor": actor}
        if case["kind"] != KIND_CONTRACT:
            raise ValueError("전속계약 건이 아님")
        if case["status"] in (S_NOTICE_SENT, S_WAIT_PARTNER, S_HUMAN, S_AGREED):
            return {**base, "changed": False, "status": case["status"], "message": "이미 발송함"}
        if case["status"] != S_NOTICE_DRAFT:
            raise ValueError(f"통보 초안 단계에서만 발송할 수 있음(지금 {case['status']})")
        notice = f["notice"]
        body = (text or "").strip() or (notice["text"] if notice["ok"] else "")
        if not body:
            raise ValueError("초안이 없어 발송할 수 없음 — 통보문을 직접 입력해 주세요")
        notice["sent_text"], notice["sent_by"] = body, actor
        self.store.update_facts(case_id, f, actor, "통보 발송")
        self.store.set_status(case_id, S_NOTICE_SENT, actor, "조건변경 통보 발송")
        for t in self.store.list_tasks(case_id):
            if t["title"] == "통보 발송" and t["status"] == "대기":
                self.store.set_task_status(t["id"], "완료", actor)
        self.store.add_request(case_id, PARTNER, body, False, purpose=P_NOTICE)
        self.store.set_status(case_id, S_WAIT_PARTNER, "시스템", "인플루언서 측 회신 대기")
        return {**base, "changed": True, "status": S_WAIT_PARTNER}

    def _on_notice(self, case_id: int, req: dict, j: judge.ReplyJudgment, text: str) -> str | None:
        """상대가 수용하면 합의(갱신 확정). 그 밖(조건부·거절·애매한 답)은 사람이 확인한다."""
        if j.stance != "수용":
            return f"상대 회신이 수용이 아님({j.stance})"
        self.store.set_status(case_id, S_AGREED, "AI", "상대가 조건변경 통보를 수용")
        return None

    def execution_check(self, influencer_id: str, day: date) -> dict:
        """그 날짜의 집행이 계약 때문에 막히는지. 갱신이 확정되지 않았으면 계약 만료 뒤 집행은 막는다(설계 4.6)."""
        end, renewal = self._contract_terms(influencer_id)
        blocked = not renewal and day > end
        return {"allowed": not blocked, "expiry": None if end == date.max else end.isoformat(),
                "renewal_confirmed": renewal,
                "reason": f"갱신 미확정이라 계약 만료({_md(end)}) 뒤 집행은 막음" if blocked else ""}

    # ---------------------------------------------------------------- 결정

    @_locked
    def decide(self, case_id: int, actor: str, action: str, comment: str = "") -> dict:
        """승인권자의 결정. 승인권자가 아니면 PermissionError, 끝난 건이면 상태 그대로."""
        if action not in DECISIONS:
            raise ValueError(f"결정은 {', '.join(DECISIONS)} 중 하나: {action!r}")
        role = self.role_of(actor)
        case = self.store.get_case(case_id)
        if case["status"] in OPEN[case["kind"]]:
            self._refresh(case_id, {"windows": self._windows()})  # 등록부의 지금 값으로 판정한 뒤 결정
            case = self.store.get_case(case_id)
        f = case["facts"]
        required = _required_roles(f)
        if role not in required:
            raise PermissionError(f"{actor}({role})는 이 건의 승인권자가 아님 — 승인권자: {'·'.join(required)}")
        base = {"case_id": case_id, "actor": actor, "role": role, "action": action}
        if case["status"] not in OPEN[case["kind"]]:
            return {**base, "changed": False, "status": case["status"], "message": "결정 단계가 지난 건이라 상태 그대로"}
        lapsed = self._lapsed_deny(case, base)
        if lapsed is not None:
            return lapsed
        if action == D_REJECT:
            self.store.add_approval(case_id, (role,), action, actor, comment)
            if case["kind"] == KIND_CONTRACT:
                # 계약 갱신 거절은 끝이 아니다: 자동 갱신을 막으려면 조건변경 통보가 나가야 한다(설계 7.4 조건변경 승인 → 통보 초안)
                self.store.set_status(case_id, S_CHANGE_OK, actor, comment or "승인권자 거절 — 조건변경 통보로 진행")
                return {**base, "changed": True, "status": self._draft_notice(case, self._today())}
            self.store.set_status(case_id, S_REJECTED, actor, comment or "승인권자 거절")
            self._close_volume_tasks(case_id)
            self._task_once(case_id, self.campaign, "확정 보류(철회) 처리", self._today(),
                            f"{case['ref_id']}: 승인권자({role})가 거절해 확정하지 않음. 상대측에 보류·철회를 알림")
            return {**base, "changed": True, "status": S_REJECTED}
        if case["status"] == S_WAIT_REPLY:
            raise ValueError("부서 회신을 기다리는 중이라 아직 승인할 수 없음")
        st = f.get("stock") or {}
        if action in (D_APPROVE, D_SPLIT) and st.get("day_qty") and st.get("share") == 0:
            raise ValueError("물류 몫이 0개라 1차 수량이 0이 됨 — 승인할 수 없음(물류와 다시 조율하거나 거절)")
        if action == D_SPLIT and not f.get("split"):
            raise ValueError("분할안이 없어 분할 승인할 수 없음")
        if action == D_APPROVE and (f.get("stock") or {}).get("shortage") and (f.get("scm") or {}).get("state") != SCM_FULL:
            raise ValueError("재고 부족으로 1차 수량이 제한되는 건이라 분할 승인만 가능(SCM이 전량 허용하면 승인도 가능)")
        if role in f.get("approved_roles", []):
            return {**base, "changed": False, "status": case["status"], "message": "이미 승인함"}
        self.store.add_approval(case_id, (role,), action, actor, comment)
        f["approved_roles"] = [*f.get("approved_roles", []), role]
        f["approved_split"] = f.get("split")  # 승인권자들이 본 분할안(나중에 달라지면 재승인)
        if action == D_SPLIT:
            f["split_chosen"] = True
        self.store.update_facts(case_id, f, actor, f"{role} {action}")
        done = self._maybe_finalize(case_id, actor)
        if done:
            return {**base, "changed": True, "status": done[0]["status"]}
        out = {**base, "changed": True, "status": case["status"], "pending": _pending_roles(f)}
        if not out["pending"] and self._stock_open(case_id):
            out["waiting_for"] = ["SCM 회신"]  # 필요한 승인은 모였고 SCM 응답만 남음 — 응답이 분할안을 바꾸면 재승인
        return out

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
            f["phase2"] = ({"qty": split["phase2_qty"], "date": split["phase2_date"],
                            "amount_krw": self._plan_amount_of(f, split["phase2_qty"])}
                           if split["phase2_qty"] > 0 else None)
            if f["phase2"] and f["phase2"]["date"]:
                self._phase2_approvers(f, case_id)
        else:
            first = S_APPROVED
            # 비분할 경로도 분할 경로와 같은 단위(집행일 하루 수량). 하루 수량을 모르면(물량 곡선 밖) 기안 물량 전체.
            st = f.get("stock") or {}
            day_qty = st.get("day_qty") or f["volume"]["units"]
            share = st.get("share")  # 0은 "몫 없음"이 아니라 몫 0개(decide가 막음). 하루 수량을 모르면(0) 물류 몫도 의미 없음
            f["phase1"] = {"qty": min(day_qty, share) if share is not None and st.get("day_qty") else day_qty,
                           "date": f.get("phase1_date") or f["settlement_date"]}
            f["phase2"] = None
        if not f["phase2"]:  # 처음부터 2차가 없는 건(비분할·2차 수량 0): 1차 집행일 + 반품 관찰 기간이 지나면 완료(결과 2차 없음)
            f["phase2_dropped"] = {"why": "분할 없음 — 2차 집행 계획이 없는 승인", "actor": actor,
                                   "at": self._today().isoformat()}
        self.store.update_facts(case_id, f, "시스템", "집행 수량 확정")
        self.store.set_status(case_id, first, actor, "승인권자 전원 승인")
        self._report(case)
        d1 = _d(f["phase1"]["date"])
        qty = f["phase1"]["qty"]
        qty_text = f"{qty:,}개" if qty is not None else f"수량 미정({NO_VOLUME})"
        self._task_once(case_id, self.logistics, "물류 출고", d1, f"{case['ref_id']} {_md(d1)}부터 1차 {qty_text} 출고")
        self._task_once(case_id, self.cs, "CS 대비", d1, f"{case['ref_id']} {_md(d1)}부터 1차 {qty_text} — 반품·문의 대비")
        self.store.set_status(case_id, S_PHASE1, "시스템", "1차 집행 시작")
        if f["phase2"]:
            self.store.set_status(case_id, S_PHASE2_LOCK, "시스템", OBSERVE_NOTE)
            self._phase2_refresh(case_id)  # 갱신 미확정이고 2차가 계약 만료 뒤면 바로 차단
            return self.store.get_case(case_id)["status"]
        return S_PHASE1

    def _report(self, case: dict) -> None:
        for label in case["facts"]["approvers"]:
            if label in REPORT_ONLY:
                self.store.add_event(case["id"], EV_REPORT, "시스템",
                                     {"target": REPORT_ONLY[label], "text": f"{case['ref_id']} 승인 보고"})

    # ---------------------------------------------------------------- 리뷰·반품·2차

    @_locked
    def add_reviews(self, case_id: int, reviews: list[tuple[str, str]], actor: str | None = None) -> GateResult:
        """리뷰를 AI로 해석한다. 색상불일치면 캠페인 담당에게 콘텐츠 수정 요청(첨부 필수), 2차는 잠금 유지.
        actor가 없으면 시연 대본 재생이라 시연 모드에서만, 운영에서는 admin.review_inputters 역할만(거부면 저장도 AI 호출도 없음)."""
        self._require_inputter(actor, "admin.review_inputters", "리뷰")
        case = self.store.get_case(case_id)
        owner = self._owner(case["kind"])
        color = human = 0
        for product, text in reviews:
            self.store.add_review(case_id, product, text)
            j = judge.interpret_review(self._provider("review"), product, text)
            self.store.add_judgment(case_id, "리뷰해석", j.model, f"{product} 리뷰: {text}",
                                    {**asdict(j), "raw": j.raw[:RAW_KEEP]}, j.needs_human, j.confidence,
                                    j.ledger_id)
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
        case = self.store.get_case(case_id)
        g = self._gate(case)
        if case["status"] == S_PHASE2_WAIT and [r for r in g.reasons if r != NO_SALES]:
            self._regress_from_wait(case, g)  # M8: 2차 승인 대기 중 들어온 리뷰가 잠금 사유를 만들면 받은 2차 승인은 무효
        return g

    @_locked
    def add_returns(self, case_id: int, change_of_mind: int, color: int, actor: str | None = None) -> GateResult:
        """1차 반품 건수 입력(시연은 모의). 통계 기준(기준선 = 과거 건수 반품률)을 넘으면 2차 자동 보류.
        actor가 없으면 시연 대본 재생이라 시연 모드에서만, 운영에서는 admin.return_inputters 역할만."""
        self._require_inputter(actor, "admin.return_inputters", "반품")
        if change_of_mind < 0 or color < 0:
            raise ValueError("반품 건수는 0 이상")
        f = self.store.get_case(case_id)["facts"]
        f["returns"] = {"change_of_mind": change_of_mind, "color": color, "date": self._today().isoformat()}
        self.store.update_facts(case_id, f, "시스템", "모의 반품 반영")
        case = self.store.get_case(case_id)
        g = self._gate(case)
        if case["status"] == S_PHASE2_WAIT and [r for r in g.reasons if r != NO_SALES]:
            self._regress_from_wait(case, g)  # M8: 2차 승인 대기 중 들어온 반품이 기준을 넘으면 받은 2차 승인은 무효
        elif g.auto_stopped and case["status"] == S_PHASE2_LOCK:
            self._hold_for_returns(case, g)
        else:
            self._phase2_judge(case_id)  # 반품 보류가 없으면 다음은 판매율(추가 결정 8)
        return g

    def _hold_for_returns(self, case: dict, g: GateResult, voided: list[str] | None = None) -> None:
        """반품이 통계 기준을 넘어 2차 자동 보류. 빠져나오는 길을 함께 연다: 캠페인 담당의 판단 작업(방치 올림 대상, 결정 9 장치).
        캠페인 담당은 2차 취소만 할 수 있고, 그래도 2차를 하려면 2차 승인권자 중 최고 역할이 예외 승인한다(H3)."""
        case_id = case["id"]
        f = self.store.get_case(case_id)["facts"]
        if f.get("phase2_decision"):  # 새 보류는 새 판단을 받는다(이전 판단은 기록으로 남김)
            f.setdefault("phase2_decision_log", []).append(f.pop("phase2_decision"))
        for key in (STALE_PHASE2_HOLD, STALE_PHASE2_WAIT):
            f.get("escalated", {}).pop(key, None)
        f["phase2_hold"] = {"cause": "반품", "reasons": list(g.reasons), "at": self._today().isoformat()}
        self.store.update_facts(case_id, f, "시스템", "2차 자동 보류(반품)")
        why = "; ".join(g.reasons)
        note = why + (f" — 받은 2차 승인({'·'.join(voided)}) 무효" if voided else "")
        self.store.set_status(case_id, S_PHASE2_HOLD, "시스템", note)
        text = (f"{case['ref_id']} 반품이 기준을 넘어 2차 자동 보류: {why}. 캠페인 담당은 2차 취소만 할 수 있고, "
                "그래도 2차를 하려면 2차 승인권자 중 최고 역할이 이유를 적어 예외 승인해야 함")
        self.store.add_event(case_id, EV_P2_HOLD, "시스템", {"cause": "반품", "reasons": list(g.reasons),
                                                          "voided_roles": voided or [], "text": text})
        self._task_once(case_id, self.campaign, STALE_PHASE2_HOLD, self._today(), text)

    def _regress_from_wait(self, case: dict, g: GateResult) -> None:
        """2차 승인 대기 중 게이트가 다시 닫혔다(M8): 받은 2차 승인을 무효로 하고, 반품 자동 보류면 2차 보류, 리뷰 잠금이면 2차 잠금."""
        case_id = case["id"]
        f = case["facts"]
        voided = list(f.get(STAGES["2차"][2], []))
        f[STAGES["2차"][2]] = []
        self.store.update_facts(case_id, f, "시스템", "2차 승인 무효(게이트 재판정)")
        if g.auto_stopped:
            self._hold_for_returns(self.store.get_case(case_id), g, voided)
            return
        note = "; ".join(g.reasons) + " — 2차 승인 대기를 2차 잠금으로 되돌림"
        self.store.set_status(case_id, S_PHASE2_LOCK, "시스템", note)
        self.store.add_event(case_id, EV_P2_HOLD, "시스템", {"cause": "리뷰", "reasons": list(g.reasons),
                                                          "voided_roles": voided, "text": f"{case['ref_id']} {note}"})

    def _renewal_confirmed(self, contract: dict) -> bool:
        """이 등록부 계약(기간·만료일)의 갱신이 확정됐는가. 같은 계약 행·만료일의 지금 모드 사건만 센다(M1)."""
        return any(c["ref_id"] == contract["influencer_code"] and c["status"] in RENEWAL_CONFIRMED
                   and c["facts"].get("contract_row_id") == contract["id"]
                   and c["facts"].get("expiry") == contract["expiry_date"]
                   for c in self._cases(KIND_CONTRACT))

    def _gate(self, case: dict) -> GateResult:
        """반품·리뷰·관찰·계약 만료 판정(_gate_core)에 1차 판매 실적 입력 여부를 더한다(추가 결정 8)."""
        g = self._gate_core(case)
        f = case["facts"]
        if not f.get("phase2") or f.get("sales"):
            return g
        return replace(g, open=False, reasons=(*g.reasons, NO_SALES), actions=(*g.actions, "1차 판매 실적 입력"))

    def _gate_core(self, case: dict) -> GateResult:
        f = case["facts"]
        review_actions = (("콘텐츠 수정 요청", "사람 확인")
                          if f.get("color_review_flagged") and not f.get("content_fix_confirmed") else ())
        p2 = f.get("phase2")
        if not p2:
            return GateResult(False, False, ("2차 집행 없음",), review_actions)
        p1 = f.get("phase1") or {}
        inf = f.get("influencer_id") or ""
        end, renewal = self._contract_terms(inf)
        p1_date = _d(p1["date"]) if p1.get("date") else self._today()
        r = {} if f.get("phase2_exception") else (f.get("returns") or {})  # 예외 승인을 받은 건은 반품 보류 사유를 보지 않는다
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

    def phase2_status(self, case_id: int) -> GateResult:
        """지금 2차 집행을 열 수 있는지(반품·리뷰·관찰·계약 만료 판정)."""
        return self._gate(self.store.get_case(case_id))

    def _phase2_blocked(self, f: dict) -> bool:
        """갱신 미확정인데 2차 집행일이 계약 만료 뒤(또는 날짜를 정할 수 없음)."""
        p2 = f.get("phase2")
        if not p2:
            return False
        end, renewal = self._contract_terms(f.get("influencer_id") or "")
        return (not renewal) and (_d(p2["date"]) if p2.get("date") else date.max) > end

    def _phase2_refresh(self, case_id: int) -> list[dict]:
        """2차 잠금 ↔ 2차 차단. 갱신이 확정되면 차단이 풀리고 비어 있던 2차 날짜를 정한다."""
        case = self.store.get_case(case_id)
        f = case["facts"]
        if case["status"] not in (S_PHASE2_LOCK, S_PHASE2_BLOCKED):
            return []
        blocked = self._phase2_blocked(f)
        today = self._today().isoformat()
        if blocked and case["status"] == S_PHASE2_LOCK:
            end, _ = self._contract_terms(f.get("influencer_id") or "")
            note = f"갱신 미확정인데 2차 집행일이 계약 만료({_md(end)}) 뒤라 2차 차단"
            self.store.set_status(case_id, S_PHASE2_BLOCKED, "시스템", note)
            return [{"date": today, "case_id": case_id, "action": "2차차단", "text": note}]
        if not blocked and case["status"] == S_PHASE2_BLOCKED:
            self._replan_phase2(case_id)
            note = "갱신이 확정되어 2차 차단 해제"
            self.store.set_status(case_id, S_PHASE2_LOCK, "시스템", note)
            return [{"date": today, "case_id": case_id, "action": "2차차단해제", "text": note},
                    *self._phase2_refresh(case_id)]  # 풀린 날 바로 2차 잠금 점검(판정이 끝난 건은 승인 대기 진입)
        if not blocked and case["status"] == S_PHASE2_LOCK:
            acts = self._phase2_judge(case_id)
            # 판매율 판정은 끝났는데 집행일이 밀려 2차 차단이 된 건이 풀린 경우: 판정은 다시 하지 않고 승인 대기로 들어간다
            if (not acts and (f.get("phase2_sellthrough") or {}).get("outcome") in (SELL_ADJUST, SELL_SOLDOUT)
                    and not [r for r in self._gate(case).reasons if r != NO_SALES]):
                acts = self._enter_phase2_wait(case_id)
            return acts
        return []

    def _replan_phase2(self, case_id: int) -> None:
        """2차 날짜가 비어 있으면(계약 만료 뒤라 못 정했던 경우) 갱신이 확정된 지금 같은 규칙으로 정한다."""
        f = self.store.get_case(case_id)["facts"]
        p1, p2 = f["phase1"], f["phase2"]
        if p2.get("date"):
            return
        line = f["volume"]["product_line"]
        sp = make_split(p1["qty"] + p2["qty"], p1["qty"], p1["qty"], _d(p1["date"]), inventory.line_restock_date(line),
                        self._windows(), date.max)
        p2["date"] = sp.phase2_date.isoformat() if sp.phase2_date else None
        if p2["date"]:
            self._phase2_approvers(f, case_id)
        self.store.update_facts(case_id, f, "시스템", "갱신 확정으로 2차 집행일 결정")
        self._notify_date(case_id, "2차", None, p2["date"], "계약 갱신 확정으로 2차 집행일 결정", "시스템")

    def _phase2_approvers(self, f: dict, case_id: int, amount_krw: int | None = None,
                          before: ApproverDecision | None = None, why: str = "") -> None:
        """2차 집행일 기준으로 승인권자를 다시 판정한다(설계 4.2·4.5). 1차와 달라지면 권한 이동으로 남긴다.
        판매율로 2차 금액이 줄어 다시 판정할 때는 amount_krw(줄어든 요청액)와 before(지금의 2차 판정)를 넘기고,
        바뀐 이유(why)를 권한 이동 사유에 쓴다."""
        a_key, h_key, ok_key, date_key = STAGES["2차"]
        d2 = _d(f["phase2"]["date"])
        if self._active_ups(f, "2차"):  # 규칙으로 2차 결재선을 다시 정하면 상신으로 바꾼 결재선은 무효
            self._void_ups(self.store.get_case(case_id), f, "2차", "2차 승인권자를 다시 판정", "시스템")
        amount = f["amount_krw"] if amount_krw is None else amount_krw
        f["phase2_judged_krw"] = amount
        dec = decide_plan(PlanFacts(f["plan_id"], f["campaign_id"] or "", f["influencer_id"] or "", amount,
                                    f["plan_total_krw"], d2, _d(f["deadline"]), "확대", f["indicator_good"]),
                          self._windows())
        change = diff_approver(before or _decision(f), dec, d2)
        if change is not None and why:
            change = replace(change, reason=f"{why}로 2차 승인권자가 {'·'.join(change.before)}에서 "
                                            f"{'·'.join(change.after)}로 바뀜. 새 근거: "
                                            + "; ".join(h.text for h in dec.hits))
        f[a_key], f[h_key], f[ok_key], f[date_key] = list(dec.approvers), _hits(dec.hits), [], f["phase2"]["date"]
        if change is not None:
            self.store.add_approver_change(case_id, change)

    # ---------------------------------------------------------------- 상부 상신 (수정 회차 2 결정 A)

    @staticmethod
    def _active_ups(f: dict, stage: str) -> list[dict]:
        return [r for r in f.get("escalations", []) if r["stage"] == stage and r["active"]]

    def _void_ups(self, case: dict, f: dict, stage: str, why: str, actor: str) -> None:
        """그 단계의 상신을 무효로 한다(기록은 남김). 결재선은 호출한 쪽이 규칙 판정으로 다시 정한다."""
        today = self._today().isoformat()
        for r in self._active_ups(f, stage):
            r["active"], r["void_at"], r["void_why"] = False, today, why
        text = f"{case['ref_id']} {stage} 상신 무효: {why}해 상신으로 바꾼 결재선을 규칙 판정으로 되돌림"
        self.store.add_event(case["id"], EV_UP_VOID, actor, {"stage": stage, "text": text})

    def _up_role(self, role: str) -> str | None:
        """보고 체계에서 한 단계 위 역할. 체계 밖이거나 맨 위면 None. 방치 올림과 달리 회의체(이사회)도 건너뛰지 않는다."""
        chain = self.people.escalation
        return chain[chain.index(role) + 1] if role in chain and chain.index(role) + 1 < len(chain) else None

    def _can_escalate(self, case: dict, role: str, stage: str) -> bool:
        f = case["facts"]
        if stage == "1차":
            if case["status"] not in OPEN[case["kind"]]:
                return False
        elif case["kind"] != KIND_PLAN or case["status"] != S_PHASE2_WAIT:
            return False
        return role in _pending_roles(f, stage) and self._up_role(role) is not None

    @_locked
    def escalate(self, case_id: int, actor: str, stage: str, opinion: str, reason: str) -> dict:
        """승인권자가 "내 권한을 넘는다"고 판단해 상급자에게 올린다(1차 또는 2차 승인 단계).
        올린 역할은 결재선에서 빠지고 보고 체계의 바로 위 역할이 들어간다(이미 있으면 중복 없이). 의견(승인 권고·반대 권고)과
        이유는 필수이고 권한 이동 기록·상신 이벤트로 남는다. 기한·경고·방치 올림은 그대로(연장 없음)."""
        if stage not in STAGES:
            raise ValueError(f"단계는 {' 또는 '.join(STAGES)}: {stage!r}")
        if opinion not in UP_OPINIONS:
            raise ValueError(f"상신 의견은 {' 또는 '.join(UP_OPINIONS)} 중 하나: {opinion!r}")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("상신 이유 문장이 필요함")
        role = self.role_of(actor)
        case = self.store.get_case(case_id)
        first = stage == "1차"
        if first:
            if case["status"] not in OPEN[case["kind"]]:
                raise ValueError(f"결정 단계가 지난 건이라 상신할 수 없음(지금 {case['status']})")
            self._refresh(case_id, {"windows": self._windows()})  # 등록부의 지금 값으로 판정한 뒤 상신
            case = self.store.get_case(case_id)
            if case["status"] not in OPEN[case["kind"]]:
                raise ValueError(f"결정 단계가 지난 건이라 상신할 수 없음(지금 {case['status']})")
        elif case["kind"] != KIND_PLAN or case["status"] != S_PHASE2_WAIT:
            raise ValueError(f"2차 승인 대기 상태인 건만 2차 상신을 할 수 있음(지금 {case['status']})")
        f = case["facts"]
        req, pending = _required_roles(f, stage), _pending_roles(f, stage)
        if role not in req:
            raise PermissionError(f"{actor}({role})는 이 건의 {stage} 승인권자가 아님 — 승인권자: {'·'.join(req)}")
        if role not in pending:
            raise ValueError(f"{actor}({role})는 이미 결정한 승인권자라 상신할 수 없음")
        today = self._today()
        if first:
            lapsed = self._lapsed_deny(case, {"case_id": case_id, "actor": actor, "role": role, "stage": stage})
            if lapsed is not None:
                return lapsed
        if not first and is_lapsed(_d(f["phase2_deadline"]), today):  # 2차 승인도 기본 거부 실행일 전날까지
            res = self._phase2_default_deny(case, today)
            return {"case_id": case_id, "actor": actor, "role": role, "stage": stage, "changed": False,
                    "status": res["status"], "message": res["text"]}
        to = self._up_role(role)
        if to is None:
            where = "보고 체계 밖의 역할이라" if role not in self.people.escalation else "보고 체계의 맨 위라"
            raise ValueError(f"{role}는 {where} 상신할 곳이 없음")
        a_key, h_key, _, _ = STAGES[stage]
        before, kept = tuple(f[a_key]), [x for x in f[a_key]]
        to_label = UP_LABEL.get(to, to)
        new: list[str] = []
        for label in kept:
            if label not in REPORT_ONLY and _role(label) == role:
                if to not in {_role(x) for x in [*new, *kept] if x not in REPORT_ONLY} and to_label not in new:
                    new.append(to_label)  # 올린 자리에 상급자(이미 결재선에 있으면 넣지 않음)
            else:
                new.append(label)
        ups = self._active_ups(f, stage)
        ok_key = STAGES[stage][2]
        voided = to in f.get(ok_key, [])  # H4: 상급자가 이미 한 승인은 무효, 다시 결재(상신만으로 확정되지 않음)
        if voided:
            f[ok_key] = [r for r in f[ok_key] if r != to]
            if first and not f[ok_key]:
                f.pop("split_chosen", None)
                f.pop("approved_split", None)
        rec = {"stage": stage, "from": role, "to": to, "actor": actor, "opinion": opinion, "reason": reason.strip(),
               "at": today.isoformat(), "active": True, "base": ups[0]["base"] if ups else list(before),
               "voided_decision": voided}
        f["escalations"] = [*f.get("escalations", []), rec]
        f[a_key] = new
        self.store.update_facts(case_id, f, actor, f"{stage} 상신: {role}→{to}")
        ref = case["ref_id"]
        text = f"{ref} {stage} 상신: {role}({actor})가 {to}에게 올림 — {opinion}: {rec['reason']}"
        if voided:
            text += f" (상신으로 이전 결정 무효: {to}가 이미 한 승인을 무효로 하고 다시 결재)"
        self.store.add_approver_change(case_id, ApproverChange(
            before, tuple(new), f"상신: {role}({actor})가 {to}에게 올림 — {opinion}: {rec['reason']}",
            tuple(RuleHit(**h) for h in f.get(h_key, [])), today))
        self.store.add_event(case_id, EV_UP, actor, {"stage": stage, "from": role, "to": to, "target": to,
                                                    "opinion": opinion, "reason": rec["reason"], "text": text})
        if voided:
            self.store.add_event(case_id, EV_REAPPROVE, actor, {"target": to, "text": text, "stage": stage})
        base = {"case_id": case_id, "actor": actor, "role": role, "stage": stage, "to": to, "opinion": opinion,
                "changed": True, "voided_decision": voided}
        # 상신만으로는 확정되지 않는다: 상급자가 (다시) 결재해야 한다
        now = self.store.get_case(case_id)
        return {**base, "status": now["status"], "approvers": now["facts"][a_key],
                "required_roles": _required_roles(now["facts"], stage), "pending": _pending_roles(now["facts"], stage)}

    # ---------------------------------------------------------------- 2차 수량의 판매율 조절 (추가 결정 8)

    @staticmethod
    def _plan_amount_of(f: dict, qty: int) -> int:
        """계획 2차 금액 = 기안 요청액 × 2차 수량 ÷ 기안 물량(원 단위 내림). 물량을 모르면 1차+2차 수량으로 나눈다."""
        units = (f.get("volume") or {}).get("units")
        if not units:
            units = ((f.get("phase1") or {}).get("qty") or 0) + qty
        return f["amount_krw"] * qty // units if units else 0

    @_locked
    def record_phase1_sales(self, case_id: int, actor: str, orders: int, returns: int) -> dict:
        """캠페인 담당이 1차 판매 실적(주문 수·반품 수)을 입력한다. 순판매 = 주문 - 반품.
        주문·반품이 0 이상 정수이고 반품이 주문 이하여야 한다(아니면 ValueError, 아무것도 바꾸지 않음).
        판정(2차 수량 조절·보류·품절 기록)은 2차 게이트가 열릴 때: 반품 보류·리뷰 잠금·관찰 기간이 먼저다.
        HTTP 연결은 Task 12."""
        role = self.role_of(actor)
        if role != self.campaign:
            raise PermissionError(f"{actor}({role})는 1차 판매 실적을 입력할 수 없음 — {self.campaign}만")
        for label, v in (("주문 수", orders), ("반품 수", returns)):
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                raise ValueError(f"{label}는 0 이상 정수여야 함: {v!r}")
        if returns > orders:
            raise ValueError(f"반품 수({returns:,})가 주문 수({orders:,})보다 클 수 없음")
        case = self.store.get_case(case_id)
        f = case["facts"]
        if case["kind"] != KIND_PLAN or not f.get("phase1"):
            raise ValueError("1차 집행이 시작된 기안만 판매 실적을 입력할 수 있음")
        if f.get("phase2_sellthrough"):
            raise ValueError("이미 판매율로 2차를 판정한 건은 판매 실적을 고칠 수 없음")
        if not f["phase1"].get("qty"):
            raise ValueError("1차 수량이 없어 판매율을 낼 수 없음")
        f["sales"] = {"orders": orders, "returns": returns, "net": orders - returns, "date": self._today().isoformat()}
        self.store.update_facts(case_id, f, actor, f"1차 판매 실적 입력: 주문 {orders:,}, 반품 {returns:,}")
        for t in self.store.list_tasks(case_id):
            if t["title"] == "1차 판매 실적 입력" and t["status"] == "대기":
                self.store.set_task_status(t["id"], "완료", actor)
        acts = self._phase2_judge(case_id)
        now = self.store.get_case(case_id)
        return {"case_id": case_id, "status": now["status"], "sales": now["facts"]["sales"], "actions": acts,
                "gate": asdict(self._gate(now))}

    def _resize_phase2(self, f: dict, case_id: int, amt_b: int, qty_a: int, amt_a: int, why: str, core: str) -> None:
        """2차 수량·금액을 바꾸고 승인권자를 다시 판정한다(자동 조절과 담당 판단이 같은 경로를 쓴다)."""
        p2 = f["phase2"]
        before = _decision(f, "2차") if f.get(STAGES["2차"][0]) else None
        p2["qty"], p2["amount_krw"] = qty_a, amt_a
        if p2.get("date"):
            # 줄어든 2차 금액만큼 요청액을 덜어 승인권자를 다시 판정한다(같은 승인권자 규칙 경로)
            self._phase2_approvers(f, case_id, f["amount_krw"] - (amt_b - amt_a), before,
                                   f"{why} 2차 금액 {amt_b:,}→{amt_a:,}원")
            f[STAGES["2차"][1]].append({"rule_id": "sellthrough_adjust", "text": core,
                                       "source": "1차 판매 실적", "badge": "계산"})

    def _hold_guard(self, case_id: int, actor: str, reason, sell_only: bool = True) -> tuple[dict, dict, dict]:
        """2차 보류 판단의 공통 검사. 보류 상태가 아니면 ValueError. sell_only(2차 계속)면 판매율 보류만, 아니면(2차 취소) 반품 보류도 가능.
        이미 판단했으면 ValueError, 담당도 올려 받은 사람도 아니면 PermissionError, 이유가 비면 ValueError."""
        case = self.store.get_case(case_id)
        f = case["facts"]
        rec = f.get("phase2_sellthrough") or {}
        if case["kind"] != KIND_PLAN or case["status"] != S_PHASE2_HOLD:
            raise ValueError("2차 보류 상태인 건만 판단할 수 있음")
        if sell_only and rec.get("outcome") != SELL_HOLD:
            raise ValueError("1차 판매율이 하한 미만이라 2차 보류가 된 건만 2차 계속을 판단할 수 있음"
                             "(반품 보류는 2차 취소 또는 2차 승인권자 중 최고 역할의 예외 승인)")
        if f.get("phase2_decision"):
            raise ValueError("이미 판단한 건 — 판단은 한 번만")
        role = self.role_of(actor)
        if not self._can_handle(f, STALE_PHASE2_HOLD, role, self.campaign):
            raise PermissionError(f"{actor}({role})는 2차 보류를 판단할 수 없음 — {self.campaign}(또는 방치로 올려 받은 사람)만")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("판단 이유 문장이 필요함")
        return case, f, rec

    def _finish_hold(self, case: dict, f: dict, rec: dict, actor: str, choice: str, reason: str, qty_a: int,
                     amt_a: int, status: str) -> dict:
        case_id, ref = case["id"], case["ref_id"]
        qty_b, amt_b = rec["qty_before"], rec["amount_before"]
        basis = (f"1차 판매율 {rec['rate']:.1%} 보류 건" if rec.get("rate") is not None else "반품 자동 보류 건")
        f["phase2_decision"] = {"choice": choice, "reason": reason.strip(), "actor": actor, "qty_before": qty_b,
                                "qty_after": qty_a, "at": self._today().isoformat()}
        self.store.update_facts(case_id, f, actor, f"판매율 보류 판단: {choice}")
        self.store.set_status(case_id, status, actor, f"{ref} {choice}: {reason.strip()}")
        task = self._hold_task(case_id)
        if task:
            self.store.set_task_status(task["id"], "완료", actor)
        text = (f"{ref} {basis}을 {choice}으로 판단: 2차 {qty_b:,}→{qty_a:,}개, "
                f"금액 {amt_b:,}→{amt_a:,}원 — 이유: {reason.strip()}")
        self.store.add_event(case_id, EV_DECIDE, actor, {
            "choice": choice, "rate": rec.get("rate"), "reason": reason.strip(), "qty_before": qty_b, "qty_after": qty_a,
            "amount_before": amt_b, "amount_after": amt_a, "text": text})
        return {"case_id": case_id, "choice": choice, "status": status, "qty_before": qty_b, "qty_after": qty_a,
                "amount_before": amt_b, "amount_after": amt_a, "text": text}

    @_locked
    def continue_phase2(self, case_id: int, actor: str, qty: int, reason: str) -> dict:
        """판매율 보류 건을 2차 계속으로 판단한다. 수량은 1 이상 계획 2차 이하, 금액은 같은 비율로 줄이고
        2차 승인권자를 다시 판정하며 2차 잠금(승인 대기) 경로로 보낸다."""
        case, f, rec = self._hold_guard(case_id, actor, reason)
        blockers = [r for r in self._gate(case).reasons if r != NO_SALES]
        if self._phase2_blocked(f) and not blockers:
            blockers = ["갱신 미확정인데 2차 집행일이 계약 만료 뒤"]
        if blockers:  # 보류 뒤에 생긴 반품 보류·리뷰 잠금이 우선: 계속은 막고(취소는 가능) 풀린 뒤 다시 판단한다
            raise ValueError("2차를 계속할 수 없음 — 자동 보류 사유가 남아 있음: " + "; ".join(blockers) +
                             " (사유가 풀린 뒤 다시 판단하거나 2차 취소)")
        qty_b, amt_b = rec["qty_before"], rec["amount_before"]
        if not isinstance(qty, int) or isinstance(qty, bool) or not 1 <= qty <= qty_b:
            raise ValueError(f"2차 수량은 1 이상 계획 2차({qty_b:,}개) 이하의 정수여야 함: {qty!r}")
        amt_a = amt_b * qty // qty_b
        core = (f"1차 판매율 {rec['rate']:.1%} 보류 건을 담당이 2차 계속으로 판단: "
                f"2차 {qty_b:,}→{qty:,}개, 금액 {amt_b:,}→{amt_a:,}원")
        self._resize_phase2(f, case_id, amt_b, qty, amt_a, "2차 계속 판단으로", core)
        out = self._finish_hold(case, f, rec, actor, CHOICE_CONTINUE, reason, qty, amt_a, S_PHASE2_LOCK)
        acts = self._enter_phase2_wait(case_id)  # 게이트가 열려 있으므로 곧바로 2차 승인 대기
        if acts:
            out |= {"status": self.store.get_case(case_id)["status"], "actions": acts}
        return out

    @_locked
    def cancel_phase2(self, case_id: int, actor: str, reason: str) -> dict:
        """판매율 보류 건을 2차 취소로 판단한다: 2차 없음, 상태는 1차 집행(2차 잠금 해제)."""
        case, f, rec = self._hold_guard(case_id, actor, reason, sell_only=False)
        if rec.get("outcome") != SELL_HOLD:  # 반품 보류: 판매율 기록이 없을 수 있으니 계획 2차에서 이전 수량·금액을 잡는다
            p2 = f["phase2"]
            rec = {"qty_before": p2["qty"], "amount_before": p2.get("amount_krw") or self._plan_amount_of(f, p2["qty"]),
                   "rate": None}
        f["phase2"] = None
        out = self._finish_hold(case, f, rec, actor, CHOICE_CANCEL, reason, 0, 0, S_PHASE1)
        acts = self._close_without_phase2(case_id, actor, f"{actor}가 2차 취소({reason.strip()})")
        if acts:
            out |= {"status": self.store.get_case(case_id)["status"], "actions": acts}
        return out

    def _exception_role(self, f: dict) -> str | None:
        """반품 보류 예외 승인을 할 수 있는 역할: 그 건 2차 승인권자(2차 판정이 없으면 1차 승인권자) 중 보고 체계에서 가장 높은 역할."""
        roles = _required_roles(f, "2차") if f.get(STAGES["2차"][0]) else _required_roles(f)
        chain = self.people.escalation
        known = [r for r in roles if r in chain]
        return max(known, key=chain.index) if known else None

    @_locked
    def approve_phase2_exception(self, case_id: int, actor: str, qty: int, reason: str) -> dict:
        """반품 자동 보류 건을 2차 승인권자 중 최고 역할이 이유를 적어 예외 승인한다(H3). 수량은 1 이상 계획 2차 이하, 금액은 같은 비율로
        줄이고 2차 승인권자를 다시 판정하며 2차 잠금(승인 대기) 경로로 보낸다. 이후 반품 보류 사유는 다시 걸지 않는다."""
        case = self.store.get_case(case_id)
        f = case["facts"]
        if case["kind"] != KIND_PLAN or case["status"] != S_PHASE2_HOLD or not f.get("phase2"):
            raise ValueError("2차 보류 상태인 건만 예외 승인할 수 있음")
        rec = f.get("phase2_sellthrough") or {}
        if rec.get("outcome") == SELL_HOLD:
            raise ValueError("판매율이 하한 미만인 보류는 예외 승인이 아니라 2차 계속·취소로 판단함")
        if f.get("phase2_decision"):
            raise ValueError("이미 판단한 건 — 판단은 한 번만")
        role, top = self.role_of(actor), self._exception_role(f)
        if top is None or role != top:
            raise PermissionError(f"{actor}({role})는 예외 승인할 수 없음 — 이 건 2차 승인권자 중 최고 역할"
                                  f"({top or '없음'})만")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("예외 승인 이유 문장이 필요함")
        p2 = f["phase2"]
        qty_b = p2["qty"]
        amt_b = p2.get("amount_krw") or self._plan_amount_of(f, qty_b)
        if not isinstance(qty, int) or isinstance(qty, bool) or not 1 <= qty <= qty_b:
            raise ValueError(f"2차 수량은 1 이상 계획 2차({qty_b:,}개) 이하의 정수여야 함: {qty!r}")
        amt_a = amt_b * qty // qty_b
        f["phase2_exception"] = {"actor": actor, "role": role, "reason": reason.strip(), "qty_before": qty_b,
                                 "qty_after": qty, "at": self._today().isoformat()}
        core = (f"반품 보류 건을 {role}({actor})가 예외 승인: 2차 {qty_b:,}→{qty:,}개, 금액 {amt_b:,}→{amt_a:,}원"
                f" — 이유: {reason.strip()}")
        self._resize_phase2(f, case_id, amt_b, qty, amt_a, "반품 보류 예외 승인으로", core)
        out = self._finish_hold(case, f, {"qty_before": qty_b, "amount_before": amt_b, "rate": None}, actor,
                                CHOICE_EXCEPTION, reason, qty, amt_a, S_PHASE2_LOCK)
        self.store.add_event(case_id, EV_P2_EXCEPTION, actor, {"role": role, "reason": reason.strip(), "qty_before": qty_b,
                                                            "qty_after": qty, "amount_after": amt_a, "text": core})
        acts = self._phase2_refresh(case_id)  # 판매 실적이 있고 다른 잠금이 없으면 곧바로 2차 승인 대기
        return {**out, "status": self.store.get_case(case_id)["status"], "actions": acts}

    # ---------------------------------------------------------------- 2차 승인·집행 (수정 회차 1 판정 3)

    def _enter_phase2_wait(self, case_id: int) -> list[dict]:
        """2차 게이트가 모두 풀리고 판매율 판정이 조절·유지(보류 아님)로 끝난 2차 잠금 건을 2차 승인 대기로 보낸다.
        2차 기한 = 2차 집행일. 기본 거부 실행일 = 집행일 - deadline.buffer_days(승인은 그 전날까지). 진입일 + phase2.min_approval_days가
        그 실행일보다 늦으면 집행일을 (진입일 + phase2.min_approval_days + deadline.buffer_days)로 민다. 필요한 2차 승인 역할이 없으면 바로 집행."""
        case = self.store.get_case(case_id)
        f = case["facts"]
        p2 = f.get("phase2")
        if case["kind"] != KIND_PLAN or case["status"] != S_PHASE2_LOCK or not p2 or not p2.get("date"):
            return []
        today = self._today()
        planned = _d(p2["date"])
        min_days, buffer = policy.get("phase2.min_approval_days"), policy.get("deadline.buffer_days")
        earliest = today + timedelta(days=min_days)  # 승인권자에게 보장하는 최소 기간이 끝나는 날
        shifted = earliest > deny_date(planned)  # 기본 거부 실행일이 그보다 이르면 집행일을 민다
        deadline = earliest + timedelta(days=buffer) if shifted else planned  # 2차 기한 = (밀린) 2차 집행일
        before = _decision(f, "2차") if f.get(STAGES["2차"][0]) else None
        if shifted:
            new_day = deadline
            f.setdefault("phase2_planned_date", p2["date"])
            p2["date"] = new_day.isoformat()
            keep = [h for h in f.get(STAGES["2차"][1], []) if h["rule_id"] == "sellthrough_adjust"]
            self._phase2_approvers(f, case_id, f.get("phase2_judged_krw"), before,  # 날짜만 바뀌므로 앞서 쓴 요청액 그대로
                                   f"2차 집행일 {_md(planned)}→{_md(new_day)} 연기" if before else "")
            f[STAGES["2차"][1]].extend(keep)  # 판매율 조절 근거는 다시 판정해도 남긴다
        elif not before:
            self._phase2_approvers(f, case_id)
        ref = case["ref_id"]
        if shifted:
            text = (f"{ref} 2차 집행일 연기(승인 기간 확보): {_md(planned)}→{_md(new_day)} — 기본 거부 실행일 "
                    f"{_md(deny_date(planned))}이 승인 최소 기간({_md(earliest)}까지)보다 이르러 집행일을 "
                    f"진입일 + {min_days}일 + 여유 {buffer}일로 민다")
            self.store.add_event(case_id, EV_P2_SHIFT, "시스템", {"from": planned.isoformat(), "to": new_day.isoformat(),
                                                               "deadline": deadline.isoformat(), "text": text})
            self.store.update_facts(case_id, f, "시스템", "2차 집행일 연기(승인 기간 확보)")
            self._notify_date(case_id, "2차", planned.isoformat(), new_day.isoformat(), "승인 기간 확보", "시스템")
            if self._phase2_blocked(f):  # 밀린 집행일이 갱신 미확정 계약의 만료 뒤면 2차 차단
                end, _ = self._contract_terms(f.get("influencer_id") or "")
                note = f"2차 집행일 {_md(new_day)}이 계약 만료({_md(end)}) 뒤라 갱신 미확정이면 2차 차단"
                self.store.set_status(case_id, S_PHASE2_BLOCKED, "시스템", note)
                return [{"date": today.isoformat(), "case_id": case_id, "action": EV_P2_SHIFT, "text": text},
                        {"date": today.isoformat(), "case_id": case_id, "action": "2차차단", "text": note}]
        f["phase2_deadline"], f["phase2_waiting_since"], f["phase2_warned_targets"] = deadline.isoformat(), today.isoformat(), []
        self.store.update_facts(case_id, f, "시스템", "2차 승인 대기 진입")
        shift_act = ([{"date": today.isoformat(), "case_id": case_id, "action": EV_P2_SHIFT, "text": text}]
                     if shifted else [])
        roles = _required_roles(f, "2차")
        if not roles:
            self._start_phase2_exec(case_id, "시스템")
            return [*shift_act, {"date": today.isoformat(), "case_id": case_id, "action": "2차집행",
                                 "text": f"{ref} 2차 승인권자가 없어 바로 2차 집행"}]
        text = (f"{ref} 2차 {p2['qty']:,}개 — 2차 게이트가 열려 2차 승인 대기: 승인권자 {'·'.join(roles)}, "
                f"마지막 승인일 {_md(approval_deadline(deadline))}(2차 집행일 {_md(deadline)}의 {buffer}일 전 기본 거부)")
        self.store.set_status(case_id, S_PHASE2_WAIT, "시스템", text)
        self.store.add_event(case_id, EV_P2_WAIT, "시스템", {"roles": roles, "deadline": deadline.isoformat(),
                                                          "approval_deadline": approval_deadline(deadline).isoformat(),
                                                          "text": text})
        alarm = self._alarm(self.store.get_case(case_id), today, "2차")  # 들어간 날이 곧 마지막 승인일이면 그날 바로 알림
        return [*shift_act, {"date": today.isoformat(), "case_id": case_id, "action": EV_P2_WAIT, "text": text}, *alarm]

    def _phase2_end(self, case_id: int, actor: str, result: str, text: str) -> str:
        """2차 없이(거절·기본 거부) 또는 2차 집행을 마치고 완료. 1차는 이미 집행됐으므로 조건 변경 통보는 만들지 않는다."""
        f = self.store.get_case(case_id)["facts"]
        f["phase2_result"] = {"result": result, "text": text, "actor": actor, "at": self._today().isoformat()}
        self.store.update_facts(case_id, f, actor, f"2차 {result}")
        self.store.set_status(case_id, S_DONE, actor, text)
        self.store.add_event(case_id, EV_P2_DONE if result == P2_EXECUTED else EV_P2_DECIDE, actor,
                             {"result": result, "text": text})
        return S_DONE

    def _close_without_phase2(self, case_id: int, actor: str, why: str) -> list[dict]:
        """2차 취소·판매율 조절 0개로 2차가 없어진 건: 1차 집행에 머물지 않고 반품 관찰 기간(split.return_observe_days)이
        끝나면 완료(결과 2차 없음 + 사유). 이미 끝났으면 바로 완료. 아직이면 표시만 남기고 매일 점검이 끝나는 날 완료한다."""
        case = self.store.get_case(case_id)
        f = case["facts"]
        if case["kind"] != KIND_PLAN or case["status"] != S_PHASE1 or f.get("phase2") or not f.get("phase1"):
            return []
        if not f.get("phase2_dropped"):
            f["phase2_dropped"] = {"why": why, "actor": actor, "at": self._today().isoformat()}
            self.store.update_facts(case_id, f, actor, "2차 없음 표시")
        p1 = f["phase1"]
        end = _d(p1["date"]) + timedelta(days=policy.get("split.return_observe_days")) if p1.get("date") else self._today()
        today = self._today()
        if today < end:
            return []
        text = (f"{case['ref_id']} 2차 없음 — {f['phase2_dropped']['why']}. 반품 관찰 기간"
                f"{'이 ' + _md(end) + '에 끝나' if today > end else '이 끝나'} 완료")
        return [{"date": today.isoformat(), "case_id": case_id, "action": EV_P2_DECIDE,
                 "status": self._phase2_end(case_id, actor, P2_NONE, text), "text": text}]

    def _phase2_default_deny(self, case: dict, d: date) -> dict:
        """2차 승인 기한까지 승인이 없으면 기본 거부 → 2차 없음, 완료(이유 문장, 이벤트). 통보는 만들지 않는다."""
        f = case["facts"]
        run = deny_date(_d(f["phase2_deadline"]))
        text = (f"{case['ref_id']} 2차 마지막 승인일 {_md(approval_deadline(_d(f['phase2_deadline'])))}까지 승인이 없어 "
                f"2차 집행일 {_md(_d(f['phase2_deadline']))}의 {policy.get('deadline.buffer_days')}일 전({_md(run)}) 기본 거부 — "
                "2차 집행 없음, 완료")
        status = self._phase2_end(case["id"], "시스템", P2_DENY, text)
        return {"date": d.isoformat(), "case_id": case["id"], "action": "2차기본거부", "status": status, "text": text}

    def _start_phase2_exec(self, case_id: int, actor: str) -> str:
        """2차 승인권자가 모두 승인함 → 2차 집행: 물류 출고·CS 대비 작업(날짜 = 2차 집행일), 그룹 보고 대상이면 보고."""
        case = self.store.get_case(case_id)
        f = case["facts"]
        ref, p2 = case["ref_id"], f["phase2"]
        d2, qty = _d(p2["date"]), p2["qty"]
        f["phase2_exec"] = {"qty": qty, "date": p2["date"], "amount_krw": p2.get("amount_krw"),
                            "approved_at": self._today().isoformat()}
        self.store.update_facts(case_id, f, actor, "2차 집행 확정")
        text = f"{ref} 2차 승인권자 전원 승인 — 2차 {qty:,}개 {_md(d2)} 집행"
        self.store.set_status(case_id, S_PHASE2_EXEC, actor, text)
        self.store.add_event(case_id, EV_P2_DECIDE, actor, {"result": "승인", "qty": qty, "date": p2["date"], "text": text})
        for label in f[STAGES["2차"][0]]:
            if label in REPORT_ONLY:
                self.store.add_event(case_id, EV_REPORT, "시스템",
                                     {"target": REPORT_ONLY[label], "text": f"{ref} 2차 승인 보고", "stage": "2차"})
        self._task_once(case_id, self.logistics, "물류 출고(2차)", d2, f"{ref} {_md(d2)}부터 2차 {qty:,}개 출고")
        self._task_once(case_id, self.cs, "CS 대비(2차)", d2, f"{ref} {_md(d2)}부터 2차 {qty:,}개 — 반품·문의 대비")
        return S_PHASE2_EXEC

    def _phase2_stand_in(self, f: dict, role: str, pending: list[str]) -> list[str]:
        """이 역할이 2차 승인으로 채우는 역할들. 승인권자면 자기 몫, 방치 올림으로 받은 상급자면 자기보다 아래 보고 체계의
        남은 역할 몫. 아니면 빈 목록."""
        if role in pending:
            return [role]
        if self._can_handle(f, STALE_PHASE2_WAIT, role, ""):
            chain = self.people.escalation
            return [r for r in pending if r in chain and role in chain and chain.index(r) < chain.index(role)]
        return []

    @_locked
    def decide_phase2(self, case_id: int, actor: str, action: str, comment: str = "") -> dict:
        """2차 승인 대기 건에 대한 2차 승인권자의 결정(승인·거절). 필요한 2차 승인권자가 모두 승인하면 2차 집행,
        한 명이라도 거절하거나 기한을 넘기면(기본 거부) 2차 없이 완료. 2차 승인권자(또는 방치로 올려 받은 상급자)가 아니면 PermissionError."""
        if action not in P2_DECISIONS:
            raise ValueError(f"2차 결정은 {' 또는 '.join(P2_DECISIONS)} 중 하나: {action!r}")
        role = self.role_of(actor)
        case = self.store.get_case(case_id)
        if case["kind"] != KIND_PLAN or case["status"] != S_PHASE2_WAIT:
            raise ValueError(f"2차 승인 대기 상태인 건만 2차 결정을 할 수 있음(지금 {case['status']})")
        f = case["facts"]
        required, pending = _required_roles(f, "2차"), _pending_roles(f, "2차")
        stand = self._phase2_stand_in(f, role, pending)
        if not stand and role not in required:
            raise PermissionError(f"{actor}({role})는 이 건의 2차 승인권자가 아님 — 2차 승인권자: {'·'.join(required)}")
        base = {"case_id": case_id, "actor": actor, "role": role, "action": action, "stage": "2차"}
        today = self._today()
        if is_lapsed(_d(f["phase2_deadline"]), today):  # 승인은 2차 기본 거부 실행일 전날까지
            res = self._phase2_default_deny(case, today)
            return {**base, "changed": False, "status": res["status"], "message": res["text"]}
        ref, qty = case["ref_id"], f["phase2"]["qty"]
        if action == D_REJECT:
            self.store.add_approval(case_id, (role,), "2차 거절", actor, comment)
            text = f"{ref} 2차 {qty:,}개를 {role}({actor})가 거절{': ' + comment if comment else ''} — 2차 집행 없음, 완료"
            return {**base, "changed": True, "status": self._phase2_end(case_id, actor, P2_REJECT, text)}
        if not stand:
            return {**base, "changed": False, "status": case["status"], "message": "이미 승인함"}
        self.store.add_approval(case_id, (role,), "2차 승인", actor, comment)
        f[STAGES["2차"][2]] = [*f.get(STAGES["2차"][2], []), *stand]
        self.store.update_facts(case_id, f, actor, f"{role} 2차 승인")
        left = _pending_roles(f, "2차")
        if not left:
            return {**base, "changed": True, "status": self._start_phase2_exec(case_id, actor)}
        return {**base, "changed": True, "status": S_PHASE2_WAIT, "pending": left}

    def _phase2_daily(self, case: dict, d: date) -> list[dict]:
        """날마다: 2차 승인 대기는 기한 점검(조기 경고·방치 올림·기본 거부), 2차 집행은 집행일이 지나면 완료."""
        f = case["facts"]
        if case["status"] == S_PHASE1 and f.get("phase2_dropped"):
            return self._close_without_phase2(case["id"], "시스템", f["phase2_dropped"]["why"])
        if case["status"] == S_PHASE2_BLOCKED:
            end, renewal = self._contract_terms(f.get("influencer_id") or "")
            if renewal or d <= end:  # 갱신이 확정되지 않은 채 계약 만료일이 지나야 끝낸다(그 전에 확정되면 차단이 풀림)
                return []
            text = (f"{case['ref_id']} 계약 만료({_md(end)})가 지나도록 갱신이 확정되지 않아 2차 없음 — 완료")
            return [{"date": d.isoformat(), "case_id": case["id"], "action": EV_P2_DECIDE,
                     "status": self._phase2_end(case["id"], "시스템", P2_NONE, text), "text": text}]
        if case["status"] == S_PHASE2_EXEC:
            if d <= _d(f["phase2"]["date"]):
                return []
            text = f"{case['ref_id']} 2차 집행일 {_md(_d(f['phase2']['date']))}이 지나 완료"
            return [{"date": d.isoformat(), "case_id": case["id"], "action": EV_P2_DONE,
                     "status": self._phase2_end(case["id"], "시스템", P2_EXECUTED, text), "text": text}]
        if case["status"] != S_PHASE2_WAIT:
            return []
        acts = deadline_actions(_d(f["phase2_deadline"]), d, approved=False)  # 1차와 같은 규칙(기본 거부 실행일 기준)
        if "기본거부" in acts:
            return [self._phase2_default_deny(case, d)]
        out: list[dict] = []
        if "조기경고" in acts:
            w = self._warn(case, d, "2차")
            if w:
                out.append(w)
            out += self._alarm(self.store.get_case(case["id"]), d, "2차")
        case = self.store.get_case(case["id"])
        f = case["facts"]
        since = f.get("phase2_warned_on")
        if since:
            got = self._escalate_stale(case, STALE_PHASE2_WAIT, _d(since), "·".join(_pending_roles(f, "2차")),
                                       _required_roles(f, "2차"), "경고", d, "2차 승인 방치")
            if got:
                out.append(got)
        return out

    def _phase2_judge(self, case_id: int) -> list[dict]:
        """2차 게이트가 열리는 시점(반품 보류·리뷰 잠금·관찰 기간·계약 만료가 모두 풀림)에 판매율로 2차를 판정한다.
        판매 실적이 없으면 열지 않고 캠페인 담당 작업만 만든다. 한 건당 한 번만 판정한다."""
        case = self.store.get_case(case_id)
        f = case["facts"]
        p2 = f.get("phase2")
        if case["kind"] != KIND_PLAN or case["status"] != S_PHASE2_LOCK or not p2 or f.get("phase2_sellthrough"):
            return []
        if self._phase2_blocked(f) or [r for r in self._gate(case).reasons if r != NO_SALES]:
            return []
        today = self._today()
        ref = case["ref_id"]
        sales = f.get("sales")
        if not sales:
            self._task_once(case_id, self.campaign, "1차 판매 실적 입력", today,
                            f"{ref} 2차를 열려면 1차 주문 수·반품 수가 필요함(판매율 = (주문-반품) ÷ 1차 {f['phase1']['qty']:,}개)")
            return []
        p1q, net = f["phase1"]["qty"], sales["net"]
        rate = net / p1q
        hold = policy.get("split.sellthrough_hold_ratio")
        qty_b = p2["qty"]
        amt_b = p2.get("amount_krw")
        if amt_b is None:
            amt_b = self._plan_amount_of(f, qty_b)
        basis = (f"1차 판매율 {rate:.1%}(순판매 {net:,}개 = 주문 {sales['orders']:,} - 반품 {sales['returns']:,}, "
                 f"1차 {p1q:,}개)")
        drop_why = None
        rec = {"rate": rate, "orders": sales["orders"], "returns": sales["returns"], "net": net, "p1_qty": p1q,
               "hold_ratio": hold, "qty_before": qty_b, "amount_before": amt_b, "at": today.isoformat()}
        if rate < hold:
            rec |= {"outcome": SELL_HOLD, "qty_after": qty_b, "amount_after": amt_b}
            core = f"{basis}가 하한 {hold:.1%} 미만이라 2차 {qty_b:,}개를 자동으로 줄이지 않고 보류 — 캠페인 담당이 판단"
            f["phase2_sellthrough"] = rec
            self.store.update_facts(case_id, f, "시스템", "판매율 하한 미만: 2차 보류")
            self.store.set_status(case_id, S_PHASE2_HOLD, "시스템", f"{ref} {core}")
            self._task_once(case_id, self.campaign, "2차 보류 판단", today, f"{ref} {core}")
        elif rate >= 1:
            rec |= {"outcome": SELL_SOLDOUT, "qty_after": qty_b, "amount_after": amt_b, "excess": max(0, net - p1q)}
            core = (f"{basis}: 1차 전량 판매(품절) — 2차 계획 {qty_b:,}개 유지, 넘친 수요 {rec['excess']:,}개는 "
                    "2차 판단 자료로 기록")
            f["phase2_sellthrough"], f["phase1_soldout"] = rec, True
            self.store.update_facts(case_id, f, "시스템", "1차 품절 기록: 2차 계획 유지")
        else:
            qty_a, amt_a = qty_b * net // p1q, amt_b * net // p1q
            rec |= {"outcome": SELL_ADJUST, "qty_after": qty_a, "amount_after": amt_a}
            core = f"{basis}에 맞춰 2차 {qty_b:,}→{qty_a:,}개, 금액 {amt_b:,}→{amt_a:,}원"
            f["phase2_sellthrough"] = rec
            if qty_a == 0:
                f["phase2"] = None
                core += " — 2차 수량이 0개가 되어 2차 없음"
                self.store.update_facts(case_id, f, "시스템", "판매율 조절: 2차 없음")
                self.store.set_status(case_id, S_PHASE1, "시스템", f"{ref} {core}")
                drop_why = f"판매율 {rate:.1%}에 맞춘 2차 수량이 0개"
            else:
                self._resize_phase2(f, case_id, amt_b, qty_a, amt_a, f"1차 판매율 {rate:.1%}로", core)
                self.store.update_facts(case_id, f, "시스템", "판매율 조절: 2차 수량·금액")
        text = f"{ref} {core}"
        self.store.add_event(case_id, EV_SELL, "시스템", {**rec, "text": text})
        return [{"date": today.isoformat(), "case_id": case_id, "action": EV_SELL, "text": text},
                *(self._close_without_phase2(case_id, "시스템", drop_why) if drop_why else []),
                *self._enter_phase2_wait(case_id)]  # 조절·품절이면 2차 승인 대기, 보류·2차 없음이면 아무것도 안 함

    # ---------------------------------------------------------------- 화면용 읽기

    @staticmethod
    def deadline_view(deadline: str | None) -> dict:
        """화면용 기한 세 날짜: 기한(deadline), 기본 거부 실행일(deny_date = 기한 - 여유일), 마지막 승인일(approval_deadline = 실행일 전날, 이날 알림).
        모두 rules/deadline.py의 같은 함수로 센다."""
        if not deadline:
            return {"deadline": deadline, "deny_date": None, "approval_deadline": None}
        d = _d(deadline)
        return {"deadline": deadline, "deny_date": deny_date(d).isoformat(), "approval_deadline": approval_deadline(d).isoformat()}

    @classmethod
    def _item(cls, c: dict) -> dict:
        return {"case_id": c["id"], "kind": c["kind"], "ref_id": c["ref_id"], "status": c["status"],
                **cls.deadline_view(c["facts"].get("deadline"))}

    def _stale_open(self, c: dict, key: str) -> bool:
        """올림 알림은 그 일이 아직 미처리일 때만 보인다."""
        if key.startswith(f"{STALE_SCM_HUMAN}#"):
            return c["status"] in OPEN[c["kind"]] and int(key.rsplit("#", 1)[1]) in self._human_stock_ids(c["id"])
        if key == STALE_PHASE2_WAIT:
            return c["status"] == S_PHASE2_WAIT
        if key == STALE_NOTICE:
            return c["status"] == S_NOTICE_DRAFT
        return c["status"] == S_PHASE2_HOLD and not c["facts"].get("phase2_decision") and self._hold_task(c["id"]) is not None

    @staticmethod
    def _ups_for(f: dict, stage: str, role: str) -> dict:
        """이 역할 앞으로 올라온 유효한 상신(올린 역할·사람·의견·이유). 없으면 빈 사전."""
        ups = [{k: r[k] for k in ("from", "actor", "opinion", "reason", "at")}
               for r in f.get("escalations", []) if r["stage"] == stage and r["active"] and r["to"] == role]
        return {"상신": ups} if ups else {}

    def todo(self, person: str) -> dict:
        """사람별 할 일(설계 6.2): 승인 대기, 기한 임박, 회신 대기, 작업, 권한 이동, 알림."""
        role = self.role_of(person)
        out: dict = {"person": person, "role": role, "승인 대기": [], "기한 임박": [], "회신 대기": [],
                     "작업": [], "권한 이동": [], "알림": []}
        cases = {c["id"]: c for c in self._cases()}
        for c in cases.values():
            if c["status"] in APPROVAL_STATES and role in _pending_roles(c["facts"]):
                out["승인 대기"].append({**self._item(c), **self._ups_for(c["facts"], "1차", role)})
            if (c["status"] == S_PHASE2_WAIT and self._phase2_stand_in(c["facts"], role, _pending_roles(c["facts"], "2차"))):
                out["승인 대기"].append({**self._item(c), "stage": "2차", **self.deadline_view(c["facts"]["phase2_deadline"]),
                                     **self._ups_for(c["facts"], "2차", role)})
            for ch in self.store.get_approver_changes(c["id"]):
                before = {_role(x) for x in ch.before if x not in REPORT_ONLY}
                after = {_role(x) for x in ch.after if x not in REPORT_ONLY}
                if role in before and role not in after:
                    out["권한 이동"].append({**self._item(c), "reason": ch.reason})
        for e in self.store.events(kind=EV_WARN):
            c = cases.get(e["case_id"])
            # 아직 승인하지 않은 동안만 보인다(승인했거나 승인권자에서 빠지면 지난 경고는 내려감)
            if e["detail"].get("stage") == "2차":  # 2차 승인 대기 건의 조기 경고
                if (c and e["detail"]["target"] == role and c["status"] == S_PHASE2_WAIT
                        and role in _pending_roles(c["facts"], "2차")):
                    out["기한 임박"].append({**self._item(c), "stage": "2차", **self.deadline_view(c["facts"]["phase2_deadline"]),
                                         "text": e["detail"]["text"]})
                continue
            if e["detail"].get("notice_overdue"):  # 통보 기한이 지났는데 통보가 안 나간 계약 건: 아직 통보 초안일 때만 보인다
                if c and e["detail"]["target"] == role and c["status"] == S_NOTICE_DRAFT:
                    out["기한 임박"].append({**self._item(c), "text": e["detail"]["text"]})
                continue
            if e["detail"].get("scm_human"):  # 승인은 모였고 SCM 회신 사람 확인만 남은 건: 아직 사람 확인 중일 때만 보인다
                if (c and e["detail"]["target"] == role and c["status"] in OPEN[c["kind"]] and
                        set(e["detail"].get("request_ids", [])) & set(self._human_stock_ids(c["id"]))):
                    out["기한 임박"].append({**self._item(c), "text": e["detail"]["text"]})
                continue
            if (c and e["detail"]["target"] == role and c["status"] in OPEN[c["kind"]]
                    and role in _pending_roles(c["facts"])):
                out["기한 임박"].append({**self._item(c), "text": e["detail"]["text"]})
        latest: dict = {}
        for e in self.store.events(kind=EV_DATE):  # 집행일 변경: 건·단계마다 마지막 변경만
            latest[(e["case_id"], e["detail"]["stage"])] = e
        for (case_id, st), e in latest.items():
            c = cases.get(case_id)
            if c and role in e["detail"]["targets"]:
                out["알림"].append({**self._item(c), "kind": EV_DATE, "stage": st, "text": e["detail"]["text"]})
        for e in self.store.events(kind=EV_ALARM):  # 마지막 승인일 알림: 그 기한에 아직 승인하지 않은 동안만 보인다
            c = cases.get(e["case_id"])
            if not c:
                continue
            st, f = e["detail"]["stage"], c["facts"]
            dkey, states = ("deadline", APPROVAL_STATES) if st == "1차" else ("phase2_deadline", (S_PHASE2_WAIT,))
            if (role in e["detail"]["targets"] and c["status"] in states and f.get(dkey) == e["detail"]["deadline"]
                    and role in _pending_roles(f, st)):
                out["알림"].append({**self._item(c), "kind": EV_ALARM, "stage": st, "text": e["detail"]["text"]})
        for kind in (EV_REPORT, EV_REAPPROVE, EV_BLOCK, EV_UNBLOCK, EV_STALE):
            for e in self.store.events(kind=kind):
                c = cases.get(e["case_id"])
                if c and e["detail"]["target"] == role and (kind != EV_STALE or self._stale_open(c, e["detail"]["key"])):
                    out["알림"].append({**self._item(c), "kind": kind, "text": e["detail"]["text"]})
        for r in self.store.all_requests(dept=role):
            if r["status"] != R_DONE and r["case_id"] in cases:
                out["회신 대기"].append({**self._item(cases[r["case_id"]]), "request_id": r["id"], "text": r["text"],
                                      "request_status": r["status"], "attach_required": r["attach_required"]})
        for t in self.store.all_tasks(dept=role):
            if t["status"] == "대기" and t["case_id"] in cases:
                out["작업"].append({**self._item(cases[t["case_id"]]), "task_id": t["id"], "title": t["title"],
                                  "detail": t["detail"], "due": t["due"]})
        return out

    def phase2_view(self, case_id: int) -> dict:
        """2차 집행 관찰 화면(설계 6.5): 계획 2차, 2차 승인권자, 게이트(열림·자동 보류·사유), 판매 실적·반품·판매율 판정·담당 판단."""
        case = self.store.get_case(case_id)
        f = case["facts"]
        has = bool(f.get(STAGES["2차"][0]))
        return {"plan": f.get("phase2"), "approvers": f.get(STAGES["2차"][0]), "hits": f.get(STAGES["2차"][1], []),
                "required_roles": _required_roles(f, "2차") if has else [],
                "pending_roles": _pending_roles(f, "2차") if has else [],
                "gate": asdict(self._gate(case)), "sales": f.get("sales"), "returns": f.get("returns"),
                "sellthrough": f.get("phase2_sellthrough"), "decision": f.get("phase2_decision"),
                **self.deadline_view(f.get("phase2_deadline")), "approved_roles": f.get(STAGES["2차"][2], []),
                "exec": f.get("phase2_exec"), "result": f.get("phase2_result")}

    BRIEFING, COUNTERPOINTS = "브리핑", "반대근거"  # ai_judgments 종류

    def _brief_basis(self, case: dict) -> dict:
        """AI 브리핑·반대 근거에 넘기는 사실(규칙 판정과 근거). 이 값이 바뀌면 저장된 브리핑은 낡은 것."""
        f = case["facts"]
        out: dict = {"건": case["ref_id"], "종류": case["kind"], "상태": case["status"],
                     "승인권자": f["approvers"], "규칙 근거": [h["text"] for h in f["approver_hits"]],
                     "지표 판정": "좋음" if f["indicator_good"] else "반대 근거 있음",
                     "지표 근거": [h["text"] for h in f["indicator_hits"]], "기한": f["deadline"]}
        if case["kind"] == KIND_PLAN:
            out |= {"요청액": f["amount_krw"], "기안 총액": f["plan_total_krw"], "집행일": f.get("phase1_date")}
            if f.get("split"):
                sp = f["split"]
                out["분할안"] = {"1차 수량": sp["phase1_qty"], "1차 날짜": sp["phase1_date"],
                              "2차 수량": sp["phase2_qty"], "2차 날짜": sp["phase2_date"]}
            if f.get("scm"):
                out["SCM 응답"] = f["scm"]["state"]
        else:
            out |= {"연 고정 피": f["annual_fixed_krw"], "계약 만료": f["expiry"]}
        return out

    @staticmethod
    def _fingerprint(basis: dict) -> str:
        return hashlib.sha256(json.dumps(basis, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()

    def _stored_text(self, case_id: int, kind: str, fp: str) -> dict | None:
        rows = [j for j in self.store.list_judgments(case_id) if j["kind"] == kind]
        if not rows:
            return None
        j = rows[-1]
        return {"text": j["result"]["text"], "ok": j["result"]["ok"], "model": j["model"], "sim_date": j["sim_date"],
                "stale": j["result"]["fingerprint"] != fp}

    @_locked
    def write_briefing(self, case_id: int, actor: str) -> dict:
        """결재권자 브리핑과 반대 근거를 AI로 만들어 판정 기록에 남긴다. 사실이 같고 이미 성공한 저장본이 있으면 다시 부르지 않는다."""
        self.role_of(actor)
        case = self.store.get_case(case_id)
        basis = self._brief_basis(case)
        fp = self._fingerprint(basis)
        for kind, make in ((self.BRIEFING, writer.briefing), (self.COUNTERPOINTS, writer.counterpoints)):
            have = self._stored_text(case_id, kind, fp)
            if have and not have["stale"] and have["ok"]:
                continue
            t = make(self._provider("writer"), basis)
            self.store.add_judgment(case_id, kind, t.model, f"{case['ref_id']} {kind}",
                                    {"text": t.text, "ok": t.ok, "fingerprint": fp}, not t.ok, None, t.ledger_id)
        return self._texts(case_id, fp)

    def _texts(self, case_id: int, fp: str) -> dict:
        return {"briefing": self._stored_text(case_id, self.BRIEFING, fp),
                "counterpoints": self._stored_text(case_id, self.COUNTERPOINTS, fp)}

    def case_detail(self, case_id: int, viewer: str | None = None) -> dict:
        """건 상세(설계 6.3): 근거, 규칙 판정, 2차 정보, AI 브리핑(저장본만 — 읽기는 AI를 부르지 않음), 기록, 권한 이동.
        viewer(보는 사람)를 주면 그 사람이 지금 결정할 수 있는지 함께 돌려준다."""
        case = self.store.get_case(case_id)
        f = case["facts"]
        open_ = case["status"] in OPEN[case["kind"]]
        pending = _pending_roles(f) if open_ else []
        p2 = self.phase2_view(case_id) if case["kind"] == KIND_PLAN and f.get("phase2") else None
        out = {
            "case": {k: case[k] for k in ("id", "kind", "ref_id", "status", "origin", "created_at", "updated_at")},
            "facts": f,
            "evidence": {"indicators": {"good": f["indicator_good"], "hits": f["indicator_hits"],
                                        "excluded": f["indicator_excluded"]}},
            "rule": {"approvers": f["approvers"], "hits": f["approver_hits"], "required_roles": _required_roles(f),
                     "approved_roles": f.get("approved_roles", []), "pending_roles": pending},
            "phase2": p2,
            **self.deadline_view(f.get("deadline")),
            "escalations": f.get("escalations", []),
            **self._texts(case_id, self._fingerprint(self._brief_basis(case))),
            "approver_changes": [{"before": list(c.before), "after": list(c.after), "reason": c.reason,
                                  "hits": _hits(c.hits), "at": c.at.isoformat()}
                                 for c in self.store.get_approver_changes(case_id)],
            "approvals": self.store.list_approvals(case_id),
            "requests": [{**r, "replies": self.store.list_replies(r["id"])} for r in self.store.list_requests(case_id)],
            "tasks": self.store.list_tasks(case_id),
            "reviews": self.store.list_reviews(case_id),
            "judgments": self.store.list_judgments(case_id),
            "history": self.store.events(case_id),
        }
        if viewer is not None:
            role = self.role_of(viewer)
            out["viewer"] = {"person": viewer, "role": role, "can_decide": open_ and role in pending,
                             "can_escalate": self._can_escalate(case, role, "1차"),
                             "can_escalate_phase2": self._can_escalate(case, role, "2차"),
                             "can_decide_phase2": case["status"] == S_PHASE2_WAIT and bool(
                                 self._phase2_stand_in(f, role, _pending_roles(f, "2차")))}
        return out

    def calendar(self) -> list[dict]:
        """캘린더(설계 6.2): 하회 구간, 확정·통보 기한, 집행일, 2차 집행일, 계약 만료, 작업 기한. 날짜순."""
        out: list[dict] = []

        def add(day: str, kind: str, label: str, case_id=None, roles=(), end=None):
            out.append({"date": day, "end": end, "kind": kind, "label": label, "case_id": case_id, "roles": list(roles)})

        for w in self._windows():
            add(w.start.isoformat(), "하회 구간", f"현금 하회 구간 {_md(w.start)}~{_md(w.end)}", end=w.end.isoformat())
        with_case = set()
        for c in self._cases():
            f = c["facts"]
            pending = _pending_roles(f) if c["status"] in OPEN[c["kind"]] else []
            if c["kind"] == KIND_PLAN:
                add(approval_deadline(_d(f["deadline"])).isoformat(), "알림", f"{c['ref_id']} 마지막 승인일(내일 기본 거부)",
                    c["id"], pending)
                add(f["deadline"], "확정 기한", f"{c['ref_id']} 확정 기한", c["id"], pending)
                add(f.get("phase1_date") or f["settlement_date"], "집행일", f"{c['ref_id']} 집행일", c["id"], [self.campaign])
                if f.get("phase2") and f["phase2"].get("date"):
                    add(f["phase2"]["date"], "2차 집행일", f"{c['ref_id']} 2차 집행일", c["id"], [self.campaign])
                if c["status"] == S_PHASE2_WAIT:
                    add(approval_deadline(_d(f["phase2_deadline"])).isoformat(), "2차 알림",
                        f"{c['ref_id']} 2차 마지막 승인일(내일 기본 거부)", c["id"], _pending_roles(f, "2차"))
            else:
                with_case.add(f["contract_row_id"])
                add(approval_deadline(_d(f["deadline"])).isoformat(), "알림", f"{c['ref_id']} 마지막 승인일(내일 기본 거부)",
                    c["id"], pending)
                add(f["deadline"], "통보 기한", f"{c['ref_id']} 해지·조건변경 통보 기한", c["id"], pending)
                add(f["expiry"], "계약 만료", f"{c['ref_id']} 계약 만료", c["id"], [self.contract_owner])
        for k in self.store.list_contracts():
            if k["id"] not in with_case:
                add(k["notice_deadline"], "통보 기한", f"{k['influencer_code']} 해지·조건변경 통보 기한", None, [self.contract_owner])
                add(k["expiry_date"], "계약 만료", f"{k['influencer_code']} 계약 만료", None, [self.contract_owner])
        shown = {c["id"] for c in self._cases()}
        for t in self.store.all_tasks():
            if t["status"] == "대기" and t["case_id"] in shown:
                add(t["due"], "작업", t["title"], t["case_id"], [t["dept"]])
        out.sort(key=lambda e: (e["date"], e["kind"]))
        return out
