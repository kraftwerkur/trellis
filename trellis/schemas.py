"""All Pydantic schemas — single file."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


# ── Agent schemas ──────────────────────────────────────────────────────────

class LLMConfig(BaseModel):
    system_prompt: str
    model: str = "qwen3.5:9b"
    temperature: float = 0.7
    max_tokens: int = 1024


class AgentCreate(BaseModel):
    agent_id: str
    name: str
    owner: str
    department: str
    framework: str = "none"
    agent_type: str = "llm"
    runtime_type: str = "pi"
    endpoint: str | None = None
    health_endpoint: str | None = None
    tools: list[str] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=list)
    maturity: str = "shadow"
    cost_mode: str = "managed"
    status: str = "unknown"
    system_prompt: str | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    llm_config: LLMConfig | None = None
    function_ref: str | None = None
    phi_shield_mode: str = "off"


class AgentUpdate(BaseModel):
    name: str | None = None
    owner: str | None = None
    department: str | None = None
    framework: str | None = None
    agent_type: str | None = None
    runtime_type: str | None = None
    endpoint: str | None = None
    health_endpoint: str | None = None
    tools: list[str] | None = None
    channels: list[str] | None = None
    maturity: str | None = None
    cost_mode: str | None = None
    status: str | None = None
    system_prompt: str | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    llm_config: dict[str, Any] | None = None
    function_ref: str | None = None
    phi_shield_mode: str | None = None


class AgentRead(BaseModel):
    agent_id: str
    name: str
    owner: str
    department: str
    framework: str
    agent_type: str
    runtime_type: str
    endpoint: str | None
    health_endpoint: str | None
    tools: list[str]
    channels: list[str]
    maturity: str
    cost_mode: str
    status: str
    system_prompt: str | None = None
    llm_config: dict[str, Any] | None = None
    function_ref: str | None = None
    phi_shield_mode: str = "off"
    created: datetime
    last_health_check: datetime | None

    model_config = {"from_attributes": True}


class AgentCreateResponse(AgentRead):
    """Returned on agent creation — includes the one-time API key."""
    api_key: str | None = None


# ── Audit schemas ──────────────────────────────────────────────────────────

class AuditEventRead(BaseModel):
    id: int
    trace_id: str | None
    envelope_id: str | None
    agent_id: str | None
    event_type: str
    details: dict[str, Any]
    timestamp: datetime

    model_config = {"from_attributes": True}


# ── Cost / API key schemas ─────────────────────────────────────────────────

class ApiKeyCreate(BaseModel):
    agent_id: str
    name: str
    budget_daily_usd: float | None = None
    budget_monthly_usd: float | None = None
    preferred_provider: str | None = None
    default_model: str | None = None


class ApiKeyCreated(BaseModel):
    id: int
    key: str
    key_prefix: str
    agent_id: str
    name: str


class ApiKeyRead(BaseModel):
    id: int
    key_prefix: str
    agent_id: str
    name: str
    budget_daily_usd: float | None
    budget_monthly_usd: float | None
    preferred_provider: str | None
    default_model: str | None
    active: bool
    created: datetime
    last_used: datetime | None

    model_config = {"from_attributes": True}


class CostEventRead(BaseModel):
    id: int
    trace_id: str | None
    agent_id: str
    model_requested: str
    model_used: str
    provider: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    has_tool_calls: bool
    complexity_class: str | None = None
    timestamp: datetime

    model_config = {"from_attributes": True}


class CostSummary(BaseModel):
    agent_id: str
    total_cost_usd: float
    total_tokens_in: int
    total_tokens_out: int
    request_count: int


# ── Envelope schemas ───────────────────────────────────────────────────────

class Sender(BaseModel):
    id: str = ""
    name: str = ""
    department: str = ""
    roles: list[str] = Field(default_factory=list)


class Metadata(BaseModel):
    trace_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    priority: str = "normal"
    sender: Sender = Field(default_factory=Sender)


class Payload(BaseModel):
    text: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class RoutingHints(BaseModel):
    agent_id: str | None = None
    department: str | None = None
    category: str | None = None
    tags: list[str] = Field(default_factory=list)


class Envelope(BaseModel):
    envelope_id: str = Field(default_factory=lambda: str(uuid4()))
    source_type: str = "api"
    source_id: str = ""
    payload: Payload = Field(default_factory=Payload)
    metadata: Metadata = Field(default_factory=Metadata)
    routing_hints: RoutingHints = Field(default_factory=RoutingHints)


class AgentResult(BaseModel):
    status: str = "completed"
    result: dict[str, Any] = Field(default_factory=dict)
    delegations: list[dict[str, Any]] = Field(default_factory=list)
    cost_report: dict[str, Any] = Field(default_factory=dict)


class EnvelopeLogRead(BaseModel):
    id: int
    envelope_id: str
    trace_id: str
    source_type: str
    matched_rule_name: str | None
    target_agent_id: str | None
    dispatch_status: str
    error: str | None
    timestamp: datetime

    model_config = {"from_attributes": True}


class HttpAdapterInput(BaseModel):
    """Simplified input for the HTTP adapter."""
    text: str
    sender_name: str = "anonymous"
    sender_department: str = ""
    priority: str = "normal"
    tags: list[str] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Gateway schemas ────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str
    content: str | None = None
    name: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None


class ToolFunction(BaseModel):
    name: str
    description: str | None = None
    parameters: dict[str, Any] | None = None


class ToolDef(BaseModel):
    type: str = "function"
    function: ToolFunction


class ChatCompletionRequest(BaseModel):
    model: str | None = None
    messages: list[ChatMessage]
    tools: list[ToolDef] | None = None
    tool_choice: str | dict[str, Any] | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    stream: bool = False


class UsageInfo(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChoiceMessage(BaseModel):
    role: str = "assistant"
    content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


class Choice(BaseModel):
    index: int = 0
    message: ChoiceMessage
    finish_reason: str = "stop"


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[Choice]
    usage: UsageInfo


# ── Rule schemas ───────────────────────────────────────────────────────────

class RuleCreate(BaseModel):
    name: str
    priority: int = 100
    conditions: dict[str, Any]
    actions: dict[str, Any]
    active: bool = True
    fan_out: bool = False


class RuleUpdate(BaseModel):
    name: str | None = None
    priority: int | None = None
    conditions: dict[str, Any] | None = None
    actions: dict[str, Any] | None = None
    active: bool | None = None
    fan_out: bool | None = None


class RuleRead(BaseModel):
    id: int
    name: str
    priority: int
    conditions: dict[str, Any]
    actions: dict[str, Any]
    active: bool
    fan_out: bool

    model_config = {"from_attributes": True}


class RuleTestRequest(BaseModel):
    envelope: dict[str, Any]


class RuleTestResult(BaseModel):
    matched_rules: list[RuleRead]
