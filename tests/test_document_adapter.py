"""Tests for the document ingestion adapter, utilities, and API endpoint."""

import io
import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport

from trellis.adapters.document_utils import (
    ExtractionError,
    chunk_text,
    detect_format,
    extract_text,
)
from trellis.adapters.document_adapter import (
    build_batch_envelopes,
    build_document_envelopes,
)


# ── Format detection ───────────────────────────────────────────────────────

class TestDetectFormat:
    def test_by_extension(self):
        assert detect_format("policy.pdf") == "pdf"
        assert detect_format("guide.docx") == "docx"
        assert detect_format("notes.txt") == "txt"
        assert detect_format("data.csv") == "csv"
        assert detect_format("README.md") == "markdown"

    def test_cda_extensions(self):
        assert detect_format("discharge.xml") == "cda"
        assert detect_format("summary.cda") == "cda"
        assert detect_format("record.ccd") == "cda"

    def test_by_content_type(self):
        assert detect_format("file", "application/pdf") == "pdf"
        assert detect_format("file", "text/csv") == "csv"
        assert detect_format("file", "text/markdown") == "markdown"

    def test_cda_content_types(self):
        assert detect_format("file", "text/xml") == "cda"
        assert detect_format("file", "application/xml") == "cda"
        assert detect_format("file", "application/hl7-cda+xml") == "cda"

    def test_content_type_takes_priority(self):
        assert detect_format("file.txt", "application/pdf") == "pdf"

    def test_unsupported_raises(self):
        with pytest.raises(ExtractionError):
            detect_format("photo.jpg")

    def test_case_insensitive_extension(self):
        assert detect_format("POLICY.PDF") == "pdf"
        assert detect_format("Guide.DOCX") == "docx"


# ── Text extraction ────────────────────────────────────────────────────────

class TestExtractText:
    def test_txt(self):
        data = b"Hello, this is a test document."
        pages = extract_text(data, "txt")
        assert len(pages) == 1
        assert pages[0]["page"] == 1
        assert "Hello" in pages[0]["text"]

    def test_markdown(self):
        data = b"# Title\n\nSome content here."
        pages = extract_text(data, "markdown")
        assert len(pages) == 1
        assert "# Title" in pages[0]["text"]

    def test_csv(self):
        data = b"Name,Department,Role\nJohn,IT,Admin\nJane,HR,Manager"
        pages = extract_text(data, "csv")
        assert len(pages) == 1
        assert "John" in pages[0]["text"]
        assert "HR" in pages[0]["text"]

    def test_csv_empty(self):
        pages = extract_text(b"", "csv")
        assert len(pages) == 1
        assert pages[0]["text"] == ""

    def test_unsupported_format_raises(self):
        with pytest.raises(ExtractionError):
            extract_text(b"data", "xlsx")

    def test_utf8_with_errors(self):
        data = b"Hello \xff world"
        pages = extract_text(data, "txt")
        assert "Hello" in pages[0]["text"]
        assert "world" in pages[0]["text"]


# ── CDA extraction ────────────────────────────────────────────────────────

SAMPLE_CDA = b"""<?xml version="1.0" encoding="UTF-8"?>
<ClinicalDocument xmlns="urn:hl7-org:v3">
  <title>Discharge Summary</title>
  <component>
    <structuredBody>
      <component>
        <section>
          <title>History of Present Illness</title>
          <text>Patient presented with chest pain lasting 3 hours.</text>
        </section>
      </component>
      <component>
        <section>
          <title>Medications</title>
          <text>
            <list>
              <item>Aspirin 81mg daily</item>
              <item>Metoprolol 25mg twice daily</item>
            </list>
          </text>
        </section>
      </component>
    </structuredBody>
  </component>
</ClinicalDocument>
"""

SAMPLE_CDA_NO_NS = b"""<?xml version="1.0"?>
<ClinicalDocument>
  <component>
    <structuredBody>
      <component>
        <section>
          <title>Assessment</title>
          <text>Patient stable for discharge.</text>
        </section>
      </component>
    </structuredBody>
  </component>
</ClinicalDocument>
"""


class TestExtractCDA:
    def test_cda_with_namespace(self):
        pages = extract_text(SAMPLE_CDA, "cda")
        assert len(pages) == 2
        assert "History of Present Illness" in pages[0]["text"]
        assert "chest pain" in pages[0]["text"]
        assert "Medications" in pages[1]["text"]
        assert "Aspirin" in pages[1]["text"]

    def test_cda_without_namespace(self):
        pages = extract_text(SAMPLE_CDA_NO_NS, "cda")
        assert len(pages) >= 1
        texts = " ".join(p["text"] for p in pages)
        assert "Assessment" in texts
        assert "stable for discharge" in texts

    def test_cda_malformed_xml_fallback(self):
        data = b"Some plain text <broken> with tags <more>"
        pages = extract_text(data, "cda")
        assert len(pages) == 1
        # Falls back to tag stripping
        assert "Some plain text" in pages[0]["text"]
        assert "with tags" in pages[0]["text"]

    def test_cda_empty_sections_fallback(self):
        data = b"""<?xml version="1.0"?>
        <ClinicalDocument xmlns="urn:hl7-org:v3">
          <title>Empty Doc</title>
        </ClinicalDocument>"""
        pages = extract_text(data, "cda")
        assert len(pages) >= 1
        # Falls back to tag stripping since no sections found
        assert "Empty Doc" in pages[0]["text"]

    def test_cda_page_numbering(self):
        pages = extract_text(SAMPLE_CDA, "cda")
        assert pages[0]["page"] == 1
        assert pages[1]["page"] == 2


# ── Chunking ───────────────────────────────────────────────────────────────

class TestChunkText:
    def test_basic_chunking(self):
        text = "a" * 2500
        chunks = chunk_text(text, chunk_size=1000, overlap=200)
        assert len(chunks) == 4
        assert len(chunks[0]) == 1000
        assert len(chunks[1]) == 1000

    def test_overlap(self):
        text = "abcdefghij" * 10  # 100 chars
        chunks = chunk_text(text, chunk_size=30, overlap=10)
        for i in range(len(chunks) - 1):
            tail = chunks[i][-10:]
            head = chunks[i + 1][:10]
            assert tail == head

    def test_short_text_single_chunk(self):
        chunks = chunk_text("short", chunk_size=1000, overlap=200)
        assert len(chunks) == 1
        assert chunks[0] == "short"

    def test_empty_text(self):
        assert chunk_text("") == []
        assert chunk_text("   ") == []

    def test_invalid_params(self):
        with pytest.raises(ValueError):
            chunk_text("text", chunk_size=0)
        with pytest.raises(ValueError):
            chunk_text("text", chunk_size=100, overlap=-1)
        with pytest.raises(ValueError):
            chunk_text("text", chunk_size=100, overlap=100)

    def test_no_overlap(self):
        text = "a" * 30
        chunks = chunk_text(text, chunk_size=10, overlap=0)
        assert len(chunks) == 3
        assert all(len(c) == 10 for c in chunks)


# ── Envelope creation ──────────────────────────────────────────────────────

class TestBuildDocumentEnvelopes:
    def test_basic_txt_envelope(self):
        data = b"This is a test policy document for Health First."
        envelopes = build_document_envelopes("policy.txt", data)
        assert len(envelopes) == 1
        env = envelopes[0]
        assert env.source_type == "document"
        assert env.source_id == "document-txt"
        assert "policy document" in env.payload.text
        assert env.payload.data["filename"] == "policy.txt"
        assert env.payload.data["format"] == "txt"
        assert env.payload.data["chunk_index"] == 0
        assert env.payload.data["total_chunks"] == 1
        assert env.routing_hints.category == "document-ingestion"
        assert "document" in env.routing_hints.tags
        assert "txt" in env.routing_hints.tags

    def test_chunking_creates_multiple_envelopes(self):
        data = ("x" * 2500).encode()
        envelopes = build_document_envelopes("big.txt", data, chunk_size=1000, overlap=200)
        assert len(envelopes) > 1
        for i, env in enumerate(envelopes):
            assert env.payload.data["chunk_index"] == i
            assert env.payload.data["total_chunks"] == len(envelopes)

    def test_healthcare_metadata(self):
        data = b"Infection control procedure."
        meta = {
            "document_type": "procedure",
            "department": "Infection Control",
            "effective_date": "2026-03-01",
            "author": "Dr. Smith",
            "version": "2.1",
        }
        envelopes = build_document_envelopes("ic-proc.txt", data, doc_metadata=meta)
        env = envelopes[0]
        assert env.payload.data["document_type"] == "procedure"
        assert env.payload.data["department"] == "Infection Control"
        assert env.payload.data["effective_date"] == "2026-03-01"
        assert env.payload.data["author"] == "Dr. Smith"
        assert env.payload.data["version"] == "2.1"
        assert "procedure" in env.routing_hints.tags
        assert "infection control" in env.routing_hints.tags
        assert env.metadata.sender.department == "Infection Control"
        assert env.routing_hints.department == "Infection Control"

    def test_csv_envelope(self):
        data = b"Name,Dept\nAlice,IT\nBob,HR"
        envelopes = build_document_envelopes("staff.csv", data)
        assert len(envelopes) == 1
        assert "Alice" in envelopes[0].payload.text

    def test_content_type_detection(self):
        data = b"some text"
        envelopes = build_document_envelopes(
            "file", data, content_type="text/plain"
        )
        assert envelopes[0].payload.data["format"] == "txt"

    def test_unsupported_format_raises(self):
        with pytest.raises(ExtractionError):
            build_document_envelopes("photo.jpg", b"not a doc")

    def test_empty_document(self):
        envelopes = build_document_envelopes("empty.txt", b"")
        assert len(envelopes) >= 1

    def test_cda_envelopes(self):
        envelopes = build_document_envelopes("discharge.cda", SAMPLE_CDA)
        assert len(envelopes) >= 1
        assert envelopes[0].source_id == "document-cda"
        assert envelopes[0].payload.data["format"] == "cda"
        texts = " ".join(e.payload.text for e in envelopes)
        assert "chest pain" in texts

    def test_cda_with_metadata(self):
        meta = {"document_type": "guideline", "department": "Cardiology"}
        envelopes = build_document_envelopes(
            "summary.xml", SAMPLE_CDA, content_type="application/hl7-cda+xml",
            doc_metadata=meta
        )
        assert len(envelopes) >= 1
        assert envelopes[0].payload.data["department"] == "Cardiology"
        assert "cda" in envelopes[0].routing_hints.tags


# ── Batch upload ───────────────────────────────────────────────────────────

class TestBatchUpload:
    def test_multiple_files(self):
        files = [
            {"filename": "a.txt", "data": b"First document content."},
            {"filename": "b.txt", "data": b"Second document content."},
        ]
        envelopes = build_batch_envelopes(files)
        assert len(envelopes) == 2
        texts = [e.payload.text for e in envelopes]
        assert any("First" in t for t in texts)
        assert any("Second" in t for t in texts)

    def test_batch_with_bad_file_skips(self):
        files = [
            {"filename": "good.txt", "data": b"Valid content."},
            {"filename": "bad.xyz", "data": b"unknown format"},
        ]
        envelopes = build_batch_envelopes(files)
        assert len(envelopes) == 1
        assert "Valid" in envelopes[0].payload.text

    def test_batch_shared_metadata(self):
        files = [
            {"filename": "a.txt", "data": b"Policy A."},
            {"filename": "b.txt", "data": b"Policy B."},
        ]
        meta = {"document_type": "policy", "department": "Compliance"}
        envelopes = build_batch_envelopes(files, doc_metadata=meta)
        for env in envelopes:
            assert env.payload.data["document_type"] == "policy"
            assert env.payload.data["department"] == "Compliance"

    def test_batch_empty_list(self):
        assert build_batch_envelopes([]) == []

    def test_batch_with_cda(self):
        files = [
            {"filename": "policy.txt", "data": b"Hand hygiene policy."},
            {"filename": "discharge.cda", "data": SAMPLE_CDA},
        ]
        envelopes = build_batch_envelopes(files)
        assert len(envelopes) >= 2
        formats = [e.payload.data["format"] for e in envelopes]
        assert "txt" in formats
        assert "cda" in formats


# ── API endpoint tests (use shared client fixture from conftest.py) ────────

@pytest.mark.anyio
async def test_document_ingest_endpoint_txt(client):
    resp = await client.post(
        "/api/documents/ingest",
        files={"file": ("policy.txt", b"Hand hygiene is critical for patient safety.", "text/plain")},
        data={"document_type": "policy", "department": "Infection Control"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["filename"] == "policy.txt"
    assert body["total_chunks"] >= 1
    assert len(body["envelope_ids"]) >= 1


@pytest.mark.anyio
async def test_document_ingest_endpoint_cda(client):
    resp = await client.post(
        "/api/documents/ingest",
        files={"file": ("discharge.cda", SAMPLE_CDA, "application/hl7-cda+xml")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["format"] == "cda"
    assert body["total_chunks"] >= 1


@pytest.mark.anyio
async def test_document_ingest_no_file(client):
    resp = await client.post("/api/documents/ingest", data={"department": "IT"})
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_document_ingest_unsupported_format(client):
    resp = await client.post(
        "/api/documents/ingest",
        files={"file": ("photo.jpg", b"not a document", "image/jpeg")},
    )
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_document_ingest_size_limit(client):
    import os
    os.environ["TRELLIS_MAX_DOCUMENT_SIZE_MB"] = "0"
    try:
        resp = await client.post(
            "/api/documents/ingest",
            files={"file": ("big.txt", b"x" * 100, "text/plain")},
        )
        assert resp.status_code == 413
    finally:
        os.environ.pop("TRELLIS_MAX_DOCUMENT_SIZE_MB", None)


@pytest.mark.anyio
async def test_document_ingest_with_metadata(client):
    resp = await client.post(
        "/api/documents/ingest",
        files={"file": ("proc.txt", b"Procedure for hand hygiene.", "text/plain")},
        data={
            "document_type": "procedure",
            "department": "Nursing",
            "author": "Dr. Jones",
            "version": "1.0",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["total_chunks"] >= 1


@pytest.mark.anyio
async def test_document_ingest_custom_chunking(client):
    big_text = b"word " * 500  # ~2500 chars
    resp = await client.post(
        "/api/documents/ingest",
        files={"file": ("big.txt", big_text, "text/plain")},
        data={"chunk_size": "500", "overlap": "100"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_chunks"] > 1


@pytest.mark.anyio
async def test_document_ingest_empty_file(client):
    resp = await client.post(
        "/api/documents/ingest",
        files={"file": ("empty.txt", b"", "text/plain")},
    )
    assert resp.status_code == 400
