from trellis.agents.health_auditor import record_task_heartbeat
"""Schema Drift Detector — platform housekeeping agent.

Monitors envelope payload structures per source_type. Detects when payload
shapes change — new fields, missing fields, type changes. Prevents silent
breakage when upstream sources change their format.

Runs every 6 hours (configurable via TRELLIS_SCHEMA_CHECK_INTERVAL).
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

logger = logging.getLogger("trellis.agents.schema_drift")

_CHECK_INTERVAL = int(os.environ.get("TRELLIS_SCHEMA_CHECK_INTERVAL", 21600))
_BASELINE_PATH = Path(os.environ.get("TRELLIS_SCHEMA_BASELINES", "data/schema_baselines.json"))

# Type name mapping for JSON types
_TYPE_MAP = {
    str: "str",
    int: "int",
    float: "float",
    bool: "bool",
    list: "list",
    dict: "dict",
    type(None): "null",
}


def _type_name(value) -> str:
    return _TYPE_MAP.get(type(value), type(value).__name__)


def _extract_fields(obj, prefix: str = "") -> dict[str, str]:
    """Recursively extract dot-path keys and their value types from a dict."""
    fields: dict[str, str] = {}
    if not isinstance(obj, dict):
        return fields
    for key, value in obj.items():
        path = f"{prefix}.{key}" if prefix else key
        fields[path] = _type_name(value)
        if isinstance(value, dict):
            fields.update(_extract_fields(value, path))
    return fields


def _load_baselines() -> dict:
    """Load schema baselines from disk. Returns empty dict if not found."""
    if _BASELINE_PATH.exists():
        try:
            return json.loads(_BASELINE_PATH.read_text())
        except Exception as e:
            logger.warning("Failed to load schema baselines: %s", e)
    return {}


def _save_baselines(baselines: dict) -> None:
    """Persist schema baselines to disk."""
    try:
        _BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _BASELINE_PATH.write_text(json.dumps(baselines, indent=2))
    except Exception as e:
        logger.warning("Failed to save schema baselines: %s", e)


def _merge_fields(existing: dict[str, str], new: dict[str, str]) -> dict[str, str]:
    """Merge new fields into existing baseline (union). Type wins from new if conflicts."""
    merged = dict(existing)
    merged.update(new)
    return merged


def _compare_schemas(baseline_fields: dict[str, str], current_fields: dict[str, str]) -> dict:
    """Compare current schema against baseline. Returns drift details."""
    baseline_keys = set(baseline_fields)
    current_keys = set(current_fields)

    new_fields = sorted(current_keys - baseline_keys)
    missing_fields = sorted(baseline_keys - current_keys)
    type_changes = []

    for key in baseline_keys & current_keys:
        if baseline_fields[key] != current_fields[key]:
            type_changes.append({
                "field": key,
                "was": baseline_fields[key],
                "now": current_fields[key],
            })

    # Determine severity
    severity = "none"
    if type_changes:
        severity = "critical"
    elif missing_fields:
        severity = "major"
    elif new_fields:
        severity = "minor"

    return {
        "severity": severity,
        "new_fields": new_fields,
        "missing_fields": missing_fields,
        "type_changes": type_changes,
    }


async def run_analysis() -> dict:
    """Run schema drift analysis. Returns structured report dict."""
    from trellis.database import async_session
    from trellis.models import AuditEvent, EnvelopeLog

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    baselines = _load_baselines()

    async with async_session() as db:
        result = await db.execute(
            select(EnvelopeLog.source_type, EnvelopeLog.envelope_data)
            .where(EnvelopeLog.timestamp >= cutoff)
        )
        rows = result.all()

    # Group by source_type
    by_source: dict[str, list[dict]] = {}
    for source_type, envelope_data in rows:
        if source_type not in by_source:
            by_source[source_type] = []
        by_source[source_type].append(envelope_data)

    drift_details = []
    drifts_detected = 0

    for source_type, envelopes in by_source.items():
        # Build current schema fingerprint (union of all envelope fields)
        current_fields: dict[str, str] = {}
        for env_data in envelopes:
            extracted = _extract_fields(env_data)
            current_fields.update(extracted)

        sample_count = len(envelopes)

        if source_type not in baselines:
            # First run — establish baseline, no drift
            baselines[source_type] = {
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "sample_count": sample_count,
                "fields": current_fields,
            }
            logger.info("Schema baseline established for '%s' (%d samples)", source_type, sample_count)
            continue

        baseline = baselines[source_type]
        baseline_fields = baseline.get("fields", {})
        baseline_sample_count = baseline.get("sample_count", 0)

        drift = _compare_schemas(baseline_fields, current_fields)

        if drift["severity"] != "none":
            drifts_detected += 1
            drift_details.append({
                "source_type": source_type,
                "severity": drift["severity"],
                "new_fields": drift["new_fields"],
                "missing_fields": drift["missing_fields"],
                "type_changes": drift["type_changes"],
                "sample_count": sample_count,
                "baseline_sample_count": baseline_sample_count,
            })

            logger.warning(
                "Schema drift detected in '%s': severity=%s, new=%d, missing=%d, type_changes=%d",
                source_type,
                drift["severity"],
                len(drift["new_fields"]),
                len(drift["missing_fields"]),
                len(drift["type_changes"]),
            )

            # Emit audit event
            async with async_session() as db:
                event = AuditEvent(
                    event_type="schema_drift_detected",
                    agent_id="schema-drift-detector",
                    details={
                        "source_type": source_type,
                        "severity": drift["severity"],
                        "new_fields": drift["new_fields"],
                        "missing_fields": drift["missing_fields"],
                        "type_changes": drift["type_changes"],
                    },
                )
                db.add(event)
                await db.commit()

        # Update baseline with merged schema
        baselines[source_type] = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "sample_count": sample_count,
            "fields": _merge_fields(baseline_fields, current_fields),
        }

    _save_baselines(baselines)

    sources_monitored = len(by_source)

    # Build summary text
    if not by_source:
        summary = "Schema Drift Report: No envelopes in last 24h — nothing to analyze."
    elif drifts_detected == 0:
        summary = f"Schema Drift Report: {sources_monitored} source(s) monitored. No drift detected."
    else:
        drift_summary_parts = []
        for d in drift_details:
            parts = []
            if d["new_fields"]:
                parts.append(f"{len(d['new_fields'])} new field(s)")
            if d["missing_fields"]:
                parts.append(f"{len(d['missing_fields'])} missing field(s)")
            if d["type_changes"]:
                parts.append(f"{len(d['type_changes'])} type change(s)")
            drift_summary_parts.append(f"'{d['source_type']}' ({', '.join(parts)})")
        summary = (
            f"Schema Drift Report: {sources_monitored} source(s) monitored. "
            f"{drifts_detected} drift(s) detected in {', '.join(drift_summary_parts)}."
        )

    return {
        "status": "completed",
        "result": {
            "text": summary,
            "data": {
                "drift_report": {
                    "sources_monitored": sources_monitored,
                    "drifts_detected": drifts_detected,
                    "details": drift_details,
                }
            },
            "attachments": [],
        },
    }


async def schema_drift_loop() -> None:
    """Background loop — runs schema drift analysis every N seconds."""
    while True:
        try:
            record_task_heartbeat("schema_drift")
            result = await run_analysis()
            report = result["result"]["data"]["drift_report"]
            logger.info(
                "Schema drift check complete: %d sources, %d drifts",
                report["sources_monitored"],
                report["drifts_detected"],
            )
        except Exception as e:
            logger.error("Schema drift loop error: %s", e)

        await asyncio.sleep(_CHECK_INTERVAL)


class SchemaDriftDetectorAgent:
    """Native agent — returns on-demand schema drift report."""

    def __init__(self, agent):
        self.agent = agent

    async def process(self, envelope) -> dict:
        return await run_analysis()
