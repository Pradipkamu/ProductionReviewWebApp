from __future__ import annotations

import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from .. import __version__
from ..auth import get_current_user
from ..config import get_settings
from ..db import get_db
from ..models import User

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])
settings = get_settings()


def _storage_check(name: str, raw_path: str) -> dict:
    path = Path(raw_path)
    exists = path.exists()
    is_directory = path.is_dir()
    writable = exists and is_directory and os.access(path, os.W_OK)
    result = {
        "name": name,
        "status": "ok" if writable else "error",
        "exists": exists,
        "writable": writable,
    }
    try:
        usage_path = path if exists else path.parent
        usage = shutil.disk_usage(usage_path)
        result.update(free_bytes=usage.free, total_bytes=usage.total)
    except OSError as exc:
        result["detail"] = f"Storage capacity unavailable: {exc.__class__.__name__}"
    return result


def _backup_check(raw_path: str) -> dict:
    path = Path(raw_path)
    if not path.is_dir():
        return {"status": "error", "detail": "Backup directory is unavailable"}
    try:
        candidates = [p for pattern in ("*.dump", "*.sql") for p in path.glob(pattern) if p.is_file()]
    except OSError as exc:
        return {"status": "error", "detail": f"Backup directory cannot be read: {exc.__class__.__name__}"}
    if not candidates:
        return {"status": "warning", "detail": "No database backup found"}
    latest = max(candidates, key=lambda p: p.stat().st_mtime)
    modified = datetime.fromtimestamp(latest.stat().st_mtime, timezone.utc)
    age_hours = max(0, (datetime.now(timezone.utc) - modified).total_seconds() / 3600)
    checksum = Path(str(latest) + ".sha256").is_file()
    status = "ok" if checksum and age_hours <= 24 * 7 else "warning"
    detail = "Latest backup has a SHA-256 sidecar" if status == "ok" else (
        "Latest backup is older than 7 days" if age_hours > 24 * 7 else "Latest backup has no SHA-256 sidecar"
    )
    return {
        "status": status,
        "detail": detail,
        "file_name": latest.name,
        "size_bytes": latest.stat().st_size,
        "modified_at": modified.isoformat(),
        "age_hours": round(age_hours, 1),
        "checksum_present": checksum,
    }


@router.get("")
def diagnostics(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    started = time.perf_counter()
    database = {"status": "error", "dialect": db.bind.dialect.name}
    try:
        db.execute(text("SELECT 1"))
        inspector = inspect(db.bind)
        schema_version = None
        if inspector.has_table("alembic_version"):
            schema_version = db.scalar(text("SELECT version_num FROM alembic_version"))
        database.update(
            status="ok",
            schema_version=schema_version or "unversioned/test schema",
            latency_ms=round((time.perf_counter() - started) * 1000, 1),
        )
    except Exception as exc:
        database["detail"] = f"Database check failed: {exc.__class__.__name__}"

    storage = [
        _storage_check("Imports", settings.upload_dir),
        _storage_check("Attachments", settings.attachments_dir),
        _storage_check("Backups", settings.backup_dir),
    ]
    backup = _backup_check(settings.backup_dir)
    statuses = [database["status"], backup["status"], *(item["status"] for item in storage)]
    overall = "error" if "error" in statuses else "warning" if "warning" in statuses else "ok"
    return {
        "status": overall,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "backend": {"status": "ok", "version": __version__, "environment": settings.environment},
        "database": database,
        "storage": storage,
        "backup": backup,
    }
