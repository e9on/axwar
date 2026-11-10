from datetime import date

from app.rules.deadline import deadline_actions

DEADLINE = date(2026, 7, 17)


def test_before_early_window_is_empty():
    assert deadline_actions(DEADLINE, date(2026, 7, 11), approved=False) == []


def test_early_window_start_unapproved_warns():
    assert deadline_actions(DEADLINE, date(2026, 7, 12), approved=False) == ["조기경고"]


def test_day_before_deadline_unapproved_warns():
    assert deadline_actions(DEADLINE, date(2026, 7, 16), approved=False) == ["조기경고"]


def test_deadline_day_unapproved_denies():
    assert deadline_actions(DEADLINE, date(2026, 7, 17), approved=False) == ["기본거부"]


def test_deadline_day_approved_is_empty():
    assert deadline_actions(DEADLINE, date(2026, 7, 17), approved=True) == []


def test_after_deadline_unapproved_denies():
    assert deadline_actions(DEADLINE, date(2026, 7, 18), approved=False) == ["기본거부"]
