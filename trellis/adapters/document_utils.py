"""Document text extraction and chunking utilities.

Supports: PDF (PyPDF2), DOCX (python-docx), TXT, CSV, Markdown.
Graceful degradation when optional libraries are not installed.
"""

import csv
import io
import logging
import re
import xml.etree.ElementTree as ET
from typing import Any

logger = logging.getLogger("trellis.adapters.document")

# Optional PDF support — try PyMuPDF (fitz) first, then PyPDF2
try:
    import fitz as _fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

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
    "text/xml": "cda",
    "application/xml": "cda",
    "application/hl7-cda+xml": "cda",
}

EXTENSION_MAP = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".txt": "txt",
    ".csv": "csv",
    ".md": "markdown",
    ".xml": "cda",
    ".cda": "cda",
    ".ccd": "cda",
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
    elif fmt == "cda":
        return _extract_cda(data, filename)
    else:
        raise ExtractionError(f"No extractor for format: {fmt}")


def _extract_pdf(data: bytes, filename: str) -> list[dict[str, Any]]:
    # Try PyMuPDF first (better extraction), then PyPDF2, then fail gracefully
    if HAS_PYMUPDF:
        return _extract_pdf_pymupdf(data, filename)
    if HAS_PYPDF2:
        return _extract_pdf_pypdf2(data, filename)
    raise ExtractionError(
        "No PDF library installed. Install PyMuPDF (pip install PyMuPDF) "
        "or PyPDF2 (pip install PyPDF2)"
    )


def _extract_pdf_pymupdf(data: bytes, filename: str) -> list[dict[str, Any]]:
    doc = _fitz.open(stream=data, filetype="pdf")
    pages = []
    for i, page in enumerate(doc):
        text = page.get_text() or ""
        if text.strip():
            pages.append({"page": i + 1, "text": text})
    doc.close()
    if not pages:
        logger.warning(f"No text extracted from PDF: {filename}")
        pages.append({"page": 1, "text": ""})
    return pages


def _extract_pdf_pypdf2(data: bytes, filename: str) -> list[dict[str, Any]]:
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


# ── CDA/CCD extraction ────────────────────────────────────────────────────

# HL7 CDA namespace
_CDA_NS = "urn:hl7-org:v3"
_NS = {"cda": _CDA_NS}


def _extract_cda(data: bytes, filename: str = "") -> list[dict[str, Any]]:
    """Extract text sections from an HL7 CDA/CCD XML document.

    Parses the structured body and extracts section titles + text content.
    Falls back to stripping all XML tags if parsing fails.
    """
    try:
        text_content = data.decode("utf-8", errors="replace")
        root = ET.fromstring(text_content)
    except ET.ParseError:
        # Fallback: strip XML tags entirely
        logger.warning(f"Failed to parse CDA XML: {filename}, falling back to tag stripping")
        raw = data.decode("utf-8", errors="replace")
        stripped = re.sub(r"<[^>]+>", " ", raw)
        stripped = re.sub(r"\s+", " ", stripped).strip()
        return [{"page": 1, "text": stripped}]

    sections = _extract_cda_sections(root)
    if not sections:
        # Try without namespace (some documents don't use it)
        raw = data.decode("utf-8", errors="replace")
        stripped = re.sub(r"<[^>]+>", " ", raw)
        stripped = re.sub(r"\s+", " ", stripped).strip()
        return [{"page": 1, "text": stripped}]

    # Each section becomes a "page" for chunking purposes
    pages = []
    for i, section in enumerate(sections):
        title = section.get("title", f"Section {i + 1}")
        body = section.get("text", "")
        pages.append({"page": i + 1, "text": f"## {title}\n\n{body}"})
    return pages


def _extract_cda_sections(root: ET.Element) -> list[dict[str, str]]:
    """Walk CDA XML tree and extract section title + text pairs."""
    sections = []

    # Try with namespace
    for section_el in root.iter(f"{{{_CDA_NS}}}section"):
        section = _parse_section_element(section_el, _CDA_NS)
        if section:
            sections.append(section)

    # Try without namespace if nothing found
    if not sections:
        for section_el in root.iter("section"):
            section = _parse_section_element(section_el, "")
            if section:
                sections.append(section)

    return sections


def _parse_section_element(el: ET.Element, ns: str) -> dict[str, str] | None:
    """Parse a single CDA <section> element into title + text."""
    prefix = f"{{{ns}}}" if ns else ""

    title_el = el.find(f"{prefix}title")
    title = title_el.text.strip() if title_el is not None and title_el.text else "Untitled Section"

    text_el = el.find(f"{prefix}text")
    if text_el is None:
        return None

    # Extract all text content from the <text> element tree
    text = _element_text_content(text_el)
    if not text.strip():
        return None

    return {"title": title, "text": text.strip()}


def _element_text_content(el: ET.Element) -> str:
    """Recursively extract all text from an XML element and its children."""
    parts = []
    if el.text:
        parts.append(el.text)
    for child in el:
        parts.append(_element_text_content(child))
        if child.tail:
            parts.append(child.tail)
    return " ".join(parts)
