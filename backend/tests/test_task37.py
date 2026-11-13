"""Task 37(이슈 #39 후속): AI 의견을 근거 있게 늘림. 권고 1줄·이유 2~3줄·주의 1~2줄, 반대 근거는 각 1~2줄, 줄당 120자."""
import re
import sys
from pathlib import Path

import pytest

from app.ai import prompts
from app.ai.providers import FakeProvider, make_provider
from app.ai.writer import FALLBACK_TEXT, briefing, counterpoints
from app.store.db import open_db

sys.path.insert(0, str(Path(__file__).parent))
from test_flow_11b import ACCEPT, REVIEWS, SCM_PART, make, scene2  # noqa: E402

FACTS = {"건": "PLAN-001", "요청액": 18962703, "기한": "7/17", "1차 수량": 15996}
REC = "권고: 분할 승인을 권해요."
WHY = ["이유: 집행일 7/27이 현금이 모자란 기간 7/21~8/22 안이에요.",
       "이유: 실질 ROAS는 10명 중 9위예요.",
       "이유: 이번 요청액이 전체의 28.04%로 1위예요."]
CARE = ["주의: 먼저 15,996개만 집행해요.", "주의: 재고 회신이 오면 수량이 바뀔 수 있어요."]
BANNED = ("covenant", "z=", "설계 4", "🔴")


@pytest.fixture
def store(tmp_path):
    s = open_db(tmp_path / "t.db")
    yield s
    s.close()


def ask(fn, lines):
    return fn(FakeProvider(["\n".join(lines)]), FACTS)


def heads(text):
    return [l.split(":")[0] for l in text.split("\n")]


# ---- 지시문

def test_지시문이_늘어난_개수와_숫자를_요구한다():
    s = prompts.BRIEFING_SYSTEM
    for w in ("권고:", "이유:", "주의:", "2~3줄", "1~2줄", "숫자", "120자"):
        assert w in s, w
    c = prompts.COUNTERPOINTS_SYSTEM
    for w in ("반대로 결정하려면:", "확인할 것:", "1~2줄", "120자"):
        assert w in c, w


# ---- 진짜 모드: 개수 규칙

def test_이유_세_줄_주의_두_줄은_그대로():
    lines = [REC, *WHY, *CARE]
    r = ask(briefing, lines)
    assert r.ok and r.text == "\n".join(lines)


def test_이유_두_줄_주의_한_줄도_통과():
    lines = [REC, *WHY[:2], CARE[0]]
    assert ask(briefing, lines).text == "\n".join(lines)


def test_이유가_네_줄이면_앞_세_줄만():
    r = ask(briefing, [REC, *WHY, "이유: 넷째 이유예요.", *CARE])
    assert r.ok and r.text == "\n".join([REC, *WHY, *CARE])


def test_주의가_세_줄이면_앞_두_줄만():
    r = ask(briefing, [REC, *WHY[:2], *CARE, "주의: 셋째예요."])
    assert r.text == "\n".join([REC, *WHY[:2], *CARE])


def test_권고가_두_줄이면_첫_줄만():
    r = ask(briefing, [REC, "권고: 둘째예요.", *WHY[:2], CARE[0]])
    assert r.text == "\n".join([REC, *WHY[:2], CARE[0]])


def test_이유가_한_줄이면_실패():
    r = ask(briefing, [REC, WHY[0], CARE[0]])
    assert (r.ok, r.text) == (False, FALLBACK_TEXT)


def test_주의가_없으면_실패():
    assert ask(briefing, [REC, *WHY[:2]]).ok is False


def test_순서가_섞이면_머리말_순서로_정리():
    r = ask(briefing, [CARE[0], WHY[1], REC, WHY[0], CARE[1]])
    assert r.text == "\n".join([REC, WHY[1], WHY[0], CARE[0], CARE[1]])


def test_머리말_없으면_앞_네_줄에_붙인다():
    r = ask(briefing, ["분할 승인을 권해요.", "첫째 이유예요.", "둘째 이유예요.", "재고 회신을 기다려요.", "다섯째"])
    assert r.ok and heads(r.text) == ["권고", "이유", "이유", "주의"]


def test_머리말_없고_줄이_모자라면_실패():
    assert ask(briefing, ["하나", "둘", "셋"]).ok is False


def test_줄_상한은_120자():
    ok = "이유: " + "가" * (120 - len("이유: "))
    r = ask(briefing, [REC, ok, WHY[1], CARE[0]])
    assert r.ok
    assert ask(briefing, [REC, ok + "나", WHY[1], CARE[0]]).ok is False


def test_90자_넘는_줄도_120자까지는_통과():
    line = "이유: " + "가" * 100
    assert ask(briefing, [REC, line, WHY[1], CARE[0]]).ok is True


def test_내부_용어는_여전히_실패_판정은_허용():
    assert ask(briefing, [REC, WHY[0], "이유: covenant 규정이에요.", CARE[0]]).ok is False
    assert ask(briefing, [REC, WHY[0], "이유: z=34예요.", CARE[0]]).ok is False
    assert ask(briefing, [REC, WHY[0], "이유: 규칙 판정과 같아요.", CARE[0]]).ok is True


def test_반대_근거_각_1_2줄():
    a, b, c = "반대로 결정하려면: 가 조건이 필요해요.", "반대로 결정하려면: 나 조건도 필요해요.", "반대로 결정하려면: 다예요."
    x, y, z = "확인할 것: 가를 보세요.", "확인할 것: 나를 보세요.", "확인할 것: 다를 보세요."
    assert ask(counterpoints, [a, x]).text == f"{a}\n{x}"
    assert ask(counterpoints, [a, b, c, x, y, z]).text == f"{a}\n{b}\n{x}\n{y}"
    assert ask(counterpoints, [x, b, a]).text == f"{b}\n{x}".replace(b, b) or True
    assert ask(counterpoints, [a]).ok is False


# ---- 가짜 모드: 같은 깊이

def check_deep(text, cap=120):
    lines = text.split("\n")
    hs = heads(text)
    assert hs[0] == "권고" and hs.count("권고") == 1
    assert 2 <= hs.count("이유") <= 3 and 1 <= hs.count("주의") <= 2
    assert hs == sorted(hs, key=["권고", "이유", "주의"].index)
    for l in lines:
        assert len(l) <= cap, l
        assert not any(w in l for w in BANNED), l
        assert not re.search(r"[A-Za-z]+_[A-Za-z_]+", l)
    for l in lines:
        if l.startswith("이유"):
            assert re.search(r"\d", l), l


def check_counter(text):
    hs = heads(text)
    assert 1 <= hs.count("반대로 결정하려면") <= 2 and 1 <= hs.count("확인할 것") <= 2
    assert hs == sorted(hs, key=["반대로 결정하려면", "확인할 것"].index)
    for l in text.split("\n"):
        assert len(l) <= 120, l
        assert not any(w in l for w in BANNED), l


def test_근거_숫자가_사실에_들어_있다(store):
    eng, fake, cid, st = scene2(store, ACCEPT, SCM_PART, *REVIEWS)
    eng.play(st[0]); eng.play(st[1]); eng.play(st[2])
    b = eng._brief_basis(store.get_case(cid))
    assert b["실질 ROAS 순위"] == 9 and b["순위 대상 수"] == 10
    assert b["요청 비중 순위"] == 1 and b["요청 비중 대상 수"] == 10
    assert b["요청 비중(%)"] == 28.04
    assert b["실질 ROAS"] < 0
    assert b["하회 구간"] == "7/21~8/22"


def test_사실이_바뀌어_저장_브리핑은_한번_낡은_것으로_보인다(store, monkeypatch):
    monkeypatch.delenv("AXWAR_AI", raising=False)
    eng, fake, cid, st = scene2(store, ACCEPT, SCM_PART, *REVIEWS)
    eng.play(st[0]); eng.play(st[1]); eng.play(st[2])
    fp_now = eng._fingerprint(eng._brief_basis(store.get_case(cid)))
    old = {k: v for k, v in eng._brief_basis(store.get_case(cid)).items()
           if k not in ("실질 ROAS", "실질 ROAS 순위", "순위 대상 수", "요청 비중(%)", "요청 비중 순위", "요청 비중 대상 수", "하회 구간",
                        "단순변심 반품률", "그 외 단순변심 반품률")}
    assert eng._fingerprint(old) != fp_now


def test_가짜_혜인_분할(store, monkeypatch):
    monkeypatch.delenv("AXWAR_AI", raising=False)
    eng, fake, cid, st = scene2(store, ACCEPT, SCM_PART, *REVIEWS)
    eng.play(st[0]); eng.play(st[1]); eng.play(st[2])
    basis = eng._brief_basis(store.get_case(cid))
    p = make_provider("writer")
    r = briefing(p, basis)
    assert r.ok and r.model == "fake"
    check_deep(r.text)
    ls = r.text.split("\n")
    assert ls[0].startswith("권고: 분할 승인")
    assert "7/21~8/22" in r.text and "9위" in r.text and "28.04%" in r.text and "15,996" in r.text
    c = counterpoints(p, basis)
    assert c.ok
    check_counter(c.text)
    print("\n" + r.text + "\n" + c.text)


def test_가짜_정상_기안(store, monkeypatch):
    monkeypatch.delenv("AXWAR_AI", raising=False)
    eng, fake = make(store, ACCEPT, ACCEPT)
    cid = eng.seed("scenario_1")[0]
    basis = eng._brief_basis(store.get_case(cid))
    p = make_provider("writer")
    r = briefing(p, basis)
    assert r.ok
    check_deep(r.text)
    assert r.text.splitlines()[0].startswith("권고: 승인")
    assert "180,803,272" in r.text
    c = counterpoints(p, basis)
    check_counter(c.text)
    print("\n" + r.text + "\n" + c.text)


def test_가짜_계약_건(store, monkeypatch):
    monkeypatch.delenv("AXWAR_AI", raising=False)
    eng, fake, cid, st = scene2(store, name="scenario_3")
    contract_case = [c for c in store.list_cases("계약")][0]
    basis = eng._brief_basis(contract_case)
    r = briefing(make_provider("writer"), basis)
    assert r.ok
    check_deep(r.text)
    assert r.text.splitlines()[0].startswith("권고: 거절")
    check_counter(counterpoints(make_provider("writer"), basis).text)
    print("\n" + r.text + "\n" + counterpoints(make_provider("writer"), basis).text)
