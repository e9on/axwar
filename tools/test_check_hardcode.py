"""하드코딩 검사 테스트.

실행: uv run --no-project --python 3.11 --with markdown --with pytest python -m pytest -q -p no:cacheprovider
"""
from pathlib import Path

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
    assert kinds(write(tmp_path, "a.py", "a = 0.0\nb = 0.5\nc = 1.0\nd = 100.0\ne = 200.0\n")) == []


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
