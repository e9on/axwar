"""기한 판정(조기 경고와 기본 거부). 순수 함수, 원본 데이터를 읽지 않는다.

1차(확정·통보 기한)·2차(집행일)·결정 입구·일일 점검이 모두 이 모듈의 같은 규칙을 쓴다.
기본 거부는 기한 당일이 아니라 기한 - deadline.buffer_days일 아침에 실행한다(상대에게 여유를 주려고).
승인·상신은 그 전날까지 받고, 실행일 당일부터는 받지 않는다.
"""
from datetime import date, timedelta
from typing import Literal

from app import policy


def deny_date(deadline: date, buffer_days: int | None = None) -> date:
    """기본 거부 실행일 = 기한 - buffer_days(그날 아침 일일 점검). buffer_days가 None이면 정책 값."""
    if buffer_days is None:
        buffer_days = policy.get("deadline.buffer_days")
    return deadline - timedelta(days=buffer_days)


def approval_deadline(deadline: date, buffer_days: int | None = None) -> date:
    """마지막 승인일 = 기본 거부 실행일 - 1일(그날까지 승인·상신 가능, 이날 남은 승인권자에게 알림)."""
    return deny_date(deadline, buffer_days) - timedelta(days=1)


def is_lapsed(deadline: date, today: date) -> bool:
    """오늘이 기본 거부 실행일이거나 그 뒤면 True(승인·상신을 더 받지 않는다)."""
    return today >= deny_date(deadline)


def deadline_actions(
    deadline: date,
    today: date,
    approved: bool,
    early_days: int | None = None,
) -> list[Literal["조기경고", "기본거부"]]:
    """승인되면 조치가 없다. 미승인이면 기본 거부 실행일 전 early_days일부터 조기경고, 실행일과 이후는 기본거부.

    early_days가 None이면 호출 시점의 policy.get("deadline.early_warning_days")를 쓴다.
    """
    if approved:
        return []
    if early_days is None:
        early_days = policy.get("deadline.early_warning_days")
    run = deny_date(deadline)
    if today >= run:
        return ["기본거부"]
    if today >= run - timedelta(days=early_days):
        return ["조기경고"]
    return []
