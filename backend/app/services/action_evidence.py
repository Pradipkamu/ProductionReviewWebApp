"""Create an optional PDF containing embedded evidence; never alter original uploads."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import subprocess

from PIL import Image, ImageOps, UnidentifiedImageError
from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from .file_security import UploadSecurityError, hash_file, safe_path

MAX_EVIDENCE_FILES = 30
MAX_PAGES_PER_FILE = 40
MAX_TOTAL_PAGES = 150
MAX_TOTAL_BYTES = 120 * 1024 * 1024
MAX_IMAGE_PIXELS = 24_000_000


class EvidenceError(ValueError):
    pass


def _image_pdf(path: Path, title: str, caption: str) -> bytes:
    # Verify format and bound decompression before decoding the image.
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        with Image.open(path) as source:
            if source.width * source.height > MAX_IMAGE_PIXELS:
                raise EvidenceError("Image pixel limit exceeded")
            picture = ImageOps.exif_transpose(source).convert("RGB")
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise EvidenceError("Unable to process image evidence") from exc
    buffer = BytesIO()
    width, height = landscape(A4)
    pdf = canvas.Canvas(buffer, pagesize=(width, height))
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(32, height - 37, "PHOTO / SCREENSHOT EVIDENCE")
    pdf.setFont("Helvetica", 8)
    pdf.drawString(32, height - 55, title[:125])
    if caption:
        pdf.drawString(32, height - 69, caption[:125])
    max_width, max_height = width - 64, height - 110
    scale = min(max_width / picture.width, max_height / picture.height)
    draw_width, draw_height = picture.width * scale, picture.height * scale
    pdf.drawImage(ImageReader(picture), (width - draw_width) / 2, 20,
                  width=draw_width, height=draw_height)
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def _convert_pptx(path: Path, work: Path) -> Path:
    # Keep conversion files and LibreOffice configuration isolated per request.
    output = work / "converted"
    output.mkdir()
    profile = (work / "lo_profile").as_uri()
    command = [
        "libreoffice", f"-env:UserInstallation={profile}",
        "--headless", "--convert-to", "pdf:impress_pdf_Export",
        "--outdir", str(output), str(path),
    ]
    try:
        subprocess.run(
            command, check=True, capture_output=True, timeout=45,
            env={**os.environ, "HOME": str(work)},
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise EvidenceError("PowerPoint conversion failed or exceeded 45 seconds") from exc
    converted = output / (path.stem + ".pdf")
    if not converted.is_file() or converted.stat().st_size == 0:
        raise EvidenceError("PowerPoint conversion produced no PDF")
    return converted


def _read_pdf(path: Path | BytesIO) -> PdfReader:
    try:
        reader = PdfReader(path, strict=True)
        if reader.is_encrypted:
            raise EvidenceError("Encrypted PDF attachments are not supported")
        return reader
    except EvidenceError:
        raise
    except Exception as exc:
        raise EvidenceError("Invalid or unsupported PDF evidence") from exc


def build_evidence_pdf(base_pdf: bytes, attachments: list, storage_dir: str) -> bytes:
    """Combine a standard action plan with verified screenshots, PDFs and converted PPTX."""
    if len(attachments) > MAX_EVIDENCE_FILES:
        raise EvidenceError(f"Maximum {MAX_EVIDENCE_FILES} attachments per evidence PDF")
    writer = PdfWriter()
    writer.append(_read_pdf(BytesIO(base_pdf)))
    total_pages = len(writer.pages)
    total_bytes = 0

    with TemporaryDirectory(prefix="action_evidence_") as directory:
        work = Path(directory)
        for entry in attachments:
            extension = Path(entry.file_name).suffix.lower()
            if extension not in {".png", ".jpg", ".jpeg", ".webp", ".pdf", ".pptx"}:
                continue  # Other originals remain referenced in the plan's evidence table.
            try:
                source = safe_path(storage_dir, entry.relative_path)
            except UploadSecurityError as exc:
                raise EvidenceError("Unsafe evidence path") from exc
            if not source.is_file() or source.is_symlink():
                raise EvidenceError(f"Attachment missing: {entry.file_name}")
            size = source.stat().st_size
            total_bytes += size
            if size <= 0 or total_bytes > MAX_TOTAL_BYTES:
                raise EvidenceError("Evidence attachment size limit exceeded")
            if hash_file(source) != entry.sha256:
                raise EvidenceError(f"Attachment integrity check failed: {entry.file_name}")
            if extension in {".png", ".jpg", ".jpeg", ".webp"}:
                data = _image_pdf(source, entry.file_name, entry.caption or "")
                reader = _read_pdf(BytesIO(data))
            elif extension == ".pptx":
                # Copy to an isolated workdir; never rewrite the original attachment.
                slide = work / f"evidence_{entry.id}.pptx"
                slide.write_bytes(source.read_bytes())
                try:
                    reader = _read_pdf(_convert_pptx(slide, work))
                    # Consume converted PDF before temporary directory cleanup.
                    pages = len(reader.pages)
                    if pages > MAX_PAGES_PER_FILE or total_pages + pages > MAX_TOTAL_PAGES:
                        raise EvidenceError("Evidence page limit exceeded")
                    writer.append(reader)
                    total_pages += pages
                finally:
                    (work / "converted" / f"{slide.stem}.pdf").unlink(missing_ok=True)
                    (work / "converted").rmdir() if (work / "converted").exists() and not list((work / "converted").iterdir()) else None
                continue
            else:
                reader = _read_pdf(source)
            pages = len(reader.pages)
            if pages > MAX_PAGES_PER_FILE or total_pages + pages > MAX_TOTAL_PAGES:
                raise EvidenceError("Evidence page limit exceeded")
            writer.append(reader)
            total_pages += pages
    output = BytesIO()
    writer.write(output)
    if output.tell() > MAX_TOTAL_BYTES:
        raise EvidenceError("Evidence PDF exceeds the output size limit")
    return output.getvalue()
