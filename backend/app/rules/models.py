"""규칙 모듈 공용 자료형."""
from dataclasses import dataclass
from datetime import date
from typing import Literal


@dataclass(frozen=True)
class RuleHit:
    rule_id: str
    text: str
    source: str
    badge: Literal["원본", "계산", "가정"]


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
