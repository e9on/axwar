"""Task 30(이슈 #39): AI 브리핑은 세 줄(권고·이유·주의), 반대 근거는 두 줄. 가짜 모드도 같은 형식."""
import re
import sys
from pathlib import Path

import pytest

from app.ai import prompts, writer
from app.ai.providers import Completion, FakeProvider, make_provider
from app.ai.writer import FALLBACK_TEXT, briefing, counterpoints, notice_draft
from app.store.db import open_db

sys.path.insert(0, str(Path(__file__).parent))
from test_flow_11b import ACCEPT, REVIEWS, SCM_PART, make, scene2  # noqa: E402

FACTS = {"건": "PLAN-001", "요청액": 18962703, "기한": "7/17"}
GOOD = "권고: 분할 승인을 권해요.\n이유: 집행일이 현금이 모자란 기간 안이에요.\n이유: 성과 순위가 낮아요.\n주의: 재고 회신을 기다리는 중이에요."
GOOD2 = "반대로 결정하려면: 재고가 충분하다는 확인이 있어야 해요.\n확인할 것: 부서 회신이 바뀌었는지 보세요."
BANNED = ("covenant", "z=", "설계 4", "🔴")


@pytest.fixture
def store(tmp_path):
    s = open_db(tmp_path / "t.db")
    yield s
    s.close()


def ask(fn, text):
    return fn(FakeProvider([text]), FACTS)


# ---- 지시문이 형식을 정한다

def test_지시문이_세_줄_머리말을_정한다():
    for head in ("권고:", "이유:", "주의:"):
        assert head in prompts.BRIEFING_SYSTEM
    for head in ("반대로 결정하려면:", "확인할 것:"):
        assert head in prompts.COUNTERPOINTS_SYSTEM
    for w in ("승인", "분할 승인", "거절", "위로 올리기", "120자"):
        assert w in prompts.BRIEFING_SYSTEM
    assert "내부 용어" in prompts.BRIEFING_SYSTEM


# ---- 진짜 모드: 응답 정리·실패 처리

def test_형식이_맞으면_그대로():
    r = ask(briefing, GOOD)
    assert r.ok and r.text == GOOD
    r2 = ask(counterpoints, GOOD2)
    assert r2.ok and r2.text == GOOD2


def test_순서가_뒤섞이면_순서대로_고친다():
    a, b, b2, c = GOOD.split("\n")
    assert ask(briefing, "\n".join([c, a, b, b2])).text == GOOD
    x, y = GOOD2.split("\n")
    assert ask(counterpoints, "\n".join([y, x])).text == GOOD2


def test_빈_줄과_목록_기호와_전각_쌍점은_정리한다():
    a, b, b2, c = GOOD.split("\n")
    messy = f"\n- {a}\n\n* {b.replace(':', '：')}\n{b2}\n{c}\n"
    assert ask(briefing, messy).text == GOOD


def test_머리말_없는_덧붙임_줄은_버린다():
    assert ask(briefing, GOOD + "\n덧붙임: 더 있어요.\n그리고 이 줄도요.").text == GOOD
    assert ask(counterpoints, GOOD2 + "\n하나 더요.").text == GOOD2


def test_머리말이_없으면_앞_네_줄에_붙인다():
    body = ["분할 승인을 권해요.", "집행일이 현금이 모자란 기간 안이에요.", "성과 순위가 낮아요.", "재고 회신을 기다리는 중이에요.", "다섯째 줄"]
    r = ask(briefing, "\n".join(body))
    assert r.ok and r.text == GOOD
    assert ask(counterpoints, "재고가 충분해야 해요.\n회신을 보세요.").text.startswith("반대로 결정하려면: 재고")


def test_긴_한_문단이나_줄이_모자라면_실패():
    for text in ("권고는 분할 승인이고 이유는 현금이 모자란 기간이며 주의할 것은 재고 회신입니다.",
                 "권고: 승인\n이유: 현금", "한 줄\n두 줄"):
        r = ask(briefing, text)
        assert (r.ok, r.text) == (False, FALLBACK_TEXT)
    assert ask(counterpoints, "한 줄뿐이에요.").ok is False


def test_머리말이_일부만_있으면_실패():
    r = ask(briefing, "권고: 승인을 권해요.\n이유: 지표가 좋아요.\n다른 말이에요.")
    assert r.ok is False
    r = ask(counterpoints, "반대로 결정하려면: 이런 근거가 필요해요.\n다른 말이에요.")
    assert r.ok is False


def test_머리말_뒤가_비면_실패():
    assert ask(briefing, "권고:\n이유: 지표가 좋아요.\n주의: 없어요.").ok is False


def test_내부_용어가_있으면_실패():
    a, b, b2, c = GOOD.split("\n")
    for bad in ("covenant 규정이에요.", "z=34.00이에요.", "설계 4장이에요.", "🔴 신호예요.",
                "coupon_stacking 신호예요."):
        assert ask(briefing, "\n".join([a, b, "이유: " + bad, c])).ok is False, bad


def test_평범한_낱말_판정은_막지_않는다():
    a, b, b2, c = GOOD.split("\n")
    assert ask(briefing, "\n".join([a, b, "이유: 규칙 판정과 지표가 같은 방향이에요.", c])).ok is True


def test_줄이_너무_길면_실패():
    long = "권고: " + "아주 긴 문장입니다 " * 12
    assert ask(briefing, "\n".join([long, *GOOD.split("\n")[1:]])).ok is False


def test_정리해도_실패하면_모델_이름은_남긴다():
    r = briefing(FakeProvider(["한 문단뿐"], model="m1"), FACTS)
    assert (r.ok, r.model) == (False, "m1")


# ---- 가짜 모드의 브리핑·반대 근거는 늘어난 형식으로 test_task37.py에서 확인한다

def test_가짜_모드_통보_초안은_짧은_통보문(monkeypatch):
    monkeypatch.delenv("AXWAR_AI", raising=False)
    contract = {"인플루언서": "혜인", "연 고정 값(원)": 2800000000, "성과 값 조건": "총매출의 5%",
                "계약 만료": "2026-08-31", "해지·조건변경 통보 기한": "2026-07-17"}
    proposal = {"fixed_fee_krw": 2800000000, "performance_base": "순액", "deductions": ["반품 환불", "쿠폰", "채널 수수료"]}
    r = notice_draft(make_provider("writer"), contract, proposal)
    assert r.ok and r.model == "fake"
    t = r.text
    assert not t.startswith("[시연용") and "계약 조건\n" not in t and "- 인플루언서" not in t
    assert "혜인" in t and "2,800,000,000" in t and "순액" in t
    for d in proposal["deductions"]:
        assert d in t
    assert "회신" in t and len(t) < 400
    assert t.count("\n") <= 6
