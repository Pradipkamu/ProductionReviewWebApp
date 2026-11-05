from __future__ import annotations

from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET

from pypdf import PdfReader

MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_PDF_PAGES = 20
MAX_TEXT_CHARS = 50_000
MAX_ARCHIVE_MEMBERS = 200
SUPPORTED_OFFICE = {".docx", ".pptx", ".xlsx", ".xlsm"}


def _zip_text(path: Path) -> str | None:
    try:
        with zipfile.ZipFile(path) as archive:
            members = [n for n in archive.namelist() if n.lower().endswith(".xml")]
            if len(members) > MAX_ARCHIVE_MEMBERS:
                members = members[:MAX_ARCHIVE_MEMBERS]
            chunks: list[str] = []
            total = 0
            for name in members:
                try:
                    raw = archive.read(name)
                    if len(raw) > MAX_SOURCE_BYTES:
                        continue
                    root = ET.fromstring(raw)
                except Exception:
                    continue
                for node in root.iter():
                    text = (node.text or "").strip()
                    if not text:
                        continue
                    chunks.append(text)
                    total += len(text) + 1
                    if total >= MAX_TEXT_CHARS:
                        return "\n".join(chunks)[:MAX_TEXT_CHARS]
            return "\n".join(chunks)[:MAX_TEXT_CHARS]
    except (OSError, zipfile.BadZipFile):
        return None


def extract_searchable_text(path: Path) -> str | None:
    """Extract bounded local text from supported evidence files.

    Supported content: PDF, TXT, CSV and Office Open XML files (DOCX/PPTX/XLSX/XLSM).
    Macro payloads are never executed. Images remain metadata-only; OCR and external
    model upload are intentionally disabled.
    """
    suffix = path.suffix.lower()
    try:
        size = path.stat().st_size
        if size <= 0 or size > MAX_SOURCE_BYTES:
            return None

        if suffix in {".txt", ".csv"}:
            raw = path.read_bytes()[:MAX_SOURCE_BYTES]
            return raw.decode("utf-8-sig", errors="replace")[:MAX_TEXT_CHARS]

        if suffix == ".pdf":
            reader = PdfReader(str(path), strict=False)
            extracted = []
            for page in reader.pages[:MAX_PDF_PAGES]:
                text = page.extract_text() or ""
                if text:
                    extracted.append(text)
                if sum(len(item) for item in extracted) >= MAX_TEXT_CHARS:
                    break
            return "\n".join(extracted)[:MAX_TEXT_CHARS]

        if suffix in SUPPORTED_OFFICE:
            return _zip_text(path)

    except Exception:
        return None
    return None


def matching_excerpt(text: str, query: str, radius: int = 100) -> str:
    folded = text.casefold()
    index = folded.find(query.casefold())
    if index < 0:
        return text[: min(len(text), radius * 2)].strip()
    start = max(0, index - radius)
    end = min(len(text), index + len(query) + radius)
    excerpt = " ".join(text[start:end].split())
    if start:
        excerpt = "…" + excerpt
    if end < len(text):
        excerpt += "…"
    return excerpt
