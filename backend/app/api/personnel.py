from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import Personnel, User
from ..schemas import PersonnelCreate

router = APIRouter(prefix="/personnel", tags=["personnel"])


def _personnel_name(first_name: str, last_name: str):
    first = " ".join(first_name.strip().split())
    last = " ".join(last_name.strip().split())
    if not first or not last:
        raise HTTPException(422, "First name and surname are required")
    full = f"{first} {last}"
    return first, last, full, full.casefold()


@router.get("")
def list_personnel(q: str = "", db: Session = Depends(get_db),
                   _: User = Depends(get_current_user)):
    query = select(Personnel).where(Personnel.is_active.is_(True))
    term = " ".join(q.strip().split()).casefold()
    if term:
        query = query.where(Personnel.normalized_name.contains(term))
    rows = db.scalars(query.order_by(Personnel.first_name, Personnel.last_name).limit(500)).all()
    return [{"id": x.id, "first_name": x.first_name, "last_name": x.last_name,
             "full_name": x.full_name, "is_active": x.is_active} for x in rows]


@router.post("")
def create_personnel(payload: PersonnelCreate, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    first, last, full, normalized = _personnel_name(payload.first_name, payload.last_name)
    duplicates = db.scalars(select(Personnel).where(
        Personnel.normalized_name == normalized, Personnel.is_active.is_(True)
    )).all()
    row = Personnel(first_name=first, last_name=last, full_name=full,
                    normalized_name=normalized, created_by_id=user.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "first_name": row.first_name, "last_name": row.last_name,
            "full_name": row.full_name, "is_active": row.is_active,
            "duplicate_warning": bool(duplicates), "created": True}


