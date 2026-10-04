from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from .. import __version__
from ..auth import get_current_user
from ..config import get_settings
from ..db import get_db
from ..models import User

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])
settings = get_settings()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


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
        return {"status": "error", "detail": "Backup directory is unavailable", "count": 0, "total_bytes": 0}
    try:
        candidates = [p for pattern in ("*.dump", "*.sql") for p in path.glob(pattern) if p.is_file()]
    except OSError as exc:
        return {"status": "error", "detail": f"Backup directory cannot be read: {exc.__class__.__name__}", "count": 0, "total_bytes": 0}
    if not candidates:
        return {"status": "warning", "detail": "No database backup found", "count": 0, "total_bytes": 0}

    latest = max(candidates, key=lambda p: p.stat().st_mtime)
    modified = datetime.fromtimestamp(latest.stat().st_mtime, timezone.utc)
    age_hours = max(0, (datetime.now(timezone.utc) - modified).total_seconds() / 3600)
    sidecar = Path(str(latest) + ".sha256")
    checksum_present = sidecar.is_file()
    checksum_valid = False
    checksum_detail = "No SHA-256 sidecar"
    if checksum_present:
        try:
            expected = sidecar.read_text(encoding="utf-8").strip().split()[0].lower()
            actual = _sha256(latest)
            checksum_valid = len(expected) == 64 and expected == actual
            checksum_detail = "SHA-256 verified" if checksum_valid else "SHA-256 mismatch"
        except Exception as exc:
            checksum_detail = f"Checksum could not be verified: {exc.__class__.__name__}"

    fresh = age_hours <= settings.backup_max_age_hours
    custom_format = latest.suffix.lower() == ".dump"
    if checksum_present and not checksum_valid:
        status = "error"
        detail = checksum_detail
    elif not fresh:
        status = "warning"
        detail = f"Latest backup is older than {settings.backup_max_age_hours} hours"
    elif not checksum_present:
        status = "warning"
        detail = "Latest backup has no SHA-256 sidecar"
    elif not custom_format:
        status = "warning"
        detail = "Latest backup is legacy SQL format; use verified .dump backups"
    else:
        status = "ok"
        detail = "Latest custom-format backup is fresh and SHA-256 verified"

    return {
        "status": status,
        "detail": detail,
        "file_name": latest.name,
        "format": "CUSTOM" if custom_format else "SQL",
        "size_bytes": latest.stat().st_size,
        "modified_at": modified.isoformat(),
        "age_hours": round(age_hours, 1),
        "checksum_present": checksum_present,
        "checksum_valid": checksum_valid,
        "count": len(candidates),
        "total_bytes": sum(p.stat().st_size for p in candidates),
    }


def _restore_verification_check(raw_path: str) -> dict:
    root = Path(raw_path)
    marker = root / "restore_verification.json"
    if not marker.is_file():
        return {"status": "warning", "detail": "No successful isolated restore verification has been recorded"}
    try:
        data = json.loads(marker.read_text(encoding="utf-8-sig"))
        verified = datetime.fromisoformat(str(data["verified_at"]).replace("Z", "+00:00"))
        if verified.tzinfo is None:
            verified = verified.replace(tzinfo=timezone.utc)
        age_days = max(0, (datetime.now(timezone.utc) - verified.astimezone(timezone.utc)).total_seconds() / 86400)
        backup_name = Path(str(data["backup_file"])).name
        backup = root / backup_name
        if not backup.is_file():
            return {"status": "warning", "detail": "Last verified backup is no longer present", **data, "age_days": round(age_days, 1)}
        expected = str(data.get("backup_sha256") or "").lower()
        if expected and _sha256(backup) != expected:
            return {"status": "error", "detail": "Last restore-verified backup now fails SHA-256 validation", **data, "age_days": round(age_days, 1)}
        fresh = age_days <= settings.restore_verify_max_age_days
        return {
            **data,
            "status": "ok" if fresh else "warning",
            "detail": "Isolated restore verification is current" if fresh else f"Restore verification is older than {settings.restore_verify_max_age_days} days",
            "age_days": round(age_days, 1),
        }
    except Exception as exc:
        return {"status": "error", "detail": f"Restore verification marker is invalid: {exc.__class__.__name__}"}


def _security_configuration() -> dict:
    checks: list[dict] = []

    secret_ok = len(settings.secret_key) >= 32 and len(set(settings.secret_key)) >= 12
    checks.append({
        "name": "Application secret",
        "status": "ok" if secret_ok else "error",
        "detail": "Persistent strong SECRET_KEY configured" if secret_ok else "SECRET_KEY is weak or invalid",
    })

    db_password_status = "ok"
    db_password_detail = "Database credential is not applicable to this database dialect"
    try:
        url = make_url(settings.database_url)
        if url.drivername.startswith("postgresql"):
            password = url.password or ""
            weak_values = {"pms", "postgres", "password", "changeme", "change_me"}
            db_password_status = "warning" if len(password) < 24 or password.lower() in weak_values or "change_this" in password.lower() else "ok"
            db_password_detail = "Database password is strong" if db_password_status == "ok" else "Legacy/weak database password detected; rotate it with the supplied rotation script"
    except Exception:
        db_password_status = "error"
        db_password_detail = "DATABASE_URL could not be parsed"
    checks.append({"name": "Database credential", "status": db_password_status, "detail": db_password_detail})

    bootstrap_default = settings.admin_password == "ChangeMe123!" or "change_this" in settings.admin_password.lower()
    checks.append({
        "name": "Bootstrap admin credential",
        "status": "warning" if bootstrap_default else "ok",
        "detail": "Bootstrap ADMIN_PASSWORD is still a known/default value in environment" if bootstrap_default else "Bootstrap ADMIN_PASSWORD is non-default",
    })

    loopback = {"127.0.0.1", "localhost", "::1"}
    db_private = settings.db_bind in loopback
    backend_private = settings.backend_bind in loopback
    checks.append({
        "name": "PostgreSQL host binding",
        "status": "ok" if db_private else "warning",
        "detail": f"Bound to {settings.db_bind}; localhost-only is recommended",
    })
    checks.append({
        "name": "FastAPI host binding",
        "status": "ok" if backend_private else "warning",
        "detail": f"Bound to {settings.backend_bind}; localhost-only is recommended",
    })

    statuses = [x["status"] for x in checks]
    status = "error" if "error" in statuses else "warning" if "warning" in statuses else "ok"
    return {"status": status, "checks": checks}


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
    restore_verification = _restore_verification_check(settings.backup_dir)
    security = _security_configuration()
    uploads = {
        "status": "ok",
        "import_max_mb": settings.import_max_mb,
        "attachment_max_mb": settings.attachment_max_mb,
        "office_max_uncompressed_mb": settings.office_max_uncompressed_mb,
        "allowed_attachment_extensions": sorted(settings.attachment_extension_set),
        "detail": "Extension, content signature/OOXML structure, size and expanded Office size are validated",
    }
    statuses = [
        database["status"],
        backup["status"],
        restore_verification["status"],
        security["status"],
        *(item["status"] for item in storage),
    ]
    overall = "error" if "error" in statuses else "warning" if "warning" in statuses else "ok"
    return {
        "status": overall,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "backend": {"status": "ok", "version": __version__, "environment": settings.environment},
        "database": database,
        "storage": storage,
        "backup": backup,
        "restore_verification": restore_verification,
        "security": security,
        "uploads": uploads,
    }
