from trellis.agents.health_auditor import record_task_heartbeat
"""Rule Optimizer Agent — platform housekeeping agent.

Analyzes routing rules for optimization opportunities: dead rules,
overlapping conditions, unmatched envelopes, and utilization ranking.
Runs nightly at 2 AM (configurable). Read-only — never modifies rules.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from collections import defaultdict

from sqlalchemy import func, select

logger = logging.getLogger("trellis.agents.rule_optimizer")

_OPTIMIZER_HOUR = int(os.environ.get("TRELLIS_RULE_OPTIMIZER_HOUR", 2))


async def run_analysis(days: int = 7) -> dict:
    """Run rule optimization analysis. Returns structured report dict."""
    from trellis.database import async_session
    from trellis.models import EnvelopeLog, Rule

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    async with async_session() as db:
        # Fetch all active rules
        rules_result = await db.execute(select(Rule).where(Rule.active == True))
        rules = list(rules_result.scalars().all())

        # Fetch envelope log entries in the analysis window
        logs_result = await db.execute(
            select(
                EnvelopeLog.matched_rule_id,
                EnvelopeLog.matched_rule_name,
                EnvelopeLog.dispatch_status,
                EnvelopeLog.source_type,
            ).where(EnvelopeLog.timestamp >= cutoff)
        )
        logs = logs_result.all()

    # --- Build match count per rule_id ---
    match_counts: dict[str, int] = defaultdict(int)
    no_match_count = 0
    no_match_sources: dict[str, int] = defaultdict(int)

    for log in logs:
        if log.dispatch_status == "no_match" or log.matched_rule_id is None:
            no_match_count += 1
            no_match_sources[log.source_type or "unknown"] += 1
        else:
            match_counts[log.matched_rule_id] += 1

    # --- Dead rules: active rules with 0 matches in period ---
    dead_rules = []
    for rule in rules:
        rid = str(rule.id)
        if match_counts.get(rid, 0) == 0:
            dead_rules.append({
                "rule_id": rule.id,
                "name": rule.name,
                "last_match": None,
                "recommendation": "Consider disabling or removing — no matches in last {} days".format(days),
            })

    # --- Overlapping rules: same conditions, different priority or target ---
    # Normalize conditions to a stable string key
    def _cond_key(conditions: dict) -> str:
        return str(sorted(conditions.items()))

    cond_groups: dict[str, list] = defaultdict(list)
    for rule in rules:
        key = _cond_key(rule.conditions)
        cond_groups[key].append(rule)

    overlapping_rules = []
    priority_conflicts = []

    for key, group in cond_groups.items():
        if len(group) < 2:
            continue
        shared = group[0].conditions
        rule_ids = [r.id for r in group]
        targets = {r.actions.get("route_to") for r in group}
        priorities = {r.priority for r in group}

        if len(priorities) > 1:
            # Same conditions, different priorities — confusing ordering
            overlapping_rules.append({
                "rules": rule_ids,
                "shared_conditions": shared,
                "recommendation": "Rules share identical conditions with different priorities — merge or differentiate",
            })

        if len(targets) > 1:
            # Same conditions routing to different targets based on priority — conflict
            priority_conflicts.append({
                "rules": rule_ids,
                "shared_conditions": shared,
                "targets": list(targets),
                "recommendation": "Same conditions route to different targets — review priority ordering",
            })

    # --- Utilization ranking ---
    utilization = []
    for i, rule in enumerate(sorted(rules, key=lambda r: match_counts.get(str(r.id), 0), reverse=True)):
        count = match_counts.get(str(rule.id), 0)
        rank = i + 1 if count > 0 else "last"
        utilization.append({
            "rule_id": rule.id,
            "name": rule.name,
            "matches": count,
            "rank": rank,
        })

    # --- Top unmatched sources ---
    top_unmatched_sources = [
        {"source_type": src, "count": cnt}
        for src, cnt in sorted(no_match_sources.items(), key=lambda x: x[1], reverse=True)
    ]

    summary_parts = []
    if dead_rules:
        summary_parts.append(f"{len(dead_rules)} dead rule(s)")
    if overlapping_rules:
        summary_parts.append(f"{len(overlapping_rules)} overlap(s) detected")
    if priority_conflicts:
        summary_parts.append(f"{len(priority_conflicts)} priority conflict(s)")
    if no_match_count:
        summary_parts.append(f"{no_match_count} unmatched envelope(s) in last {days} days")
    if not summary_parts:
        summary_parts.append("no issues found")

    summary_text = "Rule Optimization Report: " + ", ".join(summary_parts) + "."

    return {
        "status": "completed",
        "result": {
            "text": summary_text,
            "data": {
                "optimization": {
                    "analysis_period_days": days,
                    "total_rules": len(rules),
                    "dead_rules": dead_rules,
                    "overlapping_rules": overlapping_rules,
                    "priority_conflicts": priority_conflicts,
                    "unmatched_envelopes": no_match_count,
                    "top_unmatched_sources": top_unmatched_sources,
                    "utilization": utilization,
                }
            },
            "attachments": [],
        },
    }


async def rule_optimizer_loop() -> None:
    """Background loop — runs analysis once per day at the configured hour."""
    _last_run_day: int | None = None

    while True:
        now = datetime.now(timezone.utc)
        if now.hour == _OPTIMIZER_HOUR and now.day != _last_run_day:
            _last_run_day = now.day
            record_task_heartbeat("rule_optimizer")
            try:
                result = await run_analysis()
                opt = result["result"]["data"]["optimization"]
                logger.info(
                    "Rule optimizer complete: %d rules, %d dead, %d overlaps, %d unmatched",
                    opt["total_rules"],
                    len(opt["dead_rules"]),
                    len(opt["overlapping_rules"]),
                    opt["unmatched_envelopes"],
                )
            except Exception as e:
                logger.error("Rule optimizer loop error: %s", e)

        await asyncio.sleep(3600)  # check every hour


class RuleOptimizerAgent:
    """Native agent — returns on-demand rule optimization report."""

    def __init__(self, agent):
        self.agent = agent

    async def process(self, envelope) -> dict:
        hints = envelope.routing_hints or {}
        days = int(hints.get("days", 7))
        return await run_analysis(days=days)
