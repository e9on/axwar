"""A3: 이름을 끼워 넣는 문장의 조사(이/가, 을/를, 은/는, 와/과, 으로/로, 이면/면)를 받침에 따라 고른다."""
import pytest

from app.rules.josa import josa, pick


@pytest.mark.parametrize("word,kind,expected", [
    ("마케팅팀", "이가", "마케팅팀이"), ("Masil 대표", "이가", "Masil 대표가"), ("CEO", "이가", "CEO가"),
    ("물류", "이가", "물류가"), ("캠페인 담당", "이가", "캠페인 담당이"), ("CS", "이가", "CS가"), ("SCM", "이가", "SCM이"),
    ("마케팅팀", "을를", "마케팅팀을"), ("물류", "을를", "물류를"), ("CEO", "은는", "CEO는"), ("마케팅팀", "은는", "마케팅팀은"),
    ("물류", "와과", "물류와"), ("마케팅팀", "와과", "마케팅팀과"),
    ("마케팅팀", "으로", "마케팅팀으로"), ("물류", "으로", "물류로"), ("Masil 대표", "으로", "Masil 대표로"),
    ("서울", "으로", "서울로"),  # ㄹ 받침은 '로'
    ("계약 담당", "이면", "계약 담당이면"), ("CEO", "이면", "CEO면"),
    ("마케팅팀(김팀장)", "이가", "마케팅팀(김팀장)이"),  # 닫는 괄호는 건너뛰고 괄호 안 마지막 낱말 기준
    ("2차", "이가", "2차가"), ("3", "을를", "3을"), ("2", "을를", "2를"),
])
def test_조사를_받침에_따라_고른다(word, kind, expected):
    assert josa(word, kind) == expected


def test_pick은_조사만_돌려준다():
    assert pick("마케팅팀", "이가") == "이" and pick("CEO", "이가") == "가"


def test_모르는_종류는_거부():
    with pytest.raises(ValueError):
        josa("물류", "에게")


def test_엔진_문장에_이름_뒤_조사가_맞게_붙는다(tmp_path):
    from app.engine.flow import Engine
    from app.store.db import open_db
    s = open_db(tmp_path / "t.db")
    try:
        eng = Engine(s)
        who = {role: name for name, role in eng.people.people.items()}
        # 정책 변경 권한이 없는 역할의 이유 문장: '(역할)' 뒤 조사는 역할 이름의 받침을 따른다
        for role, name in who.items():
            why = eng._policy_editor_block(name, "정책")
            if why:
                assert f"({role}){pick(role, '은는')} 정책을 바꿀 수 없음" in why
        assert "마케팅팀" in who and eng._policy_editor_block(who["마케팅팀"], "정책").startswith(f"{who['마케팅팀']}(마케팅팀)은 ")
    finally:
        s.close()
