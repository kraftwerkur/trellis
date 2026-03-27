"""ReAct-style agent execution loop with tool support.

Runs a multi-step loop where the LLM can invoke tools, observe results,
and reason toward a final answer.  Compatible with OpenAI function-calling
format and the Trellis internal gateway.

Usage:
    loop = AgentLoop(
        system_prompt="You are a security analyst.",
        tools=[ ... OpenAI function schemas ... ],
        tool_executors={"check_cisa_kev": check_cisa_kev, ...},
        llm_call=my_llm_callable,          # or None → uses gateway
    )
    result = await loop.run("Analyse CVE-2024-1234")
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

logger = logging.getLogger("trellis.agent_loop")

# Type alias for the injectable LLM callable
LLMCallable = Callable[
    [list[dict], list[dict] | None, str, float],
    Awaitable[dict],
]


@dataclass
class AgentLoopResult:
    """Structured result from an agent loop run."""
    status: str                          # "complete" | "max_steps" | "error"
    result: dict = field(default_factory=dict)  # {text, data, tool_calls_made}
    total_tokens: int = 0
    steps: int = 0

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "result": self.result,
            "total_tokens": self.total_tokens,
            "steps": self.steps,
        }


async def _default_llm_call(
    messages: list[dict],
    tools: list[dict] | None = None,
    model: str = "default",
    temperature: float = 0.7,
) -> dict:
    """Default LLM callable that hits the internal gateway via httpx."""
    import httpx

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if tools:
        payload["tools"] = tools

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://127.0.0.1:8000/v1/chat/completions",
            json=payload,
            timeout=120.0,
        )
        resp.raise_for_status()
        return resp.json()


class AgentLoop:
    """ReAct-style agent execution loop.

    Parameters
    ----------
    system_prompt : str
        The agent's system prompt / persona.
    tools : list[dict] | None
        OpenAI function-calling tool schemas.
    tool_executors : dict[str, Callable]
        Mapping of tool name → sync callable that executes the tool.
    llm_call : LLMCallable | None
        Async callable for LLM inference.  Falls back to internal gateway.
    model : str
        Model identifier to pass to llm_call.
    temperature : float
        Sampling temperature.
    max_steps : int
        Maximum reasoning steps before forcing an answer.
    logger : logging.Logger | None
        Logger instance (defaults to module logger).
    """

    def __init__(
        self,
        system_prompt: str,
        tools: list[dict] | None = None,
        tool_executors: dict[str, Callable] | None = None,
        llm_call: LLMCallable | None = None,
        model: str = "default",
        temperature: float = 0.7,
        max_steps: int = 5,
        log: logging.Logger | None = None,
    ):
        self.system_prompt = system_prompt
        self.tools = tools or []
        self.tool_executors = tool_executors or {}
        self.llm_call = llm_call or _default_llm_call
        self.model = model
        self.temperature = temperature
        self.max_steps = max_steps
        self.log = log or logger

    # ── public entry point ────────────────────────────────────────────

    async def run(self, user_text: str) -> AgentLoopResult:
        """Execute the agent loop for a given user message.

        Returns an AgentLoopResult with status, text, data, and
        a record of every tool call made.
        """
        messages: list[dict] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_text},
        ]
        tool_calls_made: list[dict] = []
        total_tokens = 0
        last_content: str | None = None

        for step in range(1, self.max_steps + 1):
            self.log.info("Agent loop step %d/%d", step, self.max_steps)

            try:
                response = await self.llm_call(
                    messages,
                    self.tools or None,
                    self.model,
                    self.temperature,
                )
            except Exception as exc:
                self.log.error("LLM call failed at step %d: %s", step, exc)
                return AgentLoopResult(
                    status="error",
                    result={
                        "text": f"LLM call failed: {exc}",
                        "data": None,
                        "tool_calls_made": tool_calls_made,
                    },
                    total_tokens=total_tokens,
                    steps=step,
                )

            # Accumulate token usage
            usage = response.get("usage") or {}
            total_tokens += usage.get("total_tokens", 0)

            message = response["choices"][0]["message"]
            content = message.get("content")
            tc_list = message.get("tool_calls")

            # ── If no tool calls, we have our final answer ────────
            if not tc_list:
                self.log.info("Agent loop finished at step %d (final answer)", step)
                return AgentLoopResult(
                    status="complete",
                    result={
                        "text": content or "",
                        "data": None,
                        "tool_calls_made": tool_calls_made,
                    },
                    total_tokens=total_tokens,
                    steps=step,
                )

            # ── Execute each tool call ────────────────────────────
            # Append the assistant message with tool_calls
            messages.append(message)
            last_content = content

            for tc in tc_list:
                fn_name = tc["function"]["name"]
                call_id = tc.get("id", f"call_{uuid.uuid4().hex[:8]}")

                try:
                    raw_args = tc["function"].get("arguments", "{}")
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except json.JSONDecodeError:
                    args = {}

                self.log.info("Executing tool %s(%s)", fn_name, args)

                executor = self.tool_executors.get(fn_name)
                if executor is None:
                    tool_result = {"error": f"Tool '{fn_name}' not found"}
                    self.log.warning("Tool '%s' not found in executors", fn_name)
                else:
                    try:
                        tool_result = executor(**args)
                    except Exception as exc:
                        tool_result = {"error": str(exc)}
                        self.log.error("Tool '%s' raised: %s", fn_name, exc)

                tool_calls_made.append({
                    "tool": fn_name,
                    "arguments": args,
                    "result": tool_result,
                })

                # Append tool result as a tool message
                result_str = json.dumps(tool_result) if not isinstance(tool_result, str) else tool_result
                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": result_str,
                })

        # ── Max steps exhausted ───────────────────────────────────────
        self.log.warning("Agent loop reached max_steps (%d)", self.max_steps)
        return AgentLoopResult(
            status="max_steps",
            result={
                "text": last_content or "",
                "data": None,
                "tool_calls_made": tool_calls_made,
            },
            total_tokens=total_tokens,
            steps=self.max_steps,
        )
