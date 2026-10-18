from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..enums import UserRole
from ..models import (
    Operation, Product, QualityPhenomenon, QualityRejectionDaily,
    QualityRejectionSalvageRequest, RouteOperation, User,
)

router = APIRouter(prefix="/quality/salvage", tags=["quality-salvage"])


class SalvageRequestCreate(BaseModel):
    rejection_id: int
    salvage_qty: Decimal = Field(gt=0, max_digits=16, decimal_places=3)
    reason: str = Field(min_length=10, max_length=1000)


class SalvageReview(BaseModel):
    action: Literal["APPROVE", "REJECT"]
    note: str | None = Field(default=None, max_length=1000)


def _role(user: User) -> str:
    return user.role.value if hasattr(user.role, "value") else str(user.role)


def _require_role(user: User, allowed: set[str], message: str):
    if _role(user) not in allowed:
        raise HTTPException(403, message)


def _num(value) -> float:
    return float(value or 0)


def _eligible_row(db: Session, rejection_id: int) -> QualityRejectionDaily:
    row = db.scalar(
        select(QualityRejectionDaily)
        .where(QualityRejectionDaily.id == rejection_id)
        .with_for_update()
    )
    if not row:
        raise HTTPException(404, "Daily rejection record not found")
    return row


@router.get("/rejections")
def eligible_rejections(
    from_date: date,
    to_date: date,
    plant: str | None = None,
    product_id: int | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = (
        select(QualityRejectionDaily, Product, QualityPhenomenon, Operation)
        .join(Product, Product.id == QualityRejectionDaily.product_id)
        .join(QualityPhenomenon, QualityPhenomenon.id == QualityRejectionDaily.phenomenon_id)
        .outerjoin(RouteOperation, RouteOperation.id == QualityRejectionDaily.detection_route_operation_id)
        .outerjoin(Operation, Operation.id == RouteOperation.operation_id)
        .where(
            QualityRejectionDaily.rejection_date >= from_date,
            QualityRejectionDaily.rejection_date <= to_date,
        )
    )
    if plant:
        q = q.where(func.coalesce(QualityRejectionDaily.plant, Product.plant) == plant)
    if product_id is not None:
        q = q.where(Product.id == product_id)
    if search and search.strip():
        term = "%" + search.strip() + "%"
        q = q.where(or_(Product.name.ilike(term), Product.code.ilike(term)))
    rows = db.execute(
        q.order_by(QualityRejectionDaily.rejection_date.desc(), QualityRejectionDaily.id.desc()).limit(1000)
    ).all()
    ids = [row.id for row, *_ in rows]
    pending = {}
    if ids:
        pending_rows = db.execute(
            select(
                QualityRejectionSalvageRequest.daily_rejection_id,
                func.sum(QualityRejectionSalvageRequest.requested_qty),
            )
            .where(
                QualityRejectionSalvageRequest.daily_rejection_id.in_(ids),
                QualityRejectionSalvageRequest.status == "PENDING",
            )
            .group_by(QualityRejectionSalvageRequest.daily_rejection_id)
        ).all()
        pending = {int(rejection_id): _num(qty) for rejection_id, qty in pending_rows}

    result = []
    for rejection, product, phenomenon, operation in rows:
        original = _num(rejection.reject_qty)
        approved = _num(rejection.approved_salvage_qty)
        pending_qty = pending.get(rejection.id, 0.0)
        remaining = max(0.0, original - approved)
        result.append({
            "rejection_id": rejection.id,
            "date": rejection.rejection_date,
            "shift": rejection.shift,
            "plant": rejection.plant or product.plant,
            "product_id": product.id,
            "product_code": product.code,
            "product": product.name,
            "detection_process": operation.name if operation else None,
            "phenomenon": phenomenon.name,
            "original_reject_qty": original,
            "approved_salvage_qty": approved,
            "net_reject_qty": remaining,
            "pending_salvage_qty": pending_qty,
            "available_qty": 0.0 if pending_qty > 0 else remaining,
        })
    return result


@router.get("/requests")
def list_salvage_requests(
    from_date: date | None = None,
    to_date: date | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = (
        select(QualityRejectionSalvageRequest, QualityRejectionDaily, Product, QualityPhenomenon)
        .join(QualityRejectionDaily, QualityRejectionDaily.id == QualityRejectionSalvageRequest.daily_rejection_id)
        .join(Product, Product.id == QualityRejectionDaily.product_id)
        .join(QualityPhenomenon, QualityPhenomenon.id == QualityRejectionDaily.phenomenon_id)
    )
    if from_date:
        q = q.where(QualityRejectionDaily.rejection_date >= from_date)
    if to_date:
        q = q.where(QualityRejectionDaily.rejection_date <= to_date)
    if status:
        normalized = status.strip().upper()
        if normalized not in {"PENDING", "APPROVED", "REJECTED"}:
            raise HTTPException(400, "Status must be Pending, Approved or Rejected")
        q = q.where(QualityRejectionSalvageRequest.status == normalized)
    if _role(user) == UserRole.PRODUCTION.value:
        q = q.where(QualityRejectionSalvageRequest.requested_by_id == user.id)
    rows = db.execute(
        q.order_by(QualityRejectionSalvageRequest.created_at.desc(), QualityRejectionSalvageRequest.id.desc()).limit(500)
    ).all()
    user_ids = {
        uid for request, *_ in rows
        for uid in (request.requested_by_id, request.reviewed_by_id) if uid is not None
    }
    users = {
        x.id: x for x in db.scalars(select(User).where(User.id.in_(user_ids))).all()
    } if user_ids else {}
    result = []
    for request, rejection, product, phenomenon in rows:
        requester = users.get(request.requested_by_id)
        reviewer = users.get(request.reviewed_by_id)
        result.append({
            "id": request.id,
            "rejection_id": rejection.id,
            "date": rejection.rejection_date,
            "shift": rejection.shift,
            "plant": rejection.plant or product.plant,
            "product_code": product.code,
            "product": product.name,
            "phenomenon": phenomenon.name,
            "original_reject_qty": _num(rejection.reject_qty),
            "approved_salvage_qty": _num(rejection.approved_salvage_qty),
            "net_reject_qty": max(0.0, _num(rejection.reject_qty) - _num(rejection.approved_salvage_qty)),
            "requested_qty": _num(request.requested_qty),
            "reason": request.reason,
            "status": request.status,
            "requested_by": requester.full_name if requester else "Former User",
            "requested_by_id": request.requested_by_id,
            "requested_at": request.created_at,
            "reviewed_by": reviewer.full_name if reviewer else None,
            "reviewed_at": request.reviewed_at,
            "review_note": request.review_note,
            "approved_before_qty": _num(request.approved_before_qty) if request.approved_before_qty is not None else None,
            "approved_after_qty": _num(request.approved_after_qty) if request.approved_after_qty is not None else None,
        })
    return result


@router.post("/requests")
def create_salvage_request(
    payload: SalvageRequestCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_role(
        user,
        {UserRole.PRODUCTION.value, UserRole.ADMIN.value},
        "Only Production or Admin users can submit salvage requests",
    )
    reason = payload.reason.strip()
    if len(reason) < 10:
        raise HTTPException(422, "A salvage reason of at least 10 characters is required")
    rejection = _eligible_row(db, payload.rejection_id)
    approved = rejection.approved_salvage_qty or Decimal("0")
    original = rejection.reject_qty or Decimal("0")
    remaining = original - approved
    if remaining <= 0:
        raise HTTPException(409, "No rejected quantity remains available for salvage")
    if payload.salvage_qty > remaining:
        raise HTTPException(422, "Salvage quantity exceeds the remaining rejected quantity (" + str(remaining) + ")")
    pending = db.scalar(
        select(func.count(QualityRejectionSalvageRequest.id)).where(
            QualityRejectionSalvageRequest.daily_rejection_id == rejection.id,
            QualityRejectionSalvageRequest.status == "PENDING",
        )
    ) or 0
    if pending:
        raise HTTPException(409, "A salvage request is already pending for this rejection record")
    request = QualityRejectionSalvageRequest(
        daily_rejection_id=rejection.id,
        requested_qty=payload.salvage_qty,
        reason=reason,
        status="PENDING",
        requested_by_id=user.id,
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return {"id": request.id, "rejection_id": rejection.id, "requested_qty": _num(request.requested_qty), "status": request.status}


@router.post("/requests/{request_id}/review")
def review_salvage_request(
    request_id: int,
    payload: SalvageReview,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_role(
        user,
        {UserRole.QUALITY.value, UserRole.ADMIN.value},
        "Only Quality or Admin users can approve or reject salvage requests",
    )
    request = db.scalar(
        select(QualityRejectionSalvageRequest)
        .where(QualityRejectionSalvageRequest.id == request_id)
        .with_for_update()
    )
    if not request:
        raise HTTPException(404, "Salvage request not found")
    if request.status != "PENDING":
        raise HTTPException(409, "This salvage request has already been reviewed")
    if request.requested_by_id == user.id:
        raise HTTPException(403, "The requester cannot approve or reject their own salvage request")
    rejection = _eligible_row(db, request.daily_rejection_id)
    before = rejection.approved_salvage_qty or Decimal("0")
    after = before
    if payload.action == "APPROVE":
        original = rejection.reject_qty or Decimal("0")
        if before + request.requested_qty > original:
            raise HTTPException(409, "The remaining rejection quantity has changed; this request cannot be approved")
        after = before + request.requested_qty
        rejection.approved_salvage_qty = after
        request.status = "APPROVED"
    else:
        if not payload.note or len(payload.note.strip()) < 5:
            raise HTTPException(422, "A rejection reason of at least 5 characters is required")
        request.status = "REJECTED"
    request.approved_before_qty = before
    request.approved_after_qty = after
    request.reviewed_by_id = user.id
    request.reviewed_at = datetime.utcnow()
    request.review_note = payload.note.strip() if payload.note and payload.note.strip() else None
    db.commit()
    return {
        "id": request.id,
        "status": request.status,
        "approved_before_qty": _num(before),
        "approved_after_qty": _num(after),
        "net_reject_qty": max(0.0, _num(rejection.reject_qty) - _num(rejection.approved_salvage_qty)),
    }
