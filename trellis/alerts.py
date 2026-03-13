"""Alerting & Notification Engine — configurable alert rules, multi-channel dispatch, deduplication.

Single file, Karpathy style. Hospital IT teams need reliable alerting that doesn't spam.

Alert lifecycle: condition met → check cooldown → fire alert → dispatch to channels → track state.
"""

import asyncio
import json
import logging
import os
import smtplib
import time
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from enum import Enum
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, JSON, func, select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from trellis.database import Base, async_session, get_db

logger = logging.getLogger("trellis.alerts")


# ═══════════════════════════════════════════════════════════════════════════
# Database Model
# ═══════════════════════════════════════════════════════════════════════════


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, default="")
    source: Mapped[str] = mapped_column(String, nullable=False)  # "finops", "phi_shield", "health", "observatory", "custom"
    condition_type: Mapped[str] = mapped_column(String, nullable=False)  # "threshold", "equals", "contains", "regex"
    condition_metric: Mapped[str] = mapped_column(String, nullable=False)  # e.g. "budget_pct", "phi_detected", "error_rate"
    condition_operator: Mapped[str] = mapped_column(String, default="gt")  # "gt", "lt", "gte", "lte", "eq", "neq"
    condition_value: Mapped[str] = mapped_column(String, nullable=False)  # threshold value (stored as string, cast at eval)
    channels: Mapped[list] = mapped_column(JSON, default=list)  # ["webhook", "email", "teams"]
    channel_config: Mapped[dict] = mapped_column(JSON, default=dict)  # {"webhook_url": "...", "email_to": "...", ...}
    severity: Mapped[str] = mapped_column(String, default="warning")  # "info", "warning", "critical"
    cooldown_minutes: Mapped[int] = mapped_column(Integer, default=15)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    agent_id_filter: Mapped[str | None] = mapped_column(String, nullable=True)  # optional: only fire for specific agent
    created: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    rule_name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)  # "firing", "resolved", "test"
    severity: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    metric_value: Mapped[str | None] = mapped_column(String, nullable=True)
    channels_notified: Mapped[list] = mapped_column(JSON, default=list)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    agent_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


# ═══════════════════════════════════════════════════════════════════════════
# Pydantic Schemas
# ═══════════════════════════════════════════════════════════════════════════


class AlertRuleCreate(BaseModel):
    name: str
    description: str = ""
    source: str  # "finops", "phi_shield", "health", "observatory", "custom"
    condition_type: str = "threshold"
    condition_metric: str
    condition_operator: str = "gt"
    condition_value: str
    channels: list[str] = Field(default_factory=list)
    channel_config: dict = Field(default_factory=dict)
    severity: str = "warning"
    cooldown_minutes: int = 15
    active: bool = True
    agent_id_filter: str | None = None


class AlertRuleRead(BaseModel):
    id: int
    name: str
    description: str
    source: str
    condition_type: str
    condition_metric: str
    condition_operator: str
    condition_value: str
    channels: list[str]
    channel_config: dict
    severity: str
    cooldown_minutes: int
    active: bool
    agent_id_filter: str | None
    created: str

    model_config = {"from_attributes": True}


class AlertRuleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    source: str | None = None
    condition_type: str | None = None
    condition_metric: str | None = None
    condition_operator: str | None = None
    condition_value: str | None = None
    channels: list[str] | None = None
    channel_config: dict | None = None
    severity: str | None = None
    cooldown_minutes: int | None = None
    active: bool | None = None
    agent_id_filter: str | None = None


class AlertEventRead(BaseModel):
    id: int
    rule_id: int
    rule_name: str
    status: str
    severity: str
    source: str
    message: str
    metric_value: str | None
    channels_notified: list[str]
    details: dict
    agent_id: str | None
    timestamp: str

    model_config = {"from_attributes": True}


class AlertTestRequest(BaseModel):
    rule_id: int


class AlertTestResponse(BaseModel):
    success: bool
    message: str
    channels_tested: list[str]


# ═══════════════════════════════════════════════════════════════════════════
# Alert State Tracking (in-memory for dedup/cooldown)
# ═══════════════════════════════════════════════════════════════════════════


# rule_id -> last fire timestamp
_last_fired: dict[int, float] = {}

# rule_id -> current state ("ok" | "firing")
_rule_state: dict[int, str] = {}


def _in_cooldown(rule_id: int, cooldown_minutes: int) -> bool:
    last = _last_fired.get(rule_id)
    if last is None:
        return False
    return (time.time() - last) < (cooldown_minutes * 60)


def _mark_fired(rule_id: int):
    _last_fired[rule_id] = time.time()
    _rule_state[rule_id] = "firing"


def _mark_resolved(rule_id: int):
    _rule_state[rule_id] = "ok"


# ═══════════════════════════════════════════════════════════════════════════
# Condition Evaluation
# ═══════════════════════════════════════════════════════════════════════════


def evaluate_condition(operator: str, actual_value: float, threshold: float) -> bool:
    """Evaluate a numeric condition."""
    ops = {
        "gt": lambda a, b: a > b,
        "lt": lambda a, b: a < b,
        "gte": lambda a, b: a >= b,
        "lte": lambda a, b: a <= b,
        "eq": lambda a, b: a == b,
        "neq": lambda a, b: a != b,
    }
    fn = ops.get(operator)
    if fn is None:
        logger.warning(f"Unknown operator: {operator}")
        return False
    return fn(actual_value, threshold)


# ═══════════════════════════════════════════════════════════════════════════
# Channel Dispatchers
# ═══════════════════════════════════════════════════════════════════════════


async def dispatch_webhook(url: str, payload: dict) -> bool:
    """Send alert via HTTP POST webhook."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code < 300:
                logger.info(f"Webhook dispatched to {url}: {resp.status_code}")
                return True
            logger.warning(f"Webhook failed: {url} returned {resp.status_code}")
            return False
    except Exception as e:
        logger.error(f"Webhook dispatch error: {e}")
        return False


async def dispatch_email(to: str, subject: str, body: str, config: dict) -> bool:
    """Send alert via SMTP email."""
    smtp_host = config.get("smtp_host") or os.environ.get("TRELLIS_SMTP_HOST", "")
    smtp_port = int(config.get("smtp_port") or os.environ.get("TRELLIS_SMTP_PORT", "587"))
    smtp_user = config.get("smtp_user") or os.environ.get("TRELLIS_SMTP_USER", "")
    smtp_pass = config.get("smtp_pass") or os.environ.get("TRELLIS_SMTP_PASS", "")
    from_addr = config.get("from_addr") or os.environ.get("TRELLIS_SMTP_FROM", smtp_user)

    if not smtp_host:
        logger.warning("SMTP not configured, skipping email alert")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to
        msg.attach(MIMEText(body, "html"))

        # Run SMTP in thread to not block event loop
        def _send():
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                if smtp_user:
                    server.login(smtp_user, smtp_pass)
                server.send_message(msg)

        await asyncio.get_event_loop().run_in_executor(None, _send)
        logger.info(f"Email alert sent to {to}")
        return True
    except Exception as e:
        logger.error(f"Email dispatch error: {e}")
        return False


async def dispatch_teams(webhook_url: str, payload: dict) -> bool:
    """Send alert to Teams via incoming webhook or Bot Framework proactive message."""
    # Teams incoming webhook accepts Adaptive Card or simple message
    card = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": "FF0000" if payload.get("severity") == "critical" else "FFA500",
        "summary": payload.get("message", "Trellis Alert"),
        "sections": [{
            "activityTitle": f"🚨 Trellis Alert: {payload.get('rule_name', 'Unknown')}",
            "activitySubtitle": payload.get("source", ""),
            "facts": [
                {"name": "Severity", "value": payload.get("severity", "warning")},
                {"name": "Metric", "value": str(payload.get("metric_value", "N/A"))},
                {"name": "Status", "value": payload.get("status", "firing")},
            ],
            "text": payload.get("message", ""),
            "markdown": True,
        }],
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(webhook_url, json=card)
            if resp.status_code < 300:
                logger.info(f"Teams alert dispatched")
                return True
            logger.warning(f"Teams webhook failed: {resp.status_code}")
            return False
    except Exception as e:
        logger.error(f"Teams dispatch error: {e}")
        return False


async def dispatch_alert(rule: AlertRule, message: str, metric_value: str | None,
                         details: dict, agent_id: str | None = None,
                         status: str = "firing") -> AlertEvent:
    """Dispatch alert to all configured channels and persist event."""
    payload = {
        "rule_id": rule.id,
        "rule_name": rule.name,
        "severity": rule.severity,
        "source": rule.source,
        "message": message,
        "metric_value": metric_value,
        "status": status,
        "agent_id": agent_id,
        "details": details,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    channels_notified = []

    for channel in rule.channels:
        success = False
        if channel == "webhook":
            url = rule.channel_config.get("webhook_url", "")
            if url:
                success = await dispatch_webhook(url, payload)
        elif channel == "email":
            to = rule.channel_config.get("email_to", "")
            if to:
                subject = f"[Trellis {rule.severity.upper()}] {rule.name}"
                body = f"""
                <h2>🚨 {rule.name}</h2>
                <p><strong>Severity:</strong> {rule.severity}</p>
                <p><strong>Source:</strong> {rule.source}</p>
                <p><strong>Message:</strong> {message}</p>
                <p><strong>Metric Value:</strong> {metric_value or 'N/A'}</p>
                <p><strong>Agent:</strong> {agent_id or 'N/A'}</p>
                <p><strong>Time:</strong> {payload['timestamp']}</p>
                """
                success = await dispatch_email(to, subject, body, rule.channel_config)
        elif channel == "teams":
            url = rule.channel_config.get("teams_webhook_url", "")
            if url:
                success = await dispatch_teams(url, payload)

        if success:
            channels_notified.append(channel)

    # Persist to DB
    event = AlertEvent(
        rule_id=rule.id,
        rule_name=rule.name,
        status=status,
        severity=rule.severity,
        source=rule.source,
        message=message,
        metric_value=metric_value,
        channels_notified=channels_notified,
        details=details,
        agent_id=agent_id,
    )

    async with async_session() as db:
        db.add(event)
        await db.commit()
        await db.refresh(event)

    return event


# ═══════════════════════════════════════════════════════════════════════════
# Alert Engine — check rules against metrics and fire if needed
# ═══════════════════════════════════════════════════════════════════════════


async def fire_alert(
    source: str,
    metric: str,
    value: float,
    message: str | None = None,
    agent_id: str | None = None,
    details: dict | None = None,
):
    """Called by Observatory, FinOps, PHI Shield, Health Auditor to fire alerts.

    Checks all active rules matching this source+metric, evaluates conditions,
    respects cooldown, and dispatches.
    """
    async with async_session() as db:
        q = select(AlertRule).where(
            AlertRule.active == True,
            AlertRule.source == source,
            AlertRule.condition_metric == metric,
        )
        result = await db.execute(q)
        rules = result.scalars().all()

    for rule in rules:
        # Agent filter
        if rule.agent_id_filter and agent_id and rule.agent_id_filter != agent_id:
            continue

        # Evaluate condition
        try:
            threshold = float(rule.condition_value)
        except (ValueError, TypeError):
            logger.warning(f"Rule {rule.id} has non-numeric threshold: {rule.condition_value}")
            continue

        if not evaluate_condition(rule.condition_operator, value, threshold):
            # Condition not met — if was firing, resolve it
            if _rule_state.get(rule.id) == "firing":
                _mark_resolved(rule.id)
                resolve_msg = message or f"{metric} returned to normal (value={value})"
                await dispatch_alert(rule, resolve_msg, str(value), details or {}, agent_id, status="resolved")
            continue

        # Condition met — check cooldown
        if _in_cooldown(rule.id, rule.cooldown_minutes):
            logger.debug(f"Rule {rule.id} ({rule.name}) in cooldown, skipping")
            continue

        # Fire!
        _mark_fired(rule.id)
        fire_msg = message or f"{metric} = {value} (threshold: {rule.condition_operator} {rule.condition_value})"
        await dispatch_alert(rule, fire_msg, str(value), details or {}, agent_id)
        logger.info(f"Alert fired: {rule.name} — {fire_msg}")


async def fire_alert_event(
    source: str,
    metric: str,
    message: str,
    agent_id: str | None = None,
    details: dict | None = None,
):
    """Fire a non-numeric event alert (e.g., PHI detected, health check failed).
    Matches rules where condition_type == 'equals' and condition_value matches metric.
    """
    async with async_session() as db:
        q = select(AlertRule).where(
            AlertRule.active == True,
            AlertRule.source == source,
            AlertRule.condition_metric == metric,
        )
        result = await db.execute(q)
        rules = result.scalars().all()

    for rule in rules:
        if rule.agent_id_filter and agent_id and rule.agent_id_filter != agent_id:
            continue

        if _in_cooldown(rule.id, rule.cooldown_minutes):
            continue

        _mark_fired(rule.id)
        await dispatch_alert(rule, message, None, details or {}, agent_id)
        logger.info(f"Event alert fired: {rule.name} — {message}")


# ═══════════════════════════════════════════════════════════════════════════
# API Router
# ═══════════════════════════════════════════════════════════════════════════


alerts_router = APIRouter(prefix="/alerts", tags=["alerts"])


@alerts_router.get("/rules", response_model=list[AlertRuleRead])
async def list_alert_rules(
    source: str | None = Query(None),
    active: bool | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List all alert rules, optionally filtered by source or active status."""
    q = select(AlertRule)
    if source:
        q = q.where(AlertRule.source == source)
    if active is not None:
        q = q.where(AlertRule.active == active)
    q = q.order_by(AlertRule.created.desc())
    result = await db.execute(q)
    rules = result.scalars().all()
    return [_rule_to_read(r) for r in rules]


@alerts_router.post("/rules", response_model=AlertRuleRead, status_code=201)
async def create_alert_rule(body: AlertRuleCreate, db: AsyncSession = Depends(get_db)):
    """Create a new alert rule."""
    rule = AlertRule(
        name=body.name,
        description=body.description,
        source=body.source,
        condition_type=body.condition_type,
        condition_metric=body.condition_metric,
        condition_operator=body.condition_operator,
        condition_value=body.condition_value,
        channels=body.channels,
        channel_config=body.channel_config,
        severity=body.severity,
        cooldown_minutes=body.cooldown_minutes,
        active=body.active,
        agent_id_filter=body.agent_id_filter,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return _rule_to_read(rule)


@alerts_router.get("/rules/{rule_id}", response_model=AlertRuleRead)
async def get_alert_rule(rule_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single alert rule."""
    rule = await db.get(AlertRule, rule_id)
    if not rule:
        raise HTTPException(404, "Alert rule not found")
    return _rule_to_read(rule)


@alerts_router.put("/rules/{rule_id}", response_model=AlertRuleRead)
async def update_alert_rule(rule_id: int, body: AlertRuleUpdate, db: AsyncSession = Depends(get_db)):
    """Update an alert rule."""
    rule = await db.get(AlertRule, rule_id)
    if not rule:
        raise HTTPException(404, "Alert rule not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    await db.commit()
    await db.refresh(rule)
    return _rule_to_read(rule)


@alerts_router.delete("/rules/{rule_id}", status_code=204)
async def delete_alert_rule(rule_id: int, db: AsyncSession = Depends(get_db)):
    """Delete an alert rule."""
    rule = await db.get(AlertRule, rule_id)
    if not rule:
        raise HTTPException(404, "Alert rule not found")
    await db.delete(rule)
    await db.commit()


@alerts_router.put("/rules/{rule_id}/toggle", response_model=AlertRuleRead)
async def toggle_alert_rule(rule_id: int, db: AsyncSession = Depends(get_db)):
    """Toggle an alert rule active/inactive."""
    rule = await db.get(AlertRule, rule_id)
    if not rule:
        raise HTTPException(404, "Alert rule not found")
    rule.active = not rule.active
    await db.commit()
    await db.refresh(rule)
    return _rule_to_read(rule)


@alerts_router.get("/history", response_model=list[AlertEventRead])
async def list_alert_history(
    rule_id: int | None = Query(None),
    status: str | None = Query(None),
    severity: str | None = Query(None),
    source: str | None = Query(None),
    agent_id: str | None = Query(None),
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
):
    """List alert history with optional filters."""
    q = select(AlertEvent)
    if rule_id is not None:
        q = q.where(AlertEvent.rule_id == rule_id)
    if status:
        q = q.where(AlertEvent.status == status)
    if severity:
        q = q.where(AlertEvent.severity == severity)
    if source:
        q = q.where(AlertEvent.source == source)
    if agent_id:
        q = q.where(AlertEvent.agent_id == agent_id)
    q = q.order_by(AlertEvent.timestamp.desc()).limit(limit)
    result = await db.execute(q)
    events = result.scalars().all()
    return [_event_to_read(e) for e in events]


@alerts_router.post("/test", response_model=AlertTestResponse)
async def test_alert(body: AlertTestRequest, db: AsyncSession = Depends(get_db)):
    """Test an alert rule by sending a test notification to all configured channels."""
    rule = await db.get(AlertRule, body.rule_id)
    if not rule:
        raise HTTPException(404, "Alert rule not found")

    event = await dispatch_alert(
        rule,
        f"🧪 TEST ALERT: {rule.name} — this is a test notification",
        "test",
        {"test": True},
        status="test",
    )

    return AlertTestResponse(
        success=True,
        message=f"Test alert dispatched to {len(event.channels_notified)} channel(s)",
        channels_tested=event.channels_notified,
    )


@alerts_router.get("/summary")
async def alert_summary(db: AsyncSession = Depends(get_db)):
    """Quick summary: total rules, active rules, recent events by severity."""
    rules_result = await db.execute(select(func.count(AlertRule.id)))
    total_rules = rules_result.scalar() or 0

    active_result = await db.execute(select(func.count(AlertRule.id)).where(AlertRule.active == True))
    active_rules = active_result.scalar() or 0

    # Last 24h events by severity
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    events_result = await db.execute(
        select(AlertEvent.severity, func.count(AlertEvent.id))
        .where(AlertEvent.timestamp >= since)
        .group_by(AlertEvent.severity)
    )
    by_severity = {row[0]: row[1] for row in events_result.all()}

    # Currently firing
    firing_result = await db.execute(
        select(func.count(AlertEvent.id)).where(
            AlertEvent.status == "firing",
            AlertEvent.timestamp >= since,
        )
    )
    firing_count = firing_result.scalar() or 0

    return {
        "total_rules": total_rules,
        "active_rules": active_rules,
        "firing_count": firing_count,
        "last_24h": by_severity,
    }


# ── Helpers ────────────────────────────────────────────────────────────────


def _rule_to_read(rule: AlertRule) -> AlertRuleRead:
    return AlertRuleRead(
        id=rule.id,
        name=rule.name,
        description=rule.description,
        source=rule.source,
        condition_type=rule.condition_type,
        condition_metric=rule.condition_metric,
        condition_operator=rule.condition_operator,
        condition_value=rule.condition_value,
        channels=rule.channels or [],
        channel_config=rule.channel_config or {},
        severity=rule.severity,
        cooldown_minutes=rule.cooldown_minutes,
        active=rule.active,
        agent_id_filter=rule.agent_id_filter,
        created=rule.created.isoformat() if rule.created else "",
    )


def _event_to_read(event: AlertEvent) -> AlertEventRead:
    return AlertEventRead(
        id=event.id,
        rule_id=event.rule_id,
        rule_name=event.rule_name,
        status=event.status,
        severity=event.severity,
        source=event.source,
        message=event.message,
        metric_value=event.metric_value,
        channels_notified=event.channels_notified or [],
        details=event.details or {},
        agent_id=event.agent_id,
        timestamp=event.timestamp.isoformat() if event.timestamp else "",
    )
