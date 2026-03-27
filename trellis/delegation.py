"""Agent-to-Agent delegation protocol.

Provides DelegationRequest/DelegationResult dataclasses and a DelegationEngine
that routes work between agents with hop-limit safety, circular-delegation
detection, and full audit trails.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trellis.models import Agent, AuditEvent

logger = logging.getLogger("trellis.delegation")


# ── Data classes ──────────────────────────────────────────────────────────


@dataclass
class DelegationRequest:
    """A request to delegate work to another agent."""

    from_agent: str
    to_agent: str
    envelope: dict = field(default_factory=dict)
    callback_mode: str = "sync"  # sync | fire_and_forget
    context: dict = field(default_factory=dict)
    max_hops: int = 3
    hop_count: int = 0
    parent_trace_id: str | None = None
    delegation_chain: list[str] = field(default_factory=list)

    # Legacy compat fields
    text: str = ""
    trace_id: str | None = None
    delegation_id: str = field(default_factory=lambda: f"del-{uuid.uuid4().hex[:12]}")
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class DelegationResult:
    """Result returned from a delegated agent execution."""

    status: str  # completed | failed | rejected | error
    from_agent: str = ""
    to_agent: str = ""
    result: dict = field(default_factory=dict)
    hop_count: int = 0
    error: str | None = None

    # Legacy compat
    delegation_id: str = ""


# ── Audit helper ──────────────────────────────────────────────────────────


async def _emit_audit(
    db: AsyncSession,
    event_type: str,
    *,
    trace_id: str | None = None,
    envelope_id: str | None = None,
    agent_id: str | None = None,
    details: dict | None = None,
) -> AuditEvent:
    event = AuditEvent(
        trace_id=trace_id,
        envelope_id=envelope_id,
        agent_id=agent_id,
        event_type=event_type,
        details=details or {},
        timestamp=datetime.now(timezone.utc),
    )
    db.add(event)
    await db.flush()
    return event


# ── Engine ────────────────────────────────────────────────────────────────


class DelegationEngine:
    """Orchestrates agent-to-agent delegation with safety checks."""

    def __init__(self, db_session_factory=None, router_dispatch_fn=None, *, db=None):
        """
        Parameters
        ----------
        db_session_factory : async context-manager callable that yields AsyncSession
        router_dispatch_fn : async callable(envelope, agent, db) -> dict
        db : legacy single-session fallback
        """
        self.db_session_factory = db_session_factory
        self.router_dispatch_fn = router_dispatch_fn
        self.db = db  # legacy compat

    # ── New A2A delegation API ────────────────────────────────────────

    async def delegate(self, request: DelegationRequest, *, db=None) -> DelegationResult:
        """Execute a delegation request end-to-end.

        Uses router_dispatch_fn when db_session_factory is set (new path),
        otherwise falls back to legacy native-agent dispatch.
        """
        # Legacy path: no session factory configured
        if self.db_session_factory is None:
            return await self._legacy_delegate(request, db=db)

        return await self._a2a_delegate(request)

    async def validate_delegation(self, request: DelegationRequest) -> bool:
        """Public validation entry point (returns bool only)."""
        async with self.db_session_factory() as db:
            valid, _ = await self._validate(request, db)
            return valid

    # ── A2A delegation (new) ──────────────────────────────────────────

    async def _a2a_delegate(self, request: DelegationRequest) -> DelegationResult:
        async with self.db_session_factory() as db:
            valid, rejection_reason = await self._validate(request, db)
            if not valid:
                await _emit_audit(
                    db,
                    "delegation.rejected",
                    trace_id=request.parent_trace_id,
                    agent_id=request.from_agent,
                    details={
                        "from_agent": request.from_agent,
                        "to_agent": request.to_agent,
                        "reason": rejection_reason,
                        "hop_count": request.hop_count,
                        "delegation_chain": request.delegation_chain,
                    },
                )
                await db.commit()
                return DelegationResult(
                    status="rejected",
                    from_agent=request.from_agent,
                    to_agent=request.to_agent,
                    result={},
                    hop_count=request.hop_count,
                    error=rejection_reason,
                )

            # Look up target agent
            agent = (
                await db.execute(
                    select(Agent).where(Agent.agent_id == request.to_agent)
                )
            ).scalar_one()

            # Build delegation envelope
            envelope_id = str(uuid.uuid4())
            delegation_envelope = {
                **request.envelope,
                "envelope_id": envelope_id,
                "delegated_by": request.from_agent,
                "delegation_chain": request.delegation_chain + [request.from_agent],
                "delegation_hop": request.hop_count + 1,
                "delegation_context": request.context,
                "parent_trace_id": request.parent_trace_id,
            }

            # Emit start audit
            await _emit_audit(
                db,
                "delegation.start",
                trace_id=request.parent_trace_id,
                envelope_id=envelope_id,
                agent_id=request.from_agent,
                details={
                    "from_agent": request.from_agent,
                    "to_agent": request.to_agent,
                    "callback_mode": request.callback_mode,
                    "hop_count": request.hop_count,
                    "delegation_chain": request.delegation_chain
                    + [request.from_agent],
                },
            )
            await db.commit()

        # fire_and_forget — schedule background, return immediately
        if request.callback_mode == "fire_and_forget":
            async def _bg():
                async with self.db_session_factory() as db2:
                    try:
                        await self.router_dispatch_fn(
                            delegation_envelope, agent, db2
                        )
                        await _emit_audit(
                            db2,
                            "delegation.complete",
                            trace_id=request.parent_trace_id,
                            envelope_id=envelope_id,
                            agent_id=request.to_agent,
                            details={
                                "from_agent": request.from_agent,
                                "to_agent": request.to_agent,
                                "hop_count": request.hop_count + 1,
                            },
                        )
                        await db2.commit()
                    except Exception as exc:
                        logger.exception("Background delegation failed: %s", exc)
                        await _emit_audit(
                            db2,
                            "delegation.failed",
                            trace_id=request.parent_trace_id,
                            envelope_id=envelope_id,
                            agent_id=request.to_agent,
                            details={"error": str(exc)},
                        )
                        await db2.commit()

            asyncio.ensure_future(_bg())
            return DelegationResult(
                status="completed",
                from_agent=request.from_agent,
                to_agent=request.to_agent,
                result={"fire_and_forget": True, "envelope_id": envelope_id},
                hop_count=request.hop_count + 1,
            )

        # Synchronous delegation
        async with self.db_session_factory() as db:
            try:
                dispatch_result = await self.router_dispatch_fn(
                    delegation_envelope, agent, db
                )
                await _emit_audit(
                    db,
                    "delegation.complete",
                    trace_id=request.parent_trace_id,
                    envelope_id=envelope_id,
                    agent_id=request.to_agent,
                    details={
                        "from_agent": request.from_agent,
                        "to_agent": request.to_agent,
                        "hop_count": request.hop_count + 1,
                    },
                )
                await db.commit()
                return DelegationResult(
                    status="completed",
                    from_agent=request.from_agent,
                    to_agent=request.to_agent,
                    result=dispatch_result
                    if isinstance(dispatch_result, dict)
                    else {"raw": dispatch_result},
                    hop_count=request.hop_count + 1,
                )
            except Exception as exc:
                logger.exception("Delegation dispatch failed: %s", exc)
                await _emit_audit(
                    db,
                    "delegation.failed",
                    trace_id=request.parent_trace_id,
                    envelope_id=envelope_id,
                    agent_id=request.to_agent,
                    details={
                        "from_agent": request.from_agent,
                        "to_agent": request.to_agent,
                        "error": str(exc),
                    },
                )
                await db.commit()
                return DelegationResult(
                    status="failed",
                    from_agent=request.from_agent,
                    to_agent=request.to_agent,
                    result={},
                    hop_count=request.hop_count + 1,
                    error=str(exc),
                )

    # ── validation ────────────────────────────────────────────────────

    async def _validate(
        self, request: DelegationRequest, db: AsyncSession
    ) -> tuple[bool, str | None]:
        # Self-delegation
        if request.from_agent == request.to_agent:
            return False, "self-delegation not allowed"

        # Hop limit
        if request.hop_count >= request.max_hops:
            return False, (
                f"max hops exceeded ({request.hop_count}/{request.max_hops})"
            )

        # Circular delegation — target already in chain
        chain = request.delegation_chain + [request.from_agent]
        if request.to_agent in chain:
            return False, (
                f"circular delegation detected: "
                f"{' -> '.join(chain)} -> {request.to_agent}"
            )

        # Target agent must exist
        row = (
            await db.execute(
                select(Agent.agent_id).where(Agent.agent_id == request.to_agent)
            )
        ).scalar_one_or_none()
        if row is None:
            return False, f"target agent '{request.to_agent}' not found"

        return True, None

    # ── Legacy native-agent dispatch (backward compat) ────────────────

    async def _legacy_delegate(
        self, request: DelegationRequest, *, db=None
    ) -> DelegationResult:
        from trellis.agents import _NATIVE_AGENTS

        effective_db = db or self.db
        logger.info(
            "Delegating from=%s to=%s delegation_id=%s",
            request.from_agent,
            request.to_agent,
            request.delegation_id,
        )

        agent_cls = _NATIVE_AGENTS.get(request.to_agent)
        if agent_cls is None:
            return DelegationResult(
                delegation_id=request.delegation_id,
                status="error",
                error=f"Unknown target agent: {request.to_agent}",
            )

        try:

            class _MinimalAgent:
                def __init__(self, agent_id):
                    self.agent_id = agent_id
                    self.name = agent_id

            agent_stub = _MinimalAgent(request.to_agent)
            instance = agent_cls(agent_stub)

            envelope = {
                "envelope_id": f"dlg-{request.delegation_id}",
                "payload": {
                    "text": request.text,
                    "data": request.context,
                    **request.context,
                },
                "delegation": {
                    "delegation_id": request.delegation_id,
                    "from_agent": request.from_agent,
                },
            }

            if hasattr(instance, "process"):
                result = await instance.process(envelope)
            elif hasattr(instance, "execute"):
                result = await instance.execute(
                    envelope, db=effective_db, trace_id=request.trace_id
                )
            else:
                return DelegationResult(
                    delegation_id=request.delegation_id,
                    status="error",
                    error=f"Agent {request.to_agent} has no process/execute method",
                )

            return DelegationResult(
                delegation_id=request.delegation_id,
                status="completed",
                result=result if isinstance(result, dict) else {"raw": result},
            )

        except Exception as exc:
            logger.error("Delegation failed: %s", exc, exc_info=True)
            return DelegationResult(
                delegation_id=request.delegation_id,
                status="error",
                error=str(exc),
            )
