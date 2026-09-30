from datetime import date
from decimal import Decimal

from app.db import SessionLocal
from app.models import Customer, DailyMIS, Product, ScheduleRevision, WorkingCalendar
from app.services.planning import apply_schedule_revision, preview_revision, split_integer_quantity


def test_exact_split():
    days = [date(2026,9,d) for d in [1,2,3]]
    x = split_integer_quantity(Decimal('10'), days)
    assert sum(x.values()) == 10
    assert list(x.values()) == [4,3,3]


def test_schedule_revision_uses_actual_before_effective_date_and_off_days():
    with SessionLocal() as db:
        c=Customer(code='C1',name='Customer'); db.add(c); db.flush()
        p=Product(code='P1',name='Part',customer_id=c.id); db.add(p); db.flush()
        # Explicitly define 12-15 Sep, with Sunday/off-day 13th.
        for d, working in [(12,True),(13,False),(14,True),(15,True)]:
            db.add(WorkingCalendar(work_date=date(2026,9,d),plant='Main Plant',is_working_day=working))
        db.add(DailyMIS(mis_date=date(2026,9,11),product_id=p.id,actual_qty=Decimal('18600')))
        db.commit()
        pv=preview_revision(db,p.id,date(2026,9,12),Decimal('52000'))
        assert pv['actual_before_effective_date'] == 18600
        assert pv['balance_requirement'] == 33400
        rev=ScheduleRevision(product_id=p.id,month=date(2026,9,1),revision_no=1,effective_from=date(2026,9,12),monthly_target_qty=Decimal('52000'))
        db.add(rev);db.flush();apply_schedule_revision(db,rev);db.commit()
        assert rev.id is not None
