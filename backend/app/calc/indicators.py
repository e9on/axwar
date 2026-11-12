"""지표 판정 — 결정이 지표와 반대인지(설계 4.1의 4번) 판단할 근거. 원본 CSV만 읽는다.

설계 4.4: 위험 신호에 🔴가 있으면 '지표 반대 → 결재권자 추가'의 근거로 쓴다.
- 기안: risk_signals 중 판정 신호(실적 기반)에 🔴가 하나라도 있으면 나쁨, 없으면 좋음.
  참고 신호(예상치 기반 — 설계 4.5 예상 GMV는 성과 판단에 쓰지 않음)는 화면 근거로만 보이고, 빼는 이유를 근거 문장에 남긴다.
  🟡·⚪(측정 불가)는 판정 근거가 아니다. 측정 불가는 이유와 함께 근거에 남긴다.
- 전속계약: 인플루언서별 미래 가치 신호(future_value_signals)로 같은 규칙.
- 원본에 근거가 없으면(화면 등록 기안, 실적 없는 인플루언서) 나쁨으로 본다(손실 먼저 경계, 설계 3장 2번).
"""
from dataclasses import dataclass

from app.calc.campaign import influencer_ranking
from app.calc.signals import JUDGE, Signal, future_value_signals, risk_signals
from app.data import loader
from app.rules.models import RuleHit

_SOURCE = "설계 4.4 위험 신호"


@dataclass(frozen=True)
class KeyIndicators:
    subject: str
    good: bool
    red: tuple[str, ...]  # 판정에 쓴 기안별 🔴 신호 키
    excluded: tuple[str, ...]  # 🔴지만 참고 신호라 판정에서 뺀 키
    unmeasurable: tuple[str, ...]
    hits: tuple[RuleHit, ...]


def _judge(subject: str, signals: list[Signal]) -> KeyIndicators:
    red = [s for s in signals if s.level == "red" and s.judgment == JUDGE]
    excluded = [s for s in signals if s.level == "red" and s.judgment != JUDGE]
    unmeasurable = [s for s in signals if s.level == "unmeasurable"]
    if red:
        hits = [RuleHit(s.key, f"{s.label} 🔴({s.compare}): {s.basis}", _SOURCE, s.badge) for s in red]
    else:
        text = f"{subject}: 판정에 쓰는 위험 신호 🔴 없음"
        if excluded:
            text += "(" + "; ".join(f"{s.label}: {s.exclude_reason}이라 판정에서 뺌" for s in excluded) + ")"
        if unmeasurable:
            text += "; 측정 불가: " + ", ".join(f"{s.label}({s.basis})" for s in unmeasurable)
        hits = [RuleHit("indicators_good", text, _SOURCE, "계산")]
    return KeyIndicators(subject, not red, tuple(s.key for s in red), tuple(s.key for s in excluded),
                         tuple(s.key for s in unmeasurable), tuple(hits))


def _no_basis(subject: str, why: str) -> KeyIndicators:
    hit = RuleHit("no_signals", f"{subject}: {why}라 지표를 판단할 수 없음(나쁨으로 봄)", _SOURCE, "계산")
    return KeyIndicators(subject, False, (), (), (), (hit,))


def plan_indicators(plan_id: str) -> KeyIndicators:
    if plan_id not in {r["plan_id"] for r in loader.plan_rows()}:
        return _no_basis(plan_id, "원본 기안 파일에 없는 기안")
    return _judge(plan_id, risk_signals(plan_id))


def contract_indicators(influencer_id: str) -> KeyIndicators:
    if influencer_id not in {r.influencer_id for r in influencer_ranking()}:
        return _no_basis(influencer_id, "캠페인 실적이 원본에 없는 인플루언서")
    return _judge(influencer_id, future_value_signals(influencer_id))
