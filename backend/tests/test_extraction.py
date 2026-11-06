import pytest

from services.extraction import (
    EmptyDocumentError,
    ExtractionError,
    FileTooLargeError,
    ScannedPdfError,
    UnsupportedFileTypeError,
    extract_text,
    normalize_text,
)
from tests.conftest import make_docx, make_pdf

MB = 1024 * 1024


def test_pdf_text_extracted() -> None:
    data = make_pdf(["Jane Developer", "Senior Python Engineer with 7 years of FastAPI experience."])
    doc = extract_text("cv.pdf", data, max_bytes=MB)
    assert doc.file_type == "pdf"
    assert doc.pages == 1
    assert "7 years of FastAPI experience" in doc.text


def test_scanned_pdf_raises_clear_error() -> None:
    with pytest.raises(ScannedPdfError, match="OCR needed"):
        extract_text("scan.pdf", make_pdf([]), max_bytes=MB)


def test_corrupt_pdf_raises_extraction_error() -> None:
    with pytest.raises(ExtractionError):
        extract_text("bad.pdf", b"%PDF-1.4\ngarbage that is not a pdf", max_bytes=MB)


def test_docx_paragraphs_and_tables() -> None:
    data = make_docx(
        ["Experienced data engineer building pipelines on Spark and Airflow."],
        table=[["Skills", "Python, SQL, Kafka"], ["Education", "BSc Computer Science"]],
    )
    doc = extract_text("cv.docx", data, max_bytes=MB)
    assert doc.file_type == "docx"
    assert "Spark and Airflow" in doc.text
    assert "Skills | Python, SQL, Kafka" in doc.text


def test_txt_utf8_and_cp1252_fallback() -> None:
    assert "Résumé" in extract_text("a.txt", "Résumé of a backend developer with Go".encode(), max_bytes=MB).text
    cp = "Café owner turned software developer, Java".encode("cp1252")
    assert "Café" in extract_text("b.txt", cp, max_bytes=MB).text


def test_file_too_large() -> None:
    with pytest.raises(FileTooLargeError):
        extract_text("big.txt", b"x" * 2048, max_bytes=1024)


@pytest.mark.parametrize("name", ["photo.png", "old.doc", "noext"])
def test_unsupported_types(name: str) -> None:
    with pytest.raises(UnsupportedFileTypeError):
        extract_text(name, b"some bytes here that are long enough to pass", max_bytes=MB)


def test_empty_and_near_empty() -> None:
    with pytest.raises(EmptyDocumentError):
        extract_text("e.txt", b"", max_bytes=MB)
    with pytest.raises(EmptyDocumentError):
        extract_text("e.txt", b"   hi   ", max_bytes=MB)


def test_normalize_text() -> None:
    raw = "eﬃcient  \t team player\r\n\r\n\r\n\r\nNext\x00 line  \n"
    assert normalize_text(raw) == "efficient team player\n\nNext line"
