"""Tests for the upgraded SecurityTriageAgent with multi-step execution."""

import pytest
from unittest.mock import patch, MagicMock

from trellis.agents.security_triage import SecurityTriageAgent, CVE_PATTERN


# ── Helpers ────────────────────────────────────────────────────────────

def _make_llm_response(text="Risk assessment: MEDIUM risk."):
    """Build a mock LLM response (no tool calls → agent loop finishes)."""
    return {
        "choices": [{"message": {"content": text, "role": "assistant"}}],
        "usage": {"total_tokens": 20},
    }


async def _mock_llm_call(messages, tools, model, temperature):
    """Async mock LLM that returns a plain text response (no tool calls)."""
    return _make_llm_response("Risk assessment: MEDIUM risk. No immediate action needed.")


async def _mock_llm_call_critical(messages, tools, model, temperature):
    """Mock LLM that returns a CRITICAL assessment."""
    return _make_llm_response(
        "CRITICAL: CVE found in CISA KEV. Immediate patching required."
    )


def _mock_kev_found(cve_id):
    return {
        "found": True,
        "vulnerability": {
            "cveID": cve_id,
            "vendorProject": "TestVendor",
            "product": "TestProduct",
            "dateAdded": "2024-01-15",
            "shortDescription": "Test vulnerability actively exploited",
            "requiredAction": "Apply updates per vendor instructions",
            "dueDate": "2024-02-05",
        },
    }


def _mock_kev_not_found(cve_id):
    return {"found": False, "vulnerability": None}


# ── Tests ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_envelope_with_known_cve():
    """CVE found in KEV → CRITICAL risk level."""
    agent = SecurityTriageAgent(llm_call=_mock_llm_call_critical)

    envelope = {"text": "Alert: CVE-2024-12345 detected in production systems."}

    with patch(
        "trellis.agents.security_triage.check_cisa_kev",
        side_effect=_mock_kev_found,
    ):
        result = await agent.execute(envelope)

    assert result["status"] == "completed"
    data = result["result"]["data"]
    assert "CVE-2024-12345" in data["cve_ids"]
    assert data["any_in_kev"] is True
    assert data["risk_level"] == "CRITICAL"
    assert data["kev_results"]["CVE-2024-12345"]["found"] is True


@pytest.mark.asyncio
async def test_envelope_with_no_cves():
    """No CVE IDs → LOW risk level."""
    agent = SecurityTriageAgent(llm_call=_mock_llm_call)

    envelope = {"text": "General security notice: please update your passwords."}

    with patch(
        "trellis.agents.security_triage.check_cisa_kev",
        side_effect=_mock_kev_not_found,
    ):
        result = await agent.execute(envelope)

    assert result["status"] == "completed"
    data = result["result"]["data"]
    assert data["cve_ids"] == []
    assert data["any_in_kev"] is False
    assert data["risk_level"] == "LOW"
    assert data["kev_results"] == {}


@pytest.mark.asyncio
async def test_envelope_with_multiple_cves():
    """Multiple CVEs extracted, each gets KEV lookup."""
    agent = SecurityTriageAgent(llm_call=_mock_llm_call)

    envelope = {
        "text": "Vulnerabilities: CVE-2024-11111, CVE-2024-22222, and CVE-2024-33333."
    }

    def mixed_kev(cve_id):
        if cve_id == "CVE-2024-22222":
            return _mock_kev_found(cve_id)
        return _mock_kev_not_found(cve_id)

    with patch(
        "trellis.agents.security_triage.check_cisa_kev",
        side_effect=mixed_kev,
    ):
        result = await agent.execute(envelope)

    data = result["result"]["data"]
    assert len(data["cve_ids"]) == 3
    assert "CVE-2024-11111" in data["cve_ids"]
    assert "CVE-2024-22222" in data["cve_ids"]
    assert "CVE-2024-33333" in data["cve_ids"]
    # One is in KEV
    assert data["any_in_kev"] is True
    assert data["risk_level"] == "CRITICAL"


@pytest.mark.asyncio
async def test_kev_not_found_medium_risk():
    """CVE exists but NOT in KEV → MEDIUM risk."""
    agent = SecurityTriageAgent(llm_call=_mock_llm_call)

    envelope = {"text": "CVE-2024-99999 reported in vendor advisory."}

    with patch(
        "trellis.agents.security_triage.check_cisa_kev",
        side_effect=_mock_kev_not_found,
    ):
        result = await agent.execute(envelope)

    data = result["result"]["data"]
    assert data["cve_ids"] == ["CVE-2024-99999"]
    assert data["any_in_kev"] is False
    assert data["risk_level"] == "MEDIUM"


@pytest.mark.asyncio
async def test_response_structure():
    """Validate the full response structure."""
    agent = SecurityTriageAgent(llm_call=_mock_llm_call)

    envelope = {"text": "CVE-2024-55555 needs review."}

    with patch(
        "trellis.agents.security_triage.check_cisa_kev",
        side_effect=_mock_kev_not_found,
    ):
        result = await agent.execute(envelope)

    # Top-level keys
    assert "status" in result
    assert "result" in result
    assert isinstance(result["status"], str)

    # Result keys
    r = result["result"]
    assert "text" in r
    assert "data" in r
    assert "attachments" in r
    assert isinstance(r["text"], str)
    assert isinstance(r["data"], dict)
    assert isinstance(r["attachments"], list)

    # Data keys
    d = r["data"]
    assert "cve_ids" in d
    assert "kev_results" in d
    assert "any_in_kev" in d
    assert "risk_level" in d
    assert "agent_loop_steps" in d
    assert d["risk_level"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")


@pytest.mark.asyncio
async def test_duplicate_cves_deduplicated():
    """Same CVE mentioned twice → only one lookup."""
    agent = SecurityTriageAgent(llm_call=_mock_llm_call)

    envelope = {"text": "CVE-2024-11111 is bad. Again: CVE-2024-11111."}

    call_count = 0

    def counting_kev(cve_id):
        nonlocal call_count
        call_count += 1
        return _mock_kev_not_found(cve_id)

    with patch(
        "trellis.agents.security_triage.check_cisa_kev",
        side_effect=counting_kev,
    ):
        result = await agent.execute(envelope)

    assert result["result"]["data"]["cve_ids"] == ["CVE-2024-11111"]
    assert call_count == 1


@pytest.mark.asyncio
async def test_envelope_body_format():
    """Envelope with body.text format."""
    agent = SecurityTriageAgent(llm_call=_mock_llm_call)

    envelope = {"body": {"text": "Alert for CVE-2024-77777."}}

    with patch(
        "trellis.agents.security_triage.check_cisa_kev",
        side_effect=_mock_kev_not_found,
    ):
        result = await agent.execute(envelope)

    assert "CVE-2024-77777" in result["result"]["data"]["cve_ids"]


@pytest.mark.asyncio
async def test_cve_regex_pattern():
    """CVE regex extracts correct patterns."""
    text = "CVE-2024-1234 CVE-2023-99999 not-a-cve CVE-2025-00001"
    matches = CVE_PATTERN.findall(text)
    assert matches == ["CVE-2024-1234", "CVE-2023-99999", "CVE-2025-00001"]
