"""SSE streaming utilities with PHI-safe sentence-boundary buffering.

Provides a filter generator that buffers SSE chunks and only emits content
at sentence boundaries ('. ', '! ', '? ', '\n') to prevent partial PHI leakage
in streaming responses.
"""

import json
import logging
from typing import AsyncIterator

logger = logging.getLogger("trellis.streaming")

SENTENCE_BOUNDARIES = (". ", "! ", "? ", "\n")


def _extract_content_from_sse(line: str) -> str | None:
    """Extract delta content from an SSE data line, or None if not a content chunk."""
    if not line.startswith("data: "):
        return None
    payload = line[6:].strip()
    if payload == "[DONE]":
        return None
    try:
        obj = json.loads(payload)
        choices = obj.get("choices", [])
        if choices:
            delta = choices[0].get("delta", {})
            return delta.get("content")
    except (json.JSONDecodeError, IndexError, KeyError):
        return None
    return None


def _build_sse_chunk(content: str, model: str = "") -> str:
    """Build an SSE-formatted data line with delta content."""
    chunk = {
        "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}],
    }
    if model:
        chunk["model"] = model
    return f"data: {json.dumps(chunk)}\n\n"


def _find_last_boundary(text: str) -> int:
    """Return the index *after* the last sentence boundary, or -1 if none found."""
    last = -1
    for boundary in SENTENCE_BOUNDARIES:
        idx = text.rfind(boundary)
        if idx != -1:
            end = idx + len(boundary)
            if end > last:
                last = end
    return last


async def phi_safe_stream_filter(
    source: AsyncIterator[str],
    model: str = "",
) -> AsyncIterator[str]:
    """Wraps an async iterator of SSE lines, buffering at sentence boundaries.

    - Accumulates delta content text in a buffer
    - Only emits content when a sentence boundary is detected
    - Flushes any remaining buffer when stream ends
    - Passes through non-content SSE lines unchanged
    - Yields final `data: [DONE]` marker

    Args:
        source: Async iterator yielding SSE-formatted lines (with trailing newlines).
        model: Model name to include in re-emitted chunks.

    Yields:
        SSE-formatted data lines, emitted at sentence boundaries.
    """
    buffer = ""
    total_content = ""

    async for line in source:
        stripped = line.strip()
        if not stripped:
            continue

        # End of stream marker — flush buffer first
        if stripped == "data: [DONE]":
            if buffer:
                yield _build_sse_chunk(buffer, model)
                total_content += buffer
                buffer = ""
            yield "data: [DONE]\n\n"
            return

        # Try to extract content delta
        content = _extract_content_from_sse(stripped)
        if content is None:
            # Non-content SSE line (e.g., role delta) — pass through
            continue

        buffer += content

        # Check for sentence boundary
        boundary_pos = _find_last_boundary(buffer)
        if boundary_pos > 0:
            emit = buffer[:boundary_pos]
            buffer = buffer[boundary_pos:]
            total_content += emit
            yield _build_sse_chunk(emit, model)

    # Stream ended without [DONE] — flush remaining buffer
    if buffer:
        yield _build_sse_chunk(buffer, model)
        total_content += buffer
    yield "data: [DONE]\n\n"
