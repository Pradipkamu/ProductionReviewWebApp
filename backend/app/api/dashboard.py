from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import User
from ..services.filtering import csv_ints, csv_strings
from ..services.dashboard import daily_review_summary

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
def summary(
    as_of: date,
    plant: str | None = None,
    product_group: str | None = None,
    customer_id: str | None = None,
    product_id: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return daily_review_summary(
        db, as_of,
        plants=csv_strings(plant),
        product_groups=csv_strings(product_group),
        customer_ids=csv_ints(customer_id),
        product_ids=csv_ints(product_id),
    )
