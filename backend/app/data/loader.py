"""원본 CSV(`|` 구분, `NONE`은 값 없음)를 읽기 전용으로 불러온다."""
import csv
import re
from datetime import date
from functools import lru_cache

from app.config import DATA_ROOT

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_INT = re.compile(r"-?\d+")
_FLOAT = re.compile(r"-?\d+\.\d+")


def _convert(value: str):
    v = value.strip()
    if v == "" or v == "NONE":
        return None
    if v == "True":
        return True
    if v == "False":
        return False
    if _INT.fullmatch(v):
        return int(v)
    if _FLOAT.fullmatch(v):
        return float(v)
    if _DATE.fullmatch(v):
        try:
            return date.fromisoformat(v)
        except ValueError:
            return v
    return v


@lru_cache(maxsize=None)
def _read(root: str, rel_path: str) -> tuple:
    with open(f"{root}/{rel_path}", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter="|")
        return tuple({k: _convert(v) for k, v in row.items()} for row in reader)


def read_table(rel_path: str) -> list[dict]:
    """캐시된 결과의 복사본을 돌려준다(호출자가 바꿔도 캐시는 안전)."""
    return [dict(r) for r in _read(str(DATA_ROOT), rel_path)]
