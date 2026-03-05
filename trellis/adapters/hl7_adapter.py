"""HL7v2 adapter: lightweight manual parser for common message types.

No external dependencies — parses HL7v2 pipe-delimited format directly.
Supports: ADT^A01, ADT^A03, ORM^O01, ORU^R01, SIU^S12.
"""

import logging
from datetime import datetime
from typing import Any

from trellis.schemas import Envelope, Metadata, Payload, RoutingHints, Sender

logger = logging.getLogger("trellis.adapters.hl7")

# Message type → routing tags
HL7_TAG_MAP: dict[str, list[str]] = {
    "ADT^A01": ["admit", "adt", "patient-movement"],
    "ADT^A03": ["discharge", "adt", "patient-movement"],
    "ORM^O01": ["order", "orm"],
    "ORU^R01": ["result", "oru", "lab"],
    "SIU^S12": ["scheduling", "siu", "appointment"],
}

# Message type → category
HL7_CATEGORY_MAP: dict[str, str] = {
    "ADT^A01": "patient-movement",
    "ADT^A03": "patient-movement",
    "ORM^O01": "orders",
    "ORU^R01": "results",
    "SIU^S12": "scheduling",
}


class HL7ParseError(Exception):
    """Raised when HL7v2 message cannot be parsed."""
    pass


def _split_segments(raw: str) -> list[list[str]]:
    """Split raw HL7v2 into segments, each segment split by field separator."""
    raw = raw.strip()
    # HL7v2 uses \r as segment delimiter, but accept \n and \r\n too
    lines = raw.replace("\r\n", "\r").replace("\n", "\r").split("\r")
    segments = []
    for line in lines:
        line = line.strip()
        if line:
            segments.append(line.split("|"))
    return segments


def _get_segment(segments: list[list[str]], segment_id: str) -> list[str] | None:
    """Find first segment matching segment_id (e.g., 'MSH', 'PID')."""
    for seg in segments:
        if seg and seg[0] == segment_id:
            return seg
    return None


def _safe_get(fields: list[str], index: int, default: str = "") -> str:
    """Safely get a field by index."""
    if index < len(fields):
        return fields[index]
    return default


def _parse_component(field: str, component_index: int = 0) -> str:
    """Extract a component from a field (components separated by ^)."""
    parts = field.split("^")
    if component_index < len(parts):
        return parts[component_index]
    return ""


def parse_hl7(raw: str) -> dict[str, Any]:
    """Parse raw HL7v2 message and extract key fields.

    Returns dict with: message_type, event_type, message_type_full,
    sending_facility, timestamp, patient_mrn, patient_name, raw_segments.

    Raises HL7ParseError if MSH segment is missing or malformed.
    """
    if not raw or not raw.strip():
        raise HL7ParseError("Empty HL7 message")

    segments = _split_segments(raw)
    if not segments:
        raise HL7ParseError("No segments found in HL7 message")

    msh = _get_segment(segments, "MSH")
    if not msh:
        raise HL7ParseError("MSH segment not found")

    # MSH fields (note: MSH-1 is the field separator itself, so indexing is offset)
    # MSH|^~\\&|SendingApp|SendingFac|RecvApp|RecvFac|Timestamp||MsgType|ControlID|ProcID|Version
    # Index: 0   1         2          3        4       5        6       7  8       9        10     11
    sending_facility = _safe_get(msh, 3)
    timestamp_raw = _safe_get(msh, 6)
    message_type_field = _safe_get(msh, 8)

    # Parse message type: ADT^A01 → message_type=ADT, event_type=A01
    msg_type = _parse_component(message_type_field, 0)
    event_type = _parse_component(message_type_field, 1)
    message_type_full = f"{msg_type}^{event_type}" if event_type else msg_type

    # Parse timestamp (HL7 format: YYYYMMDDHHMMSS or YYYYMMDDHHMM)
    timestamp = None
    if timestamp_raw:
        try:
            # Strip timezone suffix if present
            ts = timestamp_raw.split("+")[0].split("-")[0]
            if len(ts) >= 14:
                timestamp = datetime.strptime(ts[:14], "%Y%m%d%H%M%S").isoformat()
            elif len(ts) >= 12:
                timestamp = datetime.strptime(ts[:12], "%Y%m%d%H%M").isoformat()
            elif len(ts) >= 8:
                timestamp = datetime.strptime(ts[:8], "%Y%m%d").isoformat()
        except ValueError:
            pass

    # Extract patient MRN from PID segment
    pid = _get_segment(segments, "PID")
    patient_mrn = ""
    patient_name = ""
    if pid:
        # PID-3 = Patient ID (MRN), PID-5 = Patient Name
        pid3 = _safe_get(pid, 3)
        patient_mrn = _parse_component(pid3, 0)  # First component is the ID
        pid5 = _safe_get(pid, 5)
        last_name = _parse_component(pid5, 0)
        first_name = _parse_component(pid5, 1)
        patient_name = f"{last_name}, {first_name}" if first_name else last_name

    return {
        "message_type": msg_type,
        "event_type": event_type,
        "message_type_full": message_type_full,
        "sending_facility": sending_facility,
        "timestamp": timestamp,
        "patient_mrn": patient_mrn,
        "patient_name": patient_name,
        "raw_segments": {seg[0]: seg for seg in segments if seg},
    }


def build_hl7_envelope(raw: str) -> Envelope:
    """Parse HL7v2 message and build a routing Envelope.

    Raises HL7ParseError on malformed input.
    """
    parsed = parse_hl7(raw)
    msg_full = parsed["message_type_full"]
    tags = HL7_TAG_MAP.get(msg_full, [parsed["message_type"].lower()])
    category = HL7_CATEGORY_MAP.get(msg_full)

    return Envelope(
        source_type="hl7",
        source_id=f"hl7-{parsed['sending_facility'] or 'unknown'}",
        payload=Payload(
            text=f"HL7 {msg_full} from {parsed['sending_facility']}",
            data={
                "message_type": parsed["message_type"],
                "event_type": parsed["event_type"],
                "message_type_full": msg_full,
                "sending_facility": parsed["sending_facility"],
                "patient_mrn": parsed["patient_mrn"],
                "patient_name": parsed["patient_name"],
                "hl7_timestamp": parsed["timestamp"],
            },
        ),
        metadata=Metadata(
            priority="high" if msg_full in ("ADT^A01", "ADT^A03") else "normal",
            sender=Sender(
                name=parsed["sending_facility"] or "hl7-sender",
                department="clinical",
            ),
        ),
        routing_hints=RoutingHints(
            tags=tags,
            category=category,
            department="clinical",
        ),
    )
