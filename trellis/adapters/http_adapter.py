"""HTTP adapter for receiving content from external sources."""

import logging

from trellis.schemas import (
    Envelope, HttpAdapterInput, Metadata, Payload, RoutingHints, Sender,
)

logger = logging.getLogger("trellis.adapters.http")


def build_envelope(input_data: HttpAdapterInput) -> Envelope:
    merged_data = {**input_data.data, **input_data.metadata}
    category = input_data.metadata.get("category")
    department = input_data.metadata.get("department") or input_data.sender_department or None
    return Envelope(
        source_type="api", source_id="http-adapter",
        payload=Payload(text=input_data.text, data=merged_data),
        metadata=Metadata(
            priority=input_data.priority,
            sender=Sender(name=input_data.sender_name, department=input_data.sender_department),
        ),
        routing_hints=RoutingHints(tags=input_data.tags, category=category, department=department),
    )
