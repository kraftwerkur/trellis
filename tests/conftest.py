"""Shared test fixtures — DB isolation for the entire test suite."""

import os

# Set test DB BEFORE any trellis imports (engine is created at import time)
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:////tmp/test_trellis.db"

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from trellis.main import app
from trellis.database import Base, engine
from trellis.router import set_client_override


@pytest_asyncio.fixture
async def client():
    """Shared async test client with clean DB per test."""
    from sqlalchemy import text

    async with engine.begin() as conn:
        # Use checkfirst to handle missing/stale tables gracefully
        await conn.run_sync(Base.metadata.drop_all, checkfirst=True)
        await conn.run_sync(Base.metadata.create_all, checkfirst=True)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        set_client_override(c)
        yield c
        set_client_override(None)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all, checkfirst=True)
