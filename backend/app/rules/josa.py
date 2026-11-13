"""한국어 조사 고르기: 바뀌는 낱말(역할·사람 이름) 뒤에 붙는 조사를 마지막 글자의 받침에 따라 정한다.

종류: "이가"(이/가), "을를"(을/를), "은는"(은/는), "와과"(와/과), "으로"(으로/로), "이면"(이면/면).
가정: 영문 글자는 영어 글자 이름의 한글 읽기로 받침을 정한다. 받침이 있는 글자는 L(엘)·M(엠)·N(엔)·R(알)뿐이고
나머지는 받침이 없다(CEO → 오, CS → 에스, SCM → 엠). 숫자는 읽는 소리(0 영·1 일·3 삼·6 육·7 칠·8 팔은 받침 있음).
끝의 괄호·공백·문장부호는 건너뛰고 그 앞 글자 기준이다. 약어를 단어로 읽는 경우(예: NASA)는 따로 다루지 않는다.
"""

_PAIRS = {"이가": ("이", "가"), "을를": ("을", "를"), "은는": ("은", "는"), "와과": ("과", "와"),
          "으로": ("으로", "로"), "이면": ("이면", "면")}  # (받침 있을 때, 없을 때)
_LATIN_BATCHIM = set("LMNRlmnr")
_DIGIT_BATCHIM = set("0,1,3,6,7,8".split(","))
_HANGUL_FIRST, _HANGUL_LAST, _JONG = "가", "힣", 28  # 유니코드 한글 음절은 28개 종성 단위로 배열됨
_RIEUL = 8  # 종성 ㄹ의 번호


def _last(word: str) -> str | None:
    for ch in reversed(word):
        if ch.isalnum():
            return ch
    return None


def _batchim(word: str) -> tuple[bool, bool]:
    """(받침이 있는가, 받침이 ㄹ인가)."""
    ch = _last(word)
    if ch is None:
        return False, False
    if _HANGUL_FIRST <= ch <= _HANGUL_LAST:
        jong = (ord(ch) - ord(_HANGUL_FIRST)) % _JONG
        return jong != 0, jong == _RIEUL
    if ch in _DIGIT_BATCHIM:
        return True, ch == "8"  # 팔의 받침은 ㄹ
    return ch in _LATIN_BATCHIM, ch in "Ll" or ch in "Rr"  # 엘·알의 받침은 ㄹ


def pick(word: str, kind: str) -> str:
    """word 뒤에 붙을 조사(조사만)."""
    if kind not in _PAIRS:
        raise ValueError(f"알 수 없는 조사 종류: {kind!r} ({', '.join(_PAIRS)})")
    with_b, without_b = _PAIRS[kind]
    has, rieul = _batchim(word)
    if kind == "으로" and rieul:
        return without_b
    return with_b if has else without_b


def josa(word: str, kind: str) -> str:
    """word에 조사를 붙인 글: josa("마케팅팀", "이가") -> "마케팅팀이"."""
    return word + pick(word, kind)
