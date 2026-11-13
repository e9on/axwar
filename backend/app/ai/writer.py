"""글쓰기: 결재권자 브리핑·반대 근거·조건변경 통보 초안.

사실(facts)을 형식화해 AI에 넘기고, 돌아온 글을 검사한다. AI가 사실에 없는 숫자를 만들면 버린다.
실패(제공자 예외·한도 도달·빈 응답·잘림·없는 숫자)는 ok False와 고정 대체 문구로 돌려준다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.ai import prompts
from app.ai.providers import Provider

FALLBACK_TEXT = "AI 응답 없음 — 규칙 판정만 표시합니다"
MIN_CHECKED_DIGITS = 3  # 이 자리수 이상 숫자만 사실과 대조한다(1·2자리는 "3가지" 같은 문장 숫자)
_NUMBER = re.compile(r"\d[\d,]*\d|\d")

BRIEFING_HEADS = ("권고", "이유", "주의")  # 브리핑은 정확히 이 세 줄
COUNTER_HEADS = ("반대로 결정하려면", "확인할 것")  # 반대 근거는 이 두 줄
LINE_MAX = 90  # 머리말 포함 한 줄 상한(프롬프트는 60자 안팎을 요청). 넘으면 정리하지 않고 실패로 본다
_BULLET = re.compile(r"^(?:[-*•·]+|\d+[.)])\s*")
_INTERNAL_WORDS = ("covenant", "z=", "판정")  # 화면에 보이면 안 되는 내부 용어(대소문자 무시)
_INTERNAL = re.compile(r"설계\s*\d|[A-Za-z]+_[A-Za-z_]+|[\u2600-\u27bf\U0001f000-\U0001faff]")


@dataclass(frozen=True)
class AiText:
    text: str
    model: str
    ok: bool
    ledger_id: int | None = None  # 비용 장부 행 ID(예산 제공자를 거쳤을 때)


def _fmt(v) -> str:
    if isinstance(v, bool):
        return "예" if v else "아니오"
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        return f"{v:,}"  # 반올림하지 않는다(사실 왜곡 방지)
    if isinstance(v, (list, tuple)):
        return ", ".join(_fmt(x) for x in v)
    if isinstance(v, dict):
        return "; ".join(f"{k} {_fmt(x)}" for k, x in v.items())
    return str(v)


def _lines(title: str, d: dict) -> str:
    return title + "\n" + "\n".join(f"- {k}: {_fmt(v)}" for k, v in d.items())


def _digits(text: str) -> set[str]:
    return {m.replace(",", "") for m in _NUMBER.findall(text)}


def _fail(model: str = "", ledger_id: int | None = None) -> AiText:
    return AiText(FALLBACK_TEXT, model, False, ledger_id)


def _write(p: Provider, system: str, user: str) -> AiText:
    try:
        c = p.complete(system, user)
    except Exception:  # noqa: BLE001 - BudgetExceeded 포함, 어떤 실패든 대체 문구
        return _fail()
    text = (c.text or "").strip()
    if not text or c.stop_reason == "max_tokens":
        return _fail(c.model, c.ledger_id)
    allowed = _digits(user)
    for n in _digits(text):
        if len(n) >= MIN_CHECKED_DIGITS and n not in allowed:
            return _fail(c.model, c.ledger_id)
    return AiText(text, c.model, True, c.ledger_id)


def _shape(text: str, heads: tuple[str, ...]) -> str | None:
    """응답을 머리말 줄 형식으로 맞춘다. 맞출 수 없으면 None.

    - 머리말이 모두 있으면 순서대로 다시 놓고 남는 줄은 버린다
    - 머리말이 하나도 없으면 앞에서부터 줄 수만큼 골라 머리말을 붙인다(줄이 모자라면 None)
    - 머리말이 일부만 있거나, 빈 내용·너무 긴 줄·내부 용어가 있으면 None
    """
    lines = [_BULLET.sub("", l.strip()).replace("：", ":") for l in text.splitlines()]
    lines = [l for l in lines if l]
    found: dict[str, str] = {}
    for l in lines:
        for h in heads:
            m = re.match(rf"{re.escape(h)}\s*:\s*(.*)$", l)
            if m and h not in found:
                found[h] = m.group(1).strip()
    if found:
        if set(found) != set(heads):
            return None
        bodies = [found[h] for h in heads]
    else:
        if len(lines) < len(heads):
            return None
        bodies = [l.strip() for l in lines[:len(heads)]]
    out = [f"{h}: {b}" for h, b in zip(heads, bodies)]
    for h, b, l in zip(heads, bodies, out):
        if not b or len(l) > LINE_MAX or _INTERNAL.search(l) or any(w in l.lower() for w in _INTERNAL_WORDS):
            return None
    return "\n".join(out)


def _write_shaped(p: Provider, system: str, user: str, heads: tuple[str, ...]) -> AiText:
    r = _write(p, system, user)
    if not r.ok:
        return r
    shaped = _shape(r.text, heads)
    return AiText(shaped, r.model, True, r.ledger_id) if shaped else _fail(r.model, r.ledger_id)


def briefing(p: Provider, facts: dict) -> AiText:
    return _write_shaped(p, prompts.BRIEFING_SYSTEM, _lines("사실", facts), BRIEFING_HEADS)


def counterpoints(p: Provider, facts: dict) -> AiText:
    return _write_shaped(p, prompts.COUNTERPOINTS_SYSTEM, _lines("사실", facts), COUNTER_HEADS)


def notice_draft(p: Provider, contract: dict, proposal: dict) -> AiText:
    deductions = proposal.get("deductions") or []
    user = (_lines("계약 조건", contract) + "\n"
            + f"재협상안\n- 고정 피(원): {_fmt(proposal['fixed_fee_krw'])}\n"
            + f"- 성과 피 기준: {proposal['performance_base']} (총매출이 아니라 공제 후 금액)\n"
            + f"- 공제 항목: {_fmt(list(deductions))}")
    return _write(p, prompts.NOTICE_SYSTEM, user)
