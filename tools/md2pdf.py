"""Markdown 문서를 사용자 검토용 PDF로 바꾼다.

사용법: uv run --no-project --with markdown python tools/md2pdf.py 작업노트/문서.md [출력.pdf]
출력을 생략하면 같은 폴더에 같은 이름의 .pdf를 만든다. Chrome(또는 Edge) 헤드리스로 인쇄한다.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

import markdown

BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]

CSS = """
@page { size: A4; margin: 16mm 14mm; }
* { box-sizing: border-box; }
body { font-family: 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif; font-size: 10.5pt; line-height: 1.6; color: #1d1d1f; }
h1 { font-size: 20pt; border-bottom: 3px solid #1f4e79; padding-bottom: 6px; margin: 0 0 12px; color: #1f4e79; }
h2 { font-size: 14pt; color: #1f4e79; border-left: 5px solid #1f4e79; padding-left: 8px; margin: 22px 0 8px; break-after: avoid; }
h3 { font-size: 11.5pt; margin: 14px 0 6px; break-after: avoid; }
p, li { margin: 3px 0; }
ul, ol { padding-left: 20px; }
hr { border: none; border-top: 1px solid #d0d7de; margin: 14px 0; }
table { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 9.5pt; break-inside: auto; }
tr { break-inside: avoid; }
th, td { border: 1px solid #c9d1d9; padding: 4px 6px; vertical-align: top; text-align: left; }
th { background: #eaf1f8; }
th:first-child, td:first-child { min-width: 4.5em; }
code { font-family: Consolas, monospace; font-size: 9pt; background: #f3f4f6; padding: 1px 4px; border-radius: 3px; }
pre { background: #f6f8fa; border: 1px solid #d0d7de; padding: 8px; border-radius: 4px; white-space: pre-wrap; font-size: 8.5pt; }
pre code { background: none; padding: 0; }
strong { color: #0b2a4a; }
img { max-width: 100%; border: 1px solid #d0d7de; margin: 6px 0; }
.b { display: inline-block; font-size: 8pt; font-weight: bold; padding: 0 5px; border-radius: 3px; margin: 0 1px; color: #fff; }
.b-원본 { background: #1f6feb; } .b-계산 { background: #8250df; } .b-가정 { background: #d4a72c; color: #222; }
.b-회신 { background: #1a7f37; } .b-의견 { background: #6e7781; } .b-AI { background: #cf222e; }
"""

BADGE = re.compile(r"(?:<strong>)?\[(원본|계산|가정|회신|의견|AI)\](?:</strong>)?")


LIST_ITEM = re.compile(r"^(\s*)([-*]|\d+\.)\s")


def normalize_lists(text: str) -> str:
    """GitHub식 목록을 Python-Markdown이 읽도록 맞춘다.
    목록 앞 빈 줄을 넣고, 2칸 들여쓰기 중첩을 4칸으로 바꾼다."""
    out: list[str] = []
    in_code = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_code = not in_code
        m = None if in_code else LIST_ITEM.match(line)
        if m:
            indent = len(m.group(1))
            line = " " * (indent * 2) + line.lstrip()
            prev = out[-1] if out else ""
            pm = LIST_ITEM.match(prev)
            if prev.strip() and not pm and not prev.startswith(" "):
                out.append("")
            elif pm and len(pm.group(1)) == len(line) - len(line.lstrip()) and pm.group(2)[0].isdigit() != m.group(2)[0].isdigit():
                out.append("")  # 같은 깊이에서 번호↔글머리 목록이 바뀌면 다른 목록으로 끊는다
        out.append(line)
    return "\n".join(out)


def convert(src: Path, dst: Path) -> None:
    text = normalize_lists(src.read_text(encoding="utf-8"))
    body = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])
    body = BADGE.sub(lambda m: f'<span class="b b-{m.group(1)}">{m.group(1)}</span>', body)
    title = next((l[2:].strip() for l in text.splitlines() if l.startswith("# ")), src.stem)
    html = f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><base href="{src.parent.resolve().as_uri()}/"><title>{title}</title><style>{CSS}</style></head><body>{body}</body></html>'
    browser = next((b for b in BROWSERS if Path(b).exists()), None)
    if not browser:
        sys.exit("Chrome 또는 Edge를 찾지 못했어요")
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "doc.html"
        page.write_text(html, encoding="utf-8")
        subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        f"--user-data-dir={Path(tmp) / 'profile'}",
                        f"--print-to-pdf={dst.resolve()}", page.as_uri()],
                       check=True, capture_output=True, timeout=120)
    print(f"PDF 생성: {dst}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_suffix(".pdf")
    convert(src, dst)
