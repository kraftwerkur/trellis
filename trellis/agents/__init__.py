"""Native agent dispatch for Trellis."""

from trellis.agents.audit_compactor import AuditCompactorAgent
from trellis.agents.health_auditor import HealthAuditorAgent
from trellis.agents.it_help import ITHelpAgent
from trellis.agents.rev_cycle import RevCycleAgent
from trellis.agents.rule_optimizer import RuleOptimizerAgent
from trellis.agents.sam_hr import SAMHRAgent
from trellis.agents.security_triage import SecurityTriageAgent

# Registry of native agent classes by agent_id
_NATIVE_AGENTS = {
    "security-triage": SecurityTriageAgent,
    "health-auditor": HealthAuditorAgent,
    "audit-compactor": AuditCompactorAgent,
    "rule-optimizer": RuleOptimizerAgent,
    "it-help": ITHelpAgent,
    "sam-hr": SAMHRAgent,
    "rev-cycle": RevCycleAgent,
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
