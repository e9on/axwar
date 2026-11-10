from app.calc import signals
from app.calc.signals import ATTRIBUTION_NOTE, CostBreakdown, breakeven_hidden_sales, cost_breakdown, future_value_signals, risk_signals
from app.calc.volume import _plans


def _by_key(signals):
    return {s.key: s for s in signals}


def test_혜인_비용분해():
    b = cost_breakdown("INF-001")
    assert b.gmv == 422424676
    assert b.pre_marketing == 248666838
    assert b.influencer_fee == 161187327
    assert b.other_media == 148788300
    assert b.after_fee == 87479511
    assert b.final == -61308789


def test_혜인_재구매는_업계보다_낮아_빨강():
    h = _by_key(future_value_signals("INF-001"))["repurchase_rate"]
    assert round(h.value, 4) == 0.0852
    assert h.level == "red"
    d = _by_key(future_value_signals("INF-002"))["repurchase_rate"]
    assert round(d.value, 3) == 0.241
    assert d.level == "green"


def test_이후주문_포함해도_음수면_빨강():
    s = _by_key(future_value_signals("INF-001"))["post_contribution"]
    assert s.level == "red"
    assert "최종 공헌에 이미 포함" in s.basis


def test_예상실적_괴리():
    s = _by_key(risk_signals("PLAN-001"))["forecast_gap"]
    assert round(s.value, 2) == 11.25
    assert s.level == "red"
    for p in _plans():
        assert _by_key(risk_signals(p["plan_id"]))["forecast_gap"].level == "red"


def test_쿠폰중복():
    s = _by_key(risk_signals("PLAN-001"))["coupon_stacking"]
    assert round(s.value, 3) == 0.175
    assert s.level == "red"


def test_결제지연_채널():
    s = _by_key(risk_signals("PLAN-001"))["slow_payment_channel"]
    assert round(s.value, 3) == 0.294
    assert s.level == "red"
    g = _by_key(risk_signals("PLAN-019"))["slow_payment_channel"]
    assert g.value == 0.0
    assert g.level == "green"


def test_광고비_쏠림():
    s = _by_key(risk_signals("PLAN-001"))["spend_concentration"]
    assert round(s.value, 0) == 2462
    assert s.level == "red"
    assert _by_key(risk_signals("PLAN-019"))["spend_concentration"].level == "green"


def test_채널반품_기준선():
    lv = lambda p: _by_key(risk_signals(p))["channel_return_vs_benchmark"].level
    assert lv("PLAN-001") == "green"
    assert lv("PLAN-003") == "yellow"
    assert lv("PLAN-002") == "red"


def test_회차추세():
    assert _by_key(risk_signals("PLAN-001"))["trend"].level == "yellow"


def test_잠식은_측정불가():
    s = _by_key(risk_signals("PLAN-001"))["cannibalization"]
    assert s.level == "unmeasurable"
    assert "표본" in s.basis


def test_혜인_본전에_필요한_기록밖_판매():
    s = breakeven_hidden_sales("INF-001")
    assert s.key == "breakeven_hidden_sales"
    assert round(s.value, 3) == 0.247
    assert s.level == "yellow"
    assert s.badge == "계산"


def test_이미_흑자면_0():
    s = breakeven_hidden_sales("INF-002")
    assert s.value == 0.0
    assert s.level == "green"


def test_측정한계_문구():
    assert "7일" in ATTRIBUTION_NOTE
    assert "클릭" in ATTRIBUTION_NOTE
    assert "빠지고" in ATTRIBUTION_NOTE
    assert "포함" in ATTRIBUTION_NOTE
    # 방향 회귀 방지: 광고 없이도 샀을 구매는 포함(과대)
    assert "광고 없이도 샀을 구매는 포함" in ATTRIBUTION_NOTE
    assert "클릭 없이 나중에 산 구매는 빠지고" in ATTRIBUTION_NOTE


def test_마케팅전_적자면_본전불가_빨강(monkeypatch):
    for pre, gmv in [(-1000, 5000), (0, 5000), (100, 0)]:
        monkeypatch.setattr(signals, "cost_breakdown", lambda _i, pre=pre, gmv=gmv: CostBreakdown("X", gmv, pre, 10, 10, pre - 10, -1))
        s = breakeven_hidden_sales("X")
        assert s.value is None
        assert s.level == "red"
        assert "본전 불가" in s.basis


def test_설명_숫자는_정책과_통지문에서_온다():
    from app import policy
    from app.data.loader import payment_term_notices
    notice = next(iter(payment_term_notices().values()))
    sig = _by_key(risk_signals("PLAN-001"))
    assert f"{notice.partner_code} {notice.new_days}일" in sig["slow_payment_channel"].basis
    assert str(policy.get("signals.hhi_limit")) in sig["spend_concentration"].basis
    assert f"{policy.get('signals.return_ratio_red'):g}배" in sig["channel_return_vs_benchmark"].basis
    assert str(policy.get("split.stop_z")) in future_value_signals("INF-001")[0].basis


def test_결제조건_통보_대상_채널은_통보문의_파트너코드로_찾는다():
    from app.calc.signals import _payment_terms
    from app.data.loader import payment_term_notices, read_table
    n = next(iter(payment_term_notices().values()))
    terms = _payment_terms()
    for r in read_table("02_masil/master/m_channel_ms.csv"):
        expect = n.new_days if r["partner_code"] == n.partner_code else r["payment_terms_days"]
        assert terms[r["channel_id"]] == expect


def test_기준값을_정책에서_바꾸면_신호가_따라간다(monkeypatch, tmp_path):
    from app import policy
    text = policy.DEFAULT_PATH.read_text(encoding="utf-8")
    f = tmp_path / "p.toml"
    f.write_text(text.replace("value = 1800", "value = 99999"), encoding="utf-8")
    monkeypatch.setenv("AXWAR_POLICY_FILE", str(f))
    policy.reload()
    try:
        assert _by_key(risk_signals("PLAN-001"))["spend_concentration"].level == "green"
    finally:
        monkeypatch.undo()
        policy.reload()


def _edit_csv(path, key_col, key, col, new):
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    head = lines[0].split("|")
    out = [lines[0]]
    for ln in lines[1:]:
        c = ln.split("|")
        if c[head.index(key_col)] == key:
            c[head.index(col)] = new
        out.append("|".join(c))
    path.write_text(chr(10).join(out) + chr(10), encoding="utf-8")


def test_반품_기준선의_소수_자릿수에_맞춰_비교한다(data_copy):
    from app.data.loader import read_table
    plan = next(p for p in read_table("02_masil/marketing/mkt_budget_plan_ms.csv") if p["plan_id"] == "PLAN-001")
    ch = next(c for c in read_table("02_masil/master/m_campaign_ms.csv") if c["campaign_id"] == plan["campaign_id"])["sales_channel"]
    before = _by_key(risk_signals("PLAN-001"))["channel_return_vs_benchmark"]
    assert "0.1%p" in before.basis
    _edit_csv(data_copy / "05_external/benchmark/ext_channel_benchmark.csv", "channel_type", ch, "return_rate_pct", "13.00")
    from app.data import loader
    loader._read.cache_clear()
    after = _by_key(risk_signals("PLAN-001"))["channel_return_vs_benchmark"]
    assert "0.01%p" in after.basis
    assert after.level == "yellow"
    assert after.value > 1


def _write_notice(root, name, text):
    (root / "02_masil/financials" / name).write_text(text, encoding="utf-8")


def _notice(partner, old, new, arrow, applied="2026년 3월 청구분부터"):
    return (
        f"# 결제조건 변경 통보{chr(10)}{chr(10)}수신: Masil 재무팀{chr(10)}발신: 어떤회사{chr(10)}  ({partner}) 구매본부{chr(10)}{chr(10)}"
        f"당사 정책 변경에 따라 정산 결제조건을 기존 {old}일{arrow}{new}일로 연장함을 통보드립니다.{chr(10)}적용: {applied}. (문의: 담당){chr(10)}"
    )


def test_통보문_여러_건_파트너별_가장_늦은_적용_시점(data_copy):
    from app.calc.cash import official_forecast_gap
    from app.data.loader import payment_term_notices, read_table
    base = next(iter(payment_term_notices().values()))
    others = [r for r in read_table("02_masil/master/m_channel_ms.csv") if r["partner_code"] not in (None, base.partner_code)]
    other = others[0]
    # 다른 파트너: 형식이 다른 통보("45일 → 60일")
    _write_notice(data_copy, "zz_payment_term_notice_a.md", _notice(other["partner_code"], 45, 60, " → ", "2026년 5월 청구분부터"))
    # 같은 파트너의 옛 통보(이름순으로 먼저, 적용 시점이 더 이름) / 새 통보(이름순으로 나중이지만 적용 시점이 더 늦음)
    _write_notice(data_copy, "aa_payment_term_notice_old.md", _notice(base.partner_code, 30, 50, "에서", "2026년 1월 청구분부터"))
    n = payment_term_notices()
    assert n[other["partner_code"]].new_days == 60 and n[other["partner_code"]].old_days == 45
    assert n[base.partner_code].new_days == base.new_days  # 옛 통보(2026-01)가 새 통보(2026-03)를 이기지 않음
    text = " ".join(official_forecast_gap()["causes"])
    assert "45일→60일" in text and f"{base.old_days}일→{base.new_days}일" in text
    sig = _by_key(risk_signals("PLAN-001"))["slow_payment_channel"]
    assert other["partner_code"] in sig.basis and base.partner_code in sig.basis


def test_같은_파트너는_이름순이_아니라_적용_시점이_늦은_통보가_이긴다(data_copy):
    from app.data.loader import payment_term_notices
    base = next(iter(payment_term_notices().values()))
    _write_notice(data_copy, "zz_payment_term_notice_new.md", _notice(base.partner_code, base.new_days, 120, "→", "2027년 1월 청구분부터"))
    assert payment_term_notices()[base.partner_code].new_days == 120


def test_형식이_깨진_통보는_파일명을_담은_오류(data_copy):
    import pytest
    from app.data.loader import DataFormatError, payment_term_notices
    _write_notice(data_copy, "bb_payment_term_notice_bad.md", "발신: 회사(XX-1)\n결제조건이 바뀝니다.\n")
    with pytest.raises(DataFormatError) as e:
        payment_term_notices()
    assert "bb_payment_term_notice_bad.md" in str(e.value)
