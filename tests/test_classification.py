"""Tests for the Classification Engine (trellis/classification.py)."""

import pytest
from trellis.schemas import Envelope, Payload, RoutingHints, Metadata
from trellis.classification import classify_envelope, SOURCE_TYPE_MAP


# ── Helpers ───────────────────────────────────────────────────────────────

def make_envelope(
    source_type: str = "api",
    text: str = "",
    data: dict | None = None,
    routing_hints: dict | None = None,
    priority: str = "normal",
) -> Envelope:
    hints = RoutingHints(**(routing_hints or {}))
    payload = Payload(text=text, data=data or {})
    metadata = Metadata(priority=priority)
    return Envelope(source_type=source_type, payload=payload, metadata=metadata, routing_hints=hints)


# ── Source-type mapping ───────────────────────────────────────────────────

class TestSourceTypeMapping:
    @pytest.mark.parametrize("source_type,expected_category,expected_dept", [
        ("cisa_kev",     "security",    "Information Security"),
        ("nvd",          "security",    "Information Security"),
        ("nist",         "security",    "Information Security"),
        ("ivanti",       "incident",    "IT"),
        ("servicenow",   "incident",    "IT"),
        ("hr_system",    "hr",          "HR"),
        ("ukg",          "hr",          "HR"),
        ("peoplesoft",   "hr",          "HR"),
        ("epic",         "clinical",    "Clinical"),
        ("claims",       "revenue",     "Revenue Cycle"),
        ("payer",        "revenue",     "Revenue Cycle"),
        ("cms",          "regulatory",  "Compliance"),
        ("healthit_news","industry",    "IT"),
        ("beckers",      "industry",    "IT"),
    ])
    def test_source_type_maps_correctly(self, source_type, expected_category, expected_dept):
        env = make_envelope(source_type=source_type)
        result = classify_envelope(env)
        assert result.routing_hints.category == expected_category, f"{source_type} → wrong category"
        assert result.routing_hints.department == expected_dept, f"{source_type} → wrong department"

    def test_source_type_map_coverage(self):
        """All keys in SOURCE_TYPE_MAP produce a classification."""
        for source_type in SOURCE_TYPE_MAP:
            env = make_envelope(source_type=source_type)
            result = classify_envelope(env)
            assert result.routing_hints.category is not None
            assert result.routing_hints.department is not None

    def test_source_type_sets_high_confidence(self):
        env = make_envelope(source_type="nvd")
        result = classify_envelope(env)
        meta = result.payload.data.get("_classification", {})
        assert meta.get("classification_source") == "source_type_map"
        assert meta.get("classification_confidence") == "high"


# ── Keyword analysis fallback ─────────────────────────────────────────────

class TestKeywordAnalysis:
    def test_security_keywords_detected(self):
        env = make_envelope(source_type="unknown_source", text="A new CVE vulnerability was found in the firewall")
        result = classify_envelope(env)
        assert result.routing_hints.category == "security"
        assert result.routing_hints.department == "Information Security"

    def test_it_keywords_detected(self):
        env = make_envelope(source_type="unknown_source", text="Ticket opened: VPN outage affecting network server")
        result = classify_envelope(env)
        assert result.routing_hints.category == "incident"

    def test_hr_keywords_detected(self):
        env = make_envelope(source_type="unknown_source", text="Employee submitted FMLA request for onboarding payroll issue")
        result = classify_envelope(env)
        assert result.routing_hints.category == "hr"

    def test_revenue_keywords_detected(self):
        env = make_envelope(source_type="unknown_source", text="Claim denial for billing coding issue, appeal submitted")
        result = classify_envelope(env)
        assert result.routing_hints.category == "revenue"

    def test_clinical_keywords_detected(self):
        env = make_envelope(source_type="unknown_source", text="Patient admission order for lab and radiology")
        result = classify_envelope(env)
        assert result.routing_hints.category == "clinical"

    def test_compliance_keywords_detected(self):
        env = make_envelope(source_type="unknown_source", text="HIPAA audit compliance policy review by OIG")
        result = classify_envelope(env)
        assert result.routing_hints.category == "compliance"

    def test_keyword_from_payload_data(self):
        env = make_envelope(
            source_type="unknown_source",
            data={"description": "ransomware attack detected on server"}
        )
        result = classify_envelope(env)
        assert result.routing_hints.category == "security"

    def test_keyword_sets_medium_confidence(self):
        env = make_envelope(source_type="unknown_source", text="employee payroll issue")
        result = classify_envelope(env)
        meta = result.payload.data.get("_classification", {})
        assert meta.get("classification_source") == "keyword_analysis"
        assert meta.get("classification_confidence") == "medium"


# ── Severity inference ────────────────────────────────────────────────────

class TestSeverityInference:
    def test_cvss_9_or_above_is_critical(self):
        env = make_envelope(source_type="nvd", data={"cvss_score": 9.8})
        result = classify_envelope(env)
        meta = result.payload.data.get("_classification", {})
        assert meta.get("severity") == "critical"

    def test_cvss_below_9_is_not_critical(self):
        env = make_envelope(source_type="nvd", data={"cvss_score": 7.5})
        result = classify_envelope(env)
        meta = result.payload.data.get("_classification", {})
        assert meta.get("severity") == "normal"

    def test_exploited_in_wild_flag_is_critical(self):
        env = make_envelope(source_type="nvd", data={"exploited_in_wild": True, "cvss_score": 6.0})
        result = classify_envelope(env)
        meta = result.payload.data.get("_classification", {})
        assert meta.get("severity") == "critical"

    def test_outage_keyword_is_critical(self):
        env = make_envelope(text="Complete network outage reported")
        result = classify_envelope(env)
        meta = result.payload.data.get("_classification", {})
        assert meta.get("severity") == "critical"

    def test_breach_keyword_is_critical(self):
        env = make_envelope(text="Security breach detected in EDR")
        result = classify_envelope(env)
        meta = result.payload.data.get("_classification", {})
        assert meta.get("severity") == "critical"

    def test_ransomware_keyword_is_critical(self):
        env = make_envelope(text="ransomware found on workstation")
        result = classify_envelope(env)
        meta = result.payload.data.get("_classification", {})
        assert meta.get("severity") == "critical"

    def test_urgent_keyword_is_high(self):
        env = make_envelope(text="urgent request from manager")
        result = classify_envelope(env)
        meta = result.payload.data.get("_classification", {})
        assert meta.get("severity") == "high"

    def test_escalation_keyword_is_high(self):
        env = make_envelope(text="escalating ticket to next tier")
        result = classify_envelope(env)
        meta = result.payload.data.get("_classification", {})
        assert meta.get("severity") == "high"

    def test_default_severity_is_normal(self):
        env = make_envelope(text="routine system check")
        result = classify_envelope(env)
        meta = result.payload.data.get("_classification", {})
        assert meta.get("severity") == "normal"

    def test_critical_severity_upgrades_priority(self):
        env = make_envelope(text="ransomware detected on all servers", priority="normal")
        result = classify_envelope(env)
        assert result.metadata.priority == "CRITICAL"

    def test_high_severity_upgrades_normal_priority(self):
        env = make_envelope(text="urgent: please escalate this ticket", priority="normal")
        result = classify_envelope(env)
        assert result.metadata.priority == "HIGH"

    def test_does_not_downgrade_existing_priority(self):
        env = make_envelope(text="routine check", priority="CRITICAL")
        result = classify_envelope(env)
        assert result.metadata.priority == "CRITICAL"


# ── Merge behavior ────────────────────────────────────────────────────────

class TestMergeBehavior:
    def test_sender_category_takes_priority(self):
        env = make_envelope(
            source_type="nvd",  # would infer "security"
            routing_hints={"category": "compliance"}  # explicit override
        )
        result = classify_envelope(env)
        assert result.routing_hints.category == "compliance"

    def test_sender_department_takes_priority(self):
        env = make_envelope(
            source_type="ukg",  # would infer "HR"
            routing_hints={"department": "IT"}
        )
        result = classify_envelope(env)
        assert result.routing_hints.department == "IT"

    def test_sender_agent_id_preserved(self):
        env = make_envelope(
            source_type="nvd",
            routing_hints={"agent_id": "my-agent"}
        )
        result = classify_envelope(env)
        assert result.routing_hints.agent_id == "my-agent"

    def test_sender_tags_preserved_and_merged(self):
        env = make_envelope(
            source_type="nvd",
            text="CVE-2024-1234 in crowdstrike",
            routing_hints={"tags": ["custom-tag"]}
        )
        result = classify_envelope(env)
        tags = result.routing_hints.tags
        assert "custom-tag" in tags
        # inferred tags also present
        assert any("cve" in t for t in tags)

    def test_no_duplicate_tags(self):
        env = make_envelope(
            source_type="nvd",
            text="crowdstrike",
            routing_hints={"tags": ["crowdstrike"]}
        )
        result = classify_envelope(env)
        assert result.routing_hints.tags.count("crowdstrike") == 1

    def test_classification_meta_always_present(self):
        env = make_envelope(source_type="nvd")
        result = classify_envelope(env)
        meta = result.payload.data.get("_classification", {})
        assert "classification_source" in meta
        assert "classification_confidence" in meta
        assert "severity" in meta


# ── Unknown source, no keywords ───────────────────────────────────────────

class TestUnknownSource:
    def test_unknown_source_no_keywords_returns_minimal_hints(self):
        env = make_envelope(source_type="unknown_source", text="hello world")
        result = classify_envelope(env)
        # No category inferred
        assert result.routing_hints.category is None
        assert result.routing_hints.department is None

    def test_unknown_source_sets_unknown_classification_source(self):
        env = make_envelope(source_type="unknown_source", text="")
        result = classify_envelope(env)
        meta = result.payload.data.get("_classification", {})
        assert meta.get("classification_source") == "unknown"
        assert meta.get("classification_confidence") == "low"

    def test_unknown_source_still_gets_tags_from_text(self):
        env = make_envelope(source_type="unknown_source", text="CVE-2024-9999 found in crowdstrike")
        result = classify_envelope(env)
        tags = result.routing_hints.tags
        assert "crowdstrike" in tags

    def test_classification_never_raises(self):
        """Engine must be resilient to bad input."""
        from trellis.schemas import Envelope
        bare = Envelope()
        result = classify_envelope(bare)
        assert result is not None


# ── Tag extraction ────────────────────────────────────────────────────────

class TestTagExtraction:
    def test_cve_id_extracted(self):
        env = make_envelope(text="Critical: CVE-2024-12345 exploited in wild")
        result = classify_envelope(env)
        assert "cve-2024-12345" in result.routing_hints.tags

    def test_tech_stack_system_extracted(self):
        env = make_envelope(text="crowdstrike alert on endpoint")
        result = classify_envelope(env)
        assert "crowdstrike" in result.routing_hints.tags

    def test_payer_name_extracted(self):
        env = make_envelope(text="Claim denial from medicare payer")
        result = classify_envelope(env)
        assert "medicare" in result.routing_hints.tags

    def test_denial_code_extracted(self):
        env = make_envelope(text="Denial code co-4 received on claim")
        result = classify_envelope(env)
        assert "co-4" in result.routing_hints.tags
