"""결재권자 브리핑·반대 근거·조건변경 통보 초안 시험. 실제 API는 부르지 않는다."""
import pytest

from app.ai import prompts, writer
from app.ai.providers import BudgetExceeded, Completion, FakeProvider
from app.ai.writer import FALLBACK_TEXT, AiText, briefing, counterpoints, notice_draft

FACTS = {"건": "2차 집행", "순매출(원)": 18962703, "기한": "7/27", "판정": "승인 가능"}
OK3 = "권고: 승인을 권해요.\n이유: 지표가 좋아요.\n주의: 회신을 기다려요."
OK2 = "반대로 결정하려면: 재고가 충분해야 해요.\n확인할 것: 회신을 보세요."
CONTRACT = {"influencer": "혜인", "fee_krw": 5000000}
PROPOSAL = {"fixed_fee_krw": 3200000, "performance_base": "순액", "deductions": ["반품 환불", "쿠폰", "채널 수수료"]}


class Stub:
    model = "stub"

    def __init__(self, c: Completion):
        self.c = c

    def complete(self, system, user):
        return self.c


def test_지시문에_사실이_들어간다():
    p = FakeProvider(["요약입니다"])
    briefing(p, FACTS)
    user = p.calls[0][1]
    assert "18,962,703" in user and "7/27" in user


def test_통보초안_지시문에_순액기준이_들어간다():
    p = FakeProvider(["초안"])
    notice_draft(p, CONTRACT, PROPOSAL)
    user = p.calls[0][1]
    assert "순액" in user and "3,200,000" in user
    for d in PROPOSAL["deductions"]:
        assert d in user
    assert "5,000,000" in user


def test_실패하면_대체문구():
    for exc in (RuntimeError("x"), BudgetExceeded("한도")):
        r = briefing(FakeProvider([exc]), FACTS)
        assert r.ok is False and r.text == FALLBACK_TEXT


def test_대체문구는_정해진_문장():
    assert FALLBACK_TEXT == "AI 의견을 만들지 못했어요. 규칙으로 정한 결과만 보여요."


def test_결과에_모델이름이_남는다():
    r = counterpoints(FakeProvider([OK2], model="m1"), FACTS)
    assert r == AiText(OK2, "m1", True)


def test_빈_응답이면_대체문구():
    r = briefing(FakeProvider(["  \n"]), FACTS)
    assert (r.ok, r.text) == (False, FALLBACK_TEXT)


def test_잘리면_대체문구():
    r = briefing(Stub(Completion("중간까지", 1, 1, "stub", "max_tokens")), FACTS)
    assert (r.ok, r.text) == (False, FALLBACK_TEXT)


def test_사실에_없는_숫자가_나오면_대체문구():
    r = briefing(FakeProvider(["권고: 승인을 권해요.\n이유: 순매출은 19,000,000원이에요.\n주의: 회신을 기다려요."]), FACTS)
    assert (r.ok, r.text) == (False, FALLBACK_TEXT)


def test_사실에_있는_숫자는_쉼표_유무와_상관없이_통과():
    assert briefing(FakeProvider(["권고: 승인을 권해요.\n이유: 순매출 18962703원이에요.\n주의: 회신을 기다려요."]), FACTS).ok is True
    assert briefing(FakeProvider(["권고: 승인을 권해요.\n이유: 순매출 18,962,703원, 기한 7/27이에요.\n주의: 회신을 기다려요."]), FACTS).ok is True


def test_두_자리_이하_숫자는_검사하지_않는다():
    assert briefing(FakeProvider(["권고: 승인을 권해요.\n이유: 2차 집행 건, 3가지 근거예요.\n주의: 회신을 기다려요."]), FACTS).ok is True


def test_통보초안도_입력에_없는_금액이면_대체문구():
    assert notice_draft(FakeProvider(["고정 피 9,999,000원"]), CONTRACT, PROPOSAL).ok is False
    assert notice_draft(FakeProvider(["고정 피 3,200,000원"]), CONTRACT, PROPOSAL).ok is True


def test_지시문_세개는_숫자를_만들지_말라고_한다():
    for s in (prompts.BRIEFING_SYSTEM, prompts.COUNTERPOINTS_SYSTEM, prompts.NOTICE_SYSTEM):
        assert "주어진 숫자만" in s and "한국어" in s


def test_제공자에_맞는_지시문이_전달된다():
    p = FakeProvider(["a", "b", "c"])
    briefing(p, FACTS); counterpoints(p, FACTS); notice_draft(p, CONTRACT, PROPOSAL)
    assert [c[0] for c in p.calls] == [prompts.BRIEFING_SYSTEM, prompts.COUNTERPOINTS_SYSTEM, prompts.NOTICE_SYSTEM]


def test_fake_모드_글쓰기는_키없이_돈다(monkeypatch):
    from app.ai.providers import make_provider
    monkeypatch.delenv("AXWAR_AI", raising=False)
    assert briefing(make_provider("writer"), FACTS).ok is True


def test_소수_사실은_반올림하지_않고_그대로_넘긴다():
    p = FakeProvider(["요약"])
    briefing(p, {"재구매율": 0.085, "손익분기 숨은 매출 비율": 0.247})
    user = p.calls[0][1]
    assert "0.085" in user and "0.247" in user


def test_글쓰기_결과는_장부_행_ID를_싣는다():
    class P:
        model = "m"

        def complete(self, system, user):
            return Completion(OK3, 1, 1, "m", ledger_id=9)

    assert briefing(P(), FACTS).ledger_id == 9
    assert briefing(FakeProvider([OK3]), FACTS).ledger_id is None
    assert briefing(FakeProvider([RuntimeError("x")]), FACTS).ledger_id is None
