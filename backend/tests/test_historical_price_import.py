from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import NamedTemporaryFile

from openpyxl import Workbook
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Customer, DailyMIS, Product, SalesPriceHistory
from app.services.historical_price_import import import_historical_sales_prices
from app.services.pricing import price_for_date


def test_historical_sales_price_import_effective_ranges_and_recalc():
    with SessionLocal() as db:
        c = Customer(code="BAJAJ", name="BAJAJ")
        db.add(c); db.flush()
        p = Product(code="K70-CYLINDER-BLOCK", name="K70 Cylinder block", customer_id=c.id, plant="2020", product_group="CI")
        db.add(p); db.flush()
        mis1 = DailyMIS(mis_date=date(2026,5,10), product_id=p.id, plan_qty=100, actual_qty=90, sales_price=0, plan_sales=0, actual_sales=0)
        mis2 = DailyMIS(mis_date=date(2026,6,20), product_id=p.id, plan_qty=100, actual_qty=80, sales_price=0, plan_sales=0, actual_sales=0)
        db.add_all([mis1, mis2]); db.commit()

        wb = Workbook(); ws = wb.active; ws.title = "Historical_Sales_Price_Import"
        ws.append(["Product","Effective_From","Sales_Price_Rs_Per_Pc","Revision_Reference","Reason","Source_Document"])
        ws.append(["K70 Cylinder block", date(2026,5,1), 607.87, "OPEN", "Opening rate", "PO-1"])
        ws.append(["K70 Cylinder block", date(2026,6,15), 620.00, "REV-01", "Increase", "PO-2"])
        with NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            path = Path(tmp.name)
        wb.save(path)
        try:
            stats = import_historical_sales_prices(db, path, None)
            db.commit()
            assert stats["price_rows_created"] == 2
            rows = db.scalars(select(SalesPriceHistory).where(SalesPriceHistory.product_id == p.id).order_by(SalesPriceHistory.effective_from)).all()
            assert len(rows) == 2
            assert rows[0].effective_to == date(2026,6,14)
            assert rows[1].effective_to is None
            assert rows[1].revision_reference == "REV-01"
            assert rows[1].source_document == "PO-2"
            assert price_for_date(db, p.id, date(2026,5,10)) == Decimal("607.8700")
            assert price_for_date(db, p.id, date(2026,6,20)) == Decimal("620.0000")
            db.refresh(mis1); db.refresh(mis2)
            assert Decimal(str(mis1.actual_sales)) == Decimal("54708.30")
            assert Decimal(str(mis2.actual_sales)) == Decimal("49600.00")

            stats2 = import_historical_sales_prices(db, path, None)
            assert stats2["price_rows_unchanged"] == 2
        finally:
            path.unlink(missing_ok=True)
