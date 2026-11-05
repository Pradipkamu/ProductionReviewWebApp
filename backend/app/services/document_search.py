from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_PDF_PAGES = 20
MAX_TEXT_CHARS = 50_000


def extract_searchable_text(path: Path) -> str | None:
    """Extract bounded local text from PDF, TXT and CSV evidence files.

    Office files and images intentionally remain metadata-searchable only in
    this first release. No OCR, macro execution, remote fetch or external model
    upload occurs here.
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

    except Exception:
        # A malformed or encrypted document should not break the search for
        # other records. Its filename and caption remain searchable.
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
