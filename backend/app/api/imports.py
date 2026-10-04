import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..config import get_settings
from ..db import get_db
from ..models import ImportBatch, User
router = APIRouter(prefix="/import", tags=["import"])


@router.post('/excel')
@router.post('/historical-daily-mis')
@router.post('/historical-sales-prices')
def require_preview(user: User = Depends(get_current_user)):
    raise HTTPException(409, 'Preview and confirm this workbook using /api/import/preview first')


@router.get("/history")
def import_history(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.scalars(select(ImportBatch).order_by(ImportBatch.created_at.desc()).limit(100)).all()
    return [{
        "id": r.id, "file_name": r.file_name, "sha256": r.file_sha256,
        "imported_at": r.created_at, "status": r.status,
        "stats": json.loads(r.stats_json) if r.stats_json else {},
    } for r in rows]
