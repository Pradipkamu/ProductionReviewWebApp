from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import DailyMIS, SalesPriceHistory


def price_for_date(db: Session, product_id: int, d: date, fallback: Decimal | None = None) -> Decimal:
    row = db.scalar(
        select(SalesPriceHistory)
        .where(
            SalesPriceHistory.product_id == product_id,
            SalesPriceHistory.effective_from <= d,
            or_(SalesPriceHistory.effective_to.is_(None), SalesPriceHistory.effective_to >= d),
        )
        .order_by(SalesPriceHistory.effective_from.desc(), SalesPriceHistory.id.desc())
        .limit(1)
    )
    if row:
        return Decimal(str(row.price or 0))
    return Decimal(str(fallback or 0))


def normalize_price_ranges(db: Session, product_id: int) -> None:
    """Make effective-to dates contiguous/non-overlapping for one product."""
    rows = db.scalars(
        select(SalesPriceHistory)
        .where(SalesPriceHistory.product_id == product_id)
        .order_by(SalesPriceHistory.effective_from, SalesPriceHistory.id)
    ).all()
    # If duplicate effective dates somehow exist, the newest id wins. Keep older
    # rows closed the day before the same date (effectively inactive).
    for idx, row in enumerate(rows):
        next_row = rows[idx + 1] if idx + 1 < len(rows) else None
        row.effective_to = (next_row.effective_from - timedelta(days=1)) if next_row else None


def recalculate_mis_sales_from(db: Session, product_id: int, start_date: date) -> int:
    rows = db.scalars(
        select(DailyMIS)
        .where(DailyMIS.product_id == product_id, DailyMIS.mis_date >= start_date)
        .order_by(DailyMIS.mis_date)
    ).all()
    count = 0
    for row in rows:
        price = price_for_date(db, product_id, row.mis_date, Decimal(str(row.sales_price or 0)))
        if Decimal(str(row.sales_price or 0)) != price:
            row.sales_price = price
            count += 1
        row.plan_sales = Decimal(str(row.plan_qty or 0)) * price
        row.actual_sales = Decimal(str(row.actual_qty or 0)) * price
    return count


def create_or_replace_manual_price(
    db: Session,
    product_id: int,
    effective_from: date,
    price: Decimal,
    reason: str,
    entered_by_id: int | None,
) -> SalesPriceHistory:
    # One logical price per product/effective date. If an imported baseline exists
    # on the same day, convert/update it rather than creating an ambiguous overlap.
    row = db.scalar(
        select(SalesPriceHistory)
        .where(
            SalesPriceHistory.product_id == product_id,
            SalesPriceHistory.effective_from == effective_from,
        )
        .order_by(SalesPriceHistory.id.desc())
        .limit(1)
    )
    if row is None:
        row = SalesPriceHistory(
            product_id=product_id,
            effective_from=effective_from,
            price=price,
            reason=reason,
            source="MANUAL",
            entered_by_id=entered_by_id,
        )
        db.add(row)
        db.flush()
    else:
        row.price = price
        row.reason = reason
        row.source = "MANUAL"
        row.entered_by_id = entered_by_id
    normalize_price_ranges(db, product_id)
    db.flush()
    recalculate_mis_sales_from(db, product_id, effective_from)
    return row
