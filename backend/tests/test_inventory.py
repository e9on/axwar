from datetime import date

from app.calc.inventory import restock_date, spare_stock


def test_여유재고():
    assert spare_stock("SKU-2001") == 7376
    assert spare_stock("SKU-2002") == 3670
    assert spare_stock("SKU-2003") == 7393


def test_기초_입고일():
    assert restock_date("SKU-2001") == date(2026, 8, 18)
    assert restock_date("SKU-2002") == date(2026, 8, 19)
    assert restock_date("SKU-2003") == date(2026, 8, 19)


# ---- 재고 장부 (설계 4.5: 쓸 수 있는 재고 = 전날 재고 + 입고 − 평소 판매 − 안전재고 최소 주수분) ----

from app.calc import inventory  # noqa: E402


def test_기초_세_상품의_7월27일_장부_재고는_설계_확인값():
    d = date(2026, 7, 27)
    assert [round(inventory.sku_stock(s, d)) for s in ("SKU-2001", "SKU-2002", "SKU-2003")] == [8012, 4231, 7942]
    assert inventory.line_skus("기초") == ["SKU-2001", "SKU-2002", "SKU-2003"]


def test_기초_라인의_7월27일_여유는_0_안전재고가_모자란다():
    d = date(2026, 7, 27)
    assert inventory.line_stock("기초", d) == 20185
    assert inventory.line_safety_min("기초") == 48868
    assert inventory.line_spare("기초", d) == 0


def test_기준일_당일에는_스냅샷_그대로():
    assert inventory.line_stock("기초", date(2026, 6, 30)) == 67307
    assert inventory.line_spare("기초", date(2026, 6, 30)) == 67307 - 48868


def test_입고일이_지나면_입고량이_재고에_더해진다():
    before = inventory.line_stock("기초", date(2026, 8, 18))
    after = inventory.line_stock("기초", date(2026, 8, 19))
    assert abs((after - before) - (2 * 16000 - 1745)) <= 1  # 그날 입고 두 상품 16,000씩, 하루 평소 판매 약 1,745


def test_라인_입고일은_가장_늦은_상품_기준():
    assert inventory.line_restock_date("기초") == date(2026, 8, 19)


def test_라인_하루_평소_판매():
    assert round(inventory.line_daily_sale("기초"), 1) == 1745.3


def test_모르는_라인은_오류():
    import pytest

    with pytest.raises(KeyError):
        inventory.line_skus("없는라인")


def test_재고_상태에서_재고_과잉은_립과_쿠션():
    from app.rules.allocate import stock_alerts

    rows = inventory.stock_state(date(2026, 7, 27))
    alerts = stock_alerts({r.sku_id: max(0, round(r.stock)) for r in rows}, {r.sku_id: r.weekly_sale for r in rows},
                          {r.sku_id: r.min_weeks for r in rows}, {r.sku_id: r.max_weeks for r in rows})
    assert sorted(s for s, kind in alerts if kind == "재고 과잉") == ["SKU-3001", "SKU-3002"]
