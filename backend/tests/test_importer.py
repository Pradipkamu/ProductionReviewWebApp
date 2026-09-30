import os
import pytest
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import DailyMIS, Product, RouteVersion
from app.services.excel_import import import_daily_production_workbook


@pytest.mark.skipif(not os.getenv('SAMPLE_XLSX'), reason='Set SAMPLE_XLSX to run workbook integration test')
def test_current_workbook_import():
    with SessionLocal() as db:
        stats=import_daily_production_workbook(db,os.environ['SAMPLE_XLSX'])
        assert stats['products_created_or_updated'] >= 20
        assert stats['mis_rows_imported'] > 500
        assert stats['routes_created'] >= 20
        assert db.scalar(select(func.count(Product.id))) >= 20
        assert db.scalar(select(func.count(DailyMIS.id))) > 500
        assert db.scalar(select(func.count(RouteVersion.id))) >= 20
