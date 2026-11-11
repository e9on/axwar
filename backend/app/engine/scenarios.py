"""시연 파일(backend/demo/*.json) 읽기·검증과 등록부 등록.

시연 장면은 파일로만 존재한다. 파일은 등록할 기안·계약의 ID만 고르고(금액·날짜는 등록부·원본에서 읽는다),
미리 넣어 둘 부서 요청과 시간 순서 대본(날짜, 행동, 입력 문장)을 담는다. 대본은 시연 조작판과 테스트가 같이 쓴다.

파일 형식
  title, description: 문자열
  plans: [기안 ID], contracts: [인플루언서 코드]
  register_contracts: [인플루언서 코드] (선택) 등록부에만 넣는 계약 — 사건은 열지 않는다(2차 집행의 계약 만료·갱신 판정용)
  requests: [{plan|contract, dept, text, attach_required?, purpose?}]
  script: [{action, plan|contract, date?, ...}]
    회신  dept, text, attachments?          (SCM 응답도 dept="SCM" 회신)
    결정  actor(보는 사람 이름), decision(승인|분할승인|거절), comment?
    리뷰  reviews: [[상품, 문장], ...]
    반품  change_of_mind, color(건수)
    공지  actor                              (캠페인 담당이 1차 수량을 소비자에게 공지: 재고·물류 예약)
    발송  actor                              (계약 담당이 조건변경 통보문을 상대에게 발송)
    기준일 date(대상 없음)
  date가 있으면 그 날짜로 기준일을 옮긴 뒤 행동한다.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app import config
from app.data import loader
from app.store.db import Store

ROLES = ("캠페인 담당", "마케팅팀", "Masil 대표", "CEO", "이사회", "그룹", "계약 담당",
         "물류", "SCM", "CS", "품질", "에이전시", "인플루언서 측")
DECISIONS = ("승인", "분할승인", "거절")
ACTION_FIELDS = {"회신": ("dept", "text"), "결정": ("actor", "decision"), "리뷰": ("reviews",),
                 "반품": ("change_of_mind", "color"), "판매": ("actor", "orders", "returns"), "공지": ("actor",), "발송": ("actor",), "기준일": ("date",)}
TARGETED = ("회신", "결정", "리뷰", "반품", "판매", "공지", "발송")
_TOP_KEYS = ("title", "description", "plans", "contracts", "requests", "script")
_NAME = re.compile(r"^[\w-]+$")
SEED_ACTOR = "시연"


@dataclass(frozen=True)
class Scenario:
    name: str
    title: str
    description: str
    plans: tuple[str, ...]
    contracts: tuple[str, ...]
    requests: tuple[dict, ...]
    script: tuple[dict, ...]
    register_contracts: tuple[str, ...] = ()


@dataclass(frozen=True)
class People:
    people: dict[str, str]  # 이름 -> 역할
    escalation: tuple[str, ...]  # 아래에서 위로
    escalation_skip: tuple[str, ...] = ()  # 회의체라 올림 대상에서 빼는 역할(그다음 높은 역할로 올린다)

    def role_of(self, who: str, allow_role_names: bool = True) -> str:
        """이름이면 그 역할, (허용할 때) 역할 이름이면 그대로. 모르면 PermissionError.
        운영에서는 역할 이름을 사람 대신 받지 않는다(적기만 하면 권한이 생기지 않게)."""
        if who in self.people:
            return self.people[who]
        if allow_role_names and who in self.people.values():
            return who
        raise PermissionError(f"등록되지 않은 사람: {who}")

    def above(self, role: str) -> str:
        """보고 체계에서 한 단계 위 역할. 맨 위이거나 체계 밖이면 맨 위 역할."""
        chain = self.escalation
        if role in chain and chain.index(role) + 1 < len(chain):
            return chain[chain.index(role) + 1]
        return chain[-1]

    def names_of(self, role: str) -> list[str]:
        return [n for n, r in self.people.items() if r == role]


def load_people(path: str | Path | None = None) -> People:
    p = Path(path) if path is not None else config.people_path()
    body = json.loads(p.read_text(encoding="utf-8"))
    rows, chain = body.get("people"), body.get("escalation")
    if not isinstance(rows, list) or not isinstance(chain, list) or not chain:
        raise ValueError(f"사람 목록 {p.name}: people·escalation 목록이 필요함")
    people: dict[str, str] = {}
    for i, r in enumerate(rows):
        if not isinstance(r, dict) or not isinstance(r.get("name"), str) or r.get("role") not in ROLES:
            raise ValueError(f"사람 목록 {p.name}: people[{i}]의 이름 또는 역할이 잘못됨: {r!r} (역할은 {', '.join(ROLES)})")
        people[r["name"]] = r["role"]
    bad = [c for c in chain if c not in ROLES]
    if bad:
        raise ValueError(f"사람 목록 {p.name}: escalation에 모르는 역할 {bad}")
    skip = body.get("escalation_skip", [])
    if not isinstance(skip, list) or [c for c in skip if c not in chain]:
        raise ValueError(f"사람 목록 {p.name}: escalation_skip은 escalation 안의 역할 목록이어야 함: {skip!r}")
    return People(people, tuple(chain), tuple(skip))


def _fail(name: str, msg: str) -> ValueError:
    return ValueError(f"시연 파일 {name}.json: {msg}")


def _check_date(name: str, where: str, v) -> None:
    try:
        date.fromisoformat(v)
    except (TypeError, ValueError):
        raise _fail(name, f"{where}의 date는 YYYY-MM-DD여야 함: {v!r}") from None


def _check_target(name: str, where: str, item: dict, plans: list, contracts: list) -> None:
    has_plan, has_contract = "plan" in item, "contract" in item
    if has_plan == has_contract:
        raise _fail(name, f"{where}에는 plan 또는 contract 중 하나가 있어야 함")
    if has_plan and item["plan"] not in plans:
        raise _fail(name, f"{where}의 기안 {item['plan']!r}이 plans에 없음")
    if has_contract and item["contract"] not in contracts:
        raise _fail(name, f"{where}의 계약 {item['contract']!r}이 contracts에 없음")


def _check_step(name: str, i: int, s, plans: list, contracts: list) -> None:
    where = f"script[{i}]"
    if not isinstance(s, dict):
        raise _fail(name, f"{where}는 객체여야 함")
    action = s.get("action")
    if action not in ACTION_FIELDS:
        raise _fail(name, f"{where}의 알 수 없는 행동 {action!r} ({', '.join(ACTION_FIELDS)})")
    for f in ACTION_FIELDS[action]:
        if f not in s:
            raise _fail(name, f"{where}({action})에 {f} 없음")
    if "date" in s:
        _check_date(name, where, s["date"])
    if action in TARGETED:
        _check_target(name, where, s, plans, contracts)
    if action == "회신":
        if s["dept"] not in ROLES or not isinstance(s["text"], str) or not s["text"].strip():
            raise _fail(name, f"{where}의 dept 또는 text가 잘못됨")
        att = s.get("attachments", 0)
        if not isinstance(att, int) or isinstance(att, bool) or att < 0:
            raise _fail(name, f"{where}의 attachments는 0 이상 정수여야 함")
    elif action in ("공지", "발송"):
        if not isinstance(s["actor"], str) or not s["actor"].strip():
            raise _fail(name, f"{where}의 actor가 잘못됨")
    elif action == "결정":
        if s["decision"] not in DECISIONS:
            raise _fail(name, f"{where}의 decision은 {', '.join(DECISIONS)} 중 하나여야 함: {s['decision']!r}")
        if not isinstance(s["actor"], str):
            raise _fail(name, f"{where}의 actor가 잘못됨")
    elif action == "리뷰":
        ok = isinstance(s["reviews"], list) and all(
            isinstance(r, list) and len(r) == 2 and all(isinstance(x, str) for x in r) for r in s["reviews"])
        if not ok:
            raise _fail(name, f"{where}의 reviews는 [[상품, 문장], ...]이어야 함")
    elif action == "판매":
        if not isinstance(s["actor"], str) or not s["actor"].strip():
            raise _fail(name, f"{where}의 actor가 잘못됨")
        for f in ("orders", "returns"):
            v = s[f]
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                raise _fail(name, f"{where}의 {f}는 0 이상 정수여야 함")
        if s["returns"] > s["orders"]:
            raise _fail(name, f"{where}의 returns는 orders보다 클 수 없음")
    elif action == "반품":
        for f in ("change_of_mind", "color"):
            v = s[f]
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                raise _fail(name, f"{where}의 {f}는 0 이상 정수여야 함")


def load(name: str, demo_dir: str | Path | None = None) -> Scenario:
    """시연 파일 이름(확장자 없이)으로 읽고 형식을 검증한다. 형식 오류는 파일·항목을 담은 ValueError."""
    if not isinstance(name, str) or not _NAME.match(name):
        raise ValueError(f"시연 파일 이름은 글자·숫자·_·-만 쓴다: {name!r}")
    folder = Path(demo_dir) if demo_dir is not None else config.demo_dir()
    path = folder / f"{name}.json"
    if not path.is_file():
        raise FileNotFoundError(f"시연 파일 없음: {path}")
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise _fail(name, f"JSON 형식 오류: {e}") from None
    if not isinstance(body, dict):
        raise _fail(name, "최상위는 객체여야 함")
    missing = [k for k in _TOP_KEYS if k not in body]
    if missing:
        raise _fail(name, f"항목이 없음: {', '.join(missing)}")
    plans, contracts = body["plans"], body["contracts"]
    reg = body.get("register_contracts", [])
    for k, v in (("plans", plans), ("contracts", contracts), ("register_contracts", reg)):
        if not isinstance(v, list) or not all(isinstance(x, str) and x for x in v):
            raise _fail(name, f"{k}는 문자열 ID 목록이어야 함")
    if not isinstance(body["requests"], list) or not isinstance(body["script"], list):
        raise _fail(name, "requests·script는 목록이어야 함")
    for i, r in enumerate(body["requests"]):
        where = f"requests[{i}]"
        if not isinstance(r, dict) or r.get("dept") not in ROLES or not isinstance(r.get("text"), str):
            raise _fail(name, f"{where}의 dept 또는 text가 잘못됨")
        _check_target(name, where, r, plans, contracts)
        if not isinstance(r.get("attach_required", False), bool):
            raise _fail(name, f"{where}의 attach_required는 참/거짓이어야 함")
    for i, s in enumerate(body["script"]):
        _check_step(name, i, s, plans, contracts)
    return Scenario(name, str(body["title"]), str(body["description"]), tuple(plans), tuple(contracts),
                    tuple(body["requests"]), tuple(body["script"]), tuple(reg))


def _source_plans() -> dict[str, dict]:
    return {r["plan_id"]: r for r in loader.plan_rows()}


def registry_contract(store: Store, code: str) -> dict | None:
    rows = [c for c in store.list_contracts() if c["influencer_code"] == code]
    return max(rows, key=lambda c: (c["expiry_date"], c["id"])) if rows else None


def _notice(code: str):
    return next((n for n in loader.contract_notices().values() if n.influencer_code == code), None)


def check_refs(store: Store, sc: Scenario) -> None:
    """시연 파일이 고른 기안·계약이 등록부나 원본에 있는지(초기화 전에 확인한다)."""
    source = _source_plans()
    missing_plans = []
    for pid in sc.plans:
        try:
            store.get_plan(pid)
        except KeyError:
            if pid not in source:
                missing_plans.append(pid)
    missing_contracts = [c for c in (*sc.contracts, *sc.register_contracts) if registry_contract(store, c) is None and _notice(c) is None]
    if missing_plans:
        raise _fail(sc.name, f"등록부·원본 기안 파일에 없는 기안 ID: {missing_plans}")
    if missing_contracts:
        raise _fail(sc.name, f"등록부·전속계약 통보문에 없는 인플루언서 코드: {missing_contracts}")


def register_plan(store: Store, plan_id: str) -> int:
    """등록부에 있으면 그 행, 없으면 원본 기안 파일의 값을 읽어 origin='시연'으로 넣는다. 행 id."""
    try:
        return store.get_plan(plan_id)["id"]
    except KeyError:
        pass
    r = _source_plans()[plan_id]
    camp = next((c for c in loader.campaign_master_rows() if c["campaign_id"] == r["campaign_id"]), {})
    fields = {"plan_id": plan_id, "campaign_id": r["campaign_id"], "influencer_id": camp.get("influencer_id"),
              "channel": camp.get("sales_channel"), "requested_budget_krw": r["requested_budget_krw"],
              "expected_gmv_krw": r["expected_gmv_krw"], "settlement_date": r["settlement_date"],
              "contract_deadline": r["contract_deadline"], "source_file": loader.PLAN_SOURCE}
    return store.add_plan(fields, SEED_ACTOR, origin="시연")


def register_contract(store: Store, influencer_code: str) -> int:
    """등록부에 있으면 그 계약(만료가 가장 늦은 것), 없으면 전속계약 통보문에서 읽어 origin='시연'으로 넣는다."""
    found = registry_contract(store, influencer_code)
    if found is not None:
        return found["id"]
    n = _notice(influencer_code)
    if n is None:
        raise KeyError(f"전속계약 통보문에 없는 인플루언서: {influencer_code}")
    fields = {"influencer_code": n.influencer_code, "influencer_name": n.influencer_name,
              "annual_fixed_krw": n.annual_fixed_krw, "performance_fee_text": n.performance_fee_text,
              "notice_deadline": n.notice_deadline, "expiry_date": n.expiry, "auto_renew": n.auto_renew,
              "source_doc": n.source_file}
    return store.add_contract(fields, SEED_ACTOR, origin="시연")
