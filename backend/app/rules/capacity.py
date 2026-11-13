"""물류 회신 문장에서 날짜별 처리 능력 두 값(평소 안정 처리량, 최대 처리량)을 뽑는다. 순수 함수.

설계 4.5: 물류팀에 ① 평소 안정적으로 처리하는 양 ② 최대 처리량(야근 포함)을 묻는다.
회신 문장에서 이름표(평소·안정·보통·기본 / 최대·야근·최고) 바로 뒤의 숫자를 읽는다.
두 이름표가 서로를 건너뛰어 읽지 않게 하고, 평소가 최대보다 크면 뒤바뀐 회신이라 둘 다 쓰지 않는다
(사람이 확인하도록 호출하는 쪽이 (None, None)을 처리 능력 없음으로 다룬다).
"""
from __future__ import annotations

import re

from app import policy

STABLE_WORDS = ("평소", "안정", "보통", "기본")
MAX_WORDS = ("최대", "야근", "최고")
_NUM = r"(\d[\d,]*\d|\d)"


def _pattern(words: tuple[str, ...], others: tuple[str, ...]) -> re.Pattern:
    """이름표와 숫자 사이 허용 글자 수는 정책값(capacity.label_span_chars)."""
    own, other, span = "|".join(words), "|".join(others), policy.get("capacity.label_span_chars")
    return re.compile(rf"(?:{own})(?:(?!{other})[^\d]){{0,{span}}}{_NUM}")


def _first(p: re.Pattern, text: str) -> int | None:
    m = p.search(text)
    return int(m.group(1).replace(",", "")) if m else None


def parse_capacity(text: str) -> tuple[int | None, int | None]:
    """(평소 안정 처리량, 최대 처리량). 문장에 없으면 None."""
    stable = _first(_pattern(STABLE_WORDS, MAX_WORDS), text or "")
    maximum = _first(_pattern(MAX_WORDS, STABLE_WORDS), text or "")
    if stable is not None and maximum is not None and stable > maximum:
        return None, None
    return stable, maximum
