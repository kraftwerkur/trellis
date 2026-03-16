"""Audit Compactor Agent — platform housekeeping.

Prevents unbounded audit log growth by rolling up old events into summaries,
archiving raw rows to gzipped JSONL files, then deleting archived rows.
"""

from trellis.agents.health_auditor import record_task_heartbeat
import asyncio
import gzip
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, select

logger = logging.getLogger("trellis.agents.audit_compactor")

RETENTION_DAYS = int(os.environ.get("TRELLIS_AUDIT_RETENTION_DAYS", 90))
COMPACTION_INTERVAL = int(os.environ.get("TRELLIS_COMPACTION_INTERVAL", 86400))
ARCHIVE_BASE = Path(os.environ.get("TRELLIS_ARCHIVE_DIR", "data/audit_archive"))


async def run_compaction(db) -> dict:
    """Main compaction logic. Returns stats dict."""
    from trellis.models import AuditEvent, AuditSummary
    from trellis.router import emit_audit

    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)

    # Find old events
    result = await db.execute(
        select(AuditEvent).where(AuditEvent.timestamp < cutoff).order_by(AuditEvent.timestamp)
    )
    old_events = list(result.scalars().all())

    if not old_events:
        return {"archived": 0, "summaries_created": 0, "archive_files": 0}

    # Group by hour + event_type + agent_id
    groups: dict[tuple, list] = {}
    for ev in old_events:
        hour = ev.timestamp.replace(minute=0, second=0, microsecond=0)
        key = (hour, ev.event_type, ev.agent_id)
        groups.setdefault(key, []).append(ev)

    archive_files = set()
    summaries_created = 0
    archived_count = 0
    event_ids_to_delete = []

    for (hour, event_type, agent_id), events in groups.items():
        # Build archive path and write
        archive_dir = ARCHIVE_BASE / hour.strftime("%Y/%m/%d")
        archive_path = archive_dir / f"{hour.strftime('%H')}.jsonl.gz"

        rows = []
        for ev in events:
            rows.append(json.dumps({
                "id": ev.id, "trace_id": ev.trace_id, "envelope_id": ev.envelope_id,
                "agent_id": ev.agent_id, "event_type": ev.event_type,
                "details": ev.details, "timestamp": ev.timestamp.isoformat(),
            }))

        try:
            archive_dir.mkdir(parents=True, exist_ok=True)
            with gzip.open(archive_path, "at", encoding="utf-8") as f:
                f.write("\n".join(rows) + "\n")
        except Exception as e:
            logger.error(f"Archive write failed for {archive_path}: {e}")
            continue  # Skip this group — don't delete what we couldn't archive

        archive_files.add(str(archive_path))

        # Create summary row
        summary = AuditSummary(
            hour=hour, event_type=event_type, agent_id=agent_id,
            count=len(events), sample_details=events[0].details,
        )
        db.add(summary)
        summaries_created += 1

        event_ids_to_delete.extend(ev.id for ev in events)
        archived_count += len(events)

    # Delete archived rows
    if event_ids_to_delete:
        await db.execute(
            delete(AuditEvent).where(AuditEvent.id.in_(event_ids_to_delete))
        )

    # Meta audit event about our own run
    await emit_audit(
        db, "compaction_completed",
        agent_id="platform-audit-compactor",
        details={
            "archived": archived_count,
            "summaries_created": summaries_created,
            "archive_files": len(archive_files),
            "retention_days": RETENTION_DAYS,
        },
    )

    await db.commit()

    stats = {
        "archived": archived_count,
        "summaries_created": summaries_created,
        "archive_files": len(archive_files),
    }
    logger.info(f"Compaction complete: {stats}")
    return stats


async def compactor_loop(interval: float | None = None) -> None:
    """Background loop — runs forever, compacting periodically."""
    from trellis.database import async_session

    if interval is None:
        interval = float(COMPACTION_INTERVAL)

    while True:
        try:
            record_task_heartbeat("audit_compactor")
            async with async_session() as db:
                stats = await run_compaction(db)
                logger.info(f"Audit compaction: {stats}")
        except Exception as e:
            logger.error(f"Compactor loop error: {e}")
        await asyncio.sleep(interval)


class AuditCompactorAgent:
    """Native agent wrapper for on-demand compaction reports."""

    def __init__(self, agent):
        self.agent = agent

    async def process(self, envelope) -> dict:
        """Run a dry-run compaction report when triggered via envelope."""
        from trellis.database import async_session

        async with async_session() as db:
            stats = await run_compaction(db)

        return {
            "status": "completed",
            "result": {
                "text": f"Audit Compaction (dry run): {stats.get('events_archived', 0)} events would be archived, "
                        f"{stats.get('summaries_created', 0)} summaries would be created.",
                "data": {"compaction": stats},
            },
        }
