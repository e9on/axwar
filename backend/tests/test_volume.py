from datetime import date

from app.calc.volume import all_plan_volumes, daily_load, plan_volume, total_daily_load


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


def test_혜인_다음날_토모카_최대일이_겹친다():
    assert round(daily_load("PLAN-008")[date(2026, 7, 28)]) == 6631


def test_7월28일_합계():
    d = date(2026, 7, 28)
    assert round(sum(total_daily_load(d, d)[d].values())) == 26553


def test_표본몫이_큰_기안은_신뢰도_낮음():
    assert plan_volume("PLAN-011").low_confidence is True
    assert plan_volume("PLAN-001").low_confidence is False
