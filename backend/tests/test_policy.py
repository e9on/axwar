from datetime import date

import pytest

from app import config, policy
from app.rules.approver import decide_plan
from app.rules.deadline import deadline_actions
from app.rules.models import PlanFacts

POLICY_DOC = config.data_root() / "00_common" / "approval_authority_policy.md"
KEYS = [
    "approval.item_limit_krw", "approval.total_limit_krw", "approval.contract_limit_krw",
    "deadline.early_warning_days", "split.return_observe_days", "split.stop_z",
    "allocate.capacity_fallback_ratio", "cash.horizon_days",
    "signals.return_ratio_red", "signals.hhi_limit", "volume.low_confidence_share",
]


@pytest.fixture(autouse=True)
def _restore(monkeypatch):
    yield
    monkeypatch.undo()
    policy.reload()


def use_file(monkeypatch, tmp_path, text):
    f = tmp_path / "p.toml"
    f.write_text(text, encoding="utf-8")
    monkeypatch.setenv("AXWAR_POLICY_FILE", str(f))
    policy.reload()


def default_text():
    return policy.DEFAULT_PATH.read_text(encoding="utf-8")


def plan(amount, total=1_000_000):
    return PlanFacts(plan_id="P", campaign_id="C", influencer_id="I", deadline=date(2030, 1, 1),
                     amount_krw=amount, plan_total_krw=total, settlement_date=date(2030, 1, 1),
                     direction="확대", indicator_good=True)


def test_정책_문서와_설정_금액이_일치():
    doc = POLICY_DOC.read_text(encoding="utf-8")
    for word, key, value in (
        ("1천만원", "approval.item_limit_krw", 10_000_000),
        ("1억원", "approval.total_limit_krw", 100_000_000),
        ("10억원", "approval.contract_limit_krw", 1_000_000_000),
    ):
        assert word in doc
        assert policy.get(key) == value


def test_모든_항목에_출처와_설명():
    for k in KEYS:
        value, source, desc = policy.entry(k)
        assert source.strip() and desc.strip()
        assert policy.get(k) == value


def test_건별_기준을_바꾸면_판정이_바뀐다(monkeypatch, tmp_path):
    assert decide_plan(plan(9_000_000), []).approvers == ("마케팅팀",)
    text = default_text().replace("value = 10000000\n", "value = 5000000\n", 1)
    use_file(monkeypatch, tmp_path, text)
    d = decide_plan(plan(9_000_000), [])
    assert d.approvers == ("Masil 대표", "그룹 보고")
    assert "500만원" in d.hits[0].text


def test_조기경고_일수를_바꾸면_판정이_바뀐다(monkeypatch, tmp_path):
    dl = date(2030, 1, 10)
    assert deadline_actions(dl, date(2030, 1, 6), approved=False) == ["조기경고"]
    text = default_text().replace("value = 5\n", "value = 3\n", 1)
    use_file(monkeypatch, tmp_path, text)
    assert deadline_actions(dl, date(2030, 1, 6), approved=False) == []


def test_필수_항목_누락은_항목_이름을_담은_오류(monkeypatch, tmp_path):
    use_file(monkeypatch, tmp_path, "")
    with pytest.raises(ValueError, match="approval.item_limit_krw"):
        policy.get("approval.item_limit_krw")


def test_음수는_오류(monkeypatch, tmp_path):
    text = default_text().replace("value = 10000000\n", "value = -1\n", 1)
    use_file(monkeypatch, tmp_path, text)
    with pytest.raises(ValueError, match="approval.item_limit_krw"):
        policy.get("approval.item_limit_krw")


def test_타입_오류는_오류(monkeypatch, tmp_path):
    text = default_text().replace("value = 10000000\n", 'value = "많음"\n', 1)
    use_file(monkeypatch, tmp_path, text)
    with pytest.raises(ValueError, match="approval.item_limit_krw"):
        policy.get("approval.item_limit_krw")


def test_코드에_정책_상수가_남아있지_않다():
    for name in ("ITEM_LIMIT_KRW", "TOTAL_LIMIT_KRW", "CONTRACT_LIMIT_KRW", "EARLY_WARNING_DAYS",
                 "RETURN_OBSERVE_DAYS", "STOP_Z", "CAPACITY_FALLBACK_RATIO"):
        assert not hasattr(config, name)


# ---- AI 설정 ----

AI_KEYS = ["ai.total_cap_usd", "ai.daily_cap_usd", "ai.max_tokens", "ai.effort", "ai.anthropic_version",
           "ai.review_model", "ai.review_backup", "ai.reply_model", "ai.reply_backup",
           "ai.writer_model", "ai.writer_backup"]


def test_AI_항목에도_출처와_설명():
    for k in AI_KEYS:
        value, source, desc = policy.entry(k)
        assert source.strip() and desc.strip() and value


def test_AI_값_형식():
    assert isinstance(policy.get("ai.total_cap_usd"), float) and policy.get("ai.total_cap_usd") > 0
    assert policy.get("ai.daily_cap_usd") < policy.get("ai.total_cap_usd")
    assert isinstance(policy.get("ai.max_tokens"), int)
    assert isinstance(policy.get("ai.effort"), str)


def test_배정_모델은_모두_단가표에_있다():
    for k in AI_KEYS:
        if k.endswith("_model") or k.endswith("_backup"):
            policy.model_price(policy.get(k))


def test_단가표는_제공자와_단가를_돌려준다():
    provider, pin, pout = policy.model_price("claude-haiku-5-5")
    assert provider == "anthropic" and pin < pout


def test_모르는_모델의_단가는_오류():
    with pytest.raises(ValueError, match="없는모델"):
        policy.model_price("없는모델")


def test_문자열_항목이_비면_오류(monkeypatch, tmp_path):
    text = default_text().replace('value = "low"', 'value = "  "', 1)
    use_file(monkeypatch, tmp_path, text)
    with pytest.raises(ValueError, match="ai.effort"):
        policy.get("ai.effort")


def test_실수_항목이_문자열이면_오류(monkeypatch, tmp_path):
    text = default_text().replace("[ai.total_cap_usd]\nvalue = 1.0\n", '[ai.total_cap_usd]\nvalue = "많음"\n', 1)
    use_file(monkeypatch, tmp_path, text)
    with pytest.raises(ValueError, match="ai.total_cap_usd"):
        policy.get("ai.total_cap_usd")


def test_단가표_단가가_음수면_오류(monkeypatch, tmp_path):
    text = default_text().replace("in_usd_per_mtok = 0.1\n", "in_usd_per_mtok = -1\n", 1)
    use_file(monkeypatch, tmp_path, text)
    with pytest.raises(ValueError, match="claude-haiku-5-5"):
        policy.model_price("claude-haiku-5-5")


def test_배정_모델이_단가표에_없으면_오류(monkeypatch, tmp_path):
    text = default_text().replace('[ai.review_backup]\nvalue = "gemini-3.1-flash-lite"',
                                  '[ai.review_backup]\nvalue = "없는모델"', 1)
    use_file(monkeypatch, tmp_path, text)
    with pytest.raises(ValueError, match="없는모델"):
        policy.get("ai.review_backup")
