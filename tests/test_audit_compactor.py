"""Tests for Audit Compactor agent."""

import gzip
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from trellis.main import app


async def _insert_old_events(count=10, days_old=100, event_type="health_check", agent_id="test-agent"):
    """Insert audit events older than retention window."""
    from trellis.database import async_session
    from trellis.models import AuditEvent

    ts = datetime.now(timezone.utc) - timedelta(days=days_old)
    async with async_session() as db:
        for i in range(count):
            db.add(AuditEvent(
                event_type=event_type,
                agent_id=agent_id,
                details={"index": i, "status": "healthy"},
                timestamp=ts + timedelta(minutes=i),
            ))
        await db.commit()


@pytest.mark.asyncio
async def test_compaction_groups_correctly(client, tmp_path):
    """Events grouped by hour+type+agent produce correct summary counts."""
    await _insert_old_events(count=5, event_type="health_check", agent_id="a1")
    await _insert_old_events(count=3, event_type="rule_matched", agent_id="a2")

    from trellis.database import async_session
    from trellis.agents.audit_compactor import run_compaction, ARCHIVE_BASE

    with patch.object(
        __import__("trellis.agents.audit_compactor", fromlist=["ARCHIVE_BASE"]),
        "ARCHIVE_BASE", tmp_path,
    ):
        async with async_session() as db:
            stats = await run_compaction(db)

    assert stats["archived"] == 8
    assert stats["summaries_created"] == 2

    from trellis.models import AuditSummary
    async with async_session() as db:
        from sqlalchemy import select
        result = await db.execute(select(AuditSummary))
        summaries = list(result.scalars().all())
    assert len(summaries) == 2
    counts = {s.event_type: s.count for s in summaries}
    assert counts["health_check"] == 5
    assert counts["rule_matched"] == 3


@pytest.mark.asyncio
async def test_archive_file_created(client, tmp_path):
    """Archive JSONL.gz file is created with correct content."""
    await _insert_old_events(count=3)

    import trellis.agents.audit_compactor as mod
    with patch.object(mod, "ARCHIVE_BASE", tmp_path):
        from trellis.database import async_session
        async with async_session() as db:
            await mod.run_compaction(db)

    gz_files = list(tmp_path.rglob("*.jsonl.gz"))
    assert len(gz_files) >= 1

    with gzip.open(gz_files[0], "rt") as f:
        lines = [json.loads(l) for l in f if l.strip()]
    assert len(lines) == 3
    assert lines[0]["event_type"] == "health_check"


@pytest.mark.asyncio
async def test_raw_rows_deleted_after_archive(client, tmp_path):
    """Raw audit events are deleted after successful archiving."""
    await _insert_old_events(count=5, days_old=100)

    import trellis.agents.audit_compactor as mod
    with patch.object(mod, "ARCHIVE_BASE", tmp_path):
        from trellis.database import async_session
        async with async_session() as db:
            await mod.run_compaction(db)

    from trellis.database import async_session
    from trellis.models import AuditEvent
    from sqlalchemy import select
    async with async_session() as db:
        result = await db.execute(select(AuditEvent).where(AuditEvent.event_type == "health_check"))
        remaining = list(result.scalars().all())
    # Old ones deleted, only compaction_completed event remains
    assert len(remaining) == 0


@pytest.mark.asyncio
async def test_nothing_deleted_if_archive_fails(client, tmp_path):
    """If archive write fails, raw rows are preserved."""
    await _insert_old_events(count=5, days_old=100)

    import trellis.agents.audit_compactor as mod
    # Use a path that can't be written to
    bad_path = Path("/nonexistent/impossible/path")
    with patch.object(mod, "ARCHIVE_BASE", bad_path):
        from trellis.database import async_session
        async with async_session() as db:
            stats = await mod.run_compaction(db)

    assert stats["archived"] == 0

    from trellis.models import AuditEvent
    from sqlalchemy import select
    from trellis.database import async_session
    async with async_session() as db:
        result = await db.execute(select(AuditEvent).where(AuditEvent.event_type == "health_check"))
        remaining = list(result.scalars().all())
    assert len(remaining) == 5


@pytest.mark.asyncio
async def test_retention_window_respected(client, tmp_path):
    """Events within retention window are NOT compacted."""
    await _insert_old_events(count=3, days_old=100)  # old — should compact
    await _insert_old_events(count=2, days_old=10, event_type="recent_event")  # recent — keep

    import trellis.agents.audit_compactor as mod
    with patch.object(mod, "ARCHIVE_BASE", tmp_path):
        from trellis.database import async_session
        async with async_session() as db:
            stats = await mod.run_compaction(db)

    assert stats["archived"] == 3  # only old ones

    from trellis.models import AuditEvent
    from sqlalchemy import select
    from trellis.database import async_session
    async with async_session() as db:
        result = await db.execute(select(AuditEvent).where(AuditEvent.event_type == "recent_event"))
        remaining = list(result.scalars().all())
    assert len(remaining) == 2
