"""All SQLAlchemy models — single file."""

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from trellis.database import Base


class Agent(Base):
    __tablename__ = "agents"

    agent_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    owner: Mapped[str] = mapped_column(String, nullable=False)
    department: Mapped[str] = mapped_column(String, nullable=False)
    framework: Mapped[str] = mapped_column(String, nullable=False)
    agent_type: Mapped[str] = mapped_column(String, default="http")
    runtime_type: Mapped[str] = mapped_column(String, default="pi")
    endpoint: Mapped[str | None] = mapped_column(String, nullable=True)
    health_endpoint: Mapped[str | None] = mapped_column(String, nullable=True)
    tools: Mapped[list] = mapped_column(JSON, default=list)
    channels: Mapped[list] = mapped_column(JSON, default=list)
    maturity: Mapped[str] = mapped_column(String, default="shadow")
    cost_mode: Mapped[str] = mapped_column(String, default="managed")
    status: Mapped[str] = mapped_column(String, default="unknown")
    llm_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    function_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    phi_shield_mode: Mapped[str] = mapped_column(String, default="off")
    created: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    last_health_check: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    key_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    agent_id: Mapped[str] = mapped_column(String, ForeignKey("agents.agent_id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    budget_daily_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    budget_monthly_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    preferred_provider: Mapped[str | None] = mapped_column(String, nullable=True)
    default_model: Mapped[str | None] = mapped_column(String, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    last_used: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trace_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    envelope_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    agent_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


class CostEvent(Base):
    __tablename__ = "cost_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trace_id: Mapped[str | None] = mapped_column(String, nullable=True)
    agent_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    model_requested: Mapped[str] = mapped_column(String, nullable=False)
    model_used: Mapped[str] = mapped_column(String, nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    has_tool_calls: Mapped[bool] = mapped_column(Boolean, default=False)
    complexity_class: Mapped[str | None] = mapped_column(String, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


class EnvelopeLog(Base):
    __tablename__ = "envelope_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    envelope_id: Mapped[str] = mapped_column(String, index=True)
    trace_id: Mapped[str] = mapped_column(String, index=True)
    source_type: Mapped[str] = mapped_column(String)
    envelope_data: Mapped[dict] = mapped_column(JSON)
    matched_rule_id: Mapped[str | None] = mapped_column(String, nullable=True)
    matched_rule_name: Mapped[str | None] = mapped_column(String, nullable=True)
    target_agent_id: Mapped[str | None] = mapped_column(String, nullable=True)
    dispatch_status: Mapped[str] = mapped_column(String, default="pending")
    dispatch_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class ModelRoute(Base):
    __tablename__ = "model_routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    cost_per_1k_input: Mapped[float] = mapped_column(Float, default=0.0)
    cost_per_1k_output: Mapped[float] = mapped_column(Float, default=0.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    conditions: Mapped[dict] = mapped_column(JSON, nullable=False)
    actions: Mapped[dict] = mapped_column(JSON, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    fan_out: Mapped[bool] = mapped_column(Boolean, default=False)
