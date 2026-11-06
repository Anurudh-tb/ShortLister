"""Text extraction from PDF / DOCX / TXT uploads."""
import io
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import PurePath

import pdfplumber
from docx import Document

from models.schemas import FileType

logger = logging.getLogger(__name__)

# A PDF yielding fewer meaningful characters than this is treated as scanned/image-only.
MIN_TEXT_CHARS = 30

_EXT_TYPES: dict[str, FileType] = {".pdf": "pdf", ".docx": "docx", ".txt": "txt", ".md": "txt"}


class ExtractionError(Exception):
    code = "extraction_failed"


class UnsupportedFileTypeError(ExtractionError):
    code = "unsupported_file_type"


class FileTooLargeError(ExtractionError):
    code = "file_too_large"


class ScannedPdfError(ExtractionError):
    code = "scanned_pdf_ocr_needed"


class EmptyDocumentError(ExtractionError):
    code = "empty_document"


@dataclass
class ExtractedDocument:
    filename: str
    file_type: FileType
    text: str
    pages: int | None = None
    ocr_used: bool = False
    warnings: list[str] = field(default_factory=list)


def detect_file_type(filename: str, data: bytes) -> FileType:
    """Detect by magic bytes first, falling back to the extension."""
    if data[:5] == b"%PDF-":
        return "pdf"
    ext = PurePath(filename).suffix.lower()
    if data[:2] == b"PK" and ext == ".docx":
        return "docx"
    if ext == ".doc":
        raise UnsupportedFileTypeError(f"{filename}: legacy .doc is not supported; save it as .docx or PDF")
    if ext in _EXT_TYPES and _EXT_TYPES[ext] == "txt":
        return "txt"
    raise UnsupportedFileTypeError(f"{filename}: unsupported file type (use PDF, DOCX or TXT)")


def extract_text(filename: str, data: bytes, *, max_bytes: int, ocr_enabled: bool = False) -> ExtractedDocument:
    if len(data) > max_bytes:
        raise FileTooLargeError(
            f"{filename}: file is {len(data) / 1_048_576:.1f} MB; limit is {max_bytes / 1_048_576:.1f} MB"
        )
    if not data:
        raise EmptyDocumentError(f"{filename}: file is empty")

    file_type = detect_file_type(filename, data)
    if file_type == "pdf":
        doc = _extract_pdf(filename, data, ocr_enabled)
    elif file_type == "docx":
        doc = ExtractedDocument(filename, "docx", _extract_docx(filename, data))
    else:
        doc = ExtractedDocument(filename, "txt", _decode_text(data))

    doc.text = normalize_text(doc.text)
    if len(doc.text.strip()) < MIN_TEXT_CHARS:
        raise EmptyDocumentError(f"{filename}: no meaningful text could be extracted")
    logger.info("extracted %s type=%s chars=%d pages=%s", filename, doc.file_type, len(doc.text), doc.pages)
    return doc


def normalize_text(text: str) -> str:
    """NFKC (fixes ligatures/full-width chars), drop control chars, tidy whitespace."""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_pdf(filename: str, data: bytes, ocr_enabled: bool) -> ExtractedDocument:
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if getattr(pdf.doc, "is_extractable", True) is False:
                raise ExtractionError(f"{filename}: PDF is encrypted / copy-protected")
            pages_text = [page.extract_text() or "" for page in pdf.pages]
            n_pages = len(pdf.pages)
            text = "\n\n".join(pages_text)
            if len(re.sub(r"\s", "", text)) >= MIN_TEXT_CHARS:
                return ExtractedDocument(filename, "pdf", text, pages=n_pages)
            if not ocr_enabled:
                raise ScannedPdfError(
                    f"{filename}: this looks like a scanned PDF with no text layer; OCR needed "
                    "(enable OCR_ENABLED=true with Tesseract installed, or upload a text-based PDF/DOCX)"
                )
            return ExtractedDocument(
                filename, "pdf", _ocr_pdf(filename, pdf), pages=n_pages, ocr_used=True,
                warnings=["Text was extracted with OCR; quotes may contain recognition errors."],
            )
    except ExtractionError:
        raise
    except Exception as e:  # pdfminer/pdfplumber raise a wide variety of exception types
        logger.warning("pdf parse failure for %s: %s", filename, type(e).__name__)
        raise ExtractionError(f"{filename}: could not read PDF ({type(e).__name__})") from e


def _ocr_pdf(filename: str, pdf: "pdfplumber.PDF") -> str:
    try:
        import pytesseract  # optional dependency
    except ImportError as e:
        raise ScannedPdfError(f"{filename}: scanned PDF; OCR enabled but pytesseract is not installed") from e
    try:
        return "\n\n".join(
            pytesseract.image_to_string(page.to_image(resolution=300).original) for page in pdf.pages
        )
    except pytesseract.TesseractNotFoundError as e:
        raise ScannedPdfError(f"{filename}: scanned PDF; Tesseract binary not found for OCR") from e


def _extract_docx(filename: str, data: bytes) -> str:
    try:
        document = Document(io.BytesIO(data))
    except Exception as e:  # python-docx raises zipfile/KeyError/etc for bad files
        raise ExtractionError(f"{filename}: could not read DOCX ({type(e).__name__})") from e
    parts: list[str] = [p.text for p in document.paragraphs]
    # Many resume templates lay content out in tables; read cells too (deduplicating merged cells).
    for table in document.tables:
        for row in table.rows:
            cells: list[str] = []
            for cell in row.cells:
                t = cell.text.strip()
                if t and t not in cells:
                    cells.append(t)
            if cells:
                parts.append(" | ".join(cells))
    for section in document.sections:
        parts.extend(p.text for p in section.header.paragraphs)
    return "\n".join(parts)


def _decode_text(data: bytes) -> str:
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")
