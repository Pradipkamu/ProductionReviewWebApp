from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from pypdf import PdfReader
from reportlab.pdfgen import canvas

from app.services.action_evidence import EvidenceError, build_evidence_pdf
from app.services.file_security import hash_file


def sample_pdf():
    output = BytesIO()
    page = canvas.Canvas(output)
    page.drawString(50, 700, "Standard action plan")
    page.showPage()
    page.save()
    return output.getvalue()


def attachment(path: Path, idx: int, caption="Evidence"):
    return SimpleNamespace(
        id=idx, file_name=path.name, relative_path=path.name,
        sha256=hash_file(path), caption=caption,
    )


def test_evidence_pdf_includes_screenshot_and_pdf_without_changing_originals(tmp_path):
    image = tmp_path / "inspection.png"
    Image.new("RGB", (500, 300), "green").save(image)
    existing = tmp_path / "evidence.pdf"
    existing.write_bytes(sample_pdf())
    before = (hash_file(image), hash_file(existing))

    result = build_evidence_pdf(sample_pdf(), [
        attachment(image, 1, "Defect photograph"), attachment(existing, 2),
    ], str(tmp_path))
    reader = PdfReader(BytesIO(result))
    assert len(reader.pages) == 3
    assert "PHOTO / SCREENSHOT EVIDENCE" in reader.pages[1].extract_text()
    assert "Defect photograph" in reader.pages[1].extract_text()
    assert (hash_file(image), hash_file(existing)) == before


def test_evidence_pdf_rejects_tampered_attachment(tmp_path):
    image = tmp_path / "broken.png"
    Image.new("RGB", (50, 30), "blue").save(image)
    saved = attachment(image, 1)
    Image.new("RGB", (60, 30), "red").save(image)
    with pytest.raises(EvidenceError, match="integrity"):
        build_evidence_pdf(sample_pdf(), [saved], str(tmp_path))


def test_evidence_pdf_rejects_missing_attachment(tmp_path):
    missing = SimpleNamespace(
        id=3, file_name="missing.pdf", relative_path="missing.pdf",
        sha256="abc", caption="Missing",
    )
    with pytest.raises(EvidenceError, match="missing"):
        build_evidence_pdf(sample_pdf(), [missing], str(tmp_path))


def test_non_visual_attachments_remain_references(tmp_path):
    result = build_evidence_pdf(sample_pdf(), [SimpleNamespace(file_name="notes.csv")], str(tmp_path))
    assert len(PdfReader(BytesIO(result)).pages) == 1
