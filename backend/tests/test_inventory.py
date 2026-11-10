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
