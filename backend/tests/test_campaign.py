from app.calc.campaign import campaign_real_roas, influencer_ranking, return_rate


def _by_id():
    return {p.influencer_id: p for p in influencer_ranking()}


def test_혜인_실질ROAS는_음수이고_9위():
    p = _by_id()["INF-001"]
    assert round(p.real_roas, 3) == -0.198
    assert p.rank == 9


def test_1위는_INF002():
    ranking = influencer_ranking()
    top = next(p for p in ranking if p.rank == 1)
    assert top.influencer_id == "INF-002"
    assert round(top.real_roas, 3) == 3.703


def test_혜인_광고비_비중_40_6():
    assert round(_by_id()["INF-001"].spend_share, 1) == 40.6


def test_배분_역전():
    ranking = influencer_ranking()
    biggest = max(ranking, key=lambda p: p.spend_share)
    assert biggest.rank > len(ranking) / 2


def test_혜인_단순변심_반품률():
    assert round(return_rate("INF-001", "단순변심"), 4) == 0.0358
    assert round(return_rate(None, "단순변심", exclude="INF-001"), 4) == 0.0175


def test_CMP0003_실질ROAS():
    assert round(campaign_real_roas("CMP-0003"), 3) == -0.248
