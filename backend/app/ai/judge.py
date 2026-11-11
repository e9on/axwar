"""리뷰·회신 해석. 모델 응답을 읽어 허용값으로 정리하고, 사람이 봐야 할 때를 표시한다.

사람 확인(needs_human) 조건: 모델이 요청(회신), 회신 stance가 거절·정보부족, JSON 파싱 실패, 허용값 밖,
응답 잘림(stop_reason max_tokens), 제공자 예외(한도 도달 포함).
confidence는 기록만 하고 판정에 쓰지 않는다(성능평가: 정답과 오답의 확신도 차이가 없음).
ALLOWED·norm·parse는 성능평가(eval)도 가져다 쓴다.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date

from app.ai import prompts
from app.ai.providers import BudgetExceeded, Completion, Provider

ALLOWED = {
    "reason": {"색상불일치", "변심후회", "배송물류", "품질불량", "만족", "기타"},
    "sentiment": {"긍정", "중립", "부정"},
    "stance": {"수용", "조건부수용", "거절", "정보부족"},
}
ALWAYS_HUMAN_STANCES = {"거절", "정보부족"}
BUDGET_RAW = "AI 사용 한도 도달"
FALLBACK_REASON = "기타"
FALLBACK_SENTIMENT = "중립"
FALLBACK_STANCE = "정보부족"


def norm(field: str, v):
    if v is None or v in ("null", ""):
        return None
    if field == "qty_limit":
        try:
            return int(float(str(v).replace(",", "")))
        except ValueError:
            return str(v)
    if field in ("content_gap", "needs_human"):
        return v is True or v == "true"
    return str(v).strip()


def parse(text: str) -> dict | None:
    m = re.search(r"\{[\s\S]*\}", text or "")
    if not m:
        return None
    try:
        out = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return out if isinstance(out, dict) else None


@dataclass(frozen=True)
class ReviewJudgment:
    reason: str
    sentiment: str
    content_gap: bool
    confidence: float | None
    needs_human: bool
    model: str
    raw: str


@dataclass(frozen=True)
class ReplyJudgment:
    stance: str
    qty_limit: int | None
    next_date: date | None
    needs_human: bool
    confidence: float | None
    model: str
    raw: str


def _call(p: Provider, system: str, user: str) -> tuple[Completion | None, str, str]:
    """(응답, 모델 이름, 실패 시 raw). 예외는 밖으로 내보내지 않고 종류만 남긴다."""
    try:
        c = p.complete(system, user)
    except BudgetExceeded:
        return None, getattr(p, "model", ""), BUDGET_RAW
    except Exception as e:  # noqa: BLE001 - 어떤 실패든 사람 확인으로 넘긴다
        return None, getattr(p, "model", ""), type(e).__name__  # 메시지에 키·요청 본문이 있을 수 있어 종류만
    return c, c.model, c.text


def _confidence(out: dict | None) -> float | None:
    v = (out or {}).get("confidence")
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def interpret_review(p: Provider, product: str, text: str) -> ReviewJudgment:
    c, model, raw = _call(p, prompts.REVIEW_SYSTEM, prompts.review_user({"product": product, "text": text}))
    out = None if c is None or c.stop_reason == "max_tokens" else parse(c.text)
    if out is None:
        return ReviewJudgment(FALLBACK_REASON, FALLBACK_SENTIMENT, False, None, True, model, raw)
    reason, sentiment = norm("reason", out.get("reason")), norm("sentiment", out.get("sentiment"))
    valid = reason in ALLOWED["reason"] and sentiment in ALLOWED["sentiment"]
    return ReviewJudgment(reason if reason in ALLOWED["reason"] else FALLBACK_REASON,
                          sentiment if sentiment in ALLOWED["sentiment"] else FALLBACK_SENTIMENT,
                          norm("content_gap", out.get("content_gap")) is True, _confidence(out),
                          not valid, model, raw)


def _to_date(v) -> tuple[date | None, bool]:
    """(날짜, 형식 이상 여부). 없으면 (None, False)."""
    v = norm("next_date", v)
    if v is None:
        return None, False
    try:
        return date.fromisoformat(v), False
    except ValueError:
        return None, True


def interpret_reply(p: Provider, dept: str, request: str, reply: str, today: date) -> ReplyJudgment:
    c, model, raw = _call(p, prompts.reply_system(today),
                          prompts.reply_user({"dept": dept, "request": request, "reply": reply}))
    out = None if c is None or c.stop_reason == "max_tokens" else parse(c.text)
    if out is None:
        return ReplyJudgment(FALLBACK_STANCE, None, None, True, None, model, raw)
    stance = norm("stance", out.get("stance"))
    qty = norm("qty_limit", out.get("qty_limit"))
    bad_qty = isinstance(qty, str)
    next_date, bad_date = _to_date(out.get("next_date"))
    human = (norm("needs_human", out.get("needs_human")) is True or stance not in ALLOWED["stance"]
             or stance in ALWAYS_HUMAN_STANCES or bad_qty or bad_date)
    return ReplyJudgment(stance if stance in ALLOWED["stance"] else FALLBACK_STANCE,
                         None if bad_qty else qty, next_date, human, _confidence(out), model, raw)
