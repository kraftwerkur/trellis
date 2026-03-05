"""Document ingestion adapter: parse uploaded documents into Trellis Envelopes.

Accepts PDF, DOCX, TXT, CSV, and Markdown files. Extracts text, chunks it,
and converts each chunk into an Envelope for routing through the event system.

Healthcare context: hospitals deal with policies, procedures, clinical guidelines,
and compliance documents constantly. This adapter makes them searchable events.
"""

import logging
from typing import Any

from trellis.adapters.document_utils import (
    ExtractionError,
    chunk_text,
    detect_format,
    extract_text,
)
from trellis.schemas import Envelope, Metadata, Payload, RoutingHints, Sender

logger = logging.getLogger("trellis.adapters.document")


def build_document_envelopes(
    filename: str,
    data: bytes,
    content_type: str | None = None,
    chunk_size: int = 1000,
    overlap: int = 200,
    doc_metadata: dict[str, Any] | None = None,
) -> list[Envelope]:
    """Extract text from a document and build one Envelope per chunk.

    Args:
        filename: Original filename (used for format detection and metadata).
        data: Raw file bytes.
        content_type: MIME type (optional, used for format detection).
        chunk_size: Max characters per chunk.
        overlap: Overlap characters between chunks.
        doc_metadata: Optional healthcare metadata dict. Supported keys:
            - document_type: policy | procedure | guideline | protocol | compliance | form | other
            - department: originating department
            - effective_date: when the document takes effect (ISO-8601)
            - author: document author
            - version: document version string

    Returns:
        List of Envelopes, one per chunk.

    Raises:
        ExtractionError: If format is unsupported or extraction fails.
    """
    fmt = detect_format(filename, content_type)
    pages = extract_text(data, fmt, filename)

    # Concatenate all page text, tracking page boundaries
    full_text = ""
    page_breaks: list[tuple[int, int]] = []  # (char_offset, page_number)
    for page_info in pages:
        page_breaks.append((len(full_text), page_info["page"]))
        full_text += page_info["text"] + "\n"

    chunks = chunk_text(full_text.strip(), chunk_size, overlap)
    if not chunks:
        chunks = [""]

    total_chunks = len(chunks)
    meta = doc_metadata or {}

    envelopes = []
    for i, chunk in enumerate(chunks):
        # Determine which page this chunk starts on
        chunk_start = full_text.find(chunk) if chunk else 0
        page_num = 1
        for offset, pnum in reversed(page_breaks):
            if chunk_start >= offset:
                page_num = pnum
                break

        # Build tags for routing
        tags = ["document", fmt]
        if meta.get("document_type"):
            tags.append(meta["document_type"])
        if meta.get("department"):
            tags.append(meta["department"].lower())

        envelopes.append(
            Envelope(
                source_type="document",
                source_id=f"document-{fmt}",
                payload=Payload(
                    text=chunk,
                    data={
                        "filename": filename,
                        "format": fmt,
                        "page": page_num,
                        "chunk_index": i,
                        "total_chunks": total_chunks,
                        "content_type": content_type or f"text/{fmt}",
                        # Healthcare-specific metadata
                        "document_type": meta.get("document_type"),
                        "department": meta.get("department"),
                        "effective_date": meta.get("effective_date"),
                        "author": meta.get("author"),
                        "version": meta.get("version"),
                    },
                ),
                metadata=Metadata(
                    priority="normal",
                    sender=Sender(
                        name="document-adapter",
                        department=meta.get("department", ""),
                    ),
                ),
                routing_hints=RoutingHints(
                    tags=tags,
                    category="document-ingestion",
                    department=meta.get("department"),
                ),
            )
        )

    logger.info(
        f"Document '{filename}' ({fmt}): {len(pages)} pages, "
        f"{total_chunks} chunks @ {chunk_size} chars"
    )
    return envelopes


def build_batch_envelopes(
    files: list[dict[str, Any]],
    chunk_size: int = 1000,
    overlap: int = 200,
    doc_metadata: dict[str, Any] | None = None,
) -> list[Envelope]:
    """Process multiple files and return all envelopes.

    Args:
        files: List of dicts with keys: filename, data (bytes), content_type (optional).
        chunk_size: Max characters per chunk.
        overlap: Overlap characters between chunks.
        doc_metadata: Optional shared metadata applied to all files.

    Returns:
        List of all Envelopes from all files.
    """
    all_envelopes = []
    for f in files:
        try:
            envelopes = build_document_envelopes(
                filename=f["filename"],
                data=f["data"],
                content_type=f.get("content_type"),
                chunk_size=chunk_size,
                overlap=overlap,
                doc_metadata=doc_metadata,
            )
            all_envelopes.extend(envelopes)
        except ExtractionError as e:
            logger.error(f"Failed to process '{f['filename']}': {e}")
    return all_envelopes
