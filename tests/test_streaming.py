"""Tests for SSE streaming support and PHI-safe sentence-boundary buffering."""

import json
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch

from trellis.streaming import (
    phi_safe_stream_filter,
    _extract_content_from_sse,
    _find_last_boundary,
    _build_sse_chunk,
    SENTENCE_BOUNDARIES,
)


# ── Helper: async iterator from list ──────────────────────────────────────

async def _aiter(items):
    for item in items:
        yield item


# ── Unit tests: streaming.py helpers ──────────────────────────────────────

class TestExtractContent:
    def test_extracts_delta_content(self):
        line = 'data: {"choices":[{"delta":{"content":"Hello"}}]}'
        assert _extract_content_from_sse(line) == "Hello"

    def test_returns_none_for_done(self):
        assert _extract_content_from_sse("data: [DONE]") is None

    def test_returns_none_for_non_data(self):
        assert _extract_content_from_sse("event: ping") is None

    def test_returns_none_for_role_delta(self):
        line = 'data: {"choices":[{"delta":{"role":"assistant"}}]}'
        assert _extract_content_from_sse(line) is None

    def test_returns_none_for_empty_delta(self):
        line = 'data: {"choices":[{"delta":{}}]}'
        assert _extract_content_from_sse(line) is None


class TestFindLastBoundary:
    def test_period_space(self):
        assert _find_last_boundary("Hello world. Next") == 13  # after ". "

    def test_exclamation(self):
        assert _find_last_boundary("Wow! More") == 5  # after "! "

    def test_question(self):
        assert _find_last_boundary("Really? Yes") == 8  # after "? "

    def test_newline(self):
        assert _find_last_boundary("Line1\nLine2") == 6  # after "\n"

    def test_no_boundary(self):
        assert _find_last_boundary("no boundary here") == -1

    def test_multiple_boundaries_returns_last(self):
        text = "First. Second. Third"
        assert _find_last_boundary(text) == 15  # after second ". "


class TestBuildSseChunk:
    def test_format(self):
        result = _build_sse_chunk("hello", model="test-model")
        assert result.startswith("data: ")
        assert result.endswith("\n\n")
        obj = json.loads(result[6:].strip())
        assert obj["choices"][0]["delta"]["content"] == "hello"
        assert obj["model"] == "test-model"


# ── PHI-safe stream filter tests ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_phi_filter_buffers_until_sentence_boundary():
    """Content should only be emitted when a sentence boundary is found."""
    chunks = [
        'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n',
        'data: {"choices":[{"delta":{"content":" world"}}]}\n\n',
        'data: {"choices":[{"delta":{"content":". Next"}}]}\n\n',
        'data: {"choices":[{"delta":{"content":" part"}}]}\n\n',
        "data: [DONE]\n\n",
    ]

    results = []
    async for line in phi_safe_stream_filter(_aiter(chunks), model="test"):
        results.append(line)

    # Should get: "Hello world. " (at boundary), then "Next part" (flush), then [DONE]
    assert len(results) == 3
    # First emit: up to boundary
    obj1 = json.loads(results[0][6:].strip())
    assert obj1["choices"][0]["delta"]["content"] == "Hello world. "
    # Second emit: flushed remainder
    obj2 = json.loads(results[1][6:].strip())
    assert obj2["choices"][0]["delta"]["content"] == "Next part"
    # Third: DONE
    assert results[2].strip() == "data: [DONE]"


@pytest.mark.asyncio
async def test_phi_filter_flushes_buffer_on_stream_end():
    """Remaining buffer should be flushed when stream ends."""
    chunks = [
        'data: {"choices":[{"delta":{"content":"no boundary"}}]}\n\n',
        "data: [DONE]\n\n",
    ]

    results = []
    async for line in phi_safe_stream_filter(_aiter(chunks)):
        results.append(line)

    assert len(results) == 2
    obj = json.loads(results[0][6:].strip())
    assert obj["choices"][0]["delta"]["content"] == "no boundary"
    assert results[1].strip() == "data: [DONE]"


@pytest.mark.asyncio
async def test_phi_filter_multiple_boundaries():
    """Multiple sentence boundaries should emit content at each one."""
    chunks = [
        'data: {"choices":[{"delta":{"content":"A. B. C"}}]}\n\n',
        "data: [DONE]\n\n",
    ]

    results = []
    async for line in phi_safe_stream_filter(_aiter(chunks)):
        results.append(line)

    # "A. B. " emitted at boundary, "C" flushed at end
    assert len(results) == 3
    obj1 = json.loads(results[0][6:].strip())
    assert obj1["choices"][0]["delta"]["content"] == "A. B. "
    obj2 = json.loads(results[1][6:].strip())
    assert obj2["choices"][0]["delta"]["content"] == "C"


@pytest.mark.asyncio
async def test_phi_filter_newline_boundary():
    """Newlines should trigger emission."""
    chunks = [
        'data: {"choices":[{"delta":{"content":"line1\\nline2"}}]}\n\n',
        "data: [DONE]\n\n",
    ]

    results = []
    async for line in phi_safe_stream_filter(_aiter(chunks)):
        results.append(line)

    assert len(results) == 3
    obj1 = json.loads(results[0][6:].strip())
    assert obj1["choices"][0]["delta"]["content"] == "line1\n"


@pytest.mark.asyncio
async def test_phi_filter_empty_stream():
    """Empty stream (just DONE) should only yield DONE."""
    chunks = ["data: [DONE]\n\n"]

    results = []
    async for line in phi_safe_stream_filter(_aiter(chunks)):
        results.append(line)

    assert len(results) == 1
    assert results[0].strip() == "data: [DONE]"


@pytest.mark.asyncio
async def test_phi_filter_stream_ends_without_done():
    """If stream ends without [DONE], buffer is flushed and [DONE] appended."""
    chunks = [
        'data: {"choices":[{"delta":{"content":"orphan"}}]}\n\n',
    ]

    results = []
    async for line in phi_safe_stream_filter(_aiter(chunks)):
        results.append(line)

    assert len(results) == 2
    obj = json.loads(results[0][6:].strip())
    assert obj["choices"][0]["delta"]["content"] == "orphan"
    assert results[1].strip() == "data: [DONE]"


# ── SSE format validation ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sse_chunks_are_valid_format():
    """Every emitted chunk (except [DONE]) must be valid JSON in SSE format."""
    chunks = [
        'data: {"choices":[{"delta":{"content":"Test. "}}]}\n\n',
        'data: {"choices":[{"delta":{"content":"More data"}}]}\n\n',
        "data: [DONE]\n\n",
    ]

    async for line in phi_safe_stream_filter(_aiter(chunks)):
        assert line.startswith("data: ")
        assert line.endswith("\n\n")
        payload = line[6:].strip()
        if payload != "[DONE]":
            obj = json.loads(payload)
            assert "choices" in obj
            assert "delta" in obj["choices"][0]


# ── Integration: non-streaming regression ─────────────────────────────────

async def _setup_agent_and_key(client, agent_id):
    """Helper: create agent + API key, return raw key string."""
    resp = await client.post("/api/agents", json={
        "agent_id": agent_id,
        "name": f"Agent {agent_id}",
        "owner": "test",
        "department": "IT",
        "framework": "mock",
        "agent_type": "http",
        "endpoint": "http://test/mock-agent/envelope",
        "health_endpoint": "http://test/mock-agent/health",
    })
    assert resp.status_code == 201

    resp = await client.post("/api/keys", json={
        "agent_id": agent_id,
        "name": f"{agent_id}-key",
    })
    assert resp.status_code == 201
    return resp.json()["key"]


@pytest.mark.asyncio
async def test_non_streaming_still_works(client):
    """Non-streaming chat completion should still return JSONResponse."""
    raw_key = await _setup_agent_and_key(client, "stream-test-agent")

    resp = await client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "hello"}],
            "stream": False,
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "choices" in data
    assert data["choices"][0]["message"]["content"] == "OK"


@pytest.mark.asyncio
async def test_streaming_returns_sse_content_type(client):
    """Streaming request should return text/event-stream content type."""
    raw_key = await _setup_agent_and_key(client, "sse-agent")

    # Streaming request — the mock provider returns non-streaming response
    # but the gateway wraps it in SSE format via the fallback path
    resp = await client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")
    # Body should contain SSE data lines
    body = resp.text
    assert "data: " in body
    assert "[DONE]" in body
