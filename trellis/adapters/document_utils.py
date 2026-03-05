"""Document text extraction and chunking utilities.

Supports: PDF (PyPDF2), DOCX (python-docx), TXT, CSV, Markdown.
Graceful degradation when optional libraries are not installed.
"""

import csv
import io
import logging
from typing import Any

logger = logging.getLogger("trellis.adapters.document")

# Optional PDF support
try:
    from PyPDF2 import PdfReader
    HAS_PYPDF2 = True
except ImportError:
    HAS_PYPDF2 = False

# Optional DOCX support
try:
    from docx import Document as DocxDocument
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False


SUPPORTED_CONTENT_TYPES = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/plain": "txt",
    "text/csv": "csv",
    "text/markdown": "markdown",
}

EXTENSION_MAP = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".txt": "txt",
    ".csv": "csv",
    ".md": "markdown",
}


class ExtractionError(Exception):
    """Raised when text cannot be extracted from a document."""
    pass


def detect_format(filename: str, content_type: str | None = None) -> str:
    """Detect document format from filename extension or content type.

    Returns one of: pdf, docx, txt, csv, markdown.
    Raises ExtractionError if format is unsupported.
    """
    if content_type and content_type in SUPPORTED_CONTENT_TYPES:
        return SUPPORTED_CONTENT_TYPES[content_type]

    lower = filename.lower()
    for ext, fmt in EXTENSION_MAP.items():
        if lower.endswith(ext):
            return fmt

    raise ExtractionError(f"Unsupported document format: {filename} (content_type={content_type})")


def extract_text(data: bytes, fmt: str, filename: str = "") -> list[dict[str, Any]]:
    """Extract text from document bytes.

    Returns a list of page dicts: [{"page": 1, "text": "..."}, ...]
    For non-paginated formats, returns a single entry with page=1.
    """
    if fmt == "pdf":
        return _extract_pdf(data, filename)
    elif fmt == "docx":
        return _extract_docx(data, filename)
    elif fmt == "txt" or fmt == "markdown":
        return _extract_text(data)
    elif fmt == "csv":
        return _extract_csv(data)
    else:
        raise ExtractionError(f"No extractor for format: {fmt}")


def _extract_pdf(data: bytes, filename: str) -> list[dict[str, Any]]:
    if not HAS_PYPDF2:
        raise ExtractionError(
            "PyPDF2 is not installed. Install it with: pip install PyPDF2"
        )
    reader = PdfReader(io.BytesIO(data))
    pages = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if text.strip():
            pages.append({"page": i + 1, "text": text})
    if not pages:
        logger.warning(f"No text extracted from PDF: {filename}")
        pages.append({"page": 1, "text": ""})
    return pages


def _extract_docx(data: bytes, filename: str) -> list[dict[str, Any]]:
    if not HAS_DOCX:
        raise ExtractionError(
            "python-docx is not installed. Install it with: pip install python-docx"
        )
    doc = DocxDocument(io.BytesIO(data))
    text = "\n".join(p.text for p in doc.paragraphs)
    return [{"page": 1, "text": text}]


def _extract_text(data: bytes) -> list[dict[str, Any]]:
    text = data.decode("utf-8", errors="replace")
    return [{"page": 1, "text": text}]


def _extract_csv(data: bytes) -> list[dict[str, Any]]:
    text = data.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    # Convert to readable text: header + rows
    if not rows:
        return [{"page": 1, "text": ""}]
    formatted = "\n".join(", ".join(row) for row in rows)
    return [{"page": 1, "text": formatted}]


def chunk_text(
    text: str,
    chunk_size: int = 1000,
    overlap: int = 200,
) -> list[str]:
    """Split text into overlapping chunks.

    Args:
        text: The text to chunk.
        chunk_size: Maximum characters per chunk.
        overlap: Number of overlapping characters between consecutive chunks.

    Returns:
        List of text chunks.
    """
    if not text or not text.strip():
        return []
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0:
        raise ValueError("overlap must be non-negative")
    if overlap >= chunk_size:
        raise ValueError("overlap must be less than chunk_size")

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks
