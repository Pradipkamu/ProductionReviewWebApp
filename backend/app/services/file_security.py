from __future__ import annotations

import hashlib
import os
import re
import stat
import zipfile
from pathlib import Path
from typing import BinaryIO
from xml.etree import ElementTree


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

OOXML_MAIN_CONTENT_TYPE = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
    ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.main+xml",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
}

MACRO_FREE_EXTENSIONS = {".xlsx", ".docx", ".pptx"}


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


def _validate_zip_members(path: Path, max_uncompressed_bytes: int) -> tuple[set[str], bytes]:
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
                if name in names:
                    raise UploadSecurityError("Office file contains duplicate internal entries")
                if info.flag_bits & 0x1:
                    raise UploadSecurityError("Encrypted Office files are not supported")
                file_type = (info.external_attr >> 16) & 0o170000
                if file_type == stat.S_IFLNK:
                    raise UploadSecurityError("Office file contains an unsafe symbolic link")
                if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                    raise UploadSecurityError("Office file uses an unsupported compression method")
                total += int(info.file_size or 0)
                if total > max_uncompressed_bytes:
                    raise UploadSecurityError("Office file expands beyond the permitted safety limit")
                names.add(name)
            if "[Content_Types].xml" not in names:
                raise UploadSecurityError("File is not a valid Office Open XML document")
            content_types_info = zf.getinfo("[Content_Types].xml")
            if content_types_info.file_size > 1024 * 1024:
                raise UploadSecurityError("Office content-type metadata exceeds the safety limit")
            content_types = zf.read(content_types_info)
            bad = zf.testzip()
            if bad:
                raise UploadSecurityError("Office file is damaged or failed integrity validation")
            return names, content_types
    except (zipfile.BadZipFile, RuntimeError) as exc:
        raise UploadSecurityError("File is not a valid Office Open XML document") from exc


def validate_office_file(path: Path, extension: str, max_uncompressed_bytes: int) -> None:
    extension = extension.lower()
    required = OOXML_REQUIRED.get(extension)
    if not required:
        raise UploadSecurityError("Unsupported Office file type")
    names, content_types_xml = _validate_zip_members(path, max_uncompressed_bytes)
    if required not in names:
        raise UploadSecurityError("Office document type does not match its file extension")
    try:
        root = ElementTree.fromstring(content_types_xml)
    except ElementTree.ParseError as exc:
        raise UploadSecurityError("Office content-type metadata is invalid") from exc
    required_part = "/" + required
    actual_types = {
        node.attrib.get("ContentType", "")
        for node in root
        if node.tag.rsplit("}", 1)[-1] == "Override" and node.attrib.get("PartName") == required_part
    }
    if not actual_types:
        required_extension = Path(required).suffix.lstrip(".")
        actual_types = {
            node.attrib.get("ContentType", "")
            for node in root
            if node.tag.rsplit("}", 1)[-1] == "Default"
            and node.attrib.get("Extension", "").lower() == required_extension.lower()
        }
    if OOXML_MAIN_CONTENT_TYPE[extension] not in actual_types:
        raise UploadSecurityError("Office document content does not match its file extension")
    lower_names = {name.lower() for name in names}
    if extension in MACRO_FREE_EXTENSIONS and any(
        name.endswith("vbaproject.bin") or "/activex/" in f"/{name}"
        for name in lower_names
    ):
        raise UploadSecurityError("Macro or ActiveX content is not allowed in this Office file type")


def validate_workbook_file(path: Path, original_name: str, max_uncompressed_bytes: int) -> str:
    ext = Path(original_name).suffix.lower()
    if ext not in {".xlsx", ".xlsm"}:
        raise UploadSecurityError("Use a valid .xlsx or .xlsm workbook")
    validate_office_file(path, ext, max_uncompressed_bytes)
    return ext


def _matches_signature(path: Path, ext: str) -> bool:
    with path.open("rb") as f:
        head = f.read(64)
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - 2048))
        tail = f.read()
    if ext == ".pdf":
        return head.startswith(b"%PDF-") and b"%%EOF" in tail
    if ext == ".png":
        return head.startswith(b"\x89PNG\r\n\x1a\n") and tail.endswith(b"IEND\xaeB`\x82")
    if ext in {".jpg", ".jpeg"}:
        return head.startswith(b"\xff\xd8\xff") and tail.endswith(b"\xff\xd9")
    if ext == ".webp":
        return (
            len(head) >= 16
            and head[:4] == b"RIFF"
            and head[8:12] == b"WEBP"
            and int.from_bytes(head[4:8], "little") + 8 == size
            and head[12:16] in {b"VP8 ", b"VP8L", b"VP8X"}
        )
    if ext in {".txt", ".csv"}:
        control_count = 0
        byte_count = 0
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                if b"\x00" in chunk:
                    return False
                byte_count += len(chunk)
                control_count += sum(byte < 32 and byte not in {9, 10, 13} for byte in chunk)
        return control_count <= max(1, byte_count // 100)
    return True


def validate_attachment_file(
    path: Path,
    original_name: str,
    allowed_extensions: set[str],
    max_uncompressed_bytes: int,
) -> str:
    ext = Path(original_name).suffix.lower()
    effective_extensions = allowed_extensions.intersection(SAFE_ATTACHMENT_MIME)
    if ext not in effective_extensions:
        allowed = ", ".join(sorted(effective_extensions)) or "none"
        raise UploadSecurityError(f"Attachment type is not allowed. Allowed: {allowed}")
    if ext in OOXML_REQUIRED:
        validate_office_file(path, ext, max_uncompressed_bytes)
    elif not _matches_signature(path, ext):
        raise UploadSecurityError("Attachment content does not match its file extension")
    return SAFE_ATTACHMENT_MIME[ext]
