"""하드코딩 자동 검사.

코드 본체(backend/app, frontend/src)에 날짜·금액·건수·정책 기준·시연 숫자·시연 이름이
박혀 있으면 실패한다. 이런 값은 데이터·설정에서 읽어야 한다.

위반 유형
  - 날짜 리터럴      : date(20..), datetime(20..), Date(20..), 문자열 안의 20YY-MM-DD
  - 큰 숫자 리터럴   : 5자리 이상 정수(밑줄 포함)
  - 시연 이름 리터럴 : 문자열 안의 PLAN-숫자, CMP-숫자, INF-숫자, SKU-숫자, CH-숫자, LC-숫자
  - 정책성 소수 리터럴: 코드에 나온 소수

허용 규칙 (여기가 전부다)
  1. 주석·파이썬 독스트링 안의 내용은 검사하지 않는다(설명용).
  2. 소수 리터럴은 값이 0.5의 배수(0.0, 0.5, 1.0, 100.0 ...)이면 단위 상수로 보고 통과한다.
     지수 표기(1e-9 등)에서 값이 작은 것도 통과한다.
  3. 5자리 이상 정수는, 그 파일 맨 위 20줄 안의 주석
       # hardcode-allow: 100_000_000 10_000 (단위 변환)
     에 적힌 값만 통과한다. 허용 목록은 다른 곳에 두지 않으며, 그 파일에서만 유효하다.
  4. 16진수 등 비십진 리터럴은 검사하지 않는다.

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
EXTENSIONS = {".py", ".ts", ".tsx"}
ALLOW_HEAD_LINES = 20

ALLOW_RE = re.compile(r"hardcode-allow:\s*((?:[\d_]+[\s,]*)+)")
DATE_CALL_RE = re.compile(r"\b(?:date|datetime|Date)\s*\(\s*20\d\d")
DATE_STR_RE = re.compile(r"(?<![\d-])20\d\d-\d\d-\d\d(?!\d)")
DEMO_NAME_RE = re.compile(r"(?<![A-Za-z])(?:PLAN|CMP|INF|SKU|CH|LC)-\d")
NUMBER_RE = re.compile(
    r"(?<![\w.])(?:0[xXbBoO][0-9a-fA-F_]+|\d[\d_]*(?:\.\d*)?(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)"
)
STRING_PREFIX_RE = re.compile(r"[rRbBuUfF]{1,2}$")


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    kind: str
    text: str

    def format(self) -> str:
        return f"{self.path}:{self.line}: {self.kind}: {self.text}"


def _scan(src: str, lang: str):
    """주석·문자열을 분리한다. (코드만 남긴 사본, [(시작줄, 내용, 삼중따옴표 여부)])를 돌려준다."""
    masked: list[str] = []
    strings: list[tuple[int, str, bool]] = []
    i, n, line = 0, len(src), 1
    py = lang == "py"
    while i < n:
        c = src[i]
        if c == "\n":
            masked.append(c)
            line += 1
            i += 1
        elif (py and c == "#") or (not py and src.startswith("//", i)):
            while i < n and src[i] != "\n":
                i += 1
        elif not py and src.startswith("/*", i):
            end = src.find("*/", i + 2)
            end = n if end < 0 else end + 2
            chunk = src[i:end]
            masked.append("\n" * chunk.count("\n"))
            line += chunk.count("\n")
            i = end
        elif c in "\"'" or (not py and c == "`"):
            triple = py and src.startswith(c * 3, i)
            quote = c * 3 if triple else c
            j = i + len(quote)
            start_line = line
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src.startswith(quote, j):
                    break
                if src[j] == "\n" and not triple and c != "`":
                    break
                j += 1
            body = src[i + len(quote) : j]
            strings.append((start_line, body, triple))
            line += body.count("\n")
            masked.append("\n" * body.count("\n"))
            masked.append(" ")  # 문자열 자리를 비운 코드 사본
            i = min(n, j + len(quote))
        else:
            masked.append(c)
            i += 1
    return "".join(masked), strings


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


def _allowed_values(src: str) -> set[str]:
    allowed: set[str] = set()
    for text in src.splitlines()[:ALLOW_HEAD_LINES]:
        m = ALLOW_RE.search(text)
        if m:
            allowed.update(tok.replace("_", "") for tok in re.findall(r"[\d_]+", m.group(1)) if tok.strip("_"))
    return allowed


def check_source(src: str, path: Path) -> list[Violation]:
    lang = "py" if path.suffix == ".py" else "ts"
    masked, strings = _scan(src, lang)
    allowed = _allowed_values(src)
    out: list[Violation] = []

    def add(line: int, kind: str, text: str) -> None:
        out.append(Violation(path, line, kind, text))

    for m in DATE_CALL_RE.finditer(masked):
        add(masked.count("\n", 0, m.start()) + 1, "날짜 리터럴", m.group(0) + "...")

    for m in NUMBER_RE.finditer(masked):
        tok = m.group(0)
        if tok[:2].lower() in ("0x", "0b", "0o"):
            continue
        line = masked.count("\n", 0, m.start()) + 1
        clean = tok.replace("_", "")
        is_float = "." in clean or "e" in clean.lower()
        if not is_float:
            if len(clean.lstrip("0") or "0") >= 5 and clean not in allowed:
                add(line, "큰 숫자 리터럴", tok)
            continue
        value = float(clean)
        if "e" in clean.lower():
            if value >= 10_000 and value.is_integer() and str(int(value)) not in allowed:
                add(line, "큰 숫자 리터럴", tok)
            continue
        if (value * 2).is_integer():
            if value >= 10_000 and str(int(value)) not in allowed:
                add(line, "큰 숫자 리터럴", tok)
        else:
            add(line, "정책성 소수 리터럴", tok)

    doc_lines = _docstring_lines(src) if lang == "py" else set()
    for start, body, triple in strings:
        if triple and start in doc_lines:
            continue
        for rx, kind in ((DATE_STR_RE, "날짜 리터럴"), (DEMO_NAME_RE, "시연 이름 리터럴")):
            for m in rx.finditer(body):
                add(start + body.count("\n", 0, m.start()), kind, m.group(0))

    out.sort(key=lambda v: (v.line, v.kind))
    return out


def check_file(path: Path) -> list[Violation]:
    path = Path(path)
    return check_source(path.read_text(encoding="utf-8"), path)


def collect_files(roots: list[str]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        p = Path(root)
        if not p.is_dir():
            print(f"건너뜀(폴더 없음): {root}")
            continue
        files += sorted(f for f in p.rglob("*") if f.is_file() and f.suffix in EXTENSIONS
                        and "node_modules" not in f.parts)
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
