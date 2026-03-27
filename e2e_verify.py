#!/usr/bin/env python3
"""
Trellis v1 End-to-End Verification Script
Tests the real server with real requests — no mocks.
"""
import asyncio
import json
import sys
import time

import httpx

BASE = "http://127.0.0.1:8099"
RESULTS = []

def report(test_name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    RESULTS.append((test_name, passed, detail))
    print(f"  [{status}] {test_name}" + (f" — {detail}" if detail else ""))


async def run_e2e():
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as c:
        
        # ── 1. Health check ──
        print("\n=== 1. Server Health ===")
        try:
            r = await c.get("/api/health")
            report("GET /api/health", r.status_code == 200, f"status={r.status_code}")
        except Exception as e:
            report("GET /api/health", False, str(e))
            print("\n  Server not running! Start with: uvicorn trellis.main:app")
            return

        # ── 2. Seed agents ──
        print("\n=== 2. Seed Agents ===")
        agents_to_create = [
            {
                "agent_id": "security-triage",
                "name": "Security Triage Agent",
                "owner": "e2e-test",
                "department": "security",
                "agent_type": "native",
                "runtime_type": "pi",
                "function_ref": "trellis.agents.security_triage",
                "tools": ["check_cisa_kev"],
                "channels": ["http"],
                "maturity": "active",
            },
            {
                "agent_id": "it-help",
                "name": "IT Help Desk Agent",
                "owner": "e2e-test",
                "department": "it",
                "agent_type": "native",
                "runtime_type": "pi",
                "function_ref": "trellis.agents.it_help",
                "channels": ["http"],
                "maturity": "active",
            },
        ]
        for agent in agents_to_create:
            r = await c.post("/api/agents", json=agent)
            if r.status_code in (200, 201):
                report(f"Create agent: {agent['agent_id']}", True)
            elif r.status_code == 409 or "already exists" in r.text.lower():
                report(f"Agent exists: {agent['agent_id']}", True, "already seeded")
            else:
                report(f"Create agent: {agent['agent_id']}", False, f"{r.status_code}: {r.text[:200]}")

        # List agents
        r = await c.get("/api/agents")
        agents = r.json() if r.status_code == 200 else []
        report("GET /api/agents", r.status_code == 200, f"{len(agents)} agents")

        # ── 3. Create a rule for security routing ──
        print("\n=== 3. Create Routing Rule ===")
        rule = {
            "name": "Route CVEs to Security Triage",
            "conditions": {"payload.text": {"$regex": "CVE-\\d{4}-\\d+"}},
            "actions": {"route_to": "security-triage"},
            "priority": 10,
            "active": True,
        }
        r = await c.post("/api/rules", json=rule)
        if r.status_code in (200, 201):
            report("Create routing rule", True)
        elif r.status_code == 409 or "exists" in r.text.lower():
            report("Routing rule exists", True, "already seeded")
        else:
            report("Create routing rule", False, f"{r.status_code}: {r.text[:200]}")

        # ── 4. Send a CVE envelope via HTTP adapter ──
        print("\n=== 4. Send CVE Envelope ===")
        envelope = {
            "text": "Critical vulnerability detected: CVE-2021-44228 (Log4Shell) found in production server log4j-core 2.14.1. Immediate remediation required.",
            "sender_name": "e2e-test",
            "sender_department": "security",
            "tags": ["cve", "critical", "log4shell"],
        }
        r = await c.post("/api/adapter/http", json=envelope)
        report("POST /api/adapter/http (CVE)", r.status_code == 200, f"status={r.status_code}")
        if r.status_code == 200:
            result = r.json()
            report("Envelope processed", True, f"envelope_id={result.get('envelope_id', '?')}")
            
            # Check if agent was matched (field is "target_agent" in dispatch result)
            agent_id = result.get("target_agent", result.get("agent_id", ""))
            report("Routed to security-triage", agent_id == "security-triage", f"routed to: {agent_id}")
            
            # Check result has content
            agent_result = result.get("result") or {}
            inner = agent_result.get("result") or {}
            has_text = bool(inner.get("text", ""))
            report("Agent returned result", has_text, f"text length: {len(inner.get('text', ''))}")

        # ── 5. Send a non-CVE envelope ──
        print("\n=== 5. Send General Envelope ===")
        general_envelope = {
            "text": "Employee John Smith is requesting PTO for next week, March 31 to April 4.",
            "sender_name": "e2e-test",
            "sender_department": "hr",
            "tags": ["hr", "pto"],
        }
        r = await c.post("/api/adapter/http", json=general_envelope)
        report("POST /api/adapter/http (general)", r.status_code == 200, f"status={r.status_code}")

        # ── 6. Check audit trail ──
        print("\n=== 6. Audit Trail ===")
        r = await c.get("/api/audit", params={"limit": 20})
        if r.status_code == 200:
            events = r.json()
            report("GET /api/audit", True, f"{len(events)} events")
            event_types = [e.get("event_type") for e in events]
            report("Has envelope_received events", "envelope_received" in event_types, 
                   f"types: {list(set(event_types))[:8]}")
        else:
            report("GET /api/audit", False, f"status={r.status_code}")

        # ── 7. Check envelope log ──
        print("\n=== 7. Envelope Log ===")
        r = await c.get("/api/envelopes", params={"limit": 10})
        if r.status_code == 200:
            envelopes = r.json()
            report("GET /api/envelopes", True, f"{len(envelopes)} envelopes")
        else:
            report("GET /api/envelopes", False, f"status={r.status_code}")

        # ── 8. Check cost tracking ──
        print("\n=== 8. Cost Tracking ===")
        r = await c.get("/api/costs/summary")
        report("GET /api/costs/summary", r.status_code == 200, f"status={r.status_code}")

        # ── 9. Test streaming endpoint ──
        print("\n=== 9. Streaming Gateway ===")
        # Just check the endpoint exists and responds (no LLM needed for format check)
        stream_body = {
            "model": "test",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
        }
        try:
            r = await c.post("/v1/chat/completions", json=stream_body)
            # Will likely fail auth or provider, but should not 404
            report("POST /v1/chat/completions (stream)", r.status_code != 404, 
                   f"status={r.status_code} (auth/provider error expected without API key)")
        except Exception as e:
            report("POST /v1/chat/completions (stream)", False, str(e))

        # ── 10. Test embeddings service ──
        print("\n=== 10. Embeddings Service ===")
        try:
            from trellis.embeddings import embedding_service
            vec = embedding_service.embed("test security vulnerability")
            if vec is not None:
                report("Embedding service", True, f"vector dim={len(vec)}")
                
                sim = embedding_service.similarity(
                    embedding_service.embed("security vulnerability CVE"),
                    embedding_service.embed("cooking recipe pasta")
                )
                report("Semantic similarity works", sim < 0.5, f"security vs cooking = {sim:.3f}")
            else:
                report("Embedding service", False, "returned None (model not loaded)")
        except Exception as e:
            report("Embedding service", False, str(e))

        # ── 11. Test delegation module ──
        print("\n=== 11. Delegation Module ===")
        try:
            from trellis.delegation import DelegationRequest, DelegationResult, DelegationEngine
            report("Delegation imports", True)
            req = DelegationRequest(from_agent="security-triage", to_agent="it-help",
                                     envelope={"payload": {"text": "test"}})
            report("DelegationRequest creation", req.max_hops == 3, f"max_hops={req.max_hops}")
        except Exception as e:
            report("Delegation module", False, str(e))

        # ── 12. Test agent loop module ──
        print("\n=== 12. Agent Loop Module ===")
        try:
            from trellis.agent_loop import AgentLoop, AgentLoopResult
            report("AgentLoop imports", True)
            loop = AgentLoop(system_prompt="You are a test agent.")
            report("AgentLoop creation", True, f"max_steps={loop.max_steps}")
        except Exception as e:
            report("Agent loop module", False, str(e))

    # ── Summary ──
    print("\n" + "=" * 60)
    passed = sum(1 for _, p, _ in RESULTS if p)
    failed = sum(1 for _, p, _ in RESULTS if not p)
    print(f"  RESULTS: {passed} passed, {failed} failed, {len(RESULTS)} total")
    if failed:
        print("\n  FAILURES:")
        for name, p, detail in RESULTS:
            if not p:
                print(f"    ✗ {name}: {detail}")
    print("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_e2e())
    sys.exit(0 if success else 1)
