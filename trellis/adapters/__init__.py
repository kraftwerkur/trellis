"""Adapters package: HTTP, HL7v2, FHIR R4, Teams Bot Framework, and Document adapters."""

from trellis.adapters.http_adapter import build_envelope
from trellis.adapters.hl7_adapter import parse_hl7, build_hl7_envelope
from trellis.adapters.fhir_adapter import parse_fhir_resource, parse_fhir_bundle, build_fhir_envelope
from trellis.adapters.teams_adapter import build_teams_envelope, validate_bot_token, TeamsClient
from trellis.adapters.teams_cards import alert_card, agent_status_card, event_summary_card, envelope_result_card
from trellis.adapters.document_adapter import build_document_envelopes, build_batch_envelopes
from trellis.adapters.document_utils import ExtractionError

__all__ = [
    "build_envelope",
    "parse_hl7", "build_hl7_envelope",
    "parse_fhir_resource", "parse_fhir_bundle", "build_fhir_envelope",
    "build_teams_envelope", "validate_bot_token", "TeamsClient",
    "alert_card", "agent_status_card", "event_summary_card", "envelope_result_card",
    "build_document_envelopes", "build_batch_envelopes", "ExtractionError",
]
