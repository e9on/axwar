"""규칙 모듈 공용 자료형."""
from dataclasses import dataclass
from datetime import date
from typing import Literal


def make_detail(formula: str, inputs: tuple = (), sources: tuple = (), policies: tuple = ()) -> dict:
    """근거 줄을 펼쳤을 때 보이는 내용(계산식·입력값·읽은 원본 파일·쓰인 정책 키). 저장용이라 정책은 키만 둔다.

    inputs = ((이름, 숫자 또는 값), ...), sources = 04_원본데이터 아래 상대 경로, policies = policy.toml 키.
    """
    return {"formula": formula, "inputs": [{"label": k, "value": v} for k, v in inputs],
            "sources": list(sources), "policy_keys": list(policies)}


@dataclass(frozen=True)
class RuleHit:
    rule_id: str
    text: str
    source: str
    badge: Literal["원본", "계산", "가정"]
    detail: dict | None = None  # 옛 저장 행에는 없을 수 있음


@dataclass(frozen=True)
class PlanFacts:
    plan_id: str
    campaign_id: str
    influencer_id: str
    amount_krw: int
    plan_total_krw: int
    settlement_date: date
    deadline: date
    direction: Literal["확대", "축소"]
    indicator_good: bool


@dataclass(frozen=True)
class ContractFacts:
    contract_id: str
    annual_fixed_krw: int
    deadline: date
    expiry: date
    direction: Literal["갱신", "조건변경", "해지"]
    indicator_good: bool


@dataclass(frozen=True)
class ApproverDecision:
    approvers: tuple[str, ...]
    hits: tuple[RuleHit, ...]


@dataclass(frozen=True)
class ApproverChange:
    before: tuple[str, ...]
    after: tuple[str, ...]
    reason: str
    hits: tuple[RuleHit, ...]
    at: date
