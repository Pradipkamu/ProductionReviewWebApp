from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import zipfile
from pathlib import Path
from typing import BinaryIO


class UploadSecurityError(ValueError):
    def __init__(self, detail: str, status_code: int = 422):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


SAFE_ATTACHMENT_MIME = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".txt": "text/plain",
    ".csv": "text/csv",
}

OOXML_REQUIRED = {
    ".xlsx": "xl/workbook.xml",
    ".xlsm": "xl/workbook.xml",
    ".docx": "word/document.xml",
    ".pptx": "ppt/presentation.xml",
}


def safe_original_name(name: str | None, fallback: str = "upload") -> str:
    raw = Path(name or fallback).name.strip()
    raw = re.sub(r"[\x00-\x1f\x7f]+", "_", raw)
    raw = re.sub(r"[^A-Za-z0-9 ._()\-]+", "_", raw).strip(" .")
    if not raw:
        raw = fallback
    if len(raw) > 180:
        suffix = Path(raw).suffix[:15]
        raw = raw[: max(1, 180 - len(suffix))].rstrip(" .") + suffix
    return raw


def safe_path(base: str | Path, relative: str | Path) -> Path:
    root = Path(base).resolve()
    target = (root / relative).resolve()
    if target != root and root not in target.parents:
        raise UploadSecurityError("Unsafe storage path", 400)
    return target


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def save_limited_stream(source: BinaryIO, target: Path, max_bytes: int) -> tuple[int, str]:
    target.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    h = hashlib.sha256()
    try:
        with target.open("xb") as output:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise UploadSecurityError(
                        f"Upload exceeds the {max_bytes // (1024 * 1024)} MB limit",
                        413,
                    )
                h.update(chunk)
                output.write(chunk)
        if size == 0:
            raise UploadSecurityError("Uploaded file is empty", 400)
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
        return size, h.hexdigest()
    except Exception:
        target.unlink(missing_ok=True)
        raise


def _validate_zip_members(path: Path, max_uncompressed_bytes: int) -> set[str]:
    try:
        with zipfile.ZipFile(path, "r") as zf:
            infos = zf.infolist()
            if len(infos) > 5000:
                raise UploadSecurityError("Office file contains too many internal entries")
            total = 0
            names: set[str] = set()
            for info in infos:
                name = info.filename.replace("\\", "/")
                parts = [p for p in name.split("/") if p]
                if name.startswith("/") or any(p == ".." for p in parts):
                    raise UploadSecurityError("Office file contains an unsafe internal path")
                total += int(info.file_size or 0)
                if total > max_uncompressed_bytes:
                    raise UploadSecurityError("Office file expands beyond the permitted safety limit")
                names.add(name)
            if "[Content_Types].xml" not in names:
                raise UploadSecurityError("File is not a valid Office Open XML document")
            bad = zf.testzip()
            if bad:
                raise UploadSecurityError("Office file is damaged or failed integrity validation")
            return names
    except zipfile.BadZipFile as exc:
        raise UploadSecurityError("File is not a valid Office Open XML document") from exc


def validate_office_file(path: Path, extension: str, max_uncompressed_bytes: int) -> None:
    required = OOXML_REQUIRED.get(extension.lower())
    if not required:
        raise UploadSecurityError("Unsupported Office file type")
    names = _validate_zip_members(path, max_uncompressed_bytes)
    if required not in names:
        raise UploadSecurityError("Office document type does not match its file extension")


def validate_workbook_file(path: Path, original_name: str, max_uncompressed_bytes: int) -> str:
    ext = Path(original_name).suffix.lower()
    if ext not in {".xlsx", ".xlsm"}:
        raise UploadSecurityError("Use a valid .xlsx or .xlsm workbook")
    validate_office_file(path, ext, max_uncompressed_bytes)
    return ext


def _matches_signature(path: Path, ext: str) -> bool:
    with path.open("rb") as f:
        head = f.read(64)
    if ext == ".pdf":
        return head.startswith(b"%PDF-")
    if ext == ".png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if ext in {".jpg", ".jpeg"}:
        return head.startswith(b"\xff\xd8\xff")
    if ext == ".webp":
        return len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    if ext in {".txt", ".csv"}:
        return b"\x00" not in head
    return True


def validate_attachment_file(
    path: Path,
    original_name: str,
    allowed_extensions: set[str],
    max_uncompressed_bytes: int,
) -> str:
    ext = Path(original_name).suffix.lower()
    if ext not in allowed_extensions or ext not in SAFE_ATTACHMENT_MIME:
        allowed = ", ".join(sorted(allowed_extensions))
        raise UploadSecurityError(f"Attachment type is not allowed. Allowed: {allowed}")
    if ext in OOXML_REQUIRED:
        validate_office_file(path, ext, max_uncompressed_bytes)
    elif not _matches_signature(path, ext):
        raise UploadSecurityError("Attachment content does not match its file extension")
    return SAFE_ATTACHMENT_MIME.get(ext) or mimetypes.guess_type(original_name)[0] or "application/octet-stream"
