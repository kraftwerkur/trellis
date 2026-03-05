"""Function agent registry + built-in function agents (echo, ticket_logger)."""

import logging
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

# Registry: function_ref → async callable(envelope_dict) → result_dict
_registry: dict[str, Callable[..., Coroutine[Any, Any, dict]]] = {}


def register(ref: str):
    """Decorator to register a function agent."""
    def decorator(fn):
        _registry[ref] = fn
        return fn
    return decorator


def get_function(ref: str) -> Callable[..., Coroutine[Any, Any, dict]] | None:
    return _registry.get(ref)


# ── Built-in function agents ───────────────────────────────────────────────

@register("trellis.functions.echo")
async def echo(envelope: dict) -> dict:
    text = envelope.get("payload", {}).get("text", "(no text)")
    return {"status": "completed", "result": {"text": f"Echo: {text}", "data": {}, "attachments": []}}


@register("trellis.functions.ticket_logger")
async def ticket_logger(envelope: dict) -> dict:
    text = envelope.get("payload", {}).get("text", "(no text)")
    envelope_id = envelope.get("envelope_id", "unknown")
    logger.info(f"Ticket logged: envelope_id={envelope_id} text={text}")
    return {"status": "completed", "result": {"text": f"Ticket logged for envelope {envelope_id}",
            "data": {"envelope_id": envelope_id}, "attachments": []}}
