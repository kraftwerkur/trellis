"""PHI Shield — HIPAA-compliant PII/PHI redaction engine.

Single file containing: regex patterns, Presidio integration, custom healthcare
recognizers, token vault, redaction/rehydration, audit event emission, stats tracking,
and API endpoint helpers.

Flow: detect PHI → tokenize → send sanitized text to LLM → rehydrate response.
"""

import logging
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("trellis.phi_shield")


# ═══════════════════════════════════════════════════════════════════════════
# Token Vault — ephemeral, per-request, never persisted
# ═══════════════════════════════════════════════════════════════════════════

class PhiVault:
    """Ephemeral per-request token vault. Never persisted."""

    def __init__(self):
        self._map: dict[str, str] = {}       # token → original
        self._reverse: dict[str, str] = {}   # original → token
        self._counters: dict[str, int] = {}  # type → count

    def tokenize(self, text: str, phi_type: str) -> str:
        """Replace PHI with a token, return the token."""
        if text in self._reverse:
            return self._reverse[text]
        count = self._counters.get(phi_type, 0) + 1
        self._counters[phi_type] = count
        token = f"[{phi_type}_{count}]"
        self._map[token] = text
        self._reverse[text] = token
        return token

    def rehydrate(self, text: str) -> str:
        """Replace all tokens in text with original values."""
        for token, original in self._map.items():
            text = text.replace(token, original)
        return text

    @property
    def detections(self) -> list[dict[str, str]]:
        """Return list of {token, type} for all stored mappings."""
        result = []
        for token in self._map:
            # Extract type from [TYPE_N]
            phi_type = token[1:token.rfind("_")]
            result.append({"token": token, "type": phi_type})
        return result

    @property
    def detection_count(self) -> int:
        return len(self._map)

    @property
    def categories(self) -> list[str]:
        return sorted(self._counters.keys())


# ═══════════════════════════════════════════════════════════════════════════
# Detection result
# ═══════════════════════════════════════════════════════════════════════════

class PhiDetection:
    """A single detected PHI span."""
    __slots__ = ("start", "end", "text", "phi_type", "source", "score")

    def __init__(self, start: int, end: int, text: str, phi_type: str,
                 source: str = "regex", score: float = 1.0):
        self.start = start
        self.end = end
        self.text = text
        self.phi_type = phi_type
        self.source = source
        self.score = score

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.phi_type, "text": self.text,
                "start": self.start, "end": self.end,
                "source": self.source, "score": self.score}


# ═══════════════════════════════════════════════════════════════════════════
# Regex patterns — structured PHI (HIPAA Safe Harbor identifiers)
# ═══════════════════════════════════════════════════════════════════════════

REGEX_PATTERNS: list[tuple[str, re.Pattern]] = [
    # SSN: 123-45-6789 or 123456789
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("SSN", re.compile(r"\b\d{9}\b(?=\s|$|[,.])")),

    # MRN: common formats — MRN-123456, MRN: 12345678, MRN#1234567890
    ("MRN", re.compile(r"\bMRN[\s:#-]*\d{6,10}\b", re.IGNORECASE)),

    # Fax: labeled fax numbers (before PHONE to take priority)
    ("FAX", re.compile(r"\b[Ff]ax[\s:#-]*\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b")),

    # Phone: (123) 456-7890, 123-456-7890, 123.456.7890
    ("PHONE", re.compile(r"\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b")),

    # Email
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")),

    # DOB patterns: DOB: 01/15/1990, Date of Birth: 1990-01-15
    ("DATE_OF_BIRTH", re.compile(
        r"\b(?:DOB|Date\s+of\s+Birth|Birth\s*Date)[\s:#-]*"
        r"(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})\b",
        re.IGNORECASE)),

    # ICD-10 codes: A00-Z99.9 pattern
    ("ICD10_CODE", re.compile(r"\b[A-Z]\d{2}(?:\.\d{1,4})?\b")),

    # CPT codes: 5-digit, commonly 00100-99499
    ("CPT_CODE", re.compile(r"\b\d{5}\b")),

    # NPI: 10-digit starting with 1 or 2
    ("NPI", re.compile(r"\b[12]\d{9}\b")),

    # Health plan beneficiary number (labeled)
    ("HEALTH_PLAN_ID", re.compile(
        r"\b(?:health\s*plan|beneficiary|member)\s*(?:#|number|id)[\s:#-]*[A-Z0-9]{6,20}\b",
        re.IGNORECASE)),

    # IP addresses
    ("IP_ADDRESS", re.compile(
        r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b")),

    # URLs
    ("URL", re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)),

    # VIN: 17 alphanumeric (no I, O, Q)
    ("VIN", re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b")),

    # Device serial/identifier (labeled)
    ("DEVICE_ID", re.compile(
        r"\b(?:device\s*(?:#|number|id|serial)|serial\s*(?:#|number|id)?)[\s:#-]*[A-Z0-9-]{6,30}\b",
        re.IGNORECASE)),

    # Account numbers (labeled)
    ("ACCOUNT_NUMBER", re.compile(
        r"\b(?:account|acct)\s*(?:#|number|no)[\s:#-]*[A-Z0-9]{4,20}\b",
        re.IGNORECASE)),

    # Certificate/license numbers (labeled)
    ("LICENSE_NUMBER", re.compile(
        r"\b(?:license|certificate|cert)\s*(?:#|number|no)[\s:#-]*[A-Z0-9-]{4,20}\b",
        re.IGNORECASE)),
]

# Patterns that are too aggressive — we only match these when context is clear
# CPT and ICD-10 can cause false positives on plain numbers/codes, so we require labels
LABELED_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("ICD10_CODE", re.compile(
        r"\b(?:ICD[- ]?10|diagnosis|dx)[\s:#-]*[A-Z]\d{2}(?:\.\d{1,4})?\b",
        re.IGNORECASE)),
    ("CPT_CODE", re.compile(
        r"\b(?:CPT|procedure)[\s:#-]*\d{5}\b",
        re.IGNORECASE)),
    ("NPI", re.compile(
        r"\b(?:NPI)[\s:#-]*[12]\d{9}\b",
        re.IGNORECASE)),
    ("MRN", re.compile(
        r"\b(?:medical\s*record|patient\s*(?:#|id|number))[\s:#-]*\d{6,10}\b",
        re.IGNORECASE)),
]


def _detect_regex(text: str) -> list[PhiDetection]:
    """Run regex patterns over text, return detections."""
    detections: list[PhiDetection] = []
    seen_spans: set[tuple[int, int]] = set()

    # Labeled patterns first (higher confidence)
    for phi_type, pattern in LABELED_PATTERNS:
        for m in pattern.finditer(text):
            span = (m.start(), m.end())
            if span not in seen_spans:
                seen_spans.add(span)
                detections.append(PhiDetection(
                    m.start(), m.end(), m.group(), phi_type, "regex", 0.95))

    # Core patterns — skip overly broad ones (CPT, ICD-10 unlabeled, NPI unlabeled)
    SKIP_UNLABELED = {"CPT_CODE", "ICD10_CODE", "NPI"}
    for phi_type, pattern in REGEX_PATTERNS:
        if phi_type in SKIP_UNLABELED:
            continue
        for m in pattern.finditer(text):
            span = (m.start(), m.end())
            # Skip if overlaps with existing detection
            overlaps = any(
                not (m.end() <= s[0] or m.start() >= s[1])
                for s in seen_spans
            )
            if not overlaps:
                seen_spans.add(span)
                detections.append(PhiDetection(
                    m.start(), m.end(), m.group(), phi_type, "regex", 0.9))

    return detections


# ═══════════════════════════════════════════════════════════════════════════
# Presidio integration — unstructured PHI (names, addresses, dates)
# ═══════════════════════════════════════════════════════════════════════════

_analyzer = None
_presidio_available = False

# Map Presidio entity types to our PHI types
PRESIDIO_TYPE_MAP = {
    "PERSON": "PERSON",
    "LOCATION": "LOCATION",
    "DATE_TIME": "DATE",
    "EMAIL_ADDRESS": "EMAIL",
    "PHONE_NUMBER": "PHONE",
    "US_SSN": "SSN",
    "IP_ADDRESS": "IP_ADDRESS",
    "URL": "URL",
    "NRP": "NRP",  # nationality/religious/political group
    "MEDICAL_LICENSE": "LICENSE_NUMBER",
    "US_DRIVER_LICENSE": "LICENSE_NUMBER",
    "CREDIT_CARD": "ACCOUNT_NUMBER",
    "IBAN_CODE": "ACCOUNT_NUMBER",
    "US_BANK_NUMBER": "ACCOUNT_NUMBER",
    "US_PASSPORT": "LICENSE_NUMBER",
}


def _get_analyzer():
    """Lazy-init Presidio analyzer with custom healthcare recognizers."""
    global _analyzer, _presidio_available
    if _analyzer is not None:
        return _analyzer

    try:
        from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern

        # Custom healthcare recognizers
        mrn_recognizer = PatternRecognizer(
            supported_entity="MRN",
            name="MRN Recognizer",
            patterns=[
                Pattern("MRN labeled", r"\bMRN[\s:#-]*\d{6,10}\b", 0.9),
                Pattern("Patient ID", r"\b(?:patient\s*(?:#|id|number))[\s:#-]*\d{6,10}\b", 0.85),
            ],
            supported_language="en",
        )

        icd10_recognizer = PatternRecognizer(
            supported_entity="ICD10_CODE",
            name="ICD-10 Recognizer",
            patterns=[
                Pattern("ICD-10 labeled", r"\b(?:ICD[- ]?10|diagnosis|dx)[\s:#-]*[A-Z]\d{2}(?:\.\d{1,4})?\b", 0.9),
            ],
            supported_language="en",
        )

        cpt_recognizer = PatternRecognizer(
            supported_entity="CPT_CODE",
            name="CPT Recognizer",
            patterns=[
                Pattern("CPT labeled", r"\b(?:CPT|procedure)[\s:#-]*\d{5}\b", 0.9),
            ],
            supported_language="en",
        )

        npi_recognizer = PatternRecognizer(
            supported_entity="NPI",
            name="NPI Recognizer",
            patterns=[
                Pattern("NPI labeled", r"\b(?:NPI)[\s:#-]*[12]\d{9}\b", 0.9),
            ],
            supported_language="en",
        )

        analyzer = AnalyzerEngine()
        analyzer.registry.add_recognizer(mrn_recognizer)
        analyzer.registry.add_recognizer(icd10_recognizer)
        analyzer.registry.add_recognizer(cpt_recognizer)
        analyzer.registry.add_recognizer(npi_recognizer)

        _analyzer = analyzer
        _presidio_available = True
        logger.info("Presidio analyzer initialized with custom healthcare recognizers")
        return _analyzer

    except ImportError:
        logger.warning("Presidio not available — using regex-only detection")
        _presidio_available = False
        return None


def _detect_presidio(text: str) -> list[PhiDetection]:
    """Run Presidio NER over text, return detections."""
    analyzer = _get_analyzer()
    if analyzer is None:
        return []

    try:
        results = analyzer.analyze(
            text=text,
            language="en",
            entities=None,  # detect all
            score_threshold=0.5,
        )
    except Exception as e:
        logger.error(f"Presidio analysis failed: {e}")
        return []

    detections = []
    for r in results:
        phi_type = PRESIDIO_TYPE_MAP.get(r.entity_type, r.entity_type)
        detections.append(PhiDetection(
            r.start, r.end, text[r.start:r.end], phi_type, "presidio", r.score))

    return detections


# ═══════════════════════════════════════════════════════════════════════════
# Detection merger — combine regex + Presidio, deduplicate overlaps
# ═══════════════════════════════════════════════════════════════════════════

def _merge_detections(regex_hits: list[PhiDetection],
                      presidio_hits: list[PhiDetection]) -> list[PhiDetection]:
    """Merge and deduplicate detections. On overlap, keep higher-confidence one."""
    all_hits = regex_hits + presidio_hits
    if not all_hits:
        return []

    # Sort by start position, then by score descending
    all_hits.sort(key=lambda d: (d.start, -d.score))

    merged: list[PhiDetection] = []
    for det in all_hits:
        # Check if this overlaps with any already-accepted detection
        overlaps = False
        for existing in merged:
            if not (det.end <= existing.start or det.start >= existing.end):
                overlaps = True
                break
        if not overlaps:
            merged.append(det)

    merged.sort(key=lambda d: d.start)
    return merged


# ═══════════════════════════════════════════════════════════════════════════
# Core API — detect, redact, rehydrate
# ═══════════════════════════════════════════════════════════════════════════

def detect(text: str) -> list[PhiDetection]:
    """Detect all PHI/PII in text. Returns merged, deduplicated detections."""
    regex_hits = _detect_regex(text)
    presidio_hits = _detect_presidio(text)
    return _merge_detections(regex_hits, presidio_hits)


def redact(text: str, vault: PhiVault) -> tuple[str, list[PhiDetection]]:
    """Detect PHI and replace with tokens. Returns (redacted_text, detections).

    Processes detections from end to start to preserve character offsets.
    """
    detections = detect(text)
    if not detections:
        return text, []

    # Process from end to start so offsets stay valid
    redacted = text
    for det in reversed(detections):
        token = vault.tokenize(det.text, det.phi_type)
        redacted = redacted[:det.start] + token + redacted[det.end:]

    return redacted, detections


def redact_messages(messages: list[dict[str, Any]], vault: PhiVault) -> tuple[list[dict[str, Any]], list[PhiDetection]]:
    """Redact PHI from a list of chat messages. Returns (redacted_messages, all_detections)."""
    all_detections: list[PhiDetection] = []
    redacted_msgs = []
    for msg in messages:
        msg_copy = dict(msg)
        if msg_copy.get("content"):
            redacted_text, dets = redact(msg_copy["content"], vault)
            msg_copy["content"] = redacted_text
            all_detections.extend(dets)
        redacted_msgs.append(msg_copy)
    return redacted_msgs, all_detections


def rehydrate(text: str, vault: PhiVault) -> str:
    """Replace tokens back to original values."""
    return vault.rehydrate(text)


def rehydrate_response(result: dict[str, Any], vault: PhiVault) -> dict[str, Any]:
    """Rehydrate tokens in a chat completion response."""
    if not vault.detection_count:
        return result
    for choice in result.get("choices", []):
        msg = choice.get("message", {})
        if msg.get("content"):
            msg["content"] = vault.rehydrate(msg["content"])
    return result


# ═══════════════════════════════════════════════════════════════════════════
# Audit — emit phi_detected events (NEVER log actual PHI values)
# ═══════════════════════════════════════════════════════════════════════════

async def emit_phi_audit(db, agent_id: str, trace_id: str | None,
                         mode: str, detections: list[PhiDetection]) -> None:
    """Emit audit event for PHI detection. Never includes actual PHI values."""
    if not detections:
        return

    from trellis.router import emit_audit

    categories = sorted(set(d.phi_type for d in detections))
    action = "redacted" if mode in ("full", "redact_only") else "logged"

    await emit_audit(db, "phi_detected", agent_id=agent_id, trace_id=trace_id, details={
        "mode": mode,
        "detections": len(detections),
        "categories": categories,
        "action": action,
    })


# ═══════════════════════════════════════════════════════════════════════════
# Stats tracking — in-memory counters for dashboard
# ═══════════════════════════════════════════════════════════════════════════

class PhiStats:
    """In-memory PHI detection statistics. Thread-safe enough for async."""

    def __init__(self):
        self._by_category: dict[str, int] = defaultdict(int)
        self._by_agent: dict[str, int] = defaultdict(int)
        self._by_day: dict[str, int] = defaultdict(int)
        self._recent_events: list[dict[str, Any]] = []  # capped ring buffer
        self._max_recent = 100

    def record(self, agent_id: str, detections: list[PhiDetection], mode: str):
        """Record detection stats (no PHI values stored)."""
        if not detections:
            return
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for d in detections:
            self._by_category[d.phi_type] += 1
        self._by_agent[agent_id] += len(detections)
        self._by_day[day] += len(detections)

        self._recent_events.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent_id": agent_id,
            "count": len(detections),
            "categories": sorted(set(d.phi_type for d in detections)),
            "mode": mode,
        })
        if len(self._recent_events) > self._max_recent:
            self._recent_events = self._recent_events[-self._max_recent:]

    def summary(self) -> dict[str, Any]:
        return {
            "total_detections": sum(self._by_category.values()),
            "by_category": dict(self._by_category),
            "by_agent": dict(self._by_agent),
            "by_day": dict(self._by_day),
            "recent_events": self._recent_events[-20:],
        }


# Global stats instance
phi_stats = PhiStats()


# ═══════════════════════════════════════════════════════════════════════════
# Gateway integration — called from gateway.py
# ═══════════════════════════════════════════════════════════════════════════

async def shield_request(
    messages: list[dict[str, Any]],
    agent_id: str,
    phi_shield_mode: str,
    db=None,
    trace_id: str | None = None,
) -> tuple[list[dict[str, Any]], PhiVault | None, list[PhiDetection]]:
    """Process messages through PHI shield based on mode.

    Returns (possibly_redacted_messages, vault_or_None, detections).
    """
    if phi_shield_mode == "off":
        return messages, None, []

    vault = PhiVault()
    redacted_msgs, detections = redact_messages(messages, vault)

    if detections:
        phi_stats.record(agent_id, detections, phi_shield_mode)
        if db is not None:
            await emit_phi_audit(db, agent_id, trace_id, phi_shield_mode, detections)
        # Fire alert for PHI detection
        try:
            from trellis.alerts import fire_alert_event
            categories = sorted(set(d.phi_type for d in detections))
            await fire_alert_event("phi_shield", "phi_detected",
                                   f"PHI detected: {len(detections)} instance(s), categories: {categories}",
                                   agent_id=agent_id,
                                   details={"count": len(detections), "categories": categories})
        except Exception as e:
            logger.debug(f"Alert dispatch failed (non-fatal): {e}")

    if phi_shield_mode == "audit_only":
        # Don't modify messages, just log
        return messages, None, detections

    # full or redact_only — return redacted messages
    return redacted_msgs, vault, detections


def shield_response(
    result: dict[str, Any],
    vault: PhiVault | None,
    phi_shield_mode: str,
) -> dict[str, Any]:
    """Rehydrate response if mode is 'full'."""
    if phi_shield_mode == "full" and vault is not None:
        return rehydrate_response(result, vault)
    return result
