"""AI 제공자·비용 한도 테스트. 실제 API는 부르지 않는다(post를 가짜로 바꾼다)."""
import importlib.util
import io
import json
import urllib.error
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import config, policy
from app.ai import providers
from app.ai.providers import (BudgetedProvider, BudgetExceeded, Completion, FakeProvider,
                              FallbackProvider, MemoryCostLedger, RealProvider, make_provider)

REPO = Path(__file__).resolve().parents[2]
HAIKU = "claude-haiku-5-5"


class Stub:
    """토큰 수가 정해진 가짜 제공자. 불린 횟수를 센다."""

    def __init__(self, model=HAIKU, in_tok=1000, out_tok=100, fail=None):
        self.model, self.in_tok, self.out_tok, self.fail, self.calls = model, in_tok, out_tok, fail, 0

    def complete(self, system, user):
        self.calls += 1
        if self.fail:
            raise self.fail
        return Completion("ok", self.in_tok, self.out_tok, self.model)


@pytest.fixture(autouse=True)
def _clean_keys(monkeypatch, tmp_path):
    for name in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "UPSTAGE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AXWAR_KEYS", str(tmp_path / "없는파일.env"))
    providers._KEYS.clear()
    yield
    providers._KEYS.clear()


def load_eval_run(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "eval" / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- 가짜 제공자 ----

def test_FakeProvider는_순서대로_응답():
    p = FakeProvider(["a", "b"])
    assert [p.complete("s", "u").text for _ in range(2)] == ["a", "b"]


def test_FakeProvider는_예외를_던진다():
    p = FakeProvider(["a", RuntimeError("실패")])
    p.complete("s", "u")
    with pytest.raises(RuntimeError, match="실패"):
        p.complete("s", "u")


def test_RealProvider는_키파일_없이_만들수_있다():
    assert RealProvider(HAIKU).model == HAIKU


def test_eval이_backend_지시문을_쓴다():
    from app.ai import prompts
    mod = load_eval_run("eval_run_for_test")
    assert mod.REVIEW_SYSTEM is prompts.REVIEW_SYSTEM
    assert mod.reply_system is prompts.reply_system
    assert not (REPO / "eval" / "prompts.py").exists()


def test_eval_단가표는_정책_단가표와_같다():
    mod = load_eval_run("eval_run_for_test2")
    assert set(mod.MODELS) == set(policy.model_names())
    assert mod.MODELS[HAIKU] == policy.model_price(HAIKU)


# ---- 키 ----

def test_키는_환경변수가_키파일보다_우선(monkeypatch, tmp_path):
    f = tmp_path / "k.env"
    f.write_text("ANTHROPIC_API_KEY=파일값\n", encoding="utf-8")
    monkeypatch.setenv("AXWAR_KEYS", str(f))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "환경값")
    assert providers.key("ANTHROPIC_API_KEY") == "환경값"


def test_환경변수가_없으면_키파일에서_처음_쓸때_읽는다(monkeypatch, tmp_path):
    f = tmp_path / "k.env"
    monkeypatch.setenv("AXWAR_KEYS", str(f))
    p = RealProvider(HAIKU)  # 만들 때는 파일이 없어도 된다
    f.write_text("# 주석\nANTHROPIC_API_KEY = 파일값\n", encoding="utf-8")
    assert providers.key("ANTHROPIC_API_KEY") == "파일값"
    assert p.model == HAIKU


def test_키가_없으면_이름만_담은_오류():
    with pytest.raises(RuntimeError) as e:
        providers.key("GEMINI_API_KEY")
    assert "GEMINI_API_KEY" in str(e.value)


def test_backend에_사용자_절대경로가_없다():
    for f in (REPO / "backend" / "app").rglob("*.py"):
        assert "e9on9" not in f.read_text(encoding="utf-8"), f


# ---- 실제 제공자의 요청·응답 처리 (가짜 post) ----

def _anthropic_body(stop="end_turn", thinking=None):
    usage = {"input_tokens": 10, "output_tokens": 20}
    if thinking is not None:
        usage["output_tokens_details"] = {"thinking_tokens": thinking}
    return {"content": [{"type": "text", "text": '{"a":1}'}], "stop_reason": stop, "usage": usage}


def test_Anthropic_요청은_정책값을_쓰고_thinking_temperature가_없다(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "가짜키")
    seen = {}

    def fake_post(url, headers, body):
        seen.update(url=url, headers=headers, body=body)
        return _anthropic_body(thinking=5)

    monkeypatch.setattr(providers, "post", fake_post)
    c = RealProvider("claude-sonnet-5-5").complete("sys", "usr")
    body = seen["body"]
    assert body["max_tokens"] == policy.get("ai.max_tokens")
    assert body["output_config"] == {"effort": policy.get("ai.effort")}
    assert "thinking" not in body and "temperature" not in body
    assert body["model"] == "claude-sonnet-5-5" and body["system"] == "sys"
    assert seen["headers"]["anthropic-version"] == policy.get("ai.anthropic_version")
    assert seen["headers"]["x-api-key"] == "가짜키"
    assert (c.text, c.in_tok, c.out_tok, c.model) == ('{"a":1}', 10, 20, "claude-sonnet-5-5")
    assert c.stop_reason == "end_turn" and c.thinking_tokens == 5


def test_thinking_토큰이_없으면_None(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "가짜키")
    monkeypatch.setattr(providers, "post", lambda *a: _anthropic_body())
    assert RealProvider(HAIKU).complete("s", "u").thinking_tokens is None


def test_잘림은_stop_reason_max_tokens로_전달된다(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "가짜키")
    monkeypatch.setattr(providers, "post", lambda *a: _anthropic_body(stop="max_tokens"))
    assert RealProvider(HAIKU).complete("s", "u").stop_reason == "max_tokens"


def test_Gemini_응답은_생각_토큰을_출력에_더하고_잘림을_표시한다(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "가짜키")
    seen = {}

    def fake_post(url, headers, body):
        seen.update(url=url, headers=headers)
        return {"candidates": [{"content": {"parts": [{"text": "답"}]}, "finishReason": "MAX_TOKENS"}],
                "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 3, "thoughtsTokenCount": 4}}

    monkeypatch.setattr(providers, "post", fake_post)
    c = RealProvider("gemini-3.1-flash-lite").complete("s", "u")
    assert "gemini-3.1-flash-lite" in seen["url"] and seen["headers"]["x-goog-api-key"] == "가짜키"
    assert (c.text, c.in_tok, c.out_tok, c.stop_reason, c.thinking_tokens) == ("답", 7, 7, "max_tokens", 4)


def test_Upstage_응답은_length를_max_tokens로_바꾼다(monkeypatch):
    monkeypatch.setenv("UPSTAGE_API_KEY", "가짜키")
    monkeypatch.setattr(providers, "post", lambda *a: {
        "choices": [{"message": {"content": "답"}, "finish_reason": "length"}],
        "usage": {"prompt_tokens": 2, "completion_tokens": 3}})
    c = RealProvider("solar-mini4").complete("s", "u")
    assert (c.in_tok, c.out_tok, c.stop_reason) == (2, 3, "max_tokens")


def test_모르는_모델은_오류():
    with pytest.raises(ValueError, match="없는모델"):
        RealProvider("없는모델")


def test_HTTP_오류는_상태코드와_본문_300자를_남긴다(monkeypatch):
    def fake_urlopen(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 400, "bad", {}, io.BytesIO(("x" * 400).encode()))

    monkeypatch.setattr(providers.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(RuntimeError) as e:
        providers.post("http://x", {}, {})
    msg = str(e.value)
    assert msg.startswith("400 ") and "x" * 300 in msg and "x" * 301 not in msg


def test_재시도_끝_실패도_마지막_상태코드와_본문을_포함한다(monkeypatch):
    monkeypatch.setattr(providers.time, "sleep", lambda s: None)

    def fake_urlopen(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 529, "over", {}, io.BytesIO(b"overloaded"))

    monkeypatch.setattr(providers.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(RuntimeError) as e:
        providers.post("http://x", {}, {})
    assert "재시도 한도 초과" in str(e.value) and "529" in str(e.value) and "overloaded" in str(e.value)


# ---- 비용 한도 ----

def test_호출마다_비용이_기록된다():
    ledger = MemoryCostLedger()
    day = date(2030, 1, 2)
    BudgetedProvider(Stub(), ledger, today=lambda: day).complete("s", "u")
    assert ledger.spent(day) == pytest.approx(0.00015)
    assert ledger.spent(None) == pytest.approx(0.00015)
    assert ledger.rows[0][:3] == (HAIKU, 1000, 100)


def test_전체한도를_넘으면_호출하지_않는다():
    ledger = MemoryCostLedger()
    ledger.record(HAIKU, 0, 0, policy.get("ai.total_cap_usd"), date(2029, 1, 1))
    inner = Stub()
    p = BudgetedProvider(inner, ledger, today=lambda: date(2030, 1, 2))
    with pytest.raises(BudgetExceeded):
        p.complete("s", "u")
    assert inner.calls == 0


def test_하루한도는_날짜별():
    ledger = MemoryCostLedger()
    today = date(2030, 1, 2)
    ledger.record(HAIKU, 0, 0, policy.get("ai.daily_cap_usd"), today - timedelta(days=1))
    inner = Stub()
    BudgetedProvider(inner, ledger, today=lambda: today).complete("s", "u")
    assert inner.calls == 1


def test_오늘_하루한도에_닿으면_막는다():
    ledger = MemoryCostLedger()
    today = date(2030, 1, 2)
    ledger.record(HAIKU, 0, 0, policy.get("ai.daily_cap_usd"), today)
    inner = Stub()
    with pytest.raises(BudgetExceeded):
        BudgetedProvider(inner, ledger, today=lambda: today).complete("s", "u")
    assert inner.calls == 0


def test_한도는_인자로_바꿀_수_있다():
    ledger = MemoryCostLedger()
    day = date(2030, 1, 2)
    est = providers.estimate_usd(HAIKU, "s", "u")
    p = BudgetedProvider(Stub(), ledger, total_cap_usd=est * 1.05, daily_cap_usd=1.0, today=lambda: day)
    p.complete("s", "u")  # 첫 호출은 이미 쓴 돈이 0이라 통과(실제 비용 0.00015)
    with pytest.raises(BudgetExceeded):
        p.complete("s", "u")


def test_단가표에_없는_모델이면_기록하지_않고_오류():
    ledger = MemoryCostLedger()
    with pytest.raises(ValueError, match="없는모델"):
        BudgetedProvider(Stub(model="없는모델"), ledger, today=lambda: date(2030, 1, 2)).complete("s", "u")
    assert ledger.rows == []


def test_날짜_기본값은_실제_오늘():
    ledger = MemoryCostLedger()
    BudgetedProvider(Stub(), ledger).complete("s", "u")
    assert ledger.spent(datetime.now(timezone.utc).date()) > 0  # 과금 기준에 맞춰 UTC 날짜


# ---- 예비 모델 ----

def test_주_모델이_실패하면_예비로_한_번_더():
    primary, backup = Stub(fail=RuntimeError("503")), Stub(model="gemini-3.1-flash-lite")
    c = FallbackProvider(primary, backup).complete("s", "u")
    assert c.model == "gemini-3.1-flash-lite" and primary.calls == 1 and backup.calls == 1


def test_주_모델이_성공하면_예비는_부르지_않는다():
    primary, backup = Stub(), Stub()
    FallbackProvider(primary, backup).complete("s", "u")
    assert backup.calls == 0


def test_BudgetExceeded는_예비로_넘기지_않는다():
    primary, backup = Stub(fail=BudgetExceeded("한도")), Stub()
    with pytest.raises(BudgetExceeded):
        FallbackProvider(primary, backup).complete("s", "u")
    assert backup.calls == 0


def test_예비도_실패하면_예비의_오류를_올린다():
    with pytest.raises(RuntimeError, match="예비실패"):
        FallbackProvider(Stub(fail=RuntimeError("a")), Stub(fail=RuntimeError("예비실패"))).complete("s", "u")


def test_예비_호출_비용도_기록된다():
    ledger = MemoryCostLedger()
    day = date(2030, 1, 2)
    inner = FallbackProvider(Stub(fail=RuntimeError("503")), Stub(model="gemini-3.1-flash-lite"))
    BudgetedProvider(inner, ledger, today=lambda: day).complete("s", "u")
    assert [r[0] for r in ledger.rows] == ["gemini-3.1-flash-lite"]
    assert ledger.spent(day) == pytest.approx((1000 * 0.25 + 100 * 1.50) / 1_000_000)


# ---- 만들기 ----

def test_AI_모드_상수는_없고_함수만_있다():
    assert not hasattr(config, "AI_MODE")


def test_기본_모드는_fake(monkeypatch):
    monkeypatch.delenv("AXWAR_AI", raising=False)
    assert config.ai_mode() == "fake"
    assert make_provider("review").complete("s", "u").model == "fake"


def test_fake_모드는_리뷰_회신_글쓰기_모두_유효한_응답(monkeypatch):
    monkeypatch.delenv("AXWAR_AI", raising=False)
    rv = json.loads(make_provider("review").complete("s", "상품: 립\n리뷰: 색이 영상과 달라요").text)
    assert rv["reason"] == "색상불일치" and rv["content_gap"] is True
    ok = json.loads(make_provider("reply").complete("s", "부서: 물류\n요청: 출고\n회신: 전량 가능합니다").text)
    assert ok["stance"] == "수용" and ok["needs_human"] is False
    no = json.loads(make_provider("reply").complete("s", "부서: 물류\n요청: 출고\n회신: 불가합니다").text)
    assert no["stance"] == "거절" and no["needs_human"] is True
    assert make_provider("writer").complete("s", "사실: 내용").text.strip()


def test_real_모드는_주_예비_각각_예산을_감싼_구조(monkeypatch):
    monkeypatch.setenv("AXWAR_AI", "real")
    ledger = MemoryCostLedger()
    p = make_provider("writer", ledger=ledger)
    assert isinstance(p, FallbackProvider)
    assert isinstance(p.primary, BudgetedProvider) and isinstance(p.backup, BudgetedProvider)
    assert p.primary.inner.model == policy.get("ai.writer_model")
    assert p.backup.inner.model == policy.get("ai.writer_backup")
    assert p.primary.ledger is ledger and p.backup.ledger is ledger


def test_모르는_모드와_작업은_오류(monkeypatch):
    monkeypatch.setenv("AXWAR_AI", "이상한모드")
    with pytest.raises(ValueError, match="이상한모드"):
        make_provider("review")
    monkeypatch.setenv("AXWAR_AI", "fake")
    with pytest.raises(ValueError, match="없는작업"):
        make_provider("없는작업")


# ---- 예약·정산 (동시 호출 한도 초과 방지) ----

def test_호출_전에_예상_비용을_예약하고_호출_뒤_실제_비용으로_정산():
    ledger = MemoryCostLedger()
    day = date(2030, 1, 2)
    seen = []

    class Peek(Stub):
        def complete(self, system, user):
            seen.append(ledger.spent(day))  # 호출 도중에는 예약분이 잡혀 있어야 한다
            return super().complete(system, user)

    BudgetedProvider(Peek(), ledger, today=lambda: day).complete("sys", "user")
    assert seen[0] == pytest.approx(providers.estimate_usd(HAIKU, "sys", "user"))
    assert ledger.spent(day) == pytest.approx(0.00015)


def test_호출이_실패하면_예약을_돌려준다():
    ledger = MemoryCostLedger()
    day = date(2030, 1, 2)
    with pytest.raises(RuntimeError):
        BudgetedProvider(Stub(fail=RuntimeError("503")), ledger, today=lambda: day).complete("s", "u")
    assert ledger.spent(None) == 0


def test_예상_비용은_입력_추정과_최대_출력_단가():
    _, p_in, p_out = policy.model_price(HAIKU)
    est = providers.estimate_usd(HAIKU, "가나", "다라마")
    expect = (5 * providers.ESTIMATE_TOKENS_PER_CHAR * p_in + policy.get("ai.max_tokens") * p_out) / providers.TOKENS_PER_PRICE_UNIT
    assert est == pytest.approx(expect)


def test_예상_비용만으로_한도를_넘으면_호출하지_않는다():
    ledger = MemoryCostLedger()
    inner = Stub()
    p = BudgetedProvider(inner, ledger, total_cap_usd=providers.estimate_usd(HAIKU, "s", "u") / 2, daily_cap_usd=1.0)
    with pytest.raises(BudgetExceeded):
        p.complete("s", "u")
    assert inner.calls == 0


def test_예비모델도_한도를_확인한다():
    ledger = MemoryCostLedger()
    day = date(2030, 1, 2)
    backup_model = "gemini-3.1-flash-lite"
    main_est = providers.estimate_usd(HAIKU, "s", "u")
    backup_est = providers.estimate_usd(backup_model, "s", "u")
    # 주 모델 예약은 통과(그리고 실패해 돌려줌)하지만 예비의 예상 비용은 남은 한도를 넘는다
    cap = max(main_est, backup_est) * 1.2
    ledger.record(HAIKU, 0, 0, cap - backup_est / 2, day)
    main_inner, backup_inner = Stub(fail=RuntimeError("503")), Stub(model=backup_model)
    primary = BudgetedProvider(main_inner, ledger, total_cap_usd=cap + main_est, daily_cap_usd=10.0, today=lambda: day)
    backup = BudgetedProvider(backup_inner, ledger, total_cap_usd=cap, daily_cap_usd=10.0, today=lambda: day)
    with pytest.raises(BudgetExceeded):
        FallbackProvider(primary, backup).complete("s", "u")
    assert main_inner.calls == 1 and backup_inner.calls == 0


def test_real모드는_장부없이_만들수_없다(monkeypatch):
    monkeypatch.setenv("AXWAR_AI", "real")
    with pytest.raises(ValueError, match="실제 AI 모드는 DB 비용 장부가 필요함"):
        make_provider("review")
    assert not hasattr(providers, "_LEDGER")
