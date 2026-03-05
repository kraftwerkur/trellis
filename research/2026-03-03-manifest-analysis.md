# Research Analysis: `mnfst/manifest` vs Trellis Architecture
**Date:** 2026-03-03
**Author:** Reef (Subagent)
**Status:** Complete

## 1. Executive Summary
`mnfst/manifest` is a high-quality, open-source (MIT) LLM routing and FinOps platform specifically designed for OpenClaw. It addresses the exact problem space of **Trellis Slice 2 (LLM Gateway)** and **Slice 5 (FinOps)**. 

Manifest operates as an **OpenAI-compatible proxy** (sidecar-style) that uses a "23-dimension scoring algorithm" to classify incoming prompts into 4 tiers (Simple, Standard, Complex, Reasoning) and routes them to the cheapest model capable of handling that tier.

**Key Finding:** Manifest is not a "threat" but a significant accelerant. It implements about 70-80% of what we envisioned for the Trellis Gateway and FinOps engine, including a sophisticated dashboard, per-agent cost tracking, and smart model routing that already accounts for "OpenClaw noise" (stripping system prompts for better scoring).

## 2. Technical Analysis: How Manifest Works

### Architecture
- **Proxy/Sidecar:** Manifest runs as a standalone service (Node.js/NestJS). It exposes an OpenAI-compatible API.
- **OpenClaw Integration:** It includes an OpenClaw plugin that registers "Manifest" as a provider. When an agent is configured to use the `manifest` provider with model `auto`, the plugin sends requests to the Manifest proxy.
- **Scoring Engine:** 
    - Uses 23 dimensions (Structural, Keyword, Contextual).
    - **Structural:** Measures complexity, logic indicators, and formatting requirements.
    - **Keyword:** Detects specific domains (coding, creative, analysis).
    - **Contextual:** Accounts for conversation depth and tool presence.
    - **OpenClaw Optimization:** Crucially, it filters out "system" and "developer" roles before scoring because OpenClaw's large system prompts otherwise bias every request toward the "Complex" tier.
- **Routing:** Maps the resulting score to a Tier. Users map Tiers to specific models (e.g., Simple -> GPT-4o-mini, Complex -> Claude 3.5 Sonnet) via a dashboard.
- **FinOps:** Real-time OTLP (OpenTelemetry) ingestion. Tracks tokens, costs, and latency per agent. Includes soft/hard budget limits.

### Comparison with Trellis

| Feature | Manifest | Trellis (Target) | Gap / Difference |
| :--- | :--- | :--- | :--- |
| **LLM Gateway** | OpenAI-compatible proxy | OpenAI-compatible proxy | Identical approach. |
| **Model Routing** | Tier-based scoring (23 dims) | Rule-based / Complexity | Manifest is more sophisticated out-of-the-box. |
| **FinOps** | Per-agent token/cost tracking | Per-agent/dept/trace tracking | Trellis aims for deeper "Trace-ID" correlation. |
| **Agent Registry** | Internal to Manifest | Enterprise-wide (Azure AD) | Trellis integrates with Health First IAM. |
| **Deployment** | Local or Cloud | Azure-native (Managed) | Trellis is specialized for Azure/HIPAA. |
| **Multi-Agent** | Supported | Core requirement | Both handle multi-agent scenarios. |

## 3. Gap Analysis

### What Manifest does that Trellis doesn't (yet):
1. **Sophisticated Scoring Algorithm:** Their 23-dimension scorer is significantly more advanced than our planned "simple/medium/complex" heuristic.
2. **OpenClaw-Specific Tuning:** Features like "Heartbeat detection" (routing `HEARTBEAT_OK` to the cheapest model automatically) and system-prompt stripping are "battle-hardened" for our specific stack.
3. **Turnkey Dashboard:** A high-quality Next.js dashboard for model mapping and cost visualization is already built.

### What Trellis does that Manifest doesn't:
1. **Enterprise Identity (Azure AD/SailPoint):** Trellis maps agents to actual employees and departments for internal billing/compliance.
2. **Generic Envelope Routing:** Trellis handles HL7/Teams/File inputs *before* they reach an agent. Manifest only handles the LLM calls *made by* the agent.
3. **Healthcare Compliance:** Trellis includes specific redaction logic for PHI and HIPAA-compliant audit trails.
4. **Tool Governance:** Trellis manages tool permissions and security reviews (CISO gateway).

## 4. Recommendation

**Status:** **Integrate and Port.**

Manifest is the perfect engine for the **internal LLM Gateway** of Trellis. We should not rebuild the scoring engine or the basic token-tracking proxy from scratch.

### Action Plan:
1. **Adopt Manifest as the Trellis Gateway Engine:** Use the `packages/backend` code as the foundation for the Trellis LLM Gateway.
2. **Extend for Enterprise:**
    - Replace the internal Auth with **Azure AD**.
    - Add the `trace_id` header to the proxy to correlate LLM costs back to the original Trellis "Generic Envelope" event.
    - Integrate the cost data into the Trellis FinOps dashboard.
3. **Port the Scoring Logic:** Even if we don't use the full Manifest backend, we should port their `StructuralDimensions` and `ContextualDimensions` logic to our Python-based core, as they've already solved the "OpenClaw system prompt inflation" problem.

## 5. PoC Implementation Note
I have cloned the repo to `projects/trellis/research/manifest_repo`. 
The core routing logic is in `packages/backend/src/routing`.
The OpenClaw plugin logic is in `packages/openclaw-plugin`.

**Recommendation for immediate next step:**
Configure a local instance of Manifest in `projects/trellis/research/manifest_poc/` and point one of our current test agents (like SAM) at it to verify the 70% cost saving claim on our typical healthcare-related prompts.
