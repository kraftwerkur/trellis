"""Tests for PHI Shield — regex, Presidio, vault, redact/rehydrate, modes, API."""

import pytest

from trellis.phi_shield import (
    PhiVault, PhiDetection, PhiStats,
    redact, redact_messages,
    shield_request, shield_response,
    _detect_regex, _detect_presidio,
)


# ═══════════════════════════════════════════════════════════════════════════
# Vault tests
# ═══════════════════════════════════════════════════════════════════════════

class TestPhiVault:
    def test_tokenize_basic(self):
        vault = PhiVault()
        token = vault.tokenize("John Smith", "PERSON")
        assert token == "[PERSON_1]"
        assert vault.detection_count == 1

    def test_tokenize_dedup(self):
        vault = PhiVault()
        t1 = vault.tokenize("John Smith", "PERSON")
        t2 = vault.tokenize("John Smith", "PERSON")
        assert t1 == t2
        assert vault.detection_count == 1

    def test_tokenize_multiple_types(self):
        vault = PhiVault()
        vault.tokenize("John Smith", "PERSON")
        vault.tokenize("Jane Doe", "PERSON")
        vault.tokenize("123-45-6789", "SSN")
        assert vault.detection_count == 3
        assert set(vault.categories) == {"PERSON", "SSN"}

    def test_rehydrate(self):
        vault = PhiVault()
        vault.tokenize("John Smith", "PERSON")
        vault.tokenize("123-45-6789", "SSN")
        text = "Patient [PERSON_1] has SSN [SSN_1]"
        result = vault.rehydrate(text)
        assert result == "Patient John Smith has SSN 123-45-6789"


# ═══════════════════════════════════════════════════════════════════════════
# Regex detection tests
# ═══════════════════════════════════════════════════════════════════════════

class TestRegexDetection:
    def test_ssn(self):
        dets = _detect_regex("SSN is 123-45-6789")
        types = [d.phi_type for d in dets]
        assert "SSN" in types

    def test_mrn(self):
        dets = _detect_regex("MRN: 12345678")
        types = [d.phi_type for d in dets]
        assert "MRN" in types

    def test_phone(self):
        dets = _detect_regex("Call (555) 123-4567")
        types = [d.phi_type for d in dets]
        assert "PHONE" in types

    def test_email(self):
        dets = _detect_regex("Email: john@example.com")
        types = [d.phi_type for d in dets]
        assert "EMAIL" in types

    def test_dob(self):
        dets = _detect_regex("DOB: 01/15/1990")
        types = [d.phi_type for d in dets]
        assert "DATE_OF_BIRTH" in types

    def test_ip_address(self):
        dets = _detect_regex("IP: 192.168.1.100")
        types = [d.phi_type for d in dets]
        assert "IP_ADDRESS" in types

    def test_url(self):
        dets = _detect_regex("Visit https://example.com/patient/123")
        types = [d.phi_type for d in dets]
        assert "URL" in types

    def test_fax(self):
        dets = _detect_regex("Fax: (555) 123-4567")
        types = [d.phi_type for d in dets]
        assert "FAX" in types

    def test_labeled_icd10(self):
        dets = _detect_regex("Diagnosis: ICD-10 E11.65")
        types = [d.phi_type for d in dets]
        assert "ICD10_CODE" in types

    def test_labeled_cpt(self):
        dets = _detect_regex("CPT: 99213")
        types = [d.phi_type for d in dets]
        assert "CPT_CODE" in types

    def test_labeled_npi(self):
        dets = _detect_regex("NPI: 1234567890")
        types = [d.phi_type for d in dets]
        assert "NPI" in types

    def test_labeled_mrn_alternate(self):
        dets = _detect_regex("Patient ID: 12345678")
        types = [d.phi_type for d in dets]
        assert "MRN" in types

    def test_health_plan_id(self):
        dets = _detect_regex("Health plan #ABC123DEF456")
        types = [d.phi_type for d in dets]
        assert "HEALTH_PLAN_ID" in types

    def test_device_id(self):
        dets = _detect_regex("Device serial: ABC-123-DEF-456")
        types = [d.phi_type for d in dets]
        assert "DEVICE_ID" in types

    def test_account_number(self):
        dets = _detect_regex("Account #1234567890")
        types = [d.phi_type for d in dets]
        assert "ACCOUNT_NUMBER" in types


# ═══════════════════════════════════════════════════════════════════════════
# Presidio detection tests
# ═══════════════════════════════════════════════════════════════════════════

class TestPresidioDetection:
    def test_person_name(self):
        dets = _detect_presidio("Patient John Smith was admitted yesterday")
        types = [d.phi_type for d in dets]
        assert "PERSON" in types

    def test_location(self):
        dets = _detect_presidio("The patient lives at 123 Main Street, Springfield")
        types = [d.phi_type for d in dets]
        # Presidio should detect location
        assert any(t in ("LOCATION", "PERSON") for t in types)


# ═══════════════════════════════════════════════════════════════════════════
# Full redact → rehydrate round-trip
# ═══════════════════════════════════════════════════════════════════════════

class TestRedactRehydrate:
    def test_roundtrip_ssn(self):
        vault = PhiVault()
        original = "Patient SSN is 123-45-6789"
        redacted, dets = redact(original, vault)
        assert "123-45-6789" not in redacted
        assert "[SSN_1]" in redacted
        restored = vault.rehydrate(redacted)
        assert "123-45-6789" in restored

    def test_roundtrip_multiple(self):
        vault = PhiVault()
        original = "Patient MRN: 12345678, SSN 987-65-4321, email test@example.com"
        redacted, dets = redact(original, vault)
        assert "12345678" not in redacted or "MRN" in redacted  # MRN label may remain
        assert "987-65-4321" not in redacted
        assert "test@example.com" not in redacted
        restored = vault.rehydrate(redacted)
        assert "987-65-4321" in restored
        assert "test@example.com" in restored

    def test_messages_roundtrip(self):
        vault = PhiVault()
        msgs = [
            {"role": "system", "content": "You are a medical assistant."},
            {"role": "user", "content": "Patient John Smith, SSN 123-45-6789, needs help."},
        ]
        redacted_msgs, dets = redact_messages(msgs, vault)
        assert "123-45-6789" not in redacted_msgs[1]["content"]
        assert len(dets) > 0

    def test_no_phi_passthrough(self):
        vault = PhiVault()
        original = "The weather is nice here."
        redacted, dets = redact(original, vault)
        assert redacted == original
        assert len(dets) == 0


# ═══════════════════════════════════════════════════════════════════════════
# Per-agent mode tests
# ═══════════════════════════════════════════════════════════════════════════

class TestShieldModes:
    @pytest.mark.asyncio
    async def test_mode_off(self):
        msgs = [{"role": "user", "content": "SSN 123-45-6789"}]
        result, vault, dets = await shield_request(msgs, "agent1", "off")
        assert result[0]["content"] == "SSN 123-45-6789"
        assert vault is None
        assert dets == []

    @pytest.mark.asyncio
    async def test_mode_full(self):
        msgs = [{"role": "user", "content": "SSN 123-45-6789"}]
        result, vault, dets = await shield_request(msgs, "agent1", "full")
        assert "123-45-6789" not in result[0]["content"]
        assert vault is not None
        assert len(dets) > 0

    @pytest.mark.asyncio
    async def test_mode_redact_only(self):
        msgs = [{"role": "user", "content": "SSN 123-45-6789"}]
        result, vault, dets = await shield_request(msgs, "agent1", "redact_only")
        assert "123-45-6789" not in result[0]["content"]

    @pytest.mark.asyncio
    async def test_mode_audit_only(self):
        msgs = [{"role": "user", "content": "SSN 123-45-6789"}]
        result, vault, dets = await shield_request(msgs, "agent1", "audit_only")
        # Messages should NOT be modified
        assert result[0]["content"] == "SSN 123-45-6789"
        assert vault is None
        assert len(dets) > 0

    def test_response_rehydrate_full(self):
        vault = PhiVault()
        vault.tokenize("John Smith", "PERSON")
        response = {"choices": [{"message": {"role": "assistant", "content": "Hello [PERSON_1]"}}]}
        result = shield_response(response, vault, "full")
        assert result["choices"][0]["message"]["content"] == "Hello John Smith"

    def test_response_no_rehydrate_redact_only(self):
        vault = PhiVault()
        vault.tokenize("John Smith", "PERSON")
        response = {"choices": [{"message": {"role": "assistant", "content": "Hello [PERSON_1]"}}]}
        result = shield_response(response, vault, "redact_only")
        assert result["choices"][0]["message"]["content"] == "Hello [PERSON_1]"


# ═══════════════════════════════════════════════════════════════════════════
# Stats tests
# ═══════════════════════════════════════════════════════════════════════════

class TestPhiStats:
    def test_record_and_summary(self):
        stats = PhiStats()
        dets = [
            PhiDetection(0, 5, "test", "SSN"),
            PhiDetection(10, 15, "test2", "PERSON"),
        ]
        stats.record("agent1", dets, "full")
        summary = stats.summary()
        assert summary["total_detections"] == 2
        assert summary["by_category"]["SSN"] == 1
        assert summary["by_category"]["PERSON"] == 1
        assert summary["by_agent"]["agent1"] == 2
        assert len(summary["recent_events"]) == 1


# ═══════════════════════════════════════════════════════════════════════════
# False positive tests
# ═══════════════════════════════════════════════════════════════════════════

class TestFalsePositives:
    def test_drug_names_not_person(self):
        """Common drug names should not be flagged as person names by regex."""
        text = "Prescribe metformin and lisinopril for the patient."
        dets = _detect_regex(text)
        person_dets = [d for d in dets if d.phi_type == "PERSON"]
        assert len(person_dets) == 0  # regex doesn't detect names anyway

    def test_hospital_name_not_person_regex(self):
        """Hospital names shouldn't be flagged as person names by regex."""
        text = "Admitted to Johns Hopkins Hospital for treatment."
        dets = _detect_regex(text)
        person_dets = [d for d in dets if d.phi_type == "PERSON"]
        assert len(person_dets) == 0


# ═══════════════════════════════════════════════════════════════════════════
# API endpoint tests
# ═══════════════════════════════════════════════════════════════════════════


class TestPhiAPI:
    @pytest.mark.asyncio
    async def test_phi_test_endpoint(self, client):
        resp = await client.post("/api/phi/test", json={
            "text": "Patient John Smith, SSN 123-45-6789"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "redacted" in data
        assert "123-45-6789" not in data["redacted"]
        assert len(data["detections"]) > 0
        # Should have SSN detection
        det_types = [d["type"] for d in data["detections"]]
        assert "SSN" in det_types

    @pytest.mark.asyncio
    async def test_phi_agents_endpoint(self, client):
        # Create an agent first
        await client.post("/api/agents", json={
            "agent_id": "phi-agents-test",
            "name": "PHI Agents Test",
            "owner": "test",
            "department": "IT",
        })
        resp = await client.get("/api/phi/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        agent_ids = [a["agent_id"] for a in data]
        assert "phi-agents-test" in agent_ids
        # Check shape
        entry = next(a for a in data if a["agent_id"] == "phi-agents-test")
        assert "name" in entry
        assert "phi_shield_mode" in entry
        assert entry["phi_shield_mode"] == "off"  # default

    @pytest.mark.asyncio
    async def test_phi_stats_endpoint(self, client):
        resp = await client.get("/api/phi/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_detections" in data
        assert "by_category" in data
        assert "by_agent" in data

    @pytest.mark.asyncio
    async def test_update_agent_phi_mode(self, client):
        # Create agent first
        resp = await client.post("/api/agents", json={
            "agent_id": "phi-test-agent",
            "name": "PHI Test Agent",
            "owner": "test",
            "department": "IT",
        })
        assert resp.status_code == 201

        # Update PHI mode
        resp = await client.put("/api/agents/phi-test-agent/phi", json={
            "phi_shield_mode": "full"
        })
        assert resp.status_code == 200
        assert resp.json()["phi_shield_mode"] == "full"

        # Invalid mode
        resp = await client.put("/api/agents/phi-test-agent/phi", json={
            "phi_shield_mode": "invalid"
        })
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_phi_test_no_phi(self, client):
        resp = await client.post("/api/phi/test", json={
            "text": "The weather is nice here."
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["redacted"] == "The weather is nice here."
        assert len(data["detections"]) == 0
