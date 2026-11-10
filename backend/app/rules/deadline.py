"""기한 판정(조기 경고와 기본 거부). 순수 함수, 원본 데이터를 읽지 않는다."""
from datetime import date, timedelta
from typing import Literal

from app import config


def deadline_actions(
    deadline: date,
    today: date,
    approved: bool,
    early_days: int | None = None,
) -> list[Literal["조기경고", "기본거부"]]:
    """승인되면 조치가 없다. 미승인이면 기한 전 early_days일부터 조기경고, 기한 당일과 이후는 기본거부.

    early_days가 None이면 호출 시점의 config.EARLY_WARNING_DAYS를 쓴다.
    """
    if approved:
        return []
    if early_days is None:
        early_days = config.EARLY_WARNING_DAYS
    if today >= deadline:
        return ["기본거부"]
    if today >= deadline - timedelta(days=early_days):
        return ["조기경고"]
    return []
