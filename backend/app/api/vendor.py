from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import Product, RouteOperation, Operation, User, Vendor, VendorMovement
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
    row = VendorMovement(**payload.model_dump())
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id}


@router.patch("/movements/{movement_id}/receipt")
def receive(movement_id: int, receipt_date: date, receipt_qty: float, reject_qty: float = 0,
            remarks: str | None = None, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    row = db.get(VendorMovement, movement_id)
    if not row:
        from fastapi import HTTPException
        raise HTTPException(404, "Vendor movement not found")
    row.receipt_date = receipt_date
    row.receipt_qty = receipt_qty
    row.reject_qty = reject_qty
    if remarks is not None:
        row.remarks = remarks
    db.commit(); db.refresh(row)
    return {"id": row.id, "pending_qty": float(row.outward_qty - row.receipt_qty)}
