"""AgentContext — runtime context passed to agents during execution.

Provides agents with access to tools, LLM, audit emission, delegation,
and per-execution scratch memory without exposing raw infrastructure.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from trellis.models import AuditEvent

logger = logging.getLogger("trellis.agent_context")


class AgentContext:
    """Runtime context for agent execution.

    Holds references to the DB session, envelope data, and provides
    convenience methods for audit, tool execution, and LLM calls.

    Usage::

        async with AgentContext(agent_id="my-agent", trace_id="t-1",
                                envelope=env_dict, db=session) as ctx:
            await ctx.emit_event("agent_started", details={"step": 1})
            ctx.memory["key"] = "scratch value"
    """

    def __init__(
        self,
        *,
        agent_id: str,
        trace_id: str,
        envelope: dict,
        db: AsyncSession,
        logger: logging.Logger | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.trace_id = trace_id
        self.envelope = envelope
        self.db = db
        self.logger = logger or logging.getLogger(f"trellis.agent.{agent_id}")
        self.memory: dict[str, Any] = {}

    # ── Tools ─────────────────────────────────────────────────────────────

    @property
    def tools(self) -> Any:
        """Access the tool registry for execution.

        Will be wired to the ToolRegistry in a future iteration.
        """
        from trellis.tool_registry import tool_registry
        return tool_registry

    # ── LLM ───────────────────────────────────────────────────────────────

    @property
    def llm(self) -> Any:
        """Access the LLM gateway for chat completions.

        Returns a thin wrapper around the gateway providers so agents
        can call ``await ctx.llm.chat_completion(body)`` without
        importing gateway internals.
        """
        from trellis.gateway import _providers, MODEL_PROVIDER_MAP

        class _LLMProxy:
            """Minimal proxy so agents never touch provider selection directly."""

            async def chat_completion(self, body: dict[str, Any]) -> dict[str, Any]:
                model = body.get("model", "")
                provider_name = MODEL_PROVIDER_MAP.get(model, "nvidia")
                provider = _providers.get(provider_name)
                configured = getattr(
                    provider, "available",
                    getattr(provider, "is_configured", lambda: False),
                )
                if not provider or not (configured() if callable(configured) else configured):
                    provider = _providers.get("ollama")
                    if not provider:
                        raise RuntimeError("No LLM provider available")
                return await provider.chat_completion(body)

        return _LLMProxy()

    # ── Audit ─────────────────────────────────────────────────────────────

    async def emit_event(
        self,
        event_type: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> AuditEvent:
        """Emit an audit event scoped to this agent and trace."""
        envelope_id = self.envelope.get("envelope_id")
        event = AuditEvent(
            trace_id=self.trace_id,
            envelope_id=envelope_id,
            agent_id=self.agent_id,
            event_type=event_type,
            details=details or {},
            timestamp=datetime.now(timezone.utc),
        )
        self.db.add(event)
        await self.db.flush()
        self.logger.debug(
            "audit event_type=%s agent=%s trace=%s",
            event_type, self.agent_id, self.trace_id,
        )
        return event

    # ── Delegation ────────────────────────────────────────────────────────

    async def delegate(
        self,
        target_agent_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Delegate work to another agent (Iteration 2)."""
        raise NotImplementedError(
            "AgentContext.delegate() is not yet implemented — coming in Iteration 2"
        )

    # ── Async context manager ─────────────────────────────────────────────

    async def __aenter__(self) -> "AgentContext":
        self.logger.debug("AgentContext entered for agent=%s trace=%s", self.agent_id, self.trace_id)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        self.memory.clear()
        self.logger.debug("AgentContext exited for agent=%s trace=%s", self.agent_id, self.trace_id)
        return None
