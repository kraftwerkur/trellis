"""Tests for the ReAct-style agent execution loop."""

import json
import pytest

from trellis.agent_loop import AgentLoop, AgentLoopResult


# ── Helpers: mock LLM responses ──────────────────────────────────────────

def _make_response(content=None, tool_calls=None, total_tokens=10):
    """Build an OpenAI-compatible chat completion response dict."""
    message: dict = {"role": "assistant"}
    if content is not None:
        message["content"] = content
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
        if content is None:
            message["content"] = None
    return {
        "choices": [{"message": message}],
        "usage": {"prompt_tokens": total_tokens // 2,
                  "completion_tokens": total_tokens // 2,
                  "total_tokens": total_tokens},
    }


def _make_tool_call(name, arguments, call_id="call_abc123"):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


# ── Test: single-step (LLM returns content immediately) ─────────────────

@pytest.mark.asyncio
async def test_single_step_content():
    """LLM answers directly without tool calls → one step, complete."""
    call_count = 0

    async def mock_llm(messages, tools, model, temperature):
        nonlocal call_count
        call_count += 1
        return _make_response(content="The answer is 42.", total_tokens=20)

    loop = AgentLoop(
        system_prompt="You are helpful.",
        llm_call=mock_llm,
    )
    result = await loop.run("What is the answer?")

    assert result.status == "complete"
    assert result.result["text"] == "The answer is 42."
    assert result.result["tool_calls_made"] == []
    assert result.total_tokens == 20
    assert result.steps == 1
    assert call_count == 1


# ── Test: multi-step (tool call then content) ───────────────────────────

@pytest.mark.asyncio
async def test_multi_step_tool_then_answer():
    """LLM calls a tool, gets result, then returns final answer."""
    call_count = 0

    async def mock_llm(messages, tools, model, temperature):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call: request a tool
            return _make_response(
                tool_calls=[_make_tool_call("check_cisa_kev", {"cve_id": "CVE-2024-1234"})],
                total_tokens=15,
            )
        else:
            # Second call: final answer after seeing tool result
            return _make_response(
                content="CVE-2024-1234 is in the KEV catalog.",
                total_tokens=25,
            )

    def mock_check_cisa(cve_id: str) -> dict:
        return {"cve_id": cve_id, "in_kev": True}

    loop = AgentLoop(
        system_prompt="You are a security analyst.",
        tools=[{"type": "function", "function": {"name": "check_cisa_kev", "parameters": {}}}],
        tool_executors={"check_cisa_kev": mock_check_cisa},
        llm_call=mock_llm,
    )
    result = await loop.run("Is CVE-2024-1234 exploited?")

    assert result.status == "complete"
    assert "KEV" in result.result["text"]
    assert len(result.result["tool_calls_made"]) == 1
    assert result.result["tool_calls_made"][0]["tool"] == "check_cisa_kev"
    assert result.result["tool_calls_made"][0]["result"]["in_kev"] is True
    assert result.total_tokens == 40  # 15 + 25
    assert result.steps == 2
    assert call_count == 2


# ── Test: max steps reached ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_max_steps_reached():
    """LLM keeps calling tools until max_steps is exhausted."""

    async def mock_llm(messages, tools, model, temperature):
        # Always request a tool — never gives a final answer
        return _make_response(
            tool_calls=[_make_tool_call("some_tool", {"q": "data"})],
            total_tokens=10,
        )

    def mock_tool(q: str) -> dict:
        return {"data": "result"}

    loop = AgentLoop(
        system_prompt="You are a researcher.",
        tools=[{"type": "function", "function": {"name": "some_tool", "parameters": {}}}],
        tool_executors={"some_tool": mock_tool},
        llm_call=mock_llm,
        max_steps=3,
    )
    result = await loop.run("Find data")

    assert result.status == "max_steps"
    assert len(result.result["tool_calls_made"]) == 3
    assert result.total_tokens == 30  # 10 × 3
    assert result.steps == 3


# ── Test: tool execution error handling ─────────────────────────────────

@pytest.mark.asyncio
async def test_tool_execution_error():
    """Tool raises an exception → error captured, loop continues."""
    call_count = 0

    async def mock_llm(messages, tools, model, temperature):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _make_response(
                tool_calls=[_make_tool_call("bad_tool", {"x": 1})],
                total_tokens=10,
            )
        else:
            return _make_response(content="I handled the error.", total_tokens=10)

    def bad_tool(x: int) -> dict:
        raise ValueError("Something went wrong!")

    loop = AgentLoop(
        system_prompt="You are resilient.",
        tools=[{"type": "function", "function": {"name": "bad_tool", "parameters": {}}}],
        tool_executors={"bad_tool": bad_tool},
        llm_call=mock_llm,
    )
    result = await loop.run("Do something")

    assert result.status == "complete"
    assert result.result["text"] == "I handled the error."
    assert len(result.result["tool_calls_made"]) == 1
    assert "error" in result.result["tool_calls_made"][0]["result"]
    assert "Something went wrong" in result.result["tool_calls_made"][0]["result"]["error"]


@pytest.mark.asyncio
async def test_tool_not_found():
    """LLM requests a tool that isn't registered → error captured gracefully."""
    call_count = 0

    async def mock_llm(messages, tools, model, temperature):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _make_response(
                tool_calls=[_make_tool_call("nonexistent_tool", {})],
                total_tokens=10,
            )
        else:
            return _make_response(content="Tool not available.", total_tokens=10)

    loop = AgentLoop(
        system_prompt="Test.",
        tools=[],
        tool_executors={},
        llm_call=mock_llm,
    )
    result = await loop.run("Use a tool")

    assert result.status == "complete"
    assert len(result.result["tool_calls_made"]) == 1
    assert "error" in result.result["tool_calls_made"][0]["result"]
    assert "not found" in result.result["tool_calls_made"][0]["result"]["error"]


# ── Test: token tracking across steps ───────────────────────────────────

@pytest.mark.asyncio
async def test_token_tracking():
    """Tokens accumulate correctly across multiple steps."""
    step = 0
    token_counts = [12, 18, 30]

    async def mock_llm(messages, tools, model, temperature):
        nonlocal step
        tokens = token_counts[step]
        step += 1
        if step < 3:
            return _make_response(
                tool_calls=[_make_tool_call("t", {}, call_id=f"call_{step}")],
                total_tokens=tokens,
            )
        return _make_response(content="Done.", total_tokens=tokens)

    loop = AgentLoop(
        system_prompt="Test.",
        tools=[{"type": "function", "function": {"name": "t", "parameters": {}}}],
        tool_executors={"t": lambda: {"ok": True}},
        llm_call=mock_llm,
    )
    result = await loop.run("Go")

    assert result.total_tokens == 60  # 12 + 18 + 30
    assert result.steps == 3


# ── Test: LLM call failure ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_llm_call_failure():
    """LLM call raises an exception → status='error'."""

    async def mock_llm(messages, tools, model, temperature):
        raise ConnectionError("Gateway unreachable")

    loop = AgentLoop(
        system_prompt="Test.",
        llm_call=mock_llm,
    )
    result = await loop.run("Hello")

    assert result.status == "error"
    assert "Gateway unreachable" in result.result["text"]
    assert result.steps == 1


# ── Test: to_dict serialisation ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_result_to_dict():
    """AgentLoopResult.to_dict() returns a clean serialisable dict."""

    async def mock_llm(messages, tools, model, temperature):
        return _make_response(content="Hi!", total_tokens=5)

    loop = AgentLoop(system_prompt="Test.", llm_call=mock_llm)
    result = await loop.run("Hi")
    d = result.to_dict()

    assert d["status"] == "complete"
    assert d["result"]["text"] == "Hi!"
    assert d["total_tokens"] == 5
    assert d["steps"] == 1


# ── Test: multiple tool calls in single step ────────────────────────────

@pytest.mark.asyncio
async def test_multiple_tool_calls_single_step():
    """LLM returns multiple tool_calls in one response."""
    call_count = 0

    async def mock_llm(messages, tools, model, temperature):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _make_response(
                tool_calls=[
                    _make_tool_call("tool_a", {"x": 1}, call_id="call_1"),
                    _make_tool_call("tool_b", {"y": 2}, call_id="call_2"),
                ],
                total_tokens=20,
            )
        return _make_response(content="Both tools done.", total_tokens=15)

    loop = AgentLoop(
        system_prompt="Test.",
        tools=[],
        tool_executors={
            "tool_a": lambda x: {"a": x},
            "tool_b": lambda y: {"b": y},
        },
        llm_call=mock_llm,
    )
    result = await loop.run("Run both")

    assert result.status == "complete"
    assert len(result.result["tool_calls_made"]) == 2
    assert result.result["tool_calls_made"][0]["tool"] == "tool_a"
    assert result.result["tool_calls_made"][1]["tool"] == "tool_b"
    assert result.total_tokens == 35
    assert result.steps == 2


# ── Test: missing usage field handled gracefully ────────────────────────

@pytest.mark.asyncio
async def test_missing_usage_field():
    """Response without 'usage' key doesn't crash token tracking."""

    async def mock_llm(messages, tools, model, temperature):
        return {"choices": [{"message": {"role": "assistant", "content": "Ok"}}]}

    loop = AgentLoop(system_prompt="Test.", llm_call=mock_llm)
    result = await loop.run("Hi")

    assert result.status == "complete"
    assert result.total_tokens == 0
