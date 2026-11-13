"""AI 제공자 연결과 비용 한도.

- RealProvider: Anthropic·Gemini·Upstage 호출 (모델 -> 제공자·단가는 policy.toml의 ai.models)
- FakeProvider / make_provider("fake"): 키 없이 도는 고정 응답 (화면 개발·시연용)
- FallbackProvider: 주 모델이 실패하면 예비 모델로 한 번 더
- BudgetedProvider: 호출 전 예상 비용을 예약하며 전체·하루 한도를 확인하고, 호출 뒤 실제 비용으로 정산

키는 환경변수(ANTHROPIC_API_KEY 등)를 먼저 보고, 없으면 키 파일(AXWAR_KEYS, 기본 ~/.axwar/keys.env)에서
처음 쓸 때 읽는다. 키 값은 로그·예외 메시지에 넣지 않는다.
"""
# hardcode-allow: 1_000_000 (모델 단가가 100만 토큰당이라 토큰당으로 바꾸는 단위 변환)
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

from app import config, policy
from app.ai import prompts

TOKENS_PER_PRICE_UNIT = 1_000_000
logger = logging.getLogger(__name__)
HTTP_TIMEOUT_SEC = 120
HTTP_ATTEMPTS = 6
TASKS = ("review", "reply", "writer")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
UPSTAGE_URL = "https://api.upstage.ai/v1/chat/completions"
KEY_NAMES = {"anthropic": "ANTHROPIC_API_KEY", "gemini": "GEMINI_API_KEY", "upstage": "UPSTAGE_API_KEY"}


@dataclass(frozen=True)
class Completion:
    text: str
    in_tok: int
    out_tok: int
    model: str
    stop_reason: str | None = None  # 잘림은 "max_tokens"
    thinking_tokens: int | None = None
    ledger_id: int | None = None  # 비용 장부(ai_calls) 행 ID. 예산 제공자를 거친 호출만 채운다


class Provider(Protocol):
    def complete(self, system: str, user: str) -> Completion: ...


class BudgetExceeded(Exception):
    """비용 한도(전체 누적 또는 하루)에 닿아 호출하지 않았다."""


# ---------------------------------------------------------------- 키


def load_keys(path: str | Path) -> dict[str, str]:
    keys: dict[str, str] = {}
    p = Path(path)
    if not p.exists():
        return keys
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            keys[k.strip()] = v.strip()
    return keys


_KEYS: dict[str, str] = {}


def _key_file() -> Path:
    env = os.environ.get("AXWAR_KEYS")
    return Path(env) if env else Path.home() / ".axwar" / "keys.env"


def key(name: str) -> str:
    """환경변수 우선, 없으면 키 파일. 처음 쓸 때 읽는다. 오류 메시지에는 이름만 담는다."""
    value = os.environ.get(name)
    if value:
        return value
    if name not in _KEYS:
        _KEYS.update(load_keys(_key_file()))
    if not _KEYS.get(name):
        raise RuntimeError(f"API 키가 없음: {name} (환경변수 또는 키 파일에 설정)")
    return _KEYS[name]


# ---------------------------------------------------------------- HTTP


def post(url: str, headers: dict, body: dict) -> dict:
    data = json.dumps(body).encode()
    last = ""
    for attempt in range(HTTP_ATTEMPTS):
        req = urllib.request.Request(url, data=data, headers={"content-type": "application/json", **headers})
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            retry = e.code == 429 or e.code >= 500
            if retry:
                ra = float(e.headers.get("retry-after") or 0)
                time.sleep(max(ra, 2 * 2**attempt))
            last = f"{e.code} {e.read().decode('utf-8', 'replace')[:300]}"
            if retry:
                continue
            raise RuntimeError(last) from None
    raise RuntimeError(f"재시도 한도 초과 (마지막: {last})")


# ---------------------------------------------------------------- 실제 제공자


class RealProvider:
    """모델 하나를 실제로 부른다. 키는 처음 complete를 부를 때 읽는다."""

    def __init__(self, model: str):
        self.model = model
        self.provider = policy.model_price(model)[0]  # 모르는 모델이면 ValueError
        if self.provider not in KEY_NAMES:
            raise ValueError(f"알 수 없는 제공자: {self.provider} (모델 {model})")

    def complete(self, system: str, user: str) -> Completion:
        return getattr(self, "_" + self.provider)(system, user)

    def _anthropic(self, system: str, user: str) -> Completion:
        # thinking·temperature는 보내지 않는다(Sonnet 5.5는 thinking disabled가 400). 깊이는 effort로만 조절.
        b = post(ANTHROPIC_URL,
                 {"x-api-key": key(KEY_NAMES["anthropic"]), "anthropic-version": policy.get("ai.anthropic_version")},
                 {"model": self.model, "max_tokens": policy.get("ai.max_tokens"),
                  "output_config": {"effort": policy.get("ai.effort")}, "system": system,
                  "messages": [{"role": "user", "content": user}]})
        text = "".join(c.get("text", "") for c in b["content"] if c["type"] == "text")
        details = b["usage"].get("output_tokens_details") or {}
        return Completion(text, b["usage"]["input_tokens"], b["usage"]["output_tokens"], self.model,
                          b.get("stop_reason"), details.get("thinking_tokens"))

    def _gemini(self, system: str, user: str) -> Completion:
        b = post(GEMINI_URL.format(model=self.model),
                 {"x-goog-api-key": key(KEY_NAMES["gemini"])},
                 {"systemInstruction": {"parts": [{"text": system}]},
                  "contents": [{"role": "user", "parts": [{"text": user}]}],
                  "generationConfig": {"responseMimeType": "application/json"}})
        u = b.get("usageMetadata", {})
        cand = (b.get("candidates") or [{}])[0]
        text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
        fin = cand.get("finishReason")
        return Completion(text, u.get("promptTokenCount", 0),
                          u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0), self.model,
                          "max_tokens" if fin == "MAX_TOKENS" else fin, u.get("thoughtsTokenCount"))

    def _upstage(self, system: str, user: str) -> Completion:
        b = post(UPSTAGE_URL, {"Authorization": "Bearer " + key(KEY_NAMES["upstage"])},
                 {"model": self.model, "max_tokens": policy.get("ai.max_tokens"),
                  "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        u = b.get("usage", {})
        fin = b["choices"][0].get("finish_reason")
        return Completion(b["choices"][0]["message"]["content"] or "", u.get("prompt_tokens", 0),
                          u.get("completion_tokens", 0), self.model, "max_tokens" if fin == "length" else fin)


# ---------------------------------------------------------------- 가짜 제공자


class FakeProvider:
    """미리 준 응답을 순서대로 돌려준다. 예외 객체면 던진다."""

    def __init__(self, responses: list[str | Exception], model: str = "fake"):
        self._responses = list(responses)
        self.model = model
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> Completion:
        self.calls.append((system, user))
        if not self._responses:
            raise RuntimeError("FakeProvider에 남은 응답이 없음")
        r = self._responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return Completion(r, 0, 0, self.model)


def _has(text: str, *words: str) -> bool:
    return any(w in text for w in words)


def _fake_review(user: str) -> str:
    """규칙 기반 고정 응답: 키워드로 분류한다(시연·화면 개발용, 모델이 아니다)."""
    if _has(user, "색") and _has(user, "다르", "영상", "라이브", "발색", "달라"):
        reason, sentiment, gap = "색상불일치", "부정", True
    elif _has(user, "오배송", "누락", "지연", "파손"):
        reason, sentiment, gap = "배송물류", "부정", False
    elif _has(user, "불량", "변질", "고장"):
        reason, sentiment, gap = "품질불량", "부정", False
    elif _has(user, "변심", "필요 없", "충동"):
        reason, sentiment, gap = "변심후회", "중립", False
    elif _has(user, "만족", "좋아", "좋네"):
        reason, sentiment, gap = "만족", "긍정", False
    else:
        reason, sentiment, gap = "기타", "중립", False
    return json.dumps({"reason": reason, "sentiment": sentiment, "content_gap": gap, "confidence": 1.0},
                      ensure_ascii=False)


def _fake_reply(user: str) -> str:
    """키워드 해석(화면에서 직접 넣은 회신용). 수량은 "N개까지 허용/가능" 형태만 읽고(일부 허용, 조건부수용) 날짜는 읽지 않는다 —
    그 밖의 수량·날짜가 필요한 시연 회신은 대본 단계의 ai 필드가 해석을 직접 준다. 거절 단어가 먼저 이긴다."""
    reply = user.split("회신:", 1)[-1]
    qty = None
    limited = re.search(r"(\d[\d,]*)\s*개\s*까지", reply)
    if _has(reply, "불가", "어렵", "안 됩니다", "거절", "않습니다", "수 없"):
        stance, human = "거절", True
    elif limited and _has(reply, "가능", "허용"):
        stance, human, qty = "조건부수용", False, int(limited.group(1).replace(",", ""))  # "N개까지 허용" = 일부 허용
    elif _has(reply, "가능", "알겠", "진행하겠", "허용"):
        stance, human = "수용", False
    else:
        stance, human = "정보부족", True
    return json.dumps({"stance": stance, "qty_limit": qty, "next_date": None, "needs_human": human,
                       "confidence": 1.0}, ensure_ascii=False)


def _facts_of(user: str) -> dict[str, str]:
    """글쓰기 입력("- 이름: 값" 줄들)을 이름 -> 값(글자)으로 읽는다. 같은 이름이 또 나오면 처음 값을 둔다."""
    out: dict[str, str] = {}
    for line in user.splitlines():
        m = re.match(r"^- ([^:]+): (.*)$", line)
        if m:
            out.setdefault(m.group(1).strip(), m.group(2).strip())
    return out


def _md_of(iso: str) -> str:
    """'2026-07-27' -> '7/27'. 날짜 모양이 아니면 그대로."""
    m = re.match(r"^\d{4}-(\d{2})-(\d{2})$", iso or "")
    return f"{int(m.group(1))}/{int(m.group(2))}" if m else (iso or "")


def _num(f: dict[str, str], key: str) -> float | None:
    try:
        return float(f[key].replace(",", ""))
    except (KeyError, ValueError):
        return None


def _rank_text(f: dict[str, str], rank_key: str, of_key: str) -> str | None:
    rank, of = _num(f, rank_key), _num(f, of_key)
    return None if rank is None or of is None else f"{int(of)}명 중 {int(rank)}위"


def _fake_reasons(f: dict[str, str], rule: str, bad: bool, contract: bool) -> list[str]:
    """이유 줄 후보를 중요한 순서로 만든다. 숫자는 사실에 있는 값만 쓴다. 2줄 미만이면 일반 줄로 채우고 3줄까지만 돌려준다."""
    out: list[str] = []
    window = f.get("하회 구간")
    if window and f.get("집행일"):
        out.append(f"집행일 {_md_of(f['집행일'])}이 현금이 모자란 기간({window}) 안이에요.")
    elif "하회 구간" in rule:
        out.append("집행일이 현금이 모자란 기간 안이에요.")
    roas, place = _num(f, "실질 ROAS"), _rank_text(f, "실질 ROAS 순위", "순위 대상 수")
    if roas is not None and place:
        out.append(f"실질 ROAS는 광고비 1원당 {abs(roas):.2f}원씩 손해이고 {place}예요." if roas < 0
                   else f"실질 ROAS는 광고비 1원당 {roas:.2f}원을 남기고 {place}예요.")
    share, req = _num(f, "요청 비중(%)"), _rank_text(f, "요청 비중 순위", "요청 비중 대상 수")
    if share is not None and req and not contract:
        out.append(f"이 인플루언서의 요청액이 기안 전체의 {share:.2f}%로 {req}예요.")
    if "초과" in rule and f.get("기안 총액"):
        out.append(f"기안 총액 {f['기안 총액']}원이 커서 높은 결재선이 필요해요.")
    mine, rest = _num(f, "단순변심 반품률"), _num(f, "그 외 단순변심 반품률")
    if mine is not None and rest is not None and (contract or mine > rest):
        out.append(f"단순변심 반품률이 {mine:.1%}로 다른 인플루언서({rest:.1%})보다 {'높아요' if mine > rest else '낮아요'}.")
    if contract and f.get("연 고정 피"):
        out.append(f"연 고정 피는 {f['연 고정 피']}원이고 계약은 {_md_of(f.get('계약 만료', ''))}에 끝나요.")
    if bad and roas is None:
        out.append("성과가 낮은데 계약 금액이 커요." if contract else "성과가 하위인데 예산 비중이 커요.")
    if len(out) < 2 and not out:
        out.append("규칙상 승인권자가 확인할 건이에요.")
    if len(out) < 2:
        out.append(f"결재할 사람은 {f.get('승인권자', '승인권자')}이에요.")
    return out[:3]


def _fake_cares(f: dict[str, str], split) -> list[str]:
    """주의 줄: 분할안·회신 대기를 먼저, 그다음 기한. 1~2줄."""
    out: list[str] = []
    if split:
        first, second = split.group(1), split.group(2)
        out.append(f"먼저 {first}개만 집행하고 나머지는 재고 회신 뒤에 정해요." if second.replace(",", "") == "0"
                   else f"{first}개를 먼저, {second}개를 나중에 집행하는 안이에요.")
    elif f.get("상태") == "회신 대기":
        out.append("부서 회신을 기다리는 중이라 내용이 바뀔 수 있어요.")
    if f.get("기한"):
        what = "통보 기한" if f.get("종류") == "계약" else "확정 기한"
        out.append(f"{what} {_md_of(f['기한'])}까지 결재하지 않으면 기본 거부돼요.")
    elif not out:
        out.append("결재가 늦으면 기한 전에 기본 거부될 수 있어요.")
    return out[:2]


def _fake_briefing(f: dict[str, str]) -> str:
    """사실의 지표 판정·분할안·규칙 근거·계산값에서 브리핑(권고 1줄·이유 2~3줄·주의 1~2줄)을 규칙으로 만든다(시연용, 모델이 아니다)."""
    rule, bad = f.get("규칙 근거", ""), f.get("지표 판정") == "반대 근거 있음"
    split = re.search(r"1차 수량 ([\d,]+); .*2차 수량 ([\d,]+)", f.get("분할안", ""))
    contract = f.get("종류") == "계약"
    if split:
        rec = "분할 승인으로 결재하길 권해요."
    elif bad:
        rec = "거절하는 쪽을 먼저 검토하길 권해요."
    else:
        rec = "승인하길 권해요."
    lines = [f"권고: {rec}"]
    lines += [f"이유: {w}" for w in _fake_reasons(f, rule, bad, contract)]
    lines += [f"주의: {c}" for c in _fake_cares(f, split)]
    return "\n".join(lines)


def _fake_counterpoints(f: dict[str, str]) -> str:
    bad = f.get("지표 판정") == "반대 근거 있음"
    place = _rank_text(f, "실질 ROAS 순위", "순위 대상 수")
    conds: list[str]
    if f.get("분할안"):
        conds = ["한 번에 승인하려면 재고가 충분하다는 확인이 있어야 해요."]
        check = "재고 부서 회신으로 수량이 바뀌었는지 보세요."
    elif bad:
        conds = ["승인하려면 성과가 나쁜 이유를 설명할 근거가 있어야 해요."]
        check = "지표 근거에 적힌 위험이 풀렸는지 보세요."
    else:
        conds = ["거절하려면 지표에 안 잡힌 다른 위험이 있어야 해요."]
        check = "그 위험이 실제 자료로 확인되는지 보세요."
    if place and (bad or f.get("분할안")):
        conds.append(f"승인하려면 실질 ROAS가 {place}인 점을 설명할 근거도 있어야 해요.")
    elif place:
        conds.append(f"거절하려면 실질 ROAS {place}와 다른 방향의 새 자료가 있어야 해요.")
    checks = [check]
    if f.get("기한"):
        checks.append(f"결재 기한 {_md_of(f['기한'])}까지 시간이 있는지도 보세요.")
    return "\n".join([f"반대로 결정하려면: {c}" for c in conds[:2]] + [f"확인할 것: {c}" for c in checks[:2]])


def _fake_notice(f: dict[str, str]) -> str:
    """조건변경 통보문 틀: 인사, 변경 요지, 재협상안 두 축(고정 피·성과 피 기준), 회신 요청."""
    base = f.get("성과 피 기준", "").split(" (")[0]
    return "\n".join([
        f"{f.get('인플루언서', '')}님께,",
        f"안녕하세요. 계약 만료({f.get('계약 만료', '')})를 앞두고 계약 조건 변경을 알려 드립니다.",
        f"고정 피는 {f.get('연 고정 피(원)', '')}원으로 하고, 성과 피는 {base} 기준으로 정산하는 안을 제안드립니다.",
        f"공제 항목은 {f.get('공제 항목', '')}입니다.",
        "내용을 확인하시고 회신 부탁드립니다."])


def _fake_writer(system: str, user: str) -> str:
    """지시문으로 어떤 글인지 가려 같은 형식의 글을 규칙으로 만든다. 입력 자료를 그대로 돌려주지 않는다."""
    f = _facts_of(user)
    if system == prompts.BRIEFING_SYSTEM:
        return _fake_briefing(f)
    if system == prompts.COUNTERPOINTS_SYSTEM:
        return _fake_counterpoints(f)
    return _fake_notice(f)


_FAKE_RULES = {"review": _fake_review, "reply": _fake_reply}


class _RuleProvider:
    model = "fake"

    def __init__(self, task: str):
        self._task = task

    def complete(self, system: str, user: str) -> Completion:
        text = _fake_writer(system, user) if self._task == "writer" else _FAKE_RULES[self._task](user)
        return Completion(text, 0, 0, self.model)


# ---------------------------------------------------------------- 예비 모델


class FallbackProvider:
    """주 모델이 예외를 내면 예비 모델로 한 번 더. 비용 한도 예외는 그대로 올린다."""

    def __init__(self, primary: Provider, backup: Provider):
        self.primary, self.backup = primary, backup

    def complete(self, system: str, user: str) -> Completion:
        try:
            return self.primary.complete(system, user)
        except BudgetExceeded:
            raise
        except Exception:  # noqa: BLE001 - 어떤 실패든 예비로 넘긴다
            return self.backup.complete(system, user)


# ---------------------------------------------------------------- 비용 한도

ESTIMATE_TOKENS_PER_CHAR = 1  # 예상 비용 추정: 글자 하나를 토큰 하나로 보는 보수적 가정(실제는 더 적게 든다)


def utc_today() -> date:
    """하루 한도의 기준 날짜. 과금 기준에 맞춰 UTC 날짜를 쓴다(운영·시연 시계와 무관)."""
    return datetime.now(timezone.utc).date()


def estimate_usd(model: str, system: str, user: str) -> float:
    """호출 전 최악 비용 추정 = 지시문 길이 기반 입력 토큰 x 입력 단가 + 정책 ai.max_tokens x 출력 단가."""
    _, price_in, price_out = policy.model_price(model)
    in_tok = (len(system) + len(user)) * ESTIMATE_TOKENS_PER_CHAR
    return (in_tok * price_in + policy.get("ai.max_tokens") * price_out) / TOKENS_PER_PRICE_UNIT


class CostLedger(Protocol):
    def spent(self, day: date | None) -> float: ...

    def record(self, model: str, in_tok: int, out_tok: int, usd: float, day: date) -> None: ...

    def reserve(self, estimate_usd: float, day: date, total_cap: float, daily_cap: float) -> int:
        """한도를 확인하고 예상 비용을 예약한다(확인과 예약이 한 묶음). 넘으면 BudgetExceeded."""

    def settle(self, reservation_id: int, model: str, in_tok: int, out_tok: int, usd: float) -> None: ...

    def release(self, reservation_id: int) -> None: ...


def check_caps(spent_total: float, spent_day: float, estimate: float, total_cap: float, daily_cap: float) -> None:
    """예약 직전 한도 판정(장부 구현 공통). 이미 닿았거나 예상 비용을 더하면 넘으면 BudgetExceeded."""
    if spent_total >= total_cap or spent_total + estimate > total_cap:
        raise BudgetExceeded("AI 사용 전체 한도 도달")
    if spent_day >= daily_cap or spent_day + estimate > daily_cap:
        raise BudgetExceeded("AI 사용 하루 한도 도달")


class MemoryCostLedger:
    """메모리 장부(재시작하면 사라진다). DB 장부(Store)와 같은 프로토콜. 예약분도 쓴 돈으로 센다."""

    def __init__(self):
        self.rows: list[tuple[str, int, int, float, date]] = []
        self._reserved: dict[int, tuple[float, date]] = {}
        self._next = 1
        self._lock = threading.Lock()

    def _spent(self, day: date | None) -> float:
        done = sum(r[3] for r in self.rows if day is None or r[4] == day)
        held = sum(e for e, d in self._reserved.values() if day is None or d == day)
        return done + held

    def spent(self, day: date | None = None) -> float:
        with self._lock:
            return self._spent(day)

    def record(self, model: str, in_tok: int, out_tok: int, usd: float, day: date) -> None:
        with self._lock:
            self.rows.append((model, in_tok, out_tok, usd, day))

    def reserve(self, estimate_usd: float, day: date, total_cap: float, daily_cap: float) -> int:
        with self._lock:
            check_caps(self._spent(None), self._spent(day), estimate_usd, total_cap, daily_cap)
            rid, self._next = self._next, self._next + 1
            self._reserved[rid] = (estimate_usd, day)
            return rid

    def settle(self, reservation_id: int, model: str, in_tok: int, out_tok: int, usd: float) -> None:
        with self._lock:
            _, day = self._reserved.pop(reservation_id)
            self.rows.append((model, in_tok, out_tok, usd, day))

    def release(self, reservation_id: int) -> None:
        with self._lock:
            self._reserved.pop(reservation_id, None)


# 가장 비싼 모델 기준 추정에 쓰는 폴백 모델 선택(inner에 model이 없을 때)
def _priciest_model() -> str:
    return max(policy.model_names(), key=lambda m: policy.model_price(m)[2])


class BudgetedProvider:
    """호출 전에 예상 비용을 예약하며 전체·하루 한도를 확인하고(넘으면 BudgetExceeded, 호출 안 함),
    호출 뒤 실제 비용으로 정산한다. 호출이 실패하면 예약을 돌려준다(가정: 제공자는 실패한 요청에 과금하지 않음).

    한도를 따로 주지 않으면 호출할 때마다 정책 설정(ai.total_cap_usd·ai.daily_cap_usd)을 읽는다.
    today는 하루 한도의 기준 날짜를 돌려주는 함수(기본 UTC 날짜, 테스트에서 주입).
    """

    def __init__(self, inner: Provider, ledger: CostLedger, total_cap_usd: float | None = None,
                 daily_cap_usd: float | None = None, today: Callable[[], date] = utc_today):
        self.inner, self.ledger, self.today = inner, ledger, today
        self.total_cap_usd, self.daily_cap_usd = total_cap_usd, daily_cap_usd

    def complete(self, system: str, user: str) -> Completion:
        total_cap = policy.get("ai.total_cap_usd") if self.total_cap_usd is None else self.total_cap_usd
        daily_cap = policy.get("ai.daily_cap_usd") if self.daily_cap_usd is None else self.daily_cap_usd
        day = self.today()
        model = getattr(self.inner, "model", None) or _priciest_model()
        estimate = estimate_usd(model, system, user)
        rid = self.ledger.reserve(estimate, day, total_cap, daily_cap)
        try:
            c = self.inner.complete(system, user)
        except BaseException:  # 호출 자체가 실패했을 때만 예약을 돌려준다
            self.ledger.release(rid)
            raise
        # 여기부터는 호출이 이미 성공(과금 가능). 정산에 문제가 있어도 결과를 돌려주고 예비 모델을 부르지 않는다.
        try:
            _, price_in, price_out = policy.model_price(c.model)
            usd = (c.in_tok * price_in + c.out_tok * price_out) / TOKENS_PER_PRICE_UNIT
        except ValueError:
            usd = estimate  # 단가를 모르면 예상 비용으로 정산(보수적)
        try:
            self.ledger.settle(rid, c.model, c.in_tok, c.out_tok, usd)
        except Exception as e:  # noqa: BLE001
            # 예약이 예상 비용으로 한도에 계속 잡혀 있다(보수적). 기록만 남긴다.
            logger.error("정산 실패(예약 %s은 예상 비용으로 남김): %s", rid, e)
            note = getattr(self.ledger, "note_settle_failure", None)
            if note is not None:
                try:
                    note(rid, e)
                except Exception:  # noqa: BLE001
                    logger.exception("정산 실패 기록도 실패")
        return replace(c, ledger_id=rid)


# ---------------------------------------------------------------- 만들기


def make_provider(task: str, ledger: CostLedger | None = None) -> Provider:
    """task: "review" | "reply" | "writer". fake 모드(기본)는 키 없이 규칙 기반 고정 응답.

    real 모드는 DB 비용 장부가 꼭 필요하다(재시작해도 누적 한도가 이어지도록). 주 모델과 예비 모델을 각각 한도로 감싼다.
    """
    if task not in TASKS:
        raise ValueError(f"알 수 없는 AI 작업: {task}")
    mode = config.ai_mode()
    if mode == "fake":
        return _RuleProvider(task)
    if mode != "real":
        raise ValueError(f"알 수 없는 AI 모드: {mode}")
    if ledger is None:
        raise ValueError("실제 AI 모드는 DB 비용 장부가 필요함")
    return FallbackProvider(BudgetedProvider(RealProvider(policy.get(f"ai.{task}_model")), ledger),
                            BudgetedProvider(RealProvider(policy.get(f"ai.{task}_backup")), ledger))
