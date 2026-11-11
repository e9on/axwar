"""리뷰·회신 해석 시험. 실제 API는 부르지 않고 FakeProvider만 쓴다."""
import json
import sys
from datetime import date
from pathlib import Path

import pytest

from app.ai import judge, prompts
from app.ai.judge import interpret_reply, interpret_review
from app.ai.providers import BudgetExceeded, Completion, FakeProvider

REPO = Path(__file__).resolve().parents[2]
TODAY = date(2030, 3, 4)


def review_json(**kw):
    d = {"reason": "색상불일치", "sentiment": "부정", "content_gap": True, "confidence": 0.9}
    d.update(kw)
    return json.dumps(d, ensure_ascii=False)


def reply_json(**kw):
    d = {"stance": "조건부수용", "qty_limit": 1800, "next_date": "2026-08-19", "needs_human": False,
         "confidence": 0.9}
    d.update(kw)
    return json.dumps(d, ensure_ascii=False)


def reply(text, **kw):
    return interpret_reply(FakeProvider([text]), "물류", "요청", "회신", TODAY, **kw)


class Stub:
    model = "stub"

    def __init__(self, c: Completion):
        self.c = c

    def complete(self, system, user):
        return self.c


# ---- 리뷰 ----

def test_정상_리뷰_해석():
    j = interpret_review(FakeProvider([review_json()]), "립틴트", "색이 영상이랑 달라요")
    assert (j.reason, j.sentiment, j.content_gap, j.confidence) == ("색상불일치", "부정", True, 0.9)
    assert j.needs_human is False
    assert j.model == "fake"


def test_확신도는_판정에_쓰지_않는다():
    j = interpret_review(FakeProvider([review_json(confidence=0.5)]), "p", "t")
    assert j.needs_human is False
    assert j.confidence == 0.5


def test_JSON이_아니면_사람확인():
    j = interpret_review(FakeProvider(["모르겠어요"]), "p", "t")
    assert j.needs_human is True
    assert j.reason == "기타"
    assert j.raw == "모르겠어요"


def test_허용값_밖이면_사람확인():
    j = interpret_review(FakeProvider([review_json(reason="짜증")]), "p", "t")
    assert j.needs_human is True


def test_감정이_허용값_밖이어도_사람확인():
    assert interpret_review(FakeProvider([review_json(sentiment="화남")]), "p", "t").needs_human is True


def test_제공자_예외면_사람확인():
    j = interpret_review(FakeProvider([TimeoutError("시간 초과")]), "p", "t")
    assert j.needs_human is True
    assert j.reason == "기타"


def test_예외의_raw에는_예외_종류만_남는다():
    j = interpret_review(FakeProvider([RuntimeError("sk-비밀키 요청본문")]), "p", "t")
    assert j.raw == "RuntimeError"


def test_한도_도달이면_고정_문구():
    j = interpret_review(FakeProvider([BudgetExceeded("x")]), "p", "t")
    assert j.needs_human is True
    assert j.raw == "AI 사용 한도 도달"


def test_잘리면_사람확인():
    c = Completion(review_json(), 10, 10, "stub", "max_tokens")
    j = interpret_review(Stub(c), "p", "t")
    assert j.needs_human is True
    assert j.raw == c.text


def test_리뷰_지시문에_상품과_본문이_들어간다():
    p = FakeProvider([review_json()])
    interpret_review(p, "립틴트", "색이 달라요")
    assert "립틴트" in p.calls[0][1] and "색이 달라요" in p.calls[0][1]
    assert p.calls[0][0] == prompts.REVIEW_SYSTEM


def test_모델_이름은_응답을_낸_모델():
    c = Completion(review_json(), 1, 1, "백업모델")
    assert interpret_review(Stub(c), "p", "t").model == "백업모델"


# ---- 회신 ----

def test_회신_분할():
    j = reply(reply_json())
    assert j.qty_limit == 1800
    assert j.next_date == date(2026, 8, 19)
    assert j.stance == "조건부수용"
    assert j.needs_human is False


def test_거절이면_사람확인():
    j = reply(reply_json(stance="거절", qty_limit=None, next_date=None, needs_human=False))
    assert j.needs_human is True


def test_정보부족이면_사람확인():
    assert reply(reply_json(stance="정보부족", needs_human=False)).needs_human is True


def test_모델이_사람확인을_요청하면_따른다():
    assert reply(reply_json(needs_human=True)).needs_human is True


def test_회신_확신도는_판정에_쓰지_않는다():
    j = reply(reply_json(confidence=0.1))
    assert j.needs_human is False and j.confidence == 0.1


def test_회신_JSON이_아니면_사람확인():
    j = reply("모르겠어요")
    assert j.needs_human is True and j.stance == "정보부족"


def test_회신_허용값_밖이면_사람확인():
    assert reply(reply_json(stance="아마도")).needs_human is True


def test_수량이_숫자가_아니면_사람확인():
    j = reply(reply_json(qty_limit="많이"))
    assert j.needs_human is True and j.qty_limit is None


def test_날짜가_형식에_맞지_않으면_사람확인():
    j = reply(reply_json(next_date="9월 초"))
    assert j.needs_human is True and j.next_date is None


def test_수량_쉼표와_문자열_숫자를_받아들인다():
    assert reply(reply_json(qty_limit="1,800")).qty_limit == 1800


def test_회신_제공자_예외면_사람확인():
    j = reply_with_exc(TimeoutError("x"))
    assert j.needs_human is True and j.raw == "TimeoutError"


def reply_with_exc(e):
    return interpret_reply(FakeProvider([e]), "d", "r", "p", TODAY)


def test_회신_한도_도달():
    j = reply_with_exc(BudgetExceeded("x"))
    assert j.raw == "AI 사용 한도 도달" and j.needs_human is True


def test_회신_잘리면_사람확인():
    j = interpret_reply(Stub(Completion(reply_json(), 1, 1, "stub", "max_tokens")), "d", "r", "p", TODAY)
    assert j.needs_human is True


def test_회신_지시문에_기준일이_들어간다():
    p = FakeProvider([reply_json()])
    interpret_reply(p, "물류", "요청", "회신", TODAY)
    assert "기준일은 2030-03-04다" in p.calls[0][0]
    assert "2026년" not in p.calls[0][0]
    assert "물류" in p.calls[0][1] and "요청" in p.calls[0][1] and "회신" in p.calls[0][1]


def test_기준일이_바뀌면_지시문도_바뀐다():
    assert prompts.reply_system(date(2031, 1, 2)) != prompts.reply_system(TODAY)


def test_회신_지시문에_위험경고_전량가능_규칙이_있다():
    assert "위험 경고만 붙은" in prompts.reply_system(TODAY)


# ---- 파싱 규칙은 eval과 공유 ----

def test_eval이_judge의_파싱_규칙을_쓴다():
    sys.path.insert(0, str(REPO / "eval"))
    import score
    assert score.norm is judge.norm
    assert score.ALLOWED is judge.ALLOWED


def test_parse는_앞뒤_글이_있어도_JSON을_찾는다():
    assert judge.parse('설명 {"a": 1} 끝') == {"a": 1}
    assert judge.parse("없음") is None
    assert judge.parse("{깨진") is None
    assert judge.parse(None) is None


# ---- 수정 회차 1 ----

@pytest.mark.parametrize("raw_qty", ["Infinity", "-Infinity", "NaN", "1e999", '"inf"', '"nan"'])
def test_수량이_무한대나_NaN이어도_예외없이_사람확인(raw_qty):
    text = '{"stance":"조건부수용","qty_limit":%s,"next_date":null,"needs_human":false}' % raw_qty
    j = reply(text)
    assert j.needs_human is True and j.qty_limit is None


@pytest.mark.parametrize("bad", ['"가끔"', "1", "null", '"maybe"'])
def test_content_gap이_불리언이_아니면_사람확인(bad):
    text = '{"reason":"만족","sentiment":"긍정","content_gap":%s}' % bad
    assert interpret_review(FakeProvider([text]), "p", "t").needs_human is True


def test_content_gap이_없어도_사람확인():
    text = '{"reason":"만족","sentiment":"긍정"}'
    assert interpret_review(FakeProvider([text]), "p", "t").needs_human is True


def test_content_gap_문자열_true_false는_받아들인다():
    for s, want in (('"true"', True), ('"false"', False), ("false", False)):
        text = '{"reason":"만족","sentiment":"긍정","content_gap":%s}' % s
        j = interpret_review(FakeProvider([text]), "p", "t")
        assert j.content_gap is want and j.needs_human is False
