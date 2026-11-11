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
    "signals.return_ratio_red": float,
    "signals.hhi_limit": int,
    "volume.low_confidence_share": float,
    "ai.total_cap_usd": float,
    "ai.daily_cap_usd": float,
    "ai.max_tokens": int,
    "ai.effort": str,
    "ai.anthropic_version": str,
    "ai.review_model": str,
    "ai.review_backup": str,
    "ai.reply_model": str,
    "ai.reply_backup": str,
    "ai.writer_model": str,
    "ai.writer_backup": str,
}

# 배정 모델 항목: 값이 모델 단가표에 있어야 한다
_MODEL_KEYS = [k for k in _SCHEMA if k.startswith("ai.") and (k.endswith("_model") or k.endswith("_backup"))]

_cache: dict[str, tuple] | None = None
_models: dict[str, tuple] | None = None


def _path() -> Path:
    env = os.environ.get("AXWAR_POLICY_FILE")
    return Path(env) if env else DEFAULT_PATH


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _load_models(raw: dict) -> dict[str, tuple]:
    """모델 단가표: 모델 -> (제공자, 입력 USD/100만 토큰, 출력 USD/100만 토큰)."""
    table = raw.get("ai", {}).get("models") if isinstance(raw.get("ai"), dict) else None
    if not isinstance(table, dict) or not table:
        raise ValueError("정책 항목 누락: ai.models")
    out: dict[str, tuple] = {}
    for name, node in table.items():
        if not isinstance(node, dict):
            raise ValueError(f"정책 항목 ai.models.{name} 형식 오류")
        for field in ("provider", "in_usd_per_mtok", "out_usd_per_mtok", "source"):
            if field not in node:
                raise ValueError(f"정책 항목 ai.models.{name}에 {field}가 없음")
        for field in ("provider", "source"):
            if not isinstance(node[field], str) or not node[field].strip():
                raise ValueError(f"정책 항목 ai.models.{name}의 {field}가 비어 있음")
        for field in ("in_usd_per_mtok", "out_usd_per_mtok"):
            if not _is_number(node[field]) or node[field] <= 0:
                raise ValueError(f"정책 항목 ai.models.{name}의 {field}는 양수여야 함: {node[field]!r}")
        out[name] = (node["provider"], float(node["in_usd_per_mtok"]), float(node["out_usd_per_mtok"]))
    return out


def _load() -> tuple[dict[str, tuple], dict[str, tuple]]:
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
        if typ is str:
            if not isinstance(value, str):
                raise ValueError(f"정책 항목 {key}의 값 형식 오류: {value!r}")
            if not value.strip():
                raise ValueError(f"정책 항목 {key}의 값이 비어 있음")
        else:
            ok = _is_number(value) if typ is float else (isinstance(value, int) and not isinstance(value, bool))
            if not ok:
                raise ValueError(f"정책 항목 {key}의 값 형식 오류: {value!r}")
            if value <= 0:
                raise ValueError(f"정책 항목 {key}의 값은 양수여야 함: {value!r}")
        for field in ("source", "description"):
            if not isinstance(node[field], str) or not node[field].strip():
                raise ValueError(f"정책 항목 {key}의 {field}가 비어 있음")
        out[key] = (typ(value), node["source"], node["description"])
    models = _load_models(raw)
    for key in _MODEL_KEYS:
        if out[key][0] not in models:
            raise ValueError(f"정책 항목 {key}의 모델 {out[key][0]!r}이 단가표(ai.models)에 없음")
    return out, models


def _data() -> dict[str, tuple]:
    global _cache, _models
    if _cache is None:
        _cache, _models = _load()
    return _cache


def reload() -> None:
    global _cache, _models
    _cache = _models = None


def model_names() -> list[str]:
    _data()
    return list(_models)


def model_price(model: str) -> tuple[str, float, float]:
    """모델의 (제공자, 입력 단가, 출력 단가). 단가는 100만 토큰당 USD. 모르는 모델이면 오류."""
    _data()
    if model not in _models:
        raise ValueError(f"단가표에 없는 모델: {model}")
    return _models[model]


def entry(key: str) -> tuple:
    data = _data()
    if key not in data:
        raise ValueError(f"알 수 없는 정책 항목: {key}")
    return data[key]


def get(key: str):
    return entry(key)[0]
