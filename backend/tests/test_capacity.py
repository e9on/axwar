"""물류 회신 문장에서 처리 능력 숫자(평소·최대)를 뽑는 규칙. 순수 함수."""
import pytest

from app.rules.capacity import parse_capacity


@pytest.mark.parametrize("text,expected", [
    ("평소 하루 20,000개, 최대 26,000개", (20000, 26000)),
    ("하루 최대 26,000개까지, 평소에는 20,000개 처리합니다", (20000, 26000)),
    ("안정적으로는 18000개, 야근하면 24000개 가능", (18000, 24000)),
    ("최대 26,000개 가능합니다", (None, 26000)),
    ("평소 20,000개 처리합니다", (20000, None)),
    ("전량 가능합니다. 집행일부터 평소 처리량 안에서 출고할 수 있습니다.", (None, None)),
    ("", (None, None)),
])
def test_처리능력_숫자_추출(text, expected):
    assert parse_capacity(text) == expected


def test_평소가_최대보다_크면_뒤바뀐_것으로_보고_추출하지_않는다():
    assert parse_capacity("평소 30,000개, 최대 20,000개") == (None, None)


def test_평소_뒤에_숫자가_없으면_최대의_숫자를_평소로_읽지_않는다():
    assert parse_capacity("평소 처리량 내, 최대 26,000개") == (None, 26000)


def test_이름표와_숫자_사이_허용_글자수는_정책값():
    from app import policy

    text = "평소 처리량은 보통 아침 점심 저녁 가리지 않고 20,000개"
    assert policy.entry("capacity.label_span_chars")[1].startswith("가정")
    policy.set_overrides({"capacity.label_span_chars": (60, "시험", "2030-01-01")})
    assert parse_capacity(text) == (20000, None)
    policy.set_overrides({"capacity.label_span_chars": (4, "시험", "2030-01-01")})
    assert parse_capacity(text) == (None, None)
