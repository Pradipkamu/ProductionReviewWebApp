from pathlib import Path
import hashlib
import json
import shutil
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..config import get_settings
from ..db import get_db
from ..models import ImportBatch, User
from ..services.excel_import import import_daily_production_workbook
from ..services.historical_mis_import import import_historical_daily_mis
from ..services.historical_price_import import import_historical_sales_prices

router = APIRouter(prefix="/import", tags=["import"])


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@router.post("/excel")
def import_excel(file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "Please upload an .xlsx or .xlsm file")
    settings = get_settings()
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    path = upload_dir / f"{uuid.uuid4().hex}_{Path(file.filename).name}"
    with path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    digest = _sha256(path)
    previous = db.scalar(select(ImportBatch).where(ImportBatch.file_sha256 == digest))
    if previous:
        # Keep the newly uploaded duplicate out of persistent storage. The original
        # import batch remains the audit record.
        path.unlink(missing_ok=True)
        stats = json.loads(previous.stats_json) if previous.stats_json else {}
        return {
            "status": "already_imported",
            "message": f"This exact workbook was already imported as batch #{previous.id}. No data was duplicated.",
            "import_batch_id": previous.id,
            "previous_file_name": previous.file_name,
            **stats,
        }

    try:
        stats = import_daily_production_workbook(db, path)
        batch = ImportBatch(
            file_name=Path(file.filename).name,
            file_sha256=digest,
            imported_by_id=user.id,
            status="COMPLETED",
            stats_json=json.dumps(stats, default=str),
        )
        db.add(batch)
        db.commit(); db.refresh(batch)
        return {
            "status": "imported",
            "message": "Import completed. Existing date/product keys were updated or left unchanged; new rows were inserted.",
            "import_batch_id": batch.id,
            **stats,
        }
    except Exception as exc:
        db.rollback()
        raise HTTPException(400, f"Import failed: {exc}") from exc


@router.post("/historical-daily-mis")
def import_historical_mis(file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "Please upload an .xlsx or .xlsm file")
    settings = get_settings()
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    path = upload_dir / f"{uuid.uuid4().hex}_{Path(file.filename).name}"
    with path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    digest = _sha256(path)
    previous = db.scalar(select(ImportBatch).where(ImportBatch.file_sha256 == digest))
    if previous:
        path.unlink(missing_ok=True)
        stats = json.loads(previous.stats_json) if previous.stats_json else {}
        return {
            "status": "already_imported",
            "message": f"This exact historical MIS workbook was already imported as batch #{previous.id}. No data was duplicated.",
            "import_batch_id": previous.id,
            **stats,
        }
    try:
        stats = import_historical_daily_mis(db, path)
        batch = ImportBatch(
            file_name=Path(file.filename).name, file_sha256=digest, imported_by_id=user.id,
            status="COMPLETED", stats_json=json.dumps(stats, default=str),
        )
        db.add(batch); db.commit(); db.refresh(batch)
        return {
            "status": "imported",
            "message": "Historical Daily MIS import completed. Existing Date + Product records were updated safely; September and other dates not in the file were untouched.",
            "import_batch_id": batch.id,
            **stats,
        }
    except Exception as exc:
        db.rollback()
        raise HTTPException(400, f"Historical MIS import failed: {exc}") from exc


@router.post("/historical-sales-prices")
def import_historical_prices(file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "Please upload an .xlsx or .xlsm file")
    settings = get_settings()
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    path = upload_dir / f"{uuid.uuid4().hex}_{Path(file.filename).name}"
    with path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    digest = _sha256(path)
    previous = db.scalar(select(ImportBatch).where(ImportBatch.file_sha256 == digest))
    if previous:
        path.unlink(missing_ok=True)
        stats = json.loads(previous.stats_json) if previous.stats_json else {}
        return {
            "status": "already_imported",
            "message": f"This exact historical sales-price workbook was already imported as batch #{previous.id}. No data was duplicated.",
            "import_batch_id": previous.id,
            **stats,
        }
    try:
        stats = import_historical_sales_prices(db, path, user.id)
        batch = ImportBatch(
            file_name=Path(file.filename).name, file_sha256=digest, imported_by_id=user.id,
            status="COMPLETED", stats_json=json.dumps(stats, default=str),
        )
        db.add(batch); db.commit(); db.refresh(batch)
        return {
            "status": "imported",
            "message": "Historical sales-price import completed. Effective-date ranges were normalized automatically and existing MIS sales were recalculated where applicable.",
            "import_batch_id": batch.id,
            **stats,
        }
    except Exception as exc:
        db.rollback()
        raise HTTPException(400, f"Historical sales-price import failed: {exc}") from exc


@router.get("/history")
def import_history(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.scalars(select(ImportBatch).order_by(ImportBatch.created_at.desc()).limit(100)).all()
    return [{
        "id": r.id, "file_name": r.file_name, "sha256": r.file_sha256,
        "imported_at": r.created_at, "status": r.status,
        "stats": json.loads(r.stats_json) if r.stats_json else {},
    } for r in rows]
