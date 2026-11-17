"""하드코딩 검사 테스트.

실행: uv run --no-project --python 3.11 --with markdown --with pytest python -m pytest -q -p no:cacheprovider
"""
from pathlib import Path

import pytest

from check_hardcode import check_file, main


def write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def kinds(path: Path) -> list[str]:
    return [v.kind for v in check_file(path)]


# --- 날짜 ---
def test_date_호출이_걸린다(tmp_path):
    p = write(tmp_path, "a.py", "from datetime import date\nx = date(2026, 11, 10)\n")
    vs = check_file(p)
    assert [v.kind for v in vs] == ["날짜 리터럴"]
    assert vs[0].line == 2


def test_datetime_호출과_문자열_날짜가_걸린다(tmp_path):
    p = write(tmp_path, "a.py", "a = datetime(2026, 1, 1)\nb = '2026-11-10'\nc = \"기한은 2026-12-31 입니다\"\n")
    assert kinds(p) == ["날짜 리터럴"] * 3


def test_날짜_변수_계산은_통과한다(tmp_path):
    p = write(tmp_path, "a.py", "x = date(year, month, day)\ny = today - timedelta(days=7)\n")
    assert kinds(p) == []


def test_ts_날짜가_걸린다(tmp_path):
    p = write(tmp_path, "a.ts", "const d = new Date(2026, 1, 1);\nconst e = '2026-01-02';\n")
    assert kinds(p) == ["날짜 리터럴"] * 2


# --- 큰 정수 ---
def test_5자리_이상_정수가_걸린다(tmp_path):
    p = write(tmp_path, "a.py", "a = 10_000_000\nb = 12345\nc = 9999\n")
    assert kinds(p) == ["큰 숫자 리터럴"] * 2


def test_허용_주석에_적힌_값만_통과한다(tmp_path):
    src = "# hardcode-allow: 100_000_000 10_000 (단위 변환)\nA = 100_000_000\nB = 10_000\nC = 50_000\n"
    p = write(tmp_path, "a.py", src)
    vs = check_file(p)
    assert [(v.kind, v.line) for v in vs] == [("큰 숫자 리터럴", 4)]


def test_허용_주석은_그_파일에서만_통한다(tmp_path):
    write(tmp_path, "a.py", "# hardcode-allow: 10_000 (단위)\nA = 10_000\n")
    b = write(tmp_path, "b.py", "B = 10_000\n")
    assert kinds(tmp_path / "a.py") == []
    assert kinds(b) == ["큰 숫자 리터럴"]


def test_허용_주석이_20줄_밖이면_무효(tmp_path):
    src = "\n" * 25 + "# hardcode-allow: 10_000\nA = 10_000\n"
    assert kinds(write(tmp_path, "a.py", src)) == ["큰 숫자 리터럴"]


def test_ts_큰_숫자와_허용(tmp_path):
    p = write(tmp_path, "a.ts", "// hardcode-allow: 10000 (단위)\nconst a = 10000;\nconst b = 20000;\n")
    assert [v.line for v in check_file(p)] == [3]


# --- 시연 이름 ---
def test_시연_이름_문자열이_걸린다(tmp_path):
    src = 'a = "PLAN-1"\nb = \'CMP-01\'\nc = "INF-3"\nd = "SKU-9"\ne = "CH-2"\nf = "LC-4"\n'
    assert kinds(write(tmp_path, "a.py", src)) == ["시연 이름 리터럴"] * 6


def test_문장_속_시연_이름도_걸린다(tmp_path):
    assert kinds(write(tmp_path, "a.py", 'msg = "CMP-1 건을 확인하세요"\n')) == ["시연 이름 리터럴"]


def test_시연_이름_비슷한_일반_문자열은_통과한다(tmp_path):
    assert kinds(write(tmp_path, "a.py", 'a = "PLAN"\nb = "PLAN-A"\nc = "X-1"\n')) == []


# --- 소수 ---
def test_정책성_소수가_걸린다(tmp_path):
    p = write(tmp_path, "a.py", "a = 0.85\nb = 1.645\nc = 1.25\n")
    assert kinds(p) == ["정책성 소수 리터럴"] * 3


def test_단위_상수_소수는_통과한다(tmp_path):
    assert kinds(write(tmp_path, "a.py", "a = 0.0\nb = 0.5\nc = 1.0\nd = 100.0\n")) == []


def test_ts_소수(tmp_path):
    assert kinds(write(tmp_path, "a.tsx", "const r = 0.85;\nconst z = 1.0;\n")) == ["정책성 소수 리터럴"]


def test_식별자_속_숫자와_작은_정수는_통과한다(tmp_path):
    assert kinds(write(tmp_path, "a.py", "x1 = 3\ny_2024 = 7\nz = a[0] + 12\n")) == []


# --- 주석·독스트링 ---
def test_주석_안_숫자는_통과한다(tmp_path):
    src = "# 기준 0.85, 2026-11-10, PLAN-1, 10_000_000\nx = 1  # date(2026, 1, 1) 예시 99999\n"
    assert kinds(write(tmp_path, "a.py", src)) == []


def test_독스트링_안_숫자는_통과한다(tmp_path):
    src = '"""모듈 설명: 0.85, 2026-11-10, PLAN-1."""\n\n\ndef f():\n    """함수 설명 12345 date(2026, 1, 1)"""\n    return 1\n'
    assert kinds(write(tmp_path, "a.py", src)) == []


def test_일반_문자열의_날짜는_독스트링이_아니라서_걸린다(tmp_path):
    src = 'def f():\n    x = "2026-11-10"\n    return x\n'
    assert kinds(write(tmp_path, "a.py", src)) == ["날짜 리터럴"]


def test_ts_주석_안_숫자는_통과한다(tmp_path):
    src = "// 0.85 PLAN-1\n/* 2026-11-10\n 99999 */\nconst u = 'http://a.b/c';\n"
    assert kinds(write(tmp_path, "a.ts", src)) == []


# --- 폴더·CLI ---
def test_없는_폴더는_건너뛴다(tmp_path, capsys):
    assert main(["--paths", str(tmp_path / "없음")]) == 0


def test_위반이_있으면_종료코드_1과_목록(tmp_path, capsys):
    d = tmp_path / "app"
    d.mkdir()
    (d / "m.py").write_text("x = 0.85\n", encoding="utf-8")
    assert main(["--paths", str(d)]) == 1
    out = capsys.readouterr().out
    assert "m.py:1: 정책성 소수 리터럴: 0.85" in out


def test_위반이_없으면_0(tmp_path):
    d = tmp_path / "app"
    d.mkdir()
    (d / "m.py").write_text("x = 1\n", encoding="utf-8")
    (d / "n.txt").write_text("0.85", encoding="utf-8")
    assert main(["--paths", str(d)]) == 0


def test_하위_폴더도_검사한다(tmp_path):
    d = tmp_path / "app" / "sub"
    d.mkdir(parents=True)
    (d / "m.ts").write_text("const a = 0.85;\n", encoding="utf-8")
    assert main(["--paths", str(tmp_path / "app")]) == 1



# --- 수정 1회차: 우회 차단 ---
def test_소수_허용은_네_값뿐(tmp_path):
    assert kinds(write(tmp_path, "a.py", "a = 2.0\nb = 10.0\nc = 1.5\n")) == ["정책성 소수 리터럴"] * 3


def test_소수_허용_주석은_순수_주석_줄에서만(tmp_path):
    src = "# hardcode-allow: 0.6 1.05 (화면 투명도·확대 — 스타일)\na = 0.6\nb = 1.05\nc = 0.7\n"
    assert [(v.kind, v.line) for v in check_file(write(tmp_path, "a.py", src))] == [("정책성 소수 리터럴", 4)]
    assert kinds(write(tmp_path, "b.py", "x = 1  # hardcode-allow: 0.6\ny = 0.6\n")) == ["정책성 소수 리터럴"]
    assert kinds(write(tmp_path, "c.py", 's = "# hardcode-allow: 0.6"\ny = 0.6\n')) == ["정책성 소수 리터럴"]
    assert kinds(write(tmp_path, "d.py", "x = 1  # hardcode-allow: 50000\ny = 50000\n")) == ["큰 숫자 리터럴"]


@pytest.mark.parametrize("lit,kind", [
    ("8.5e-1", "정책성 소수 리터럴"), ("85e-2", "정책성 소수 리터럴"), ("1.5e-3", "정책성 소수 리터럴"),
    ("1e6", "큰 숫자 리터럴"), ("0x2710", "큰 숫자 리터럴"), ("0o23420", "큰 숫자 리터럴"),
    ("0b10011100010000", "큰 숫자 리터럴"),
])
def test_지수와_비십진은_값으로_판정(tmp_path, lit, kind):
    assert kinds(write(tmp_path, "a.py", f"a = {lit}\n")) == [kind]


def test_작은_비십진과_허용값_지수는_통과(tmp_path):
    assert kinds(write(tmp_path, "a.py", "a = 0xFF\nb = 0b11\nc = 5e-1\nd = 1e2\n")) == []


def test_f문자열_안쪽은_코드로_검사(tmp_path):
    assert kinds(write(tmp_path, "a.py", 'x = f"{date(2026,1,1)}"\n')) == ["날짜 리터럴"]
    assert kinds(write(tmp_path, "b.py", 'x = f"{0.85*y}"\n')) == ["정책성 소수 리터럴"]
    assert kinds(write(tmp_path, "c.py", 'x = f"{y:.2f} {{0.85}} {z!r}"\n')) == []
    assert kinds(write(tmp_path, "d.py", 'x = f"기한 2026-01-01 {y}"\n')) == ["날짜 리터럴"]


def test_ts_템플릿_안쪽은_코드로_검사(tmp_path):
    assert kinds(write(tmp_path, "a.ts", "const s = `${new Date(2026, 1, 1)}`;\n")) == ["날짜 리터럴"]
    assert kinds(write(tmp_path, "b.ts", "const s = `${0.85 * y} 원`;\n")) == ["정책성 소수 리터럴"]
    assert kinds(write(tmp_path, "c.ts", "const s = `${y} 원`;\n")) == []


@pytest.mark.parametrize("src,name", [
    ("x = date(year=2026, month=1, day=1)", "a.py"),
    ("x = datetime(year=2026, month=1, day=1)", "a.py"),
    ("const d = Date.UTC(2026, 0, 1);", "a.ts"),
    ('x = "a-2026-11-10"', "a.py"),
    ('x = "2026/11/10"', "a.py"),
    ('x = "20261110"', "a.py"),
    ('x = "2026년 11월 기준"', "a.py"),
    ('x = "2026년 1월"', "a.py"),
])
def test_날짜_우회_표기도_걸린다(tmp_path, src, name):
    assert kinds(write(tmp_path, name, src + "\n")) == ["날짜 리터럴"]


def test_숫자만_든_문자열도_걸린다(tmp_path):
    src = 'a = int("50000")\nb = \'1_000_000\'\nc = "1234"\nd = "A50000"\n'
    assert kinds(write(tmp_path, "a.py", src)) == ["큰 숫자 리터럴"] * 2
    assert kinds(write(tmp_path, "b.py", '# hardcode-allow: 50000\na = int("50000")\n')) == []


def test_시연_이름은_대소문자_무시(tmp_path):
    assert kinds(write(tmp_path, "a.py", 'a = "plan-1"\nb = "Cmp-2"\nc = "arch-1"\n')) == ["시연 이름 리터럴"] * 2


def test_js_계열도_검사하고_테스트_파일은_제외(tmp_path):
    d = tmp_path / "src"
    (d / "__tests__").mkdir(parents=True)
    for name in ["test_x.py", "x_test.py", "a.test.ts", "a.spec.tsx", "__tests__/b.ts"]:
        (d / name).write_text("const a = 0.85;\nx = 0.85\n", encoding="utf-8")
    assert main(["--paths", str(d)]) == 0
    for name in ["a.js", "b.jsx", "c.mjs"]:
        (d / name).write_text("const a = 0.85;\n", encoding="utf-8")
        assert main(["--paths", str(d)]) == 1
        (d / name).unlink()


def test_ts_아포스트로피가_줄_번호를_밀지_않는다(tmp_path):
    p = write(tmp_path, "a.tsx", "const a = <p>don't</p>;\nconst b = 0.85;\n")
    assert [v.line for v in check_file(p)] == [2]


def test_ts_정규식_리터럴_한계를_고정한다(tmp_path):
    # 알려진 한계: 정규식 리터럴 안의 따옴표를 문자열 시작으로 본다. 프론트 단계에서 ESLint 규칙으로 보완.
    p = write(tmp_path, "a.ts", 'const r = /"/; const x = 0.85;\nconst y = 0.85;\n')
    assert [v.line for v in check_file(p)] == [2]
