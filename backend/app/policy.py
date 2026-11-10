"""정책 설정(policy.toml) 읽기와 검증. 규칙은 호출 시점에 get()으로 값을 읽는다.

AXWAR_POLICY_FILE 환경변수로 파일을 바꿀 수 있고, reload()로 다시 읽는다.
"""
import os
import tomllib
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "policy.toml"

# 키 -> (자료형, 양수 필요 여부)
_SCHEMA: dict[str, type] = {
    "approval.item_limit_krw": int,
    "approval.total_limit_krw": int,
    "approval.contract_limit_krw": int,
    "deadline.early_warning_days": int,
    "split.return_observe_days": int,
    "split.stop_z": float,
    "allocate.capacity_fallback_ratio": float,
    "cash.horizon_days": int,
}

_cache: dict[str, tuple] | None = None


def _path() -> Path:
    env = os.environ.get("AXWAR_POLICY_FILE")
    return Path(env) if env else DEFAULT_PATH


def _load() -> dict[str, tuple]:
    with open(_path(), "rb") as f:
        raw = tomllib.load(f)
    out: dict[str, tuple] = {}
    for key, typ in _SCHEMA.items():
        node = raw
        for part in key.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if not isinstance(node, dict):
            raise ValueError(f"정책 항목 누락: {key}")
        for field in ("value", "source", "description"):
            if field not in node:
                raise ValueError(f"정책 항목 {key}에 {field}가 없음")
        value = node["value"]
        ok = (isinstance(value, (int, float)) and not isinstance(value, bool)) if typ is float \
            else (isinstance(value, int) and not isinstance(value, bool))
        if not ok:
            raise ValueError(f"정책 항목 {key}의 값 형식 오류: {value!r}")
        if value <= 0:
            raise ValueError(f"정책 항목 {key}의 값은 양수여야 함: {value!r}")
        for field in ("source", "description"):
            if not isinstance(node[field], str) or not node[field].strip():
                raise ValueError(f"정책 항목 {key}의 {field}가 비어 있음")
        out[key] = (typ(value), node["source"], node["description"])
    return out


def _data() -> dict[str, tuple]:
    global _cache
    if _cache is None:
        _cache = _load()
    return _cache


def reload() -> None:
    global _cache
    _cache = None


def entry(key: str) -> tuple:
    data = _data()
    if key not in data:
        raise ValueError(f"알 수 없는 정책 항목: {key}")
    return data[key]


def get(key: str):
    return entry(key)[0]
