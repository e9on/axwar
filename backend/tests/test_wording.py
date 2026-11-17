"""#41: 수수료 뜻의 '피'는 사용자에게 '값'으로 말한다. 괄호 조사(을(를) 꼴)는 서버 문장에 남기지 않는다."""
import json
import re
import sys
from pathlib import Path

import pytest

from app import policy
from app.ai import prompts, providers
from app.ai.providers import FakeProvider
from app.engine import scenarios
from app.engine.flow import Engine
from app.store.db import open_db

sys.path.insert(0, str(Path(__file__).parent))
from test_flow_11b import ACCEPT  # noqa: E402

BAD_PI = ("인플루언서 피", "고정 피", "성과 피", "피 뒤", "준 피")
PAREN_JOSA = re.compile(r"[가-힣0-9A-Za-z]\((?:을|를|이|가|은|는|와|과|으|로|이라|라)\)|을\(를\)|\(으\)로|\(이\)가|은\(는\)|와\(과\)")


def _assert_clean(text: str):
    for bad in BAD_PI:
        assert bad not in text, f"{bad!r} 남음: {text[:120]}"
    assert not PAREN_JOSA.search(text), f"괄호 조사 남음: {text[:120]}"


@pytest.fixture
def store(tmp_path):
    s = open_db(tmp_path / "t.db")
    yield s
    s.close()


def _eng(store):
    return Engine(store, provider=FakeProvider([ACCEPT, ACCEPT, ACCEPT, ACCEPT]))


def test_근거_API_문장에_피_표현이_없다(store):
    eng = _eng(store)
    scenarios.register_plan(store, "PLAN-001")
    ev = eng.case_evidence(eng.open_plan("PLAN-001"))
    _assert_clean(json.dumps(ev, ensure_ascii=False))
    assert "인플루언서 값" in json.dumps(ev["cost_breakdown"], ensure_ascii=False)
    assert "인플루언서 값을 뺀 공헌" in json.dumps(ev["cost_breakdown"], ensure_ascii=False)


def test_계약_근거와_가짜_AI_브리핑에_피_표현이_없다(store):
    eng = _eng(store)
    scenarios.register_contract(store, "INF-001")
    cid = eng.open_contract("INF-001")
    _assert_clean(json.dumps(eng.case_evidence(cid), ensure_ascii=False))
    facts = {"인플루언서": "혜인", "연 고정 값": "2800000000", "계약 만료": "2026-12-31", "기안 총액": "1"}
    _assert_clean(providers._fake_briefing(facts))
    for r in providers._fake_reasons(facts, "", False, True):
        _assert_clean(r)


def test_통보_초안과_AI_지시문에_피_표현이_없다():
    facts = {"인플루언서": "혜인", "계약 만료": "2026-12-31", "연 고정 값(원)": "2800000000",
             "성과 값 기준": "공제 후 순액 (총매출 아님)", "공제 항목": "반품·수수료"}
    draft = providers._fake_notice(facts)
    _assert_clean(draft)
    assert "고정 값은 2800000000원" in draft and "성과 값은 공제 후 순액 기준" in draft
    for name in dir(prompts):
        v = getattr(prompts, name)
        if isinstance(v, str):
            _assert_clean(v)


def test_정책_설명에_피_표현이_없다():
    for k in policy.keys():
        _assert_clean(str(policy.entry(k)[2]) if len(policy.entry(k)) > 2 else "")


def test_데모_설명에_피_표현이_없다():
    for p in (Path(__file__).parents[1] / "demo").glob("*.json"):
        _assert_clean(p.read_text(encoding="utf-8"))


def test_정책_변경_거부_문장에_괄호_조사가_없다(store):
    eng = _eng(store)
    for name in eng.people.people:
        for what in ("정책", "실행 모드"):
            why = eng._policy_editor_block(name, what)
            if why:
                _assert_clean(why)
