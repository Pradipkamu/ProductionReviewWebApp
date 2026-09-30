from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import ReviewSession, User
from ..schemas import ReviewClose, ReviewStart

router = APIRouter(prefix="/reviews", tags=["reviews"])


def serialize_review(row: ReviewSession) -> dict:
    return {
        "id": row.id,
        "review_date": row.review_date,
        "started_at": row.started_at,
        "ended_at": row.ended_at,
        "participants": row.participants,
        "total_sales_gap": float(row.total_sales_gap) if row.total_sales_gap is not None else None,
        "comments": row.comments,
    }


@router.get("/active")
def get_active_review(
    review_date: date,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Return the server-side active review for a date, or null when none exists.

    The frontend uses this endpoint as the source of truth instead of trusting
    browser localStorage.  This makes review sessions survive app upgrades and
    also clears stale browser state after a database reset.
    """
    row = db.scalar(
        select(ReviewSession)
        .where(
            ReviewSession.review_date == review_date,
            ReviewSession.ended_at.is_(None),
        )
        .order_by(ReviewSession.started_at.desc(), ReviewSession.id.desc())
        .limit(1)
    )
    return serialize_review(row) if row else None


@router.get("")
def list_reviews(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.scalars(
        select(ReviewSession)
        .order_by(ReviewSession.review_date.desc(), ReviewSession.id.desc())
        .limit(100)
    ).all()
    return [serialize_review(x) for x in rows]


@router.post("")
def start_review(
    payload: ReviewStart,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    # Re-use an already active review for the date rather than creating
    # multiple parallel sessions if Start Review is clicked twice.
    existing = db.scalar(
        select(ReviewSession)
        .where(
            ReviewSession.review_date == payload.review_date,
            ReviewSession.ended_at.is_(None),
        )
        .order_by(ReviewSession.started_at.desc(), ReviewSession.id.desc())
        .limit(1)
    )
    if existing:
        result = serialize_review(existing)
        result["existing"] = True
        return result

    row = ReviewSession(
        review_date=payload.review_date,
        started_at=datetime.utcnow(),
        participants=payload.participants,
        comments=payload.comments,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    result = serialize_review(row)
    result["existing"] = False
    return result


@router.patch("/{review_id}/close")
def close_review(
    review_id: int,
    payload: ReviewClose,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    row = db.get(ReviewSession, review_id)
    if not row:
        raise HTTPException(404, "Review session not found. Refresh Daily Review to resynchronise the browser session.")

    # Idempotent close: repeated clicks return the already-closed timestamp.
    if row.ended_at is None:
        row.ended_at = datetime.utcnow()
    if payload.comments is not None:
        row.comments = payload.comments
    db.commit()
    db.refresh(row)
    return serialize_review(row)
