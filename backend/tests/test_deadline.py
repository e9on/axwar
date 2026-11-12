"""기한 판정. 기본 거부는 기한 - buffer_days일 아침, 승인은 그 전날까지, 조기 경고는 기본 거부 실행일 기준."""
from datetime import date

from app import policy
from app.rules.deadline import approval_deadline, deadline_actions, deny_date, is_lapsed

DEADLINE = date(2026, 7, 17)  # 기본 거부 7/14, 승인 마감 7/13, 조기 경고 7/9~


def test_정책_여유일은_3일이고_출처가_사용자_지정이다():
    assert policy.get("deadline.buffer_days") == 3
    assert policy.base_entry("deadline.buffer_days")[1].startswith("사용자 지정")


def test_기본_거부_실행일과_승인_마감일():
    assert deny_date(DEADLINE) == date(2026, 7, 14)
    assert approval_deadline(DEADLINE) == date(2026, 7, 13)
    assert deny_date(DEADLINE, 0) == DEADLINE and deny_date(DEADLINE, 1) == date(2026, 7, 16)


def test_승인은_마감일까지_실행일_당일부터_거부():
    assert not is_lapsed(DEADLINE, date(2026, 7, 13))
    assert is_lapsed(DEADLINE, date(2026, 7, 14))
    assert is_lapsed(DEADLINE, date(2026, 7, 17))


def test_before_early_window_is_empty():
    assert deadline_actions(DEADLINE, date(2026, 7, 8), approved=False) == []


def test_조기_경고는_기본_거부_실행일_기준으로_센다():
    assert deadline_actions(DEADLINE, date(2026, 7, 9), approved=False) == ["조기경고"]  # 7/14 - 5일
    assert deadline_actions(DEADLINE, date(2026, 7, 13), approved=False) == ["조기경고"]


def test_기본_거부_실행일_미승인이면_기본거부():
    assert deadline_actions(DEADLINE, date(2026, 7, 14), approved=False) == ["기본거부"]
    assert deadline_actions(DEADLINE, date(2026, 7, 16), approved=False) == ["기본거부"]


def test_기한_당일도_미승인이면_기본거부():
    assert deadline_actions(DEADLINE, date(2026, 7, 17), approved=False) == ["기본거부"]


def test_approved_is_empty_on_every_day():
    for d in (date(2026, 7, 9), date(2026, 7, 14), date(2026, 7, 17), date(2026, 7, 20)):
        assert deadline_actions(DEADLINE, d, approved=True) == []


def test_after_deadline_unapproved_denies():
    assert deadline_actions(DEADLINE, date(2026, 7, 18), approved=False) == ["기본거부"]


def test_여유일_정책을_바꾸면_같이_움직인다():
    policy.set_overrides({"deadline.buffer_days": (1, "시험", "t")})
    assert deny_date(DEADLINE) == date(2026, 7, 16)
    assert deadline_actions(DEADLINE, date(2026, 7, 15), approved=False) == ["조기경고"]
