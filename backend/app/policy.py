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
    "deadline.buffer_days": int,
    "escalation.after_days": int,
    "split.return_observe_days": int,
    "split.stop_z": float,
    "split.sellthrough_hold_ratio": float,
    "allocate.capacity_fallback_ratio": float,
    "cash.horizon_days": int,
    "signals.return_ratio_red": float,
    "signals.hhi_limit": int,
    "volume.low_confidence_share": float,
    "scm.stockout_loss_pct": float,
    "scm.no_reply_days": int,
    "capacity.label_span_chars": int,
    "ai.total_cap_usd": float,
    "ai.daily_cap_usd": float,
    "ai.max_tokens": int,
    "ai.reservation_stale_seconds": int,
    "ai.effort": str,
    "ai.anthropic_version": str,
    "ai.review_model": str,
    "ai.review_backup": str,
    "ai.reply_model": str,
    "ai.reply_backup": str,
    "ai.writer_model": str,
    "ai.writer_backup": str,
    "admin.policy_editors": str,
    "admin.review_inputters": str,
    "admin.return_inputters": str,
    "admin.registry_editors": str,
    "phase2.min_approval_days": int,
    "roles.campaign": str,
    "roles.contract": str,
    "roles.logistics": str,
    "roles.cs": str,
    "volume.input_lead_days": int,
}

# 0 초과 1 이하여야 하는 비율 항목(1.5 같은 값이 들어가면 규칙이 거꾸로 동작한다)
_RATIO_KEYS = ("split.sellthrough_hold_ratio", "allocate.capacity_fallback_ratio", "volume.low_confidence_share",
               "scm.stockout_loss_pct")

# 배정 모델 항목: 값이 모델 단가표에 있어야 한다
_MODEL_KEYS = [k for k in _SCHEMA if k.startswith("ai.") and (k.endswith("_model") or k.endswith("_backup"))]

# 설정 화면 덮어쓰기: 키 -> (값, 바꾼 사람, 시각). 정책 파일은 고치지 않는다.
_overrides: dict[str, tuple] = {}
_cache: dict[str, tuple] | None = None
_base: dict[str, tuple] | None = None  # 파일 값(덮어쓰기 적용 전): 출처·설명을 화면에 그대로 보이기 위해
_models: dict[str, tuple] | None = None


def _path() -> Path:
    env = os.environ.get("AXWAR_POLICY_FILE")
    return Path(env) if env else DEFAULT_PATH


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_value(key: str, typ: type, value):
    """항목 하나의 값 검증(형식·양수·빈 문자열). 통과한 값을 자료형에 맞춰 돌려준다."""
    if typ is str:
        if not isinstance(value, str):
            raise ValueError(f"정책 항목 {key}의 값 형식 오류: {value!r}")
        if not value.strip():
            raise ValueError(f"정책 항목 {key}의 값이 비어 있음")
        return value
    ok = _is_number(value) if typ is float else (isinstance(value, int) and not isinstance(value, bool))
    if not ok:
        raise ValueError(f"정책 항목 {key}의 값 형식 오류: {value!r}")
    if value <= 0:
        raise ValueError(f"정책 항목 {key}의 값은 양수여야 함: {value!r}")
    if key in _RATIO_KEYS and value > 1:
        raise ValueError(f"정책 항목 {key}는 비율이라 1 이하여야 함: {value!r}")
    return typ(value)


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
        value = _check_value(key, typ, node["value"])
        for field in ("source", "description"):
            if not isinstance(node[field], str) or not node[field].strip():
                raise ValueError(f"정책 항목 {key}의 {field}가 비어 있음")
        out[key] = (value, node["source"], node["description"])
    models = _load_models(raw)
    for key in _MODEL_KEYS:
        if out[key][0] not in models:
            raise ValueError(f"정책 항목 {key}의 모델 {out[key][0]!r}이 단가표(ai.models)에 없음")
    return out, models


def _apply(key: str, item: tuple) -> tuple:
    if key not in _overrides:
        return item
    value, actor, at = _overrides[key]
    return (value, f"설정 화면 변경: {actor} {at}", item[2])


def _data() -> dict[str, tuple]:
    global _cache, _models, _base
    if _cache is None:
        loaded, _models = _load()
        _base = loaded
        _cache = {k: _apply(k, v) for k, v in loaded.items()}
    return _cache


def reload() -> None:
    global _cache, _models, _base
    _cache = _models = _base = None


def keys() -> list[str]:
    """정책 항목 키 전부(파일에 적힌 순서와 상관없이 스키마 순서)."""
    return list(_data())


def base_entry(key: str) -> tuple:
    """덮어쓰기를 적용하기 전의 파일 항목 (값, 출처, 설명). 출처가 "가정"인지 보려면 이것을 쓴다."""
    _data()
    if key not in _base:
        raise ValueError(f"알 수 없는 정책 항목: {key}")
    return _base[key]


def is_overridden(key: str) -> bool:
    _data()
    return key in _overrides


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


def validate(key: str, value):
    """설정 화면에서 받은 새 값을 검증한다(같은 자료형·양수·비어 있지 않은 문자열, 모델은 단가표에 있어야 함).

    통과하면 자료형에 맞춘 값을 돌려주고, 아니면 ValueError.
    """
    _data()
    if key not in _SCHEMA:
        raise ValueError(f"알 수 없는 정책 항목: {key}")
    checked = _check_value(key, _SCHEMA[key], value)
    if key in _MODEL_KEYS and checked not in _models:
        raise ValueError(f"정책 항목 {key}의 모델 {checked!r}이 단가표(ai.models)에 없음")
    return checked


def set_overrides(overrides: dict[str, tuple]) -> None:
    """파일 값 위에 덮어쓸 값들(키 -> (값, 바꾼 사람, 시각))로 통째로 바꾼다. 각 값은 validate를 통과해야 한다."""
    global _cache
    checked = {k: (validate(k, v[0]), v[1], v[2]) for k, v in overrides.items()}
    _overrides.clear()
    _overrides.update(checked)
    _cache = None


def clear_overrides() -> None:
    set_overrides({})
