"""End-to-end integration tests for Trellis.

Tests the full pipeline: adapters → event router → rules engine → dispatch → audit.
Each test is self-contained. No shared state between tests.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from trellis.main import app
from trellis.router import set_client_override


@pytest_asyncio.fixture
async def client():
    """Fresh database + test client for each test."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        set_client_override(c)
        from trellis.database import Base, engine
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield c
        set_client_override(None)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)


# ════════════════════════════════════════════════════════════════════════════
# 1. HTTP Adapter → Event Router → Rule Engine → Agent Dispatch → Audit Trail
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_full_pipeline_http_to_audit(client: AsyncClient):
    """Submit event via HTTP adapter → routed by rule → dispatched to agent → audit trail complete."""
    # Register a function agent
    resp = await client.post("/api/agents", json={
        "agent_id": "pipeline-echo", "name": "Pipeline Echo", "owner": "test",
        "department": "IT", "agent_type": "function",
        "function_ref": "trellis.functions.echo",
    })
    assert resp.status_code == 201

    # Create routing rule
    resp = await client.post("/api/rules", json={
        "name": "Route API to pipeline-echo", "priority": 100,
        "conditions": {"source_type": "api"},
        "actions": {"route_to": "pipeline-echo"},
    })
    assert resp.status_code == 201

    # Submit event via HTTP adapter
    resp = await client.post("/api/adapter/http", json={
        "text": "Integration test message", "sender_name": "IntegrationTest",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert "Integration test message" in data["result"]["result"]["text"]
    trace_id = data.get("trace_id")

    # Verify audit trail has full chain
    resp = await client.get("/api/audit")
    events = resp.json()
    event_types = [e["event_type"] for e in events]
    assert "envelope_received" in event_types
    assert "rule_matched" in event_types
    assert "agent_dispatched" in event_types
    assert "agent_responded" in event_types

    # Verify envelope was logged
    resp = await client.get("/api/envelopes")
    assert resp.status_code == 200
    envelopes = resp.json()
    assert len(envelopes) >= 1
    assert envelopes[0]["source_type"] == "api"


@pytest.mark.asyncio
async def test_no_matching_rule_dead_letter(client: AsyncClient):
    """Event with no matching rule results in no_match status."""
    resp = await client.post("/api/adapter/http", json={
        "text": "Orphan message", "sender_name": "Test",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "no_match"


# ════════════════════════════════════════════════════════════════════════════
# 2. PHI Shield Integration
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_phi_detection_in_envelope_payload(client: AsyncClient):
    """PHI (MRN, SSN) in text is detected by regex patterns."""
    from trellis.phi_shield import _detect_regex

    text = "Patient MRN: 12345678, SSN 123-45-6789, name John Smith"
    detections = _detect_regex(text)
    detected_types = {d.phi_type for d in detections}
    assert "MRN" in detected_types
    assert "SSN" in detected_types


@pytest.mark.asyncio
async def test_phi_redaction_before_agent(client: AsyncClient):
    """PHI is redacted via vault tokenization."""
    from trellis.phi_shield import PhiVault, _detect_regex

    text = "Patient MRN: 12345678 has SSN 123-45-6789"
    vault = PhiVault()
    detections = _detect_regex(text)
    assert len(detections) >= 2

    # Tokenize each detection (process end-to-start to preserve offsets)
    redacted = text
    for det in reversed(sorted(detections, key=lambda d: d.start)):
        token = vault.tokenize(det.text, det.phi_type)
        redacted = redacted[:det.start] + token + redacted[det.end:]

    assert "123-45-6789" not in redacted
    assert "[SSN_1]" in redacted
    assert "[MRN_1]" in redacted

    # Rehydration restores original
    restored = vault.rehydrate(redacted)
    assert "12345678" in restored
    assert "123-45-6789" in restored


@pytest.mark.asyncio
async def test_phi_shield_full_mode_redact_rehydrate(client: AsyncClient):
    """Full PHI shield flow: detect → tokenize → rehydrate response."""
    from trellis.phi_shield import PhiVault, _detect_regex, rehydrate_response

    text = "Look up patient MRN: 12345678"
    vault = PhiVault()
    detections = _detect_regex(text)
    assert len(detections) >= 1

    # Tokenize
    redacted = text
    for det in reversed(sorted(detections, key=lambda d: d.start)):
        token = vault.tokenize(det.text, det.phi_type)
        redacted = redacted[:det.start] + token + redacted[det.end:]

    assert "12345678" not in redacted
    assert "[MRN_1]" in redacted

    # Simulate LLM response containing tokens
    fake_response = {
        "choices": [{"message": {"content": "Patient [MRN_1] is admitted."}}]
    }
    restored = rehydrate_response(fake_response, vault)
    assert "12345678" in restored["choices"][0]["message"]["content"]


@pytest.mark.asyncio
async def test_phi_vault_categories_and_counts(client: AsyncClient):
    """Vault tracks PHI categories and detection counts."""
    from trellis.phi_shield import PhiVault

    vault = PhiVault()
    vault.tokenize("123-45-6789", "SSN")
    vault.tokenize("MRN: 12345678", "MRN")
    vault.tokenize("john@test.com", "EMAIL")

    assert vault.detection_count == 3
    assert set(vault.categories) == {"EMAIL", "MRN", "SSN"}


# ════════════════════════════════════════════════════════════════════════════
# 3. FinOps Tracking
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_finops_cost_event_logging(client: AsyncClient):
    """Cost events are logged and attributed to agent/department."""
    from trellis.gateway import log_cost_event
    from trellis.database import async_session

    # Register an agent
    resp = await client.post("/api/agents", json={
        "agent_id": "finops-agent", "name": "FinOps Test", "owner": "test",
        "department": "HR", "agent_type": "function",
        "function_ref": "trellis.functions.echo",
    })
    assert resp.status_code == 201

    # Log a cost event directly
    async with async_session() as db:
        await log_cost_event(
            db, agent_id="finops-agent", model_requested="gpt-4o-mini",
            model_used="gpt-4o-mini", provider="openai",
            tokens_in=500, tokens_out=200,
            trace_id="finops-trace-1", latency_ms=150,
            has_tool_calls=False,
        )

    # Query costs
    resp = await client.get("/api/costs", params={"agent_id": "finops-agent"})
    assert resp.status_code == 200
    costs = resp.json()
    assert len(costs) >= 1
    assert costs[0]["agent_id"] == "finops-agent"
    assert costs[0]["model_used"] == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_finops_cost_summary(client: AsyncClient):
    """Cost summary endpoint aggregates by agent and department."""
    from trellis.gateway import log_cost_event
    from trellis.database import async_session

    # Register agents in different departments
    await client.post("/api/agents", json={
        "agent_id": "hr-agent", "name": "HR Agent", "owner": "test",
        "department": "HR", "agent_type": "function",
        "function_ref": "trellis.functions.echo",
    })
    await client.post("/api/agents", json={
        "agent_id": "it-agent", "name": "IT Agent", "owner": "test",
        "department": "IT", "agent_type": "function",
        "function_ref": "trellis.functions.echo",
    })

    # Log costs for both
    async with async_session() as db:
        await log_cost_event(db, agent_id="hr-agent", model_requested="gpt-4o",
                             model_used="gpt-4o", provider="openai",
                             tokens_in=1000, tokens_out=500,
                             trace_id="t1", latency_ms=200, has_tool_calls=False)
        await log_cost_event(db, agent_id="it-agent", model_requested="gpt-4o-mini",
                             model_used="gpt-4o-mini", provider="openai",
                             tokens_in=200, tokens_out=100,
                             trace_id="t2", latency_ms=100, has_tool_calls=False)

    # Check summary (returns list of per-agent summaries)
    resp = await client.get("/api/costs/summary")
    assert resp.status_code == 200
    summaries = resp.json()
    assert len(summaries) >= 2
    total_cost = sum(s["total_cost_usd"] for s in summaries)
    assert total_cost > 0


# ════════════════════════════════════════════════════════════════════════════
# 4. Multi-Agent Fan-Out
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_fan_out_to_multiple_agents(client: AsyncClient):
    """Fan-out rule dispatches same event to multiple agents, all receive it."""
    # Register 3 agents
    for i in range(1, 4):
        resp = await client.post("/api/agents", json={
            "agent_id": f"fan-agent-{i}", "name": f"Fan Agent {i}", "owner": "test",
            "department": "IT", "agent_type": "function",
            "function_ref": "trellis.functions.echo",
        })
        assert resp.status_code == 201

    # Create fan-out rules
    for i in range(1, 4):
        resp = await client.post("/api/rules", json={
            "name": f"Fan to agent {i}", "priority": i * 100,
            "conditions": {"source_type": "api"},
            "actions": {"route_to": f"fan-agent-{i}"},
            "fan_out": True,
        })
        assert resp.status_code == 201

    # Submit event
    resp = await client.post("/api/adapter/http", json={
        "text": "Fan out integration test", "sender_name": "Test",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "fan_out"
    assert len(data["dispatches"]) == 3

    # All 3 agents should have received and responded
    targets = {d["target_agent"] for d in data["dispatches"]}
    assert targets == {"fan-agent-1", "fan-agent-2", "fan-agent-3"}
    for d in data["dispatches"]:
        assert d["status"] == "success"

    # Audit should show dispatches for all 3
    resp = await client.get("/api/audit", params={"event_type": "agent_dispatched"})
    dispatched = resp.json()
    dispatched_agents = {e["agent_id"] for e in dispatched}
    assert "fan-agent-1" in dispatched_agents
    assert "fan-agent-2" in dispatched_agents
    assert "fan-agent-3" in dispatched_agents


@pytest.mark.asyncio
async def test_fan_out_mixed_with_normal_rule(client: AsyncClient):
    """Fan-out rules + normal rule: normal rule stops at first match, fan-out rules all fire."""
    await client.post("/api/agents", json={
        "agent_id": "primary", "name": "Primary", "owner": "test",
        "department": "IT", "agent_type": "function",
        "function_ref": "trellis.functions.echo",
    })
    await client.post("/api/agents", json={
        "agent_id": "audit-copy", "name": "Audit Copy", "owner": "test",
        "department": "IT", "agent_type": "function",
        "function_ref": "trellis.functions.echo",
    })
    await client.post("/api/agents", json={
        "agent_id": "backup", "name": "Backup", "owner": "test",
        "department": "IT", "agent_type": "function",
        "function_ref": "trellis.functions.echo",
    })

    # Fan-out audit copy (low priority = evaluated first)
    await client.post("/api/rules", json={
        "name": "Audit copy", "priority": 50,
        "conditions": {"source_type": "api"},
        "actions": {"route_to": "audit-copy"},
        "fan_out": True,
    })
    # Normal primary (first non-fanout match wins)
    await client.post("/api/rules", json={
        "name": "Primary handler", "priority": 100,
        "conditions": {"source_type": "api"},
        "actions": {"route_to": "primary"},
    })
    # Normal backup (should NOT fire — primary already matched)
    await client.post("/api/rules", json={
        "name": "Backup handler", "priority": 200,
        "conditions": {"source_type": "api"},
        "actions": {"route_to": "backup"},
    })

    resp = await client.post("/api/adapter/http", json={
        "text": "Mixed rules test", "sender_name": "Test",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "fan_out"
    targets = {d["target_agent"] for d in data["dispatches"]}
    assert targets == {"audit-copy", "primary"}  # backup excluded


# ════════════════════════════════════════════════════════════════════════════
# 5. Health Check Flow
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_platform_health_endpoint(client: AsyncClient):
    """Platform health endpoint returns healthy."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


@pytest.mark.asyncio
async def test_agent_registration_and_status(client: AsyncClient):
    """Register agent, verify it appears in registry with correct status."""
    resp = await client.post("/api/agents", json={
        "agent_id": "health-test", "name": "Health Test Agent", "owner": "test",
        "department": "IT", "agent_type": "function",
        "function_ref": "trellis.functions.echo",
    })
    assert resp.status_code == 201
    agent_data = resp.json()
    assert agent_data["agent_id"] == "health-test"

    # Verify agent in registry
    resp = await client.get("/api/agents/health-test")
    assert resp.status_code == 200
    agent = resp.json()
    assert agent["name"] == "Health Test Agent"
    assert agent["department"] == "IT"


@pytest.mark.asyncio
async def test_agent_status_update(client: AsyncClient):
    """Update agent status to simulate healthy/unhealthy transitions."""
    await client.post("/api/agents", json={
        "agent_id": "status-test", "name": "Status Test", "owner": "test",
        "department": "IT", "agent_type": "function",
        "function_ref": "trellis.functions.echo",
    })

    # Update to unhealthy
    resp = await client.put("/api/agents/status-test", json={"status": "unhealthy"})
    assert resp.status_code == 200

    resp = await client.get("/api/agents/status-test")
    assert resp.json()["status"] == "unhealthy"

    # Update back to healthy
    resp = await client.put("/api/agents/status-test", json={"status": "healthy"})
    assert resp.status_code == 200
    resp = await client.get("/api/agents/status-test")
    assert resp.json()["status"] == "healthy"


@pytest.mark.asyncio
async def test_agent_with_api_key_provisioning(client: AsyncClient):
    """Agent registration auto-provisions an API key."""
    resp = await client.post("/api/agents", json={
        "agent_id": "key-test", "name": "Key Test", "owner": "test",
        "department": "IT", "agent_type": "function",
        "function_ref": "trellis.functions.echo",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert "api_key" in data
    assert data["api_key"].startswith("trl_")

    # Verify key exists in registry
    resp = await client.get("/api/keys")
    keys = [k for k in resp.json() if k["agent_id"] == "key-test"]
    assert len(keys) >= 1


# ════════════════════════════════════════════════════════════════════════════
# 6. HL7/FHIR Adapter → Pipeline
# ════════════════════════════════════════════════════════════════════════════


HL7_ADT_A01 = (
    "MSH|^~\\&|Epic|HF-HOLMES|Trellis|HF|20260306120000||ADT^A01|MSG001|P|2.5\r"
    "PID|||12345678^^^HF||DOE^JOHN||19800115|M\r"
    "PV1||I|4E^401^A|||||||||||||||VN12345|||||||||||||||||||||||||20260306120000\r"
)


@pytest.mark.asyncio
async def test_hl7_adt_full_pipeline(client: AsyncClient):
    """HL7 ADT^A01 → parsed → routed by rule → dispatched → audit trail."""
    # Register agent for clinical events
    await client.post("/api/agents", json={
        "agent_id": "bed-mgmt", "name": "Bed Management Agent", "owner": "test",
        "department": "Clinical", "agent_type": "function",
        "function_ref": "trellis.functions.echo",
    })

    # Rule: HL7 ADT events → bed management
    await client.post("/api/rules", json={
        "name": "ADT to bed mgmt", "priority": 100,
        "conditions": {"source_type": "hl7", "payload.data.message_type_full": "ADT^A01"},
        "actions": {"route_to": "bed-mgmt"},
    })

    # Submit raw HL7 message
    resp = await client.post("/api/adapter/hl7", content=HL7_ADT_A01,
                             headers={"Content-Type": "text/plain"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["target_agent"] == "bed-mgmt"

    # Verify audit trail
    resp = await client.get("/api/audit", params={"event_type": "envelope_received"})
    events = resp.json()
    hl7_events = [e for e in events if e.get("details", {}).get("source_type") == "hl7"]
    assert len(hl7_events) >= 1


@pytest.mark.asyncio
async def test_hl7_parsed_fields(client: AsyncClient):
    """HL7 adapter correctly extracts patient MRN, name, facility, message type."""
    from trellis.adapters.hl7_adapter import parse_hl7

    parsed = parse_hl7(HL7_ADT_A01)
    assert parsed["message_type"] == "ADT"
    assert parsed["event_type"] == "A01"
    assert parsed["message_type_full"] == "ADT^A01"
    assert parsed["sending_facility"] == "HF-HOLMES"
    assert parsed["patient_mrn"] == "12345678"
    assert "DOE" in parsed["patient_name"]
    assert "JOHN" in parsed["patient_name"]


@pytest.mark.asyncio
async def test_hl7_envelope_routing_hints(client: AsyncClient):
    """HL7 envelope has correct routing hints for rule matching."""
    from trellis.adapters.hl7_adapter import build_hl7_envelope

    envelope = build_hl7_envelope(HL7_ADT_A01)
    assert envelope.source_type == "hl7"
    assert envelope.metadata.priority == "high"  # ADT^A01 = high priority
    assert "admit" in envelope.routing_hints.tags
    assert "adt" in envelope.routing_hints.tags
    assert envelope.routing_hints.category == "patient-movement"


@pytest.mark.asyncio
async def test_hl7_malformed_message(client: AsyncClient):
    """Malformed HL7 returns 400."""
    resp = await client.post("/api/adapter/hl7", content="NOT_HL7_MESSAGE",
                             headers={"Content-Type": "text/plain"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_fhir_resource_pipeline(client: AsyncClient):
    """FHIR Patient resource → parsed → routed → dispatched."""
    await client.post("/api/agents", json={
        "agent_id": "fhir-handler", "name": "FHIR Handler", "owner": "test",
        "department": "Clinical", "agent_type": "function",
        "function_ref": "trellis.functions.echo",
    })
    await client.post("/api/rules", json={
        "name": "FHIR patients to handler", "priority": 100,
        "conditions": {"source_type": "fhir"},
        "actions": {"route_to": "fhir-handler"},
    })

    resp = await client.post("/api/adapter/fhir", json={
        "resourceType": "Patient",
        "id": "pat-001",
        "name": [{"family": "Smith", "given": ["Jane"]}],
        "gender": "female",
        "birthDate": "1985-03-15",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"


# ════════════════════════════════════════════════════════════════════════════
# 7. Cross-Cutting: Trace-Level Audit Chain
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_trace_id_propagation(client: AsyncClient):
    """trace_id propagates through entire pipeline and links all audit events."""
    await client.post("/api/agents", json={
        "agent_id": "trace-agent", "name": "Trace Agent", "owner": "test",
        "department": "IT", "agent_type": "function",
        "function_ref": "trellis.functions.echo",
    })
    await client.post("/api/rules", json={
        "name": "Trace route", "priority": 100,
        "conditions": {"source_type": "api"},
        "actions": {"route_to": "trace-agent"},
    })

    # Submit with explicit trace_id
    resp = await client.post("/api/envelopes", json={
        "source_type": "api",
        "payload": {"text": "trace test"},
        "metadata": {"trace_id": "integration-trace-42"},
    })
    assert resp.status_code == 200

    # All audit events should share the trace_id
    resp = await client.get("/api/audit/trace/integration-trace-42")
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) >= 3
    for e in events:
        assert e["trace_id"] == "integration-trace-42"

    # Verify chronological order and completeness
    types = [e["event_type"] for e in events]
    assert types[0] == "envelope_received"
    assert "rule_matched" in types
    assert "agent_dispatched" in types
