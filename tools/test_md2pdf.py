"""md2pdf 목록 정규화 테스트.

실행: uv run --no-project --with markdown --with pytest python -m pytest tools/test_md2pdf.py -q
"""
import markdown

from md2pdf import normalize_lists


def render(md: str) -> str:
    return markdown.markdown(normalize_lists(md), extensions=["tables", "fenced_code", "sane_lists"])


def test_문단_바로_뒤_번호목록이_목록으로_보인다():
    html = render("입력: 건 종류\n1. 첫째\n2. 둘째")
    assert "<ol>" in html
    assert html.count("<li>") == 2


def test_문단_바로_뒤_글머리목록이_목록으로_보인다():
    html = render("확인할 것:\n- 가\n- 나")
    assert "<ul>" in html
    assert html.count("<li>") == 2


def test_두칸_들여쓴_하위목록이_중첩된다():
    html = render("- 상위\n  - 하위")
    assert html.count("<ul>") == 2


def test_번호목록_뒤_글머리목록은_따로_목록이_된다():
    html = render("1. 첫째\n2. 둘째\n- 덧붙임")
    assert "<ol>" in html and "<ul>" in html
    assert html.count("<li>") == 3


def test_코드블록_안의_대시는_건드리지_않는다():
    md = "```\n텍스트\n- 목록 아님\n```"
    assert normalize_lists(md) == md


def test_이미_빈줄이_있는_목록은_그대로다():
    md = "문단\n\n- 가\n- 나"
    assert normalize_lists(md) == md
