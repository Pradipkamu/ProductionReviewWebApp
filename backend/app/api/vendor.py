from datetime import date
from decimal import Decimal
import uuid
from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import Product, RouteOperation, Operation, User, Vendor, VendorMovement, VendorReceipt, RouteVersion
from ..schemas import VendorMovementCreate

router = APIRouter(prefix="/vendor", tags=["vendor"])


def _serialize(vm: VendorMovement, product: Product, op: Operation, vendor: Vendor) -> dict:
    pending = float(vm.outward_qty - vm.receipt_qty)
    age = (date.today() - vm.outward_date).days if pending > 0 else 0
    overdue = bool(pending > 0 and vm.expected_return_date and vm.expected_return_date < date.today())
    return {
        "id": vm.id,
        "product_id": vm.product_id,
        "product": product.name,
        "route_operation_id": vm.route_operation_id,
        "operation": op.name,
        "vendor_id": vm.vendor_id,
        "vendor": vendor.name,
        "outward_date": vm.outward_date,
        "outward_qty": float(vm.outward_qty),
        "receipt_date": vm.receipt_date,
        "receipt_qty": float(vm.receipt_qty),
        "reject_qty": float(vm.reject_qty),
        "pending_qty": pending,
        "challan_no": vm.challan_no,
        "expected_return_date": vm.expected_return_date,
        "age_days": age,
        "overdue": overdue,
        "remarks": vm.remarks,
    }


@router.get("/movements")
def list_movements(product_id: int | None = None, pending_only: bool = False,
                   db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    q = (
        select(VendorMovement, Product, Operation, Vendor)
        .join(Product, Product.id == VendorMovement.product_id)
        .join(RouteOperation, RouteOperation.id == VendorMovement.route_operation_id)
        .join(Operation, Operation.id == RouteOperation.operation_id)
        .join(Vendor, Vendor.id == VendorMovement.vendor_id)
        .order_by(VendorMovement.outward_date.desc())
    )
    if product_id:
        q = q.where(VendorMovement.product_id == product_id)
    rows = [_serialize(*r) for r in db.execute(q).all()]
    if pending_only:
        rows = [r for r in rows if r["pending_qty"] > 0]
    return rows


@router.post("/movements")
def create_movement(payload: VendorMovementCreate, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    route = db.get(RouteOperation, payload.route_operation_id)
    version = db.get(RouteVersion, route.route_version_id) if route else None
    if not route or not version or version.product_id != payload.product_id or not db.get(Vendor,payload.vendor_id):
        raise HTTPException(422, 'Product, route operation and vendor must match valid masters')
    if payload.outward_qty <= 0 or payload.receipt_qty or payload.reject_qty or payload.receipt_date:
        raise HTTPException(422, 'Outward quantity must be positive; record receipts separately')
    if payload.expected_return_date and payload.expected_return_date < payload.outward_date:
        raise HTTPException(422, 'Expected return cannot precede outward date')
    row = VendorMovement(**payload.model_dump())
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id}



class ReceiptCreate(BaseModel):
    receipt_date: date
    receipt_qty: Decimal = Field(gt=0)
    reject_qty: Decimal = Field(default=Decimal('0'), ge=0)
    reference: str = Field(min_length=1, max_length=160)
    remarks: str | None = None


def append_receipt(movement_id, payload, db, user):
    row = db.scalar(select(VendorMovement).where(VendorMovement.id == movement_id).with_for_update())
    if not row:
        raise HTTPException(404, 'Vendor movement not found')
    previous = db.scalar(select(VendorReceipt).where(VendorReceipt.movement_id == movement_id, VendorReceipt.reference == payload.reference))
    if previous:
        if previous.receipt_qty != payload.receipt_qty or previous.reject_qty != payload.reject_qty or previous.receipt_date != payload.receipt_date:
            raise HTTPException(409, 'Receipt reference already exists with different values')
        return {'id': previous.id, 'status': 'already_received', 'pending_qty': float(row.outward_qty-row.receipt_qty)}
    if payload.receipt_date < row.outward_date:
        raise HTTPException(422, 'Receipt date cannot precede outward date')
    if payload.reject_qty > payload.receipt_qty:
        raise HTTPException(422, 'Reject quantity is included in received quantity and cannot exceed it')
    if payload.receipt_qty > row.outward_qty-row.receipt_qty:
        raise HTTPException(409, 'Receipt exceeds pending quantity')
    receipt = VendorReceipt(movement_id=row.id, **payload.model_dump(), entered_by_id=user.id)
    db.add(receipt)
    row.receipt_qty += payload.receipt_qty
    row.reject_qty += payload.reject_qty
    row.receipt_date = max(row.receipt_date or payload.receipt_date,payload.receipt_date)
    db.commit(); db.refresh(receipt)
    return {'id': receipt.id, 'pending_qty': float(row.outward_qty-row.receipt_qty)}

@router.post('/movements/{movement_id}/receipts')
def add_receipt(movement_id: int, payload: ReceiptCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return append_receipt(movement_id,payload,db,user)

@router.get('/movements/{movement_id}/receipts')
def receipts(movement_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.scalars(select(VendorReceipt).where(VendorReceipt.movement_id==movement_id).order_by(VendorReceipt.receipt_date,VendorReceipt.id)).all()

@router.patch('/movements/{movement_id}/receipt')
def receive(movement_id: int, receipt_date: date, receipt_qty: float, reject_qty: float = 0,
            remarks: str | None = None, reference: str | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return append_receipt(movement_id, ReceiptCreate(receipt_date=receipt_date, receipt_qty=Decimal(str(receipt_qty)), reject_qty=Decimal(str(reject_qty)), reference=reference or uuid.uuid4().hex, remarks=remarks), db, user)
