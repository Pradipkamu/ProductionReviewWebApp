from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile

from openpyxl import Workbook
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Customer, DailyMIS, DailyRequirement, Product
from app.services.historical_mis_import import import_historical_daily_mis


def test_historical_daily_mis_one_time_import():
    with SessionLocal() as db:
        customer = Customer(code="BAJAJ", name="BAJAJ")
        db.add(customer); db.flush()
        product = Product(code="K70-CYLINDER-BLOCK", name="K70 Cylinder block", customer_id=customer.id, plant="2020", product_group="CI")
        db.add(product); db.commit()

        wb = Workbook(); ws = wb.active; ws.title = "Historical_Daily_MIS_Import"
        ws.append(["Date", "Product", "Plan_Qty", "Actual_Qty"])
        ws.append([date(2026,5,2), "K70 Cylinder block", 2000, 1850])
        with NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            path = Path(tmp.name)
        wb.save(path)
        try:
            stats = import_historical_daily_mis(db, path)
            assert stats["mis_created"] == 1
            mis = db.scalar(select(DailyMIS).where(DailyMIS.mis_date == date(2026,5,2), DailyMIS.product_id == product.id))
            assert float(mis.plan_qty) == 2000
            assert float(mis.actual_qty) == 1850
            req = db.scalar(select(DailyRequirement).where(DailyRequirement.req_date == date(2026,5,2), DailyRequirement.product_id == product.id, DailyRequirement.route_operation_id.is_(None)))
            assert float(req.baseline_plan_qty) == 2000
            assert req.is_frozen is True

            stats2 = import_historical_daily_mis(db, path)
            assert stats2["mis_unchanged"] == 1
            assert stats2["requirements_unchanged"] == 1
        finally:
            path.unlink(missing_ok=True)
