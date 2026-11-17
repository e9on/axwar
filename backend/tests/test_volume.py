from datetime import date, timedelta

from app.data.loader import read_table
from app.calc.volume import all_plan_volumes, daily_load, plan_volume, total_daily_load


def settlement(plan_id):
    return next(r["settlement_date"] for r in read_table("02_masil/marketing/mkt_budget_plan_ms.csv") if r["plan_id"] == plan_id)


def test_PLAN001_배율과_물량():
    v = plan_volume("PLAN-001")
    assert round(v.multiplier, 2) == 1.35
    assert round(v.plan_units) == 147001


def test_PLAN001_최대일은_집행일_7월27일():
    assert round(daily_load("PLAN-001")[date(2026, 7, 27)]) == 15996
    assert round(plan_volume("PLAN-001").peak_share, 3) == 0.109


def test_25건_배율은_세_단계():
    vols = all_plan_volumes()
    assert len(vols) == 25
    assert {round(v.multiplier, 2) for v in vols} == {1.1, 1.25, 1.35}


def test_PLAN008_마켓플레이스_첫날은_집행일_7월28일():
    assert round(daily_load("PLAN-008")[date(2026, 7, 28)]) == 947


def test_7월27일_합계():
    d = date(2026, 7, 27)
    assert round(sum(total_daily_load(d, d)[d].values())) == 18064


def test_7월28일_합계():
    d = date(2026, 7, 28)
    assert round(sum(total_daily_load(d, d)[d].values())) == 2013


def test_모든_물량은_집행일_이후():
    for v in all_plan_volumes():
        settle = settlement(v.plan_id)
        assert min(daily_load(v.plan_id)) >= settle, v.plan_id


def test_라이브는_집행일이_최대일():
    assert plan_volume("PLAN-001").sales_channel == "라이브"
    assert round(daily_load("PLAN-001")[date(2026, 7, 27)]) == 15996


def test_표본몫이_큰_기안은_신뢰도_낮음():
    assert plan_volume("PLAN-011").low_confidence is True
    assert plan_volume("PLAN-001").low_confidence is False


def test_그외_채널은_첫날이_집행일():
    assert plan_volume("PLAN-018").sales_channel != "라이브"
    assert min(daily_load("PLAN-018")) == date(2026, 9, 1)


def test_PLAN018_동률_최대일_후보는_모두_최대_비중():
    # 최대 비중 동률 일수 89, 166, 215: 그외 채널은 집행일 + 일수에 놓인다
    load = daily_load("PLAN-018")
    v = plan_volume("PLAN-018")
    peak = v.plan_units * v.peak_share
    for dd in (89, 166, 215):
        assert round(load[date(2026, 9, 1) + timedelta(days=dd)], 6) == round(peak, 6)


def test_표본_비중_기준은_정책에서_온다(monkeypatch, tmp_path):
    from app import policy
    from app.calc.volume import all_plan_volumes
    text = policy.DEFAULT_PATH.read_text(encoding="utf-8")
    assert policy.get("volume.low_confidence_share") == 0.9
    f = tmp_path / "p.toml"
    f.write_text(text.replace("value = 0.9", "value = 0.0001"), encoding="utf-8")
    monkeypatch.setenv("AXWAR_POLICY_FILE", str(f))
    policy.reload()
    try:
        assert all(v.low_confidence for v in all_plan_volumes())
    finally:
        monkeypatch.undo()
        policy.reload()
