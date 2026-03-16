"""Tool Registry — centralized tool execution with permissions and audit.

Agents request tool execution through the registry instead of calling
functions directly. The registry handles permission checking, audit
logging, timing, and error handling.

Usage:
    # Register a tool (done once at module level):
    @register_tool(name="my_tool", category="data", description="Does stuff")
    def my_tool(param: str) -> dict:
        ...

    # Execute via registry (async, from agent code):
    result = await tool_registry.execute(
        agent_id="my-agent",
        tool_name="my_tool",
        params={"param": "value"},
        trace_id="abc-123"
    )
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger("trellis.tool_registry")


# ── Exceptions ─────────────────────────────────────────────────────────────

class ToolPermissionDenied(Exception):
    def __init__(self, agent_id: str, tool_name: str):
        self.agent_id = agent_id
        self.tool_name = tool_name
        super().__init__(f"Agent '{agent_id}' does not have permission to use tool '{tool_name}'")


class ToolNotFound(Exception):
    def __init__(self, tool_name: str):
        self.tool_name = tool_name
        super().__init__(f"Tool '{tool_name}' is not registered")


# ── Tool metadata ──────────────────────────────────────────────────────────

@dataclass
class ToolMeta:
    name: str
    fn: Callable
    category: str
    description: str
    requires_permissions: list[str] = field(default_factory=list)
    # Runtime stats (updated in-memory; persisted via ToolCallLog)
    call_count: int = 0
    error_count: int = 0
    total_latency_ms: float = 0.0


# ── Registry ───────────────────────────────────────────────────────────────

class ToolRegistry:
    """Central registry for all Trellis agent tools."""

    def __init__(self):
        self._tools: dict[str, ToolMeta] = {}

    def register(
        self,
        fn: Callable,
        *,
        name: str | None = None,
        category: str = "data",
        description: str = "",
        requires_permissions: list[str] | None = None,
    ) -> Callable:
        """Register a function as a tool. Returns the function unchanged."""
        tool_name = name or fn.__name__
        self._tools[tool_name] = ToolMeta(
            name=tool_name,
            fn=fn,
            category=category,
            description=description or (fn.__doc__ or "").strip().split("\n")[0],
            requires_permissions=requires_permissions or [],
        )
        logger.debug(f"Registered tool: {tool_name} ({category})")
        return fn

    def get(self, tool_name: str) -> ToolMeta:
        """Look up a registered tool. Raises ToolNotFound if missing."""
        meta = self._tools.get(tool_name)
        if meta is None:
            raise ToolNotFound(tool_name)
        return meta

    def list_tools(self) -> list[dict]:
        """Return catalog of all registered tools with metadata."""
        return [
            {
                "name": m.name,
                "category": m.category,
                "description": m.description,
                "requires_permissions": m.requires_permissions,
                "call_count": m.call_count,
                "error_count": m.error_count,
                "avg_latency_ms": (
                    round(m.total_latency_ms / m.call_count, 1) if m.call_count else 0.0
                ),
            }
            for m in self._tools.values()
        ]

    def _check_permission(self, agent_tools: list[str], tool_name: str, agent_id: str) -> None:
        """Raise ToolPermissionDenied if agent can't use this tool."""
        if "*" in agent_tools or tool_name in agent_tools:
            return
        raise ToolPermissionDenied(agent_id, tool_name)

    async def execute(
        self,
        agent_id: str,
        tool_name: str,
        params: dict[str, Any],
        trace_id: str | None = None,
        agent_tools: list[str] | None = None,
        db=None,
    ) -> Any:
        """Execute a tool with permission check and audit logging.

        Args:
            agent_id: ID of the requesting agent
            tool_name: Name of the registered tool
            params: Tool parameters (keyword args)
            trace_id: Optional trace ID for correlation
            agent_tools: Agent's allowed tools list (from Agent.tools).
                         Pass None to skip permission check (internal use only).
            db: Optional AsyncSession for persisting ToolCallLog.
                If None, logs to audit events in-memory only.

        Returns:
            Tool result (whatever the tool function returns)

        Raises:
            ToolPermissionDenied: If agent lacks permission
            ToolNotFound: If tool isn't registered
        """
        meta = self.get(tool_name)

        # Permission check
        if agent_tools is not None:
            self._check_permission(agent_tools, tool_name, agent_id)

        # Execute with timing
        start = time.monotonic()
        error_msg = None
        result = None

        try:
            await self._emit_audit(db, "tool_call_started", agent_id=agent_id,
                                   trace_id=trace_id, tool_name=tool_name, params=params)
            result = meta.fn(**params)
            latency_ms = (time.monotonic() - start) * 1000

            meta.call_count += 1
            meta.total_latency_ms += latency_ms

        except ToolPermissionDenied:
            latency_ms = (time.monotonic() - start) * 1000
            meta.error_count += 1
            await self._emit_audit(db, "tool_call_failed", agent_id=agent_id,
                                   trace_id=trace_id, tool_name=tool_name,
                                   error="Permission denied", status="denied")
            await self._log_call(db, trace_id=trace_id, agent_id=agent_id,
                                 meta=meta, params=params, result=None,
                                 status="denied", latency_ms=latency_ms, error="Permission denied")
            raise

        except Exception as e:
            latency_ms = (time.monotonic() - start) * 1000
            error_msg = str(e)
            meta.error_count += 1
            logger.error(f"Tool '{tool_name}' failed for agent '{agent_id}': {e}")
            await self._emit_audit(db, "tool_call_failed", agent_id=agent_id,
                                   trace_id=trace_id, tool_name=tool_name,
                                   error=error_msg, status="error")
            await self._log_call(db, trace_id=trace_id, agent_id=agent_id,
                                 meta=meta, params=params, result=None,
                                 status="error", latency_ms=latency_ms, error=error_msg)
            return {"error": error_msg, "tool": tool_name, "status": "error"}

        await self._emit_audit(db, "tool_call_completed", agent_id=agent_id,
                               trace_id=trace_id, tool_name=tool_name,
                               latency_ms=round(latency_ms, 1))
        await self._log_call(db, trace_id=trace_id, agent_id=agent_id,
                             meta=meta, params=params, result=result,
                             status="success", latency_ms=latency_ms, error=None)
        return result

    async def _emit_audit(self, db, event_type: str, **details) -> None:
        """Emit an audit event. Logs to DB if available, always logs to logger."""
        logger.debug(f"audit:{event_type} agent={details.get('agent_id')} tool={details.get('tool_name')}")
        if db is None:
            return
        try:
            from trellis.router import emit_audit
            await emit_audit(
                db, event_type,
                trace_id=details.get("trace_id"),
                agent_id=details.get("agent_id"),
                details={k: v for k, v in details.items() if k not in ("trace_id", "agent_id")},
            )
        except Exception as e:
            logger.warning(f"Failed to emit audit event '{event_type}': {e}")

    async def _log_call(
        self, db, *, trace_id, agent_id, meta: ToolMeta, params, result, status, latency_ms, error
    ) -> None:
        """Persist a ToolCallLog record."""
        if db is None:
            return
        try:
            from trellis.models import ToolCallLog
            # Summarize result for audit (truncate large payloads)
            result_summary = None
            if result is not None:
                import json
                try:
                    s = json.dumps(result)
                    result_summary = s[:500] if len(s) > 500 else s
                except Exception:
                    result_summary = str(result)[:500]

            log = ToolCallLog(
                trace_id=trace_id,
                agent_id=agent_id,
                tool_name=meta.name,
                tool_category=meta.category,
                params=params,
                result_summary=result_summary,
                status=status,
                latency_ms=round(latency_ms, 2),
                error=error,
            )
            db.add(log)
            await db.commit()
        except Exception as e:
            logger.warning(f"Failed to persist ToolCallLog: {e}")


# ── Singleton registry ─────────────────────────────────────────────────────

tool_registry = ToolRegistry()


def register_tool(
    name: str | None = None,
    category: str = "data",
    description: str = "",
    requires_permissions: list[str] | None = None,
):
    """Decorator to register a function in the global tool registry."""
    def decorator(fn: Callable) -> Callable:
        return tool_registry.register(
            fn,
            name=name,
            category=category,
            description=description,
            requires_permissions=requires_permissions or [],
        )
    return decorator


# ── Register all existing tools ────────────────────────────────────────────
# Import tools and register them with the registry. This does NOT change
# the tools themselves — they remain callable directly. The registry just
# adds a mediation layer for agents that opt in.

def _register_builtin_tools():
    """Register all tools from trellis.agents.tools into the global registry."""
    from trellis.agents import tools as T

    # Security / vulnerability tools
    tool_registry.register(T.lookup_tech_stack, name="lookup_tech_stack", category="data",
        description="Check if a product/vendor is in Health First's tech stack",
        requires_permissions=["tech_stack.read"])
    tool_registry.register(T.check_cisa_kev, name="check_cisa_kev", category="data",
        description="Check if a CVE is in the CISA Known Exploited Vulnerabilities catalog",
        requires_permissions=["cisa_kev.read"])
    tool_registry.register(T.get_cvss_details, name="get_cvss_details", category="data",
        description="Get CVSS score breakdown for a CVE",
        requires_permissions=["cvss.read"])
    tool_registry.register(T.calculate_risk_score, name="calculate_risk_score", category="assess",
        description="Calculate composite risk score for Health First",
        requires_permissions=["risk.assess"])

    # IT help desk tools
    tool_registry.register(T.classify_ticket, name="classify_ticket", category="classify",
        description="Classify an IT ticket by category based on keyword matching",
        requires_permissions=["tickets.classify"])
    tool_registry.register(T.lookup_known_resolution, name="lookup_known_resolution", category="lookup",
        description="Look up a known resolution for common IT issues",
        requires_permissions=["resolutions.read"])
    tool_registry.register(T.assess_priority, name="assess_priority", category="assess",
        description="Assess IT ticket priority based on severity and impact",
        requires_permissions=["tickets.assess"])

    # HR tools
    tool_registry.register(T.classify_hr_case, name="classify_hr_case", category="classify",
        description="Classify an HR case by category",
        requires_permissions=["hr.classify"])
    tool_registry.register(T.assess_hr_priority, name="assess_hr_priority", category="assess",
        description="Assess HR case priority based on category and regulatory flags",
        requires_permissions=["hr.assess"])
    tool_registry.register(T.lookup_hr_policy, name="lookup_hr_policy", category="lookup",
        description="Look up HR policy reference and standard procedure",
        requires_permissions=["hr.policy.read"])

    # Revenue cycle tools
    tool_registry.register(T.classify_rev_cycle_case, name="classify_rev_cycle_case", category="classify",
        description="Classify a revenue cycle case by category",
        requires_permissions=["revcycle.classify"])
    tool_registry.register(T.analyze_denial, name="analyze_denial", category="assess",
        description="Analyze a denial code and return root cause and resolution steps",
        requires_permissions=["revcycle.analyze"])
    tool_registry.register(T.assess_rev_cycle_priority, name="assess_rev_cycle_priority", category="assess",
        description="Assess revenue cycle case priority",
        requires_permissions=["revcycle.assess"])


_register_builtin_tools()
