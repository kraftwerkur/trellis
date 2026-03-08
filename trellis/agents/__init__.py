"""Native agent dispatch for Trellis."""

from trellis.agents.health_auditor import HealthAuditorAgent
from trellis.agents.security_triage import SecurityTriageAgent

# Registry of native agent classes by agent_id
_NATIVE_AGENTS = {
    "security-triage": SecurityTriageAgent,
    "health-auditor": HealthAuditorAgent,
}


async def dispatch_native_agent(agent, envelope) -> tuple[str, dict | None, str | None]:
    """Dispatch to a native Python agent class."""
    cls = _NATIVE_AGENTS.get(agent.agent_id)
    if cls is None:
        return "error", None, f"No native agent registered for '{agent.agent_id}'"
    try:
        instance = cls(agent)
        result = await instance.process(envelope)
        return "success", result, None
    except Exception as e:
        return "error", None, f"Native agent error: {str(e)[:500]}"
