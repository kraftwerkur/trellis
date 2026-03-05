"""FHIR R4 adapter: parse FHIR resources and bundles into Trellis Envelopes.

No external FHIR library — lightweight dict-based parsing of JSON FHIR resources.
Supports: Patient, Encounter, Observation, DiagnosticReport, ServiceRequest, Appointment.
"""

import logging
from typing import Any

from trellis.schemas import Envelope, Metadata, Payload, RoutingHints, Sender

logger = logging.getLogger("trellis.adapters.fhir")

# Resource type → routing tags
FHIR_TAG_MAP: dict[str, list[str]] = {
    "Patient": ["patient", "demographics"],
    "Encounter": ["encounter", "patient-movement"],
    "Observation": ["observation", "result", "lab"],
    "DiagnosticReport": ["diagnostic-report", "result", "lab"],
    "ServiceRequest": ["service-request", "order"],
    "Appointment": ["appointment", "scheduling"],
}

# Resource type → category
FHIR_CATEGORY_MAP: dict[str, str] = {
    "Patient": "demographics",
    "Encounter": "patient-movement",
    "Observation": "results",
    "DiagnosticReport": "results",
    "ServiceRequest": "orders",
    "Appointment": "scheduling",
}

SUPPORTED_RESOURCE_TYPES = set(FHIR_TAG_MAP.keys())


class FHIRParseError(Exception):
    """Raised when a FHIR resource cannot be parsed."""
    pass


def _extract_patient_reference(resource: dict[str, Any]) -> str:
    """Extract patient reference from a FHIR resource."""
    # Direct subject reference (most resources)
    subject = resource.get("subject", {})
    if isinstance(subject, dict):
        ref = subject.get("reference", "")
        if ref:
            return ref

    # Patient resource itself
    if resource.get("resourceType") == "Patient":
        return f"Patient/{resource.get('id', '')}"

    # Encounter participant / patient field
    patient = resource.get("patient", {})
    if isinstance(patient, dict):
        ref = patient.get("reference", "")
        if ref:
            return ref

    # Appointment participant
    participants = resource.get("participant", [])
    if isinstance(participants, list):
        for p in participants:
            actor = p.get("actor", {})
            if isinstance(actor, dict):
                ref = actor.get("reference", "")
                if ref and ref.startswith("Patient/"):
                    return ref

    return ""


def _extract_status(resource: dict[str, Any]) -> str:
    """Extract status from a FHIR resource."""
    return resource.get("status", "")


def _extract_category(resource: dict[str, Any]) -> list[str]:
    """Extract category codes from a FHIR resource."""
    categories = resource.get("category", [])
    if not isinstance(categories, list):
        categories = [categories]
    codes = []
    for cat in categories:
        if isinstance(cat, dict):
            for coding in cat.get("coding", []):
                code = coding.get("code", "")
                if code:
                    codes.append(code)
    return codes


def parse_fhir_resource(resource: dict[str, Any]) -> dict[str, Any]:
    """Parse a single FHIR R4 resource and extract key fields.

    Returns dict with: resource_type, resource_id, patient_reference,
    status, categories, raw_resource.

    Raises FHIRParseError if resourceType is missing.
    """
    if not isinstance(resource, dict):
        raise FHIRParseError("FHIR resource must be a JSON object")

    resource_type = resource.get("resourceType")
    if not resource_type:
        raise FHIRParseError("Missing resourceType in FHIR resource")

    return {
        "resource_type": resource_type,
        "resource_id": resource.get("id", ""),
        "patient_reference": _extract_patient_reference(resource),
        "status": _extract_status(resource),
        "categories": _extract_category(resource),
        "raw_resource": resource,
    }


def parse_fhir_bundle(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse a FHIR R4 Bundle and extract all entries.

    Returns list of parsed resources (same format as parse_fhir_resource).
    Raises FHIRParseError if not a valid Bundle.
    """
    if not isinstance(bundle, dict):
        raise FHIRParseError("FHIR Bundle must be a JSON object")

    if bundle.get("resourceType") != "Bundle":
        raise FHIRParseError(f"Expected resourceType 'Bundle', got '{bundle.get('resourceType')}'")

    entries = bundle.get("entry", [])
    if not isinstance(entries, list):
        raise FHIRParseError("Bundle entries must be a list")

    results = []
    for entry in entries:
        resource = entry.get("resource")
        if resource:
            try:
                results.append(parse_fhir_resource(resource))
            except FHIRParseError as e:
                logger.warning(f"Skipping malformed bundle entry: {e}")
    return results


def build_fhir_envelope(resource: dict[str, Any]) -> Envelope:
    """Build routing Envelope from a single FHIR resource.

    Raises FHIRParseError on malformed input.
    """
    parsed = parse_fhir_resource(resource)
    rtype = parsed["resource_type"]
    tags = FHIR_TAG_MAP.get(rtype, [rtype.lower()])
    category = FHIR_CATEGORY_MAP.get(rtype)

    # Add status as tag if present
    status = parsed["status"]
    if status:
        tags = tags + [f"status:{status}"]

    return Envelope(
        source_type="fhir",
        source_id=f"fhir-{rtype.lower()}",
        payload=Payload(
            text=f"FHIR {rtype} ({parsed['resource_id'] or 'new'})",
            data={
                "resource_type": rtype,
                "resource_id": parsed["resource_id"],
                "patient_reference": parsed["patient_reference"],
                "status": status,
                "categories": parsed["categories"],
            },
        ),
        metadata=Metadata(
            priority="normal",
            sender=Sender(name="fhir-adapter", department="clinical"),
        ),
        routing_hints=RoutingHints(
            tags=tags,
            category=category,
            department="clinical",
        ),
    )


def build_fhir_bundle_envelopes(bundle: dict[str, Any]) -> list[Envelope]:
    """Parse a FHIR Bundle and build an Envelope for each entry."""
    entries = parse_fhir_bundle(bundle)
    envelopes = []
    for parsed in entries:
        try:
            envelopes.append(build_fhir_envelope(parsed["raw_resource"]))
        except FHIRParseError as e:
            logger.warning(f"Skipping bundle entry: {e}")
    return envelopes


def parse_fhir_subscription_notification(payload: dict[str, Any]) -> dict[str, Any]:
    """Parse a FHIR Subscription notification (e.g., from Epic).

    Expected format: A Bundle with type 'subscription-notification' or
    a simple notification with subscription reference and focus resource.
    """
    if not isinstance(payload, dict):
        raise FHIRParseError("Subscription notification must be a JSON object")

    # R4 Subscription notification is a Bundle
    if payload.get("resourceType") == "Bundle":
        bundle_type = payload.get("type", "")
        entries = payload.get("entry", [])

        # Extract the focus resources (skip SubscriptionStatus entry)
        resources = []
        for entry in entries:
            resource = entry.get("resource", {})
            rt = resource.get("resourceType", "")
            if rt and rt not in ("SubscriptionStatus", "Subscription"):
                resources.append(resource)

        return {
            "bundle_type": bundle_type,
            "subscription_url": payload.get("subscription", ""),
            "resources": resources,
            "entry_count": len(entries),
            "focus_count": len(resources),
        }

    # Simple notification wrapper
    resource = payload.get("resource") or payload.get("focus")
    if resource:
        return {
            "bundle_type": "notification",
            "subscription_url": payload.get("subscription", ""),
            "resources": [resource],
            "entry_count": 1,
            "focus_count": 1,
        }

    raise FHIRParseError("Could not parse subscription notification — no recognizable structure")
