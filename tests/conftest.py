"""Shared test fixtures — DB isolation for the entire test suite."""

import os

# Set test DB BEFORE any trellis imports (engine is created at import time)
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:////tmp/test_trellis.db"

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, patch

from trellis.main import app
from trellis.database import Base, engine
from trellis.router import set_client_override

# ── Fast LLM mock ──────────────────────────────────────────────────────────
# Any test that creates an LLM agent and dispatches to it will use this mock
# instead of making a real Ollama call (~40-50s → <0.1s).
# Tests can opt out with @pytest.mark.no_llm_mock.

_MOCK_LLM_RESPONSE = {
    "choices": [{"message": {"content": "OK", "role": "assistant"}}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
    "model": "qwen3.5:9b",
    "object": "chat.completion",
}

@pytest.fixture(autouse=True)
def mock_llm_provider(request):
    """Patch OllamaProvider.chat_completion with a fast mock for all tests.

    Skip patching for tests marked @pytest.mark.no_llm_mock (real integration tests).
    This converts ~90s of Ollama wall time into <0.1s per test.
    """
    if request.node.get_closest_marker("no_llm_mock"):
        yield
        return

    mock_chat = AsyncMock(return_value=_MOCK_LLM_RESPONSE)
    # _providers["ollama"] is an OpenAICompatibleProvider instance (always_available=True)
    # Patch the instance method directly so no real HTTP calls go to Ollama.
    with patch("trellis.gateway.OpenAICompatibleProvider.chat_completion", mock_chat):
        yield mock_chat


@pytest_asyncio.fixture
async def client():
    """Shared async test client — truncates data between tests (schema created once)."""
    # Create tables if not exist, truncate rows for isolation — skip expensive drop_all
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, checkfirst=True)
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        set_client_override(c)
        yield c
        set_client_override(None)
