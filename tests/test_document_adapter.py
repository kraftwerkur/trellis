"""Tests for the document ingestion adapter and utilities."""

import pytest

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

    def test_by_content_type(self):
        assert detect_format("file", "application/pdf") == "pdf"
        assert detect_format("file", "text/csv") == "csv"
        assert detect_format("file", "text/markdown") == "markdown"

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


# ── Chunking ───────────────────────────────────────────────────────────────

class TestChunkText:
    def test_basic_chunking(self):
        text = "a" * 2500
        chunks = chunk_text(text, chunk_size=1000, overlap=200)
        assert len(chunks) == 4  # 0-1000, 800-1800, 1600-2500, 2400-2500(short)
        assert len(chunks[0]) == 1000
        assert len(chunks[1]) == 1000

    def test_overlap(self):
        text = "abcdefghij" * 10  # 100 chars
        chunks = chunk_text(text, chunk_size=30, overlap=10)
        # Each consecutive pair should share 10 chars
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
        # Should return at least one envelope (empty chunk)
        assert len(envelopes) >= 1


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
