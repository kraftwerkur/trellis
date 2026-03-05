"""Tests for HL7v2 and FHIR R4 adapters — parsing, envelope construction, and API routes."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from trellis.adapters.hl7_adapter import parse_hl7, build_hl7_envelope, HL7ParseError
from trellis.adapters.fhir_adapter import (
    parse_fhir_resource, parse_fhir_bundle, build_fhir_envelope,
    build_fhir_bundle_envelopes, parse_fhir_subscription_notification,
    FHIRParseError,
)
from trellis.router import set_client_override
from trellis.main import app


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client():
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


# ── Sample HL7 Messages ───────────────────────────────────────────────────

ADT_A01 = (
    "MSH|^~\\&|EPIC|HEALTHFIRST|TRELLIS|HF|20260301120000||ADT^A01|MSG001|P|2.5\r"
    "PID|||MRN12345^^^HF||DOE^JOHN||19800101|M\r"
    "PV1||I|ICU^101^A"
)

ADT_A03 = (
    "MSH|^~\\&|EPIC|HEALTHFIRST|TRELLIS|HF|20260301150000||ADT^A03|MSG002|P|2.5\r"
    "PID|||MRN67890^^^HF||SMITH^JANE||19750615|F\r"
    "PV1||I|MED^201^B"
)

ORM_O01 = (
    "MSH|^~\\&|CPOE|HEALTHFIRST|LAB|HF|20260301100000||ORM^O01|MSG003|P|2.5\r"
    "PID|||MRN12345^^^HF||DOE^JOHN||19800101|M\r"
    "ORC|NW|ORD001\r"
    "OBR|1|ORD001||CBC^Complete Blood Count"
)

ORU_R01 = (
    "MSH|^~\\&|LAB|HEALTHFIRST|EPIC|HF|20260301110000||ORU^R01|MSG004|P|2.5\r"
    "PID|||MRN12345^^^HF||DOE^JOHN||19800101|M\r"
    "OBR|1|ORD001||CBC^Complete Blood Count\r"
    "OBX|1|NM|WBC^White Blood Cell||7.5|10*3/uL|4.5-11.0|N"
)

SIU_S12 = (
    "MSH|^~\\&|SCHED|HEALTHFIRST|TRELLIS|HF|20260301080000||SIU^S12|MSG005|P|2.5\r"
    "PID|||MRN99999^^^HF||JONES^BOB||19900301|M"
)


# ── HL7v2 Parsing Tests ───────────────────────────────────────────────────

class TestHL7Parsing:
    def test_parse_adt_a01(self):
        result = parse_hl7(ADT_A01)
        assert result["message_type"] == "ADT"
        assert result["event_type"] == "A01"
        assert result["message_type_full"] == "ADT^A01"
        assert result["sending_facility"] == "HEALTHFIRST"
        assert result["patient_mrn"] == "MRN12345"
        assert result["patient_name"] == "DOE, JOHN"
        assert result["timestamp"] == "2026-03-01T12:00:00"

    def test_parse_adt_a03(self):
        result = parse_hl7(ADT_A03)
        assert result["message_type"] == "ADT"
        assert result["event_type"] == "A03"
        assert result["patient_mrn"] == "MRN67890"
        assert result["patient_name"] == "SMITH, JANE"

    def test_parse_orm_o01(self):
        result = parse_hl7(ORM_O01)
        assert result["message_type"] == "ORM"
        assert result["event_type"] == "O01"
        assert result["sending_facility"] == "HEALTHFIRST"
        assert result["patient_mrn"] == "MRN12345"

    def test_parse_oru_r01(self):
        result = parse_hl7(ORU_R01)
        assert result["message_type"] == "ORU"
        assert result["event_type"] == "R01"
        assert "OBX" in result["raw_segments"]

    def test_parse_siu_s12(self):
        result = parse_hl7(SIU_S12)
        assert result["message_type"] == "SIU"
        assert result["event_type"] == "S12"
        assert result["patient_mrn"] == "MRN99999"

    def test_parse_empty_message(self):
        with pytest.raises(HL7ParseError, match="Empty"):
            parse_hl7("")

    def test_parse_no_msh(self):
        with pytest.raises(HL7ParseError, match="MSH"):
            parse_hl7("PID|||MRN123^^^HF||DOE^JOHN")

    def test_parse_newline_delimiters(self):
        """HL7 with \\n instead of \\r should still parse."""
        msg = ADT_A01.replace("\r", "\n")
        result = parse_hl7(msg)
        assert result["message_type"] == "ADT"
        assert result["patient_mrn"] == "MRN12345"


# ── HL7v2 Envelope Tests ──────────────────────────────────────────────────

class TestHL7Envelope:
    def test_adt_a01_envelope(self):
        env = build_hl7_envelope(ADT_A01)
        assert env.source_type == "hl7"
        assert "admit" in env.routing_hints.tags
        assert "adt" in env.routing_hints.tags
        assert env.routing_hints.category == "patient-movement"
        assert env.metadata.priority == "high"
        assert env.payload.data["patient_mrn"] == "MRN12345"

    def test_adt_a03_envelope(self):
        env = build_hl7_envelope(ADT_A03)
        assert "discharge" in env.routing_hints.tags
        assert env.metadata.priority == "high"

    def test_orm_envelope(self):
        env = build_hl7_envelope(ORM_O01)
        assert "order" in env.routing_hints.tags
        assert env.routing_hints.category == "orders"
        assert env.metadata.priority == "normal"

    def test_oru_envelope(self):
        env = build_hl7_envelope(ORU_R01)
        assert "result" in env.routing_hints.tags
        assert env.routing_hints.category == "results"

    def test_siu_envelope(self):
        env = build_hl7_envelope(SIU_S12)
        assert "scheduling" in env.routing_hints.tags
        assert env.routing_hints.category == "scheduling"

    def test_envelope_source_id_includes_facility(self):
        env = build_hl7_envelope(ADT_A01)
        assert "HEALTHFIRST" in env.source_id


# ── FHIR Parsing Tests ────────────────────────────────────────────────────

FHIR_PATIENT = {
    "resourceType": "Patient",
    "id": "pat-001",
    "name": [{"family": "Doe", "given": ["John"]}],
    "gender": "male",
}

FHIR_ENCOUNTER = {
    "resourceType": "Encounter",
    "id": "enc-001",
    "status": "in-progress",
    "subject": {"reference": "Patient/pat-001"},
    "class": {"code": "IMP"},
}

FHIR_OBSERVATION = {
    "resourceType": "Observation",
    "id": "obs-001",
    "status": "final",
    "subject": {"reference": "Patient/pat-001"},
    "category": [{"coding": [{"code": "laboratory"}]}],
    "code": {"coding": [{"code": "WBC"}]},
    "valueQuantity": {"value": 7.5, "unit": "10*3/uL"},
}

FHIR_DIAGNOSTIC_REPORT = {
    "resourceType": "DiagnosticReport",
    "id": "dr-001",
    "status": "final",
    "subject": {"reference": "Patient/pat-001"},
    "category": [{"coding": [{"code": "LAB"}]}],
}

FHIR_SERVICE_REQUEST = {
    "resourceType": "ServiceRequest",
    "id": "sr-001",
    "status": "active",
    "subject": {"reference": "Patient/pat-001"},
}

FHIR_APPOINTMENT = {
    "resourceType": "Appointment",
    "id": "appt-001",
    "status": "booked",
    "participant": [
        {"actor": {"reference": "Patient/pat-001"}},
        {"actor": {"reference": "Practitioner/doc-001"}},
    ],
}


class TestFHIRParsing:
    def test_parse_patient(self):
        result = parse_fhir_resource(FHIR_PATIENT)
        assert result["resource_type"] == "Patient"
        assert result["patient_reference"] == "Patient/pat-001"

    def test_parse_encounter(self):
        result = parse_fhir_resource(FHIR_ENCOUNTER)
        assert result["resource_type"] == "Encounter"
        assert result["status"] == "in-progress"
        assert result["patient_reference"] == "Patient/pat-001"

    def test_parse_observation(self):
        result = parse_fhir_resource(FHIR_OBSERVATION)
        assert result["resource_type"] == "Observation"
        assert "laboratory" in result["categories"]

    def test_parse_diagnostic_report(self):
        result = parse_fhir_resource(FHIR_DIAGNOSTIC_REPORT)
        assert result["resource_type"] == "DiagnosticReport"
        assert "LAB" in result["categories"]

    def test_parse_service_request(self):
        result = parse_fhir_resource(FHIR_SERVICE_REQUEST)
        assert result["resource_type"] == "ServiceRequest"
        assert result["status"] == "active"

    def test_parse_appointment(self):
        result = parse_fhir_resource(FHIR_APPOINTMENT)
        assert result["resource_type"] == "Appointment"
        assert result["patient_reference"] == "Patient/pat-001"

    def test_parse_missing_resource_type(self):
        with pytest.raises(FHIRParseError, match="resourceType"):
            parse_fhir_resource({"id": "bad"})

    def test_parse_non_dict(self):
        with pytest.raises(FHIRParseError):
            parse_fhir_resource("not a dict")


# ── FHIR Bundle Tests ─────────────────────────────────────────────────────

class TestFHIRBundle:
    def test_parse_bundle(self):
        bundle = {
            "resourceType": "Bundle",
            "type": "transaction",
            "entry": [
                {"resource": FHIR_PATIENT},
                {"resource": FHIR_OBSERVATION},
            ],
        }
        results = parse_fhir_bundle(bundle)
        assert len(results) == 2
        assert results[0]["resource_type"] == "Patient"
        assert results[1]["resource_type"] == "Observation"

    def test_bundle_envelopes(self):
        bundle = {
            "resourceType": "Bundle",
            "type": "transaction",
            "entry": [
                {"resource": FHIR_ENCOUNTER},
                {"resource": FHIR_APPOINTMENT},
            ],
        }
        envelopes = build_fhir_bundle_envelopes(bundle)
        assert len(envelopes) == 2
        assert envelopes[0].source_type == "fhir"

    def test_invalid_bundle_type(self):
        with pytest.raises(FHIRParseError, match="Bundle"):
            parse_fhir_bundle({"resourceType": "Patient"})


# ── FHIR Envelope Tests ───────────────────────────────────────────────────

class TestFHIREnvelope:
    def test_observation_envelope(self):
        env = build_fhir_envelope(FHIR_OBSERVATION)
        assert env.source_type == "fhir"
        assert "observation" in env.routing_hints.tags
        assert "result" in env.routing_hints.tags
        assert env.routing_hints.category == "results"
        assert env.payload.data["status"] == "final"
        assert "status:final" in env.routing_hints.tags

    def test_encounter_envelope(self):
        env = build_fhir_envelope(FHIR_ENCOUNTER)
        assert "encounter" in env.routing_hints.tags
        assert env.routing_hints.category == "patient-movement"

    def test_appointment_envelope(self):
        env = build_fhir_envelope(FHIR_APPOINTMENT)
        assert "appointment" in env.routing_hints.tags
        assert env.routing_hints.category == "scheduling"


# ── FHIR Subscription Tests ───────────────────────────────────────────────

class TestFHIRSubscription:
    def test_subscription_bundle_notification(self):
        notification = {
            "resourceType": "Bundle",
            "type": "subscription-notification",
            "entry": [
                {"resource": {"resourceType": "SubscriptionStatus", "status": "active"}},
                {"resource": FHIR_ENCOUNTER},
            ],
        }
        result = parse_fhir_subscription_notification(notification)
        assert result["focus_count"] == 1
        assert result["resources"][0]["resourceType"] == "Encounter"

    def test_subscription_invalid(self):
        with pytest.raises(FHIRParseError):
            parse_fhir_subscription_notification("not a dict")


# ── API Route Tests ────────────────────────────────────────────────────────

class TestHL7API:
    @pytest.mark.asyncio
    async def test_hl7_endpoint(self, client: AsyncClient):
        resp = await client.post(
            "/api/adapter/hl7",
            content=ADT_A01,
            headers={"Content-Type": "text/plain"},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_hl7_malformed(self, client: AsyncClient):
        resp = await client.post(
            "/api/adapter/hl7",
            content="THIS IS NOT HL7",
            headers={"Content-Type": "text/plain"},
        )
        assert resp.status_code == 400


class TestFHIRAPI:
    @pytest.mark.asyncio
    async def test_fhir_resource_endpoint(self, client: AsyncClient):
        resp = await client.post("/api/adapter/fhir", json=FHIR_OBSERVATION)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_fhir_bundle_endpoint(self, client: AsyncClient):
        bundle = {
            "resourceType": "Bundle",
            "type": "transaction",
            "entry": [{"resource": FHIR_PATIENT}, {"resource": FHIR_ENCOUNTER}],
        }
        resp = await client.post("/api/adapter/fhir", json=bundle)
        assert resp.status_code == 200
        data = resp.json()
        assert data["envelopes_processed"] == 2

    @pytest.mark.asyncio
    async def test_fhir_malformed(self, client: AsyncClient):
        resp = await client.post("/api/adapter/fhir", json={"bad": "data"})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_fhir_subscription_endpoint(self, client: AsyncClient):
        notification = {
            "resourceType": "Bundle",
            "type": "subscription-notification",
            "entry": [
                {"resource": {"resourceType": "SubscriptionStatus", "status": "active"}},
                {"resource": FHIR_OBSERVATION},
            ],
        }
        resp = await client.post("/api/adapter/fhir/subscription", json=notification)
        assert resp.status_code == 200
        data = resp.json()
        assert data["envelopes_processed"] == 1
