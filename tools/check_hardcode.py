"""하드코딩 자동 검사.

코드 본체(backend/app, frontend/src)에 날짜·금액·건수·정책 기준·시연 숫자·시연 이름이
박혀 있으면 실패한다. 이런 값은 데이터·설정에서 읽어야 한다.

검사 대상: .py .ts .tsx .js .jsx .mjs
제외(테스트 파일): test_*.py, *_test.py, *.test.ts(x/js/jsx), *.spec.ts(x/js/jsx), __tests__/ 폴더 아래

위반 유형
  - 날짜 리터럴      : date(20..)/datetime(20..)/Date(20..)/Date.UTC(20..) (year= 인자 포함),
                       문자열 안의 YYYY-MM-DD, YYYY/MM/DD, YYYYMMDD(20으로 시작 8자리), YYYY년 M월
  - 큰 숫자 리터럴   : 값이 10000 이상(5자리 이상)인 정수. 16진·8진·2진, 1e6 같은 지수 표기도 값으로 판정.
                       숫자만 든 문자열("50000")도 같다.
  - 시연 이름 리터럴 : 문자열 안의 PLAN-숫자, CMP-숫자, INF-숫자, SKU-숫자, CH-숫자, LC-숫자 (대소문자 무시)
  - 정책성 소수 리터럴: 코드에 나온 소수. 지수 표기(8.5e-1)는 값을 계산해 판정한다.

허용 규칙 (여기가 전부다)
  1. 주석·파이썬 독스트링 안의 내용은 검사하지 않는다(설명용).
     f-string의 {...}, TS 템플릿의 ${...} 안쪽은 코드로 다시 검사한다(형식 지정 :.2f 는 제외).
  2. 소수는 0.0, 0.5, 1.0, 100.0 (값 기준)만 단위 상수로 통과한다. 2.0, 10.0 등도 위반이다.
  3. 그 외 소수와 5자리 이상 정수는, 그 파일 맨 위 20줄 안의 "순수 주석 줄"
       # hardcode-allow: 100_000_000 10_000 (단위 변환)
       # hardcode-allow: 0.6 1.05 (화면 투명도·확대 — 스타일)
     에 적힌 값만 통과한다. 코드 줄 끝 주석이나 문자열 안의 같은 글은 무시한다.
     허용 목록은 다른 곳에 두지 않으며, 그 파일에서만 유효하다. 이유를 괄호로 적는다.

알려진 한계: 정규식 리터럴(/"/ 같은)은 해석하지 않아 그 안의 따옴표를 문자열 시작으로 본다.
  JSX 텍스트의 아포스트로피(don't)는 줄 끝까지를 문자열로 본다(줄 번호는 유지).
  정규식 리터럴은 프론트 단계에서 ESLint 규칙으로 보완한다.

사용: python tools/check_hardcode.py [--paths 폴더 ...]  (기본 backend/app frontend/src)
없는 폴더는 건너뛴다. 위반이 있으면 종료 코드 1.
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PATHS = ["backend/app", "frontend/src"]
EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs"}
ALLOW_HEAD_LINES = 20
UNIT_FLOATS = {0.0, 0.5, 1.0, 100.0}
BIG_NUMBER = 10_000  # 5자리 이상

ALLOW_RE = re.compile(r"hardcode-allow:\s*((?:\d[\d_]*(?:\.\d+)?[\s,]*)+)")
DATE_CALL_RE = re.compile(r"\b(?:date|datetime|Date(?:\.UTC)?)\s*\(\s*(?:year\s*=\s*)?20\d\d")
DATE_STR_RES = [
    re.compile(r"(?<!\d)20\d\d-\d\d-\d\d(?!\d)"),
    re.compile(r"(?<!\d)20\d\d/\d\d/\d\d(?!\d)"),
    re.compile(r"(?<!\d)20\d{6}(?!\d)"),
    re.compile(r"(?<!\d)20\d\d년\s*\d{1,2}월"),
]
DEMO_NAME_RE = re.compile(r"(?<![A-Za-z])(?:PLAN|CMP|INF|SKU|CH|LC)-\d", re.I)
DIGIT_STR_RE = re.compile(r"^\s*\d[\d_]*\s*$")
NUMBER_RE = re.compile(
    r"(?<![\w.])(?:0[xXbBoO][0-9a-fA-F_]+|\d[\d_]*(?:\.\d*)?(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)"
)
TEST_FILE_RE = re.compile(r"^(?:test_.*\.py|.*_test\.py|.*\.(?:test|spec)\.(?:ts|tsx|js|jsx))$")


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    kind: str
    text: str

    def format(self) -> str:
        return f"{self.path}:{self.line}: {self.kind}: {self.text}"


@dataclass
class Scan:
    masked: str
    strings: list  # (시작줄, 내용, 삼중따옴표 여부, 접두어, 템플릿 여부)
    comments: list  # (줄, 글) - 줄 맨 앞에서 시작한 순수 주석만


def _scan(src: str, lang: str) -> Scan:
    """주석·문자열을 분리한다. 줄 수는 항상 보존한다."""
    masked: list[str] = []
    strings: list = []
    comments: list = []
    i, n, line = 0, len(src), 1
    py = lang == "py"

    def pure(pos: int) -> bool:
        return src[src.rfind("\n", 0, pos) + 1 : pos].strip() == ""

    while i < n:
        c = src[i]
        if c == "\n":
            masked.append(c)
            line += 1
            i += 1
        elif (py and c == "#") or (not py and src.startswith("//", i)):
            j = src.find("\n", i)
            j = n if j < 0 else j
            if pure(i):
                comments.append((line, src[i:j]))
            i = j
        elif not py and src.startswith("/*", i):
            end = src.find("*/", i + 2)
            end = n if end < 0 else end + 2
            chunk = src[i:end]
            if pure(i):
                for k, part in enumerate(chunk.split("\n")):
                    comments.append((line + k, part))
            masked.append("\n" * chunk.count("\n"))
            line += chunk.count("\n")
            i = end
        elif c in "\"'" or (not py and c == "`"):
            k = i
            while k > 0 and src[k - 1] in "rRbBuUfF" and i - k < 2:
                k -= 1
            ok_prefix = k == 0 or not (src[k - 1].isalnum() or src[k - 1] == "_")
            prefix = src[k:i] if py and ok_prefix else ""
            triple = py and src.startswith(c * 3, i)
            quote = c * 3 if triple else c
            j = i + len(quote)
            start_line = line
            closed = False
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src.startswith(quote, j):
                    closed = True
                    break
                if src[j] == "\n" and not triple and c != "`":
                    break
                j += 1
            j = min(j, n)
            body = src[i + len(quote) : j]
            strings.append((start_line, body, triple, prefix, c == "`"))
            line += body.count("\n")
            masked.append("\n" * body.count("\n"))
            masked.append(" ")  # 문자열 자리를 비운 코드 사본
            # 닫는 따옴표 없이 줄바꿈에서 끊기면 줄바꿈을 소비하지 않는다(줄 번호 유지)
            i = j + len(quote) if closed else j
        else:
            masked.append(c)
            i += 1
    return Scan("".join(masked), strings, comments)


def _docstring_lines(src: str) -> set[int]:
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return set()
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                lines.add(body[0].value.lineno)
    return lines


def _allowed_values(comments: list) -> tuple[set[int], set[float]]:
    ints: set[int] = set()
    floats: set[float] = set()
    for line, text in comments:
        if line > ALLOW_HEAD_LINES:
            continue
        m = ALLOW_RE.search(text)
        if not m:
            continue
        for tok in re.findall(r"\d[\d_]*(?:\.\d+)?", m.group(1)):
            tok = tok.replace("_", "")
            if "." in tok:
                floats.add(float(tok))
            else:
                ints.add(int(tok))
    return ints, floats


def _cut_format_spec(expr: str) -> str:
    """f-string 식에서 형식 지정(:.2f)과 변환(!r)을 잘라낸다."""
    depth, quote = 0, ""
    for idx, ch in enumerate(expr):
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif depth == 0 and (ch == ":" or (ch == "!" and expr[idx + 1 : idx + 2] != "=")):
            return expr[:idx]
    return expr


def _split_template(body: str, dollar: bool) -> tuple[str, list[tuple[int, str]]]:
    """문자열 내용을 (식을 지운 글, [(식 시작 줄 오프셋, 식)])으로 나눈다."""
    literal: list[str] = []
    exprs: list[tuple[int, str]] = []
    i, n = 0, len(body)
    while i < n:
        ch = body[i]
        opens = body.startswith("${", i) if dollar else ch == "{"
        if not dollar and ch == "{" and body.startswith("{{", i):
            literal.append("  ")
            i += 2
            continue
        if not opens:
            literal.append(ch)
            i += 1
            continue
        start = i + (2 if dollar else 1)
        depth, j = 1, start
        while j < n and depth:
            if body[j] == "{":
                depth += 1
            elif body[j] == "}":
                depth -= 1
            j += 1
        expr = body[start : j - 1] if depth == 0 else body[start:j]
        if not dollar:
            expr = _cut_format_spec(expr)
        exprs.append((body.count("\n", 0, start), expr))
        literal.append("".join(c2 if c2 == "\n" else " " for c2 in body[i:j]))
        i = j
    return "".join(literal), exprs


def _number_violation(tok: str, ints: set[int], floats: set[float]) -> str | None:
    low = tok.replace("_", "").lower()
    try:
        if low[:2] in ("0x", "0b", "0o"):
            value: float = int(low, 0)
            plain_int = True
        elif "." in low or "e" in low:
            value = float(low)
            plain_int = False
        else:
            value = int(low)
            plain_int = True
    except ValueError:
        return None
    if value >= BIG_NUMBER and value == int(value):
        return None if int(value) in ints else "큰 숫자 리터럴"
    if plain_int:
        return None
    if value in UNIT_FLOATS or value in floats:
        return None
    return "정책성 소수 리터럴"


def _analyze(src: str, lang: str, base_line: int, path: Path, ints: set[int], floats: set[float],
             doc_lines: set[int]) -> list[Violation]:
    sc = _scan(src, lang)
    out: list[Violation] = []

    def add(line: int, kind: str, text: str) -> None:
        out.append(Violation(path, base_line + line - 1, kind, text))

    for m in DATE_CALL_RE.finditer(sc.masked):
        add(sc.masked.count("\n", 0, m.start()) + 1, "날짜 리터럴", m.group(0) + "...")
    for m in NUMBER_RE.finditer(sc.masked):
        kind = _number_violation(m.group(0), ints, floats)
        if kind:
            add(sc.masked.count("\n", 0, m.start()) + 1, kind, m.group(0))

    for start, body, triple, prefix, template in sc.strings:
        if triple and start in doc_lines:
            continue
        literal = body
        if "f" in prefix.lower() or template:
            literal, exprs = _split_template(body, dollar=template)
            for off, expr in exprs:
                out.extend(_analyze(expr, lang, base_line + start - 1 + off, path, ints, floats, set()))
        dated = False
        for rx in DATE_STR_RES:
            for m in rx.finditer(literal):
                dated = True
                add(start + literal.count("\n", 0, m.start()), "날짜 리터럴", m.group(0))
        for m in DEMO_NAME_RE.finditer(literal):
            add(start + literal.count("\n", 0, m.start()), "시연 이름 리터럴", m.group(0))
        if not dated and DIGIT_STR_RE.match(literal):
            value = int(literal.strip().replace("_", ""))
            if value >= BIG_NUMBER and value not in ints:
                add(start, "큰 숫자 리터럴", f'"{literal.strip()}"')
    return out


def check_source(src: str, path: Path) -> list[Violation]:
    lang = "py" if path.suffix == ".py" else "ts"
    # 허용 주석은 최상위 스캔의 순수 주석 줄에서만 읽는다
    ints, floats = _allowed_values(_scan(src, lang).comments)
    doc_lines = _docstring_lines(src) if lang == "py" else set()
    out = _analyze(src, lang, 1, path, ints, floats, doc_lines)
    out.sort(key=lambda v: (v.line, v.kind))
    return out


def check_file(path: Path) -> list[Violation]:
    path = Path(path)
    return check_source(path.read_text(encoding="utf-8"), path)


def is_test_file(root: Path, f: Path) -> bool:
    rel = f.relative_to(root)
    return bool(TEST_FILE_RE.match(f.name)) or "__tests__" in rel.parts[:-1]


def collect_files(roots: list[str]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        p = Path(root)
        if not p.is_dir():
            print(f"건너뜀(폴더 없음): {root}")
            continue
        files += sorted(f for f in p.rglob("*") if f.is_file() and f.suffix in EXTENSIONS
                        and "node_modules" not in f.parts and not is_test_file(p, f))
    return files


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="코드 본체의 하드코딩 검사")
    ap.add_argument("--paths", nargs="+", default=DEFAULT_PATHS, help="검사할 폴더")
    args = ap.parse_args(argv)
    violations: list[Violation] = []
    for f in collect_files(args.paths):
        violations += check_file(f)
    for v in violations:
        print(v.format())
    if violations:
        print(f"하드코딩 {len(violations)}건 발견")
        return 1
    print("하드코딩 없음")
    return 0


if __name__ == "__main__":
    sys.exit(main())
