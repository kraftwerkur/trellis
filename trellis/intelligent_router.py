"""Intelligent Routing — Agent-Declared Intake + Scored Matching.

Single-file implementation (Karpathy style). Agents declare what they handle via
intake declarations, incoming envelopes get scored against all agents, best match wins.
Falls back to rule-based routing when no agent scores above threshold.

Phase 13 of Trellis platform.
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trellis.models import Agent, EnvelopeLog, RoutingFeedback, ShadowComparison
from trellis.schemas import Envelope

logger = logging.getLogger("trellis.intelligent_router")


# ═══════════════════════════════════════════════════════════════════════════
# Intake Declaration Schema
# ═══════════════════════════════════════════════════════════════════════════

class AgentIntake(BaseModel):
    """What an agent declares it can handle."""
    categories: list[str] = Field(default_factory=list)
    negative_categories: list[str] = Field(default_factory=list)
    source_types: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    systems: list[str] = Field(default_factory=list)
    priority_range: list[str] = Field(
        default_factory=lambda: ["low", "normal", "high", "critical"]
    )
    description: str = ""
    max_concurrent: int = 10
    sla_seconds: int = 300
    phi_allowed: bool = False
    department_scope: list[str] = Field(default_factory=list)
    facility_scope: list[str] = Field(default_factory=list)

    def validate_no_overlap(self) -> list[str]:
        """Check that negative_categories don't overlap with categories."""
        errors = []
        for neg in self.negative_categories:
            for cat in self.categories:
                if cat.startswith(neg) or neg.startswith(cat):
                    errors.append(
                        f"negative_category '{neg}' overlaps with category '{cat}'"
                    )
        return errors


# ═══════════════════════════════════════════════════════════════════════════
# Scoring Data Structures
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ScoredAgent:
    agent_id: str
    score: float
    dimension_scores: dict[str, float] = field(default_factory=dict)
    excluded_by: str | None = None
    cold_start: bool = False
    selected: bool = False
    dispatch_role: str = ""  # "primary", "co_primary", "cc"
    categories: list[str] = field(default_factory=list)


class RoutingConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNROUTABLE = "unroutable"


@dataclass
class RoutingDecision:
    primary: str | None = None
    cc: list[str] = field(default_factory=list)
    confidence: str = "unroutable"
    unroutable: bool = True
    scores: list[ScoredAgent] = field(default_factory=list)
    policies_applied: list[str] = field(default_factory=list)
    shadow_only: bool = False


# ═══════════════════════════════════════════════════════════════════════════
# Default Scoring Weights
# ═══════════════════════════════════════════════════════════════════════════

DEFAULT_WEIGHTS = {
    "category": 0.30,
    "source_type": 0.25,
    "keyword": 0.20,
    "system": 0.15,
    "priority": 0.10,
}

# Multi-dispatch category pairs
MULTI_DISPATCH_CATEGORY_PAIRS = {
    ("security", "incident"): "co_primary",
    ("incident", "security"): "co_primary",
    ("compliance", "clinical"): "cc_only",
    ("clinical", "compliance"): "cc_only",
    ("hr", "compliance"): "cc_only",
    ("compliance", "hr"): "cc_only",
}

# Confidence thresholds
SCORE_THRESHOLD_HIGH = 0.65
SCORE_THRESHOLD_MEDIUM = 0.40
SCORE_THRESHOLD_LOW = 0.20

# Multi-dispatch triggers
MULTI_DISPATCH_MIN_SCORE = 0.55
MULTI_DISPATCH_MAX_DIFF = 0.15


# ═══════════════════════════════════════════════════════════════════════════
# Stop Words for keyword tokenization
# ═══════════════════════════════════════════════════════════════════════════

_STOP_WORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "shall", "can", "this", "that",
    "these", "those", "it", "its", "not", "no", "nor", "so", "if", "then",
    "than", "too", "very", "just", "about", "also", "into", "over",
})


# ═══════════════════════════════════════════════════════════════════════════
# Dimension Scoring Functions
# ═══════════════════════════════════════════════════════════════════════════

def category_match_score(agent_categories: list[str], envelope_category: str) -> float:
    """Hierarchical category match. Dot-notation hierarchy."""
    if not agent_categories or not envelope_category:
        return 0.0

    best = 0.0
    env_parts = envelope_category.split(".")

    for agent_cat in agent_categories:
        ag_parts = agent_cat.split(".")

        if ag_parts == env_parts:
            best = max(best, 1.0)
        elif env_parts[: len(ag_parts)] == ag_parts:
            # Agent is parent of envelope category
            depth_ratio = len(ag_parts) / len(env_parts)
            best = max(best, 0.5 + 0.3 * depth_ratio)
        elif ag_parts[: len(env_parts)] == env_parts:
            # Agent is child (specialized), envelope is broader
            best = max(best, 0.4)
        else:
            # Check common ancestor
            common = 0
            for a, e in zip(ag_parts, env_parts):
                if a == e:
                    common += 1
                else:
                    break
            if common > 0:
                best = max(best, 0.1 * common)

    return round(best, 3)


def source_type_score(agent_source_types: list[str], envelope_source_type: str) -> float:
    """Exact match on source type."""
    if not agent_source_types:
        return 0.3  # Neutral
    if envelope_source_type in agent_source_types:
        return 1.0
    return 0.0


def _tokenize_significant(text: str) -> set[str]:
    """Extract significant words from text (>3 chars, not stop words)."""
    if not text:
        return set()
    words = re.findall(r"[a-zA-Z0-9_-]{4,}", text.lower())
    return {w for w in words if w not in _STOP_WORDS}


def keyword_score(
    agent_keywords: list[str],
    envelope_tags: list[str],
    envelope_text: str,
) -> float:
    """Jaccard similarity between agent keywords and envelope content."""
    if not agent_keywords:
        return 0.2  # Neutral

    envelope_words = {t.lower() for t in envelope_tags}
    envelope_words.update(_tokenize_significant(envelope_text))

    if not envelope_words:
        return 0.0

    agent_set = {kw.lower() for kw in agent_keywords}
    intersection = agent_set & envelope_words
    union = agent_set | envelope_words

    jaccard = len(intersection) / len(union) if union else 0.0

    # Bonus for high-value terms (CVE IDs, long specific terms)
    high_value = {t for t in intersection if t.startswith("cve-") or len(t) > 8}
    bonus = min(0.2, len(high_value) * 0.05)

    return min(1.0, round(jaccard + bonus, 3))


def system_score(agent_systems: list[str], envelope_system_tags: list[str]) -> float:
    """Match named systems."""
    if not agent_systems or not envelope_system_tags:
        return 0.2  # Neutral

    agent_lower = {s.lower() for s in agent_systems}
    env_lower = {s.lower() for s in envelope_system_tags}
    matches = agent_lower & env_lower

    if not matches:
        return 0.0
    return min(1.0, round(len(matches) * 0.4, 3))


def priority_score(agent_priority_range: list[str], envelope_priority: str) -> float:
    """Check if agent handles this priority level."""
    if not agent_priority_range:
        return 0.5  # Neutral
    p = (envelope_priority or "normal").lower()
    if p in [pr.lower() for pr in agent_priority_range]:
        return 1.0
    return 0.0


# ═══════════════════════════════════════════════════════════════════════════
# Historical Multiplier + Load Factor
# ═══════════════════════════════════════════════════════════════════════════

# In-memory caches (populated on startup, updated by background tasks)
_stats_cache: dict[str, dict[str, Any]] = {}  # "agent:category" -> {success_rate, sample_count}
_load_cache: dict[str, dict[str, int]] = {}   # agent_id -> {in_flight, max_concurrent}
_load_lock = asyncio.Lock()


def historical_multiplier(agent_id: str, category: str) -> float:
    """Returns multiplier in [0.70, 1.30]. Cold start = 1.0."""
    key = f"{agent_id}:{category}"
    stats = _stats_cache.get(key)
    if not stats or stats.get("sample_count", 0) < 10:
        return 1.0
    success_rate = stats.get("success_rate", 0.5)
    return round(0.70 + (success_rate * 0.60), 3)


def load_multiplier(agent_id: str) -> float:
    """Penalizes overloaded agents. 1.0 at ≤50%, 0.0 at 100%."""
    info = _load_cache.get(agent_id, {})
    in_flight = info.get("in_flight", 0)
    max_concurrent = max(info.get("max_concurrent", 10), 1)
    utilization = in_flight / max_concurrent

    if utilization <= 0.5:
        return 1.0
    elif utilization >= 1.0:
        return 0.0
    else:
        return round(2.0 * (1.0 - utilization), 3)


async def increment_load(agent_id: str) -> None:
    async with _load_lock:
        if agent_id not in _load_cache:
            _load_cache[agent_id] = {"in_flight": 0, "max_concurrent": 10}
        _load_cache[agent_id]["in_flight"] = (
            _load_cache[agent_id].get("in_flight", 0) + 1
        )


async def decrement_load(agent_id: str) -> None:
    async with _load_lock:
        if agent_id in _load_cache:
            _load_cache[agent_id]["in_flight"] = max(
                0, _load_cache[agent_id].get("in_flight", 0) - 1
            )


def set_agent_max_concurrent(agent_id: str, max_concurrent: int) -> None:
    if agent_id not in _load_cache:
        _load_cache[agent_id] = {"in_flight": 0, "max_concurrent": max_concurrent}
    else:
        _load_cache[agent_id]["max_concurrent"] = max_concurrent


def update_stats_cache(agent_id: str, category: str, success_rate: float, sample_count: int) -> None:
    """Update the in-memory stats cache (called by weight updater)."""
    _stats_cache[f"{agent_id}:{category}"] = {
        "success_rate": success_rate,
        "sample_count": sample_count,
    }


def get_load_snapshot() -> dict[str, dict[str, int]]:
    """Return a copy of the current load cache."""
    return dict(_load_cache)


# ═══════════════════════════════════════════════════════════════════════════
# Overlap Detection
# ═══════════════════════════════════════════════════════════════════════════

def compute_intake_overlap(intake_a: AgentIntake, intake_b: AgentIntake) -> float:
    """Compute overlap score between two intake declarations. Returns 0.0-1.0."""
    # Category overlap (weight 0.4)
    cats_a = set(intake_a.categories)
    cats_b = set(intake_b.categories)
    if cats_a or cats_b:
        cat_overlap = len(cats_a & cats_b) / max(len(cats_a | cats_b), 1)
    else:
        cat_overlap = 0.0

    # Source type overlap (weight 0.3)
    src_a = set(intake_a.source_types)
    src_b = set(intake_b.source_types)
    if src_a or src_b:
        src_overlap = len(src_a & src_b) / max(len(src_a | src_b), 1)
    else:
        src_overlap = 0.0

    # Keyword Jaccard (weight 0.3)
    kw_a = {k.lower() for k in intake_a.keywords}
    kw_b = {k.lower() for k in intake_b.keywords}
    if kw_a or kw_b:
        kw_overlap = len(kw_a & kw_b) / max(len(kw_a | kw_b), 1)
    else:
        kw_overlap = 0.0

    return round(cat_overlap * 0.4 + src_overlap * 0.3 + kw_overlap * 0.3, 3)


def check_intake_overlaps(
    agent_id: str,
    intake: AgentIntake,
    all_agents: list[tuple[str, AgentIntake]],
) -> tuple[list[str], list[str]]:
    """Check overlap against all other agents. Returns (warnings, errors)."""
    warnings = []
    errors = []

    for other_id, other_intake in all_agents:
        if other_id == agent_id:
            continue
        overlap = compute_intake_overlap(intake, other_intake)
        if overlap >= 0.90:
            errors.append(
                f"Critical overlap ({overlap:.2f}) with agent '{other_id}' — "
                f"registration blocked pending admin review"
            )
        elif overlap >= 0.70:
            warnings.append(
                f"High overlap ({overlap:.2f}) with agent '{other_id}'"
            )

    return warnings, errors


# ═══════════════════════════════════════════════════════════════════════════
# Core Scoring Engine
# ═══════════════════════════════════════════════════════════════════════════

def _extract_envelope_signals(envelope: Envelope) -> dict[str, Any]:
    """Extract all scoring-relevant signals from an envelope."""
    classification = envelope.payload.data.get("_classification", {})
    env_category = (
        classification.get("category")
        or envelope.routing_hints.category
        or ""
    )
    env_tags = list(envelope.routing_hints.tags or [])
    env_text = envelope.payload.text or ""
    env_priority = envelope.metadata.priority or "normal"

    # System tags: look in classification and tags
    env_systems = classification.get("systems", [])
    if not env_systems:
        # Fallback: treat tags that look like system names
        env_systems = [t for t in env_tags if not t.startswith("cve-") and len(t) > 3]

    return {
        "category": env_category,
        "source_type": envelope.source_type,
        "tags": env_tags,
        "text": env_text,
        "priority": env_priority,
        "systems": env_systems,
    }


def score_agent(
    intake: AgentIntake,
    agent_id: str,
    signals: dict[str, Any],
    weights: dict[str, float] | None = None,
) -> ScoredAgent:
    """Score a single agent against envelope signals."""
    w = weights or DEFAULT_WEIGHTS

    # Negative category check (hard veto)
    env_category = signals["category"]
    for neg in intake.negative_categories:
        if env_category and (env_category.startswith(neg) or neg.startswith(env_category)):
            return ScoredAgent(
                agent_id=agent_id,
                score=0.0,
                excluded_by="negative_category",
                dimension_scores={},
                categories=list(intake.categories),
            )

    # Compute dimensions
    cat = category_match_score(intake.categories, env_category)
    src = source_type_score(intake.source_types, signals["source_type"])
    kw = keyword_score(intake.keywords, signals["tags"], signals["text"])
    sys = system_score(intake.systems, signals["systems"])
    pri = priority_score(intake.priority_range, signals["priority"])

    base = (
        cat * w["category"]
        + src * w["source_type"]
        + kw * w["keyword"]
        + sys * w["system"]
        + pri * w["priority"]
    )

    hist = historical_multiplier(agent_id, env_category)
    load = load_multiplier(agent_id)
    final_score = round(base * hist * load, 4)

    sample_count = _stats_cache.get(
        f"{agent_id}:{env_category}", {}
    ).get("sample_count", 0)

    return ScoredAgent(
        agent_id=agent_id,
        score=final_score,
        dimension_scores={
            "category": cat,
            "source_type": src,
            "keyword": kw,
            "system": sys,
            "priority": pri,
            "historical_multiplier": hist,
            "load_multiplier": load,
            "base_score": round(base, 4),
        },
        cold_start=(sample_count < 10),
        categories=list(intake.categories),
    )


def score_all_agents(
    envelope: Envelope,
    agents_with_intake: list[tuple[str, AgentIntake]],
    weights: dict[str, float] | None = None,
) -> list[ScoredAgent]:
    """Score all agents against an envelope. Returns sorted list (descending)."""
    signals = _extract_envelope_signals(envelope)
    scores = []

    for agent_id, intake in agents_with_intake:
        scored = score_agent(intake, agent_id, signals, weights)
        scores.append(scored)

    return sorted(scores, key=lambda s: s.score, reverse=True)


def make_routing_decision(scores: list[ScoredAgent]) -> RoutingDecision:
    """Given sorted scores, produce a routing decision."""
    if not scores or scores[0].score < SCORE_THRESHOLD_LOW:
        return RoutingDecision(
            unroutable=True,
            confidence="unroutable",
            scores=scores,
        )

    top = scores[0]
    top.selected = True
    top.dispatch_role = "primary"

    # Determine confidence
    if top.score >= SCORE_THRESHOLD_HIGH:
        confidence = "high"
    elif top.score >= SCORE_THRESHOLD_MEDIUM:
        confidence = "medium"
    else:
        confidence = "low"

    cc_agents: list[str] = []

    # Check multi-dispatch
    if len(scores) >= 2:
        second = scores[1]
        if (
            top.score >= MULTI_DISPATCH_MIN_SCORE
            and second.score >= MULTI_DISPATCH_MIN_SCORE
            and (top.score - second.score) <= MULTI_DISPATCH_MAX_DIFF
        ):
            # Check category pair
            top_cat = _primary_category(top)
            second_cat = _primary_category(second)
            pair_key = (top_cat, second_cat)
            dispatch_type = MULTI_DISPATCH_CATEGORY_PAIRS.get(pair_key)

            if dispatch_type == "co_primary":
                second.selected = True
                second.dispatch_role = "co_primary"
                cc_agents.append(second.agent_id)
            elif dispatch_type == "cc_only":
                second.selected = True
                second.dispatch_role = "cc"
                cc_agents.append(second.agent_id)

    return RoutingDecision(
        primary=top.agent_id,
        cc=cc_agents,
        confidence=confidence,
        unroutable=False,
        scores=scores,
    )


def _primary_category(scored: ScoredAgent) -> str:
    """Extract the primary category from a scored agent's intake declaration."""
    if scored.categories:
        return scored.categories[0]
    return ""


# ═══════════════════════════════════════════════════════════════════════════
# Intelligent Route Entry Point
# ═══════════════════════════════════════════════════════════════════════════

async def route_intelligent(
    envelope: Envelope,
    db: AsyncSession,
    weights: dict[str, float] | None = None,
) -> RoutingDecision:
    """Score envelope against all agents with intake declarations.
    
    This is the main entry point for intelligent routing. Returns a 
    RoutingDecision which the caller can use to dispatch or fall back 
    to rule-based routing.
    """
    # Fetch all agents with intake declarations
    result = await db.execute(select(Agent))
    all_agents = list(result.scalars().all())

    agents_with_intake: list[tuple[str, AgentIntake]] = []
    for agent in all_agents:
        intake_data = getattr(agent, "intake", None)
        if intake_data and isinstance(intake_data, dict):
            try:
                intake = AgentIntake(**intake_data)
                agents_with_intake.append((agent.agent_id, intake))
            except Exception as e:
                logger.warning(f"Invalid intake for agent {agent.agent_id}: {e}")

    if not agents_with_intake:
        return RoutingDecision(unroutable=True, confidence="unroutable", scores=[])

    scores = score_all_agents(envelope, agents_with_intake, weights)
    decision = make_routing_decision(scores)
    return decision


# ═══════════════════════════════════════════════════════════════════════════
# API Schemas (for endpoint request/response)
# ═══════════════════════════════════════════════════════════════════════════

class IntelligentRouteRequest(BaseModel):
    """Request body for POST /api/route/intelligent"""
    envelope: dict[str, Any]
    weights: dict[str, float] | None = None


class ScoredAgentResponse(BaseModel):
    agent_id: str
    score: float
    dimension_scores: dict[str, float]
    excluded_by: str | None = None
    cold_start: bool = False
    selected: bool = False
    dispatch_role: str = ""


class RoutingDecisionResponse(BaseModel):
    primary: str | None = None
    cc: list[str] = Field(default_factory=list)
    confidence: str = "unroutable"
    unroutable: bool = True
    scores: list[ScoredAgentResponse] = Field(default_factory=list)
    policies_applied: list[str] = Field(default_factory=list)


class IntakeUpdateRequest(BaseModel):
    intake: AgentIntake


class IntakeResponse(BaseModel):
    agent_id: str
    intake: AgentIntake | None = None
    intake_warnings: list[str] = Field(default_factory=list)
    intake_errors: list[str] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
# FastAPI Router
# ═══════════════════════════════════════════════════════════════════════════

from fastapi import APIRouter, Depends, HTTPException
from trellis.database import get_db
from trellis.api import require_management_auth

intelligent_router = APIRouter(tags=["intelligent-routing"], dependencies=[Depends(require_management_auth)])


@intelligent_router.post("/route/intelligent", response_model=RoutingDecisionResponse)
async def score_envelope_endpoint(
    body: IntelligentRouteRequest,
    db: AsyncSession = Depends(get_db),
):
    """Score an envelope against all agents with intake declarations."""
    try:
        envelope = Envelope(**body.envelope)
    except Exception as e:
        raise HTTPException(400, f"Invalid envelope: {e}")

    # Run classification if available
    try:
        from trellis.classification import classify_envelope
        envelope = classify_envelope(envelope)
    except Exception:
        pass  # Classification is optional for scoring

    decision = await route_intelligent(envelope, db, body.weights)

    return RoutingDecisionResponse(
        primary=decision.primary,
        cc=decision.cc,
        confidence=decision.confidence,
        unroutable=decision.unroutable,
        scores=[
            ScoredAgentResponse(
                agent_id=s.agent_id,
                score=s.score,
                dimension_scores=s.dimension_scores,
                excluded_by=s.excluded_by,
                cold_start=s.cold_start,
                selected=s.selected,
                dispatch_role=s.dispatch_role,
            )
            for s in decision.scores
        ],
        policies_applied=decision.policies_applied,
    )


@intelligent_router.get("/agents/{agent_id}/intake", response_model=IntakeResponse)
async def get_agent_intake(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
):
    """View an agent's declared intake."""
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, f"Agent '{agent_id}' not found")

    intake_data = getattr(agent, "intake", None)
    intake = None
    if intake_data and isinstance(intake_data, dict):
        try:
            intake = AgentIntake(**intake_data)
        except Exception:
            pass

    return IntakeResponse(agent_id=agent_id, intake=intake)


@intelligent_router.put("/agents/{agent_id}/intake", response_model=IntakeResponse)
async def update_agent_intake(
    agent_id: str,
    body: IntakeUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update an agent's intake declaration."""
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, f"Agent '{agent_id}' not found")

    # Validate no internal overlaps
    validation_errors = body.intake.validate_no_overlap()
    if validation_errors:
        raise HTTPException(422, detail=validation_errors)

    # Check overlap against other agents
    result = await db.execute(select(Agent).where(Agent.agent_id != agent_id))
    other_agents = result.scalars().all()

    other_intakes: list[tuple[str, AgentIntake]] = []
    for other in other_agents:
        other_data = getattr(other, "intake", None)
        if other_data and isinstance(other_data, dict):
            try:
                other_intakes.append((other.agent_id, AgentIntake(**other_data)))
            except Exception:
                pass

    warnings, errors = check_intake_overlaps(agent_id, body.intake, other_intakes)

    if errors:
        raise HTTPException(
            409,
            detail={
                "message": "Intake registration blocked due to critical overlap",
                "errors": errors,
                "warnings": warnings,
            },
        )

    # Store intake as JSON on agent
    agent.intake = body.intake.model_dump()  # type: ignore[attr-defined]

    # Update load cache
    set_agent_max_concurrent(agent_id, body.intake.max_concurrent)

    await db.commit()
    await db.refresh(agent)

    return IntakeResponse(
        agent_id=agent_id,
        intake=body.intake,
        intake_warnings=warnings,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Feedback Collection & Weight Adaptation
# ═══════════════════════════════════════════════════════════════════════════

# EMA smoothing factor for historical multiplier updates
EMA_ALPHA = 0.1

# Adaptive dimension weights — machinery in place, starts with fixed weights
_adaptive_weights: dict[str, float] = dict(DEFAULT_WEIGHTS)
_dimension_success_counts: dict[str, dict[str, int]] = {}  # dimension -> {hits, total}


class FeedbackRequest(BaseModel):
    envelope_id: str
    agent_id: str
    outcome: str = Field(..., pattern="^(success|failure|partial)$")
    response_time_ms: int | None = None
    notes: str | None = None


class FeedbackResponse(BaseModel):
    id: int
    envelope_id: str
    agent_id: str
    outcome: str
    ema_multiplier: float
    message: str


def _outcome_to_score(outcome: str) -> float:
    """Convert outcome string to numeric score for EMA."""
    return {"success": 1.0, "partial": 0.5, "failure": 0.0}.get(outcome, 0.5)


def update_ema(agent_id: str, category: str, outcome: str) -> float:
    """Update the EMA-based historical multiplier for an agent+category.
    
    Returns the new success_rate after update.
    """
    key = f"{agent_id}:{category}"
    stats = _stats_cache.get(key, {"success_rate": 0.5, "sample_count": 0})
    
    outcome_val = _outcome_to_score(outcome)
    old_rate = stats.get("success_rate", 0.5)
    count = stats.get("sample_count", 0)
    
    if count == 0:
        new_rate = outcome_val
    else:
        new_rate = old_rate * (1 - EMA_ALPHA) + outcome_val * EMA_ALPHA
    
    new_rate = round(new_rate, 4)
    update_stats_cache(agent_id, category, new_rate, count + 1)
    return new_rate


def record_dimension_success(dimension_scores: dict[str, float], outcome: str) -> None:
    """Track which dimensions correlated with successful outcomes.
    
    This is the machinery for adaptive weights — not yet used for
    actual weight updates, but collects the data needed to do so.
    """
    is_success = outcome == "success"
    score_threshold = 0.5
    
    for dim in DEFAULT_WEIGHTS:
        if dim not in _dimension_success_counts:
            _dimension_success_counts[dim] = {"hits": 0, "total": 0}
        
        dim_score = dimension_scores.get(dim, 0.0)
        if dim_score >= score_threshold:
            _dimension_success_counts[dim]["total"] += 1
            if is_success:
                _dimension_success_counts[dim]["hits"] += 1


def get_adaptive_weights() -> dict[str, float]:
    """Return current adaptive weights (currently fixed, machinery ready)."""
    return dict(_adaptive_weights)


def compute_adaptive_weights() -> dict[str, float]:
    """Compute new weights based on dimension success correlation.
    
    Call this periodically to update weights. Returns new weights but
    does NOT apply them automatically — caller decides.
    """
    min_samples = 50
    new_weights = dict(DEFAULT_WEIGHTS)
    
    adjustable = []
    for dim in DEFAULT_WEIGHTS:
        counts = _dimension_success_counts.get(dim, {"hits": 0, "total": 0})
        if counts["total"] >= min_samples:
            hit_rate = counts["hits"] / counts["total"]
            adjustable.append((dim, hit_rate))
    
    if not adjustable:
        return new_weights
    
    # Scale weights proportional to hit rates, keeping sum = 1.0
    total_hit = sum(hr for _, hr in adjustable)
    if total_hit > 0:
        for dim, hit_rate in adjustable:
            # Blend: 70% original weight + 30% hit-rate-proportional
            proportional = hit_rate / total_hit * sum(DEFAULT_WEIGHTS[d] for d, _ in adjustable)
            new_weights[dim] = round(0.7 * DEFAULT_WEIGHTS[dim] + 0.3 * proportional, 4)
    
    # Normalize to sum=1
    total = sum(new_weights.values())
    if total > 0:
        new_weights = {k: round(v / total, 4) for k, v in new_weights.items()}
    
    return new_weights


@intelligent_router.post("/route/feedback", response_model=FeedbackResponse)
async def submit_routing_feedback(
    body: FeedbackRequest,
    db: AsyncSession = Depends(get_db),
):
    """Submit feedback on a routing decision to update agent scoring."""
    from sqlalchemy import func as sa_func
    
    # Look up the envelope to get category context
    envelope_log = (
        await db.execute(
            select(EnvelopeLog).where(EnvelopeLog.envelope_id == body.envelope_id).limit(1)
        )
    ).scalar_one_or_none()
    
    category = ""
    dimension_scores: dict[str, float] = {}
    if envelope_log and envelope_log.envelope_data:
        env_data = envelope_log.envelope_data
        classification = env_data.get("payload", {}).get("data", {}).get("_classification", {})
        category = classification.get("category", "")
        # If dispatch_result has scores, grab dimension_scores
        if envelope_log.dispatch_result and isinstance(envelope_log.dispatch_result, dict):
            dimension_scores = envelope_log.dispatch_result.get("dimension_scores", {})
    
    # Store feedback
    feedback = RoutingFeedback(
        envelope_id=body.envelope_id,
        agent_id=body.agent_id,
        outcome=body.outcome,
        response_time_ms=body.response_time_ms,
        notes=body.notes,
        category=category or None,
    )
    db.add(feedback)
    await db.flush()
    
    # Update EMA
    new_rate = update_ema(body.agent_id, category, body.outcome)
    new_mult = historical_multiplier(body.agent_id, category)
    
    # Track dimension success correlation
    if dimension_scores:
        record_dimension_success(dimension_scores, body.outcome)
    
    await db.commit()
    
    return FeedbackResponse(
        id=feedback.id,
        envelope_id=body.envelope_id,
        agent_id=body.agent_id,
        outcome=body.outcome,
        ema_multiplier=new_mult,
        message=f"Feedback recorded. EMA success_rate={new_rate}, multiplier={new_mult}",
    )


# ═══════════════════════════════════════════════════════════════════════════
# Shadow Mode
# ═══════════════════════════════════════════════════════════════════════════

class ShadowResult(BaseModel):
    """Side-by-side comparison of rule-based vs intelligent routing."""
    rule_based: dict[str, Any] = Field(default_factory=dict)
    intelligent: RoutingDecisionResponse
    agreed: bool
    comparison_id: int | None = None


class ShadowReportResponse(BaseModel):
    total_comparisons: int
    agreement_rate: float
    disagreements: int
    confidence_distribution: dict[str, int]
    recent_disagreements: list[dict[str, Any]]


@intelligent_router.post("/route/intelligent/shadow", response_model=ShadowResult)
async def shadow_route_endpoint(
    body: IntelligentRouteRequest,
    db: AsyncSession = Depends(get_db),
):
    """Run both rule-based and intelligent routing, return side-by-side comparison."""
    try:
        envelope = Envelope(**body.envelope)
    except Exception as e:
        raise HTTPException(400, f"Invalid envelope: {e}")

    # Classify if available
    try:
        from trellis.classification import classify_envelope
        envelope = classify_envelope(envelope)
    except Exception:
        pass

    # Run intelligent routing
    decision = await route_intelligent(envelope, db, body.weights)

    # Run rule-based routing
    rule_result: dict[str, Any] = {}
    try:
        from trellis.router import route_envelope
        rule_result = await route_envelope(envelope, db)
    except Exception as e:
        rule_result = {"error": str(e), "target_agent_id": None}

    rule_agent = rule_result.get("target_agent_id")
    intelligent_agent = decision.primary
    agreed = rule_agent == intelligent_agent

    intelligent_response = RoutingDecisionResponse(
        primary=decision.primary,
        cc=decision.cc,
        confidence=decision.confidence,
        unroutable=decision.unroutable,
        scores=[
            ScoredAgentResponse(
                agent_id=s.agent_id,
                score=s.score,
                dimension_scores=s.dimension_scores,
                excluded_by=s.excluded_by,
                cold_start=s.cold_start,
                selected=s.selected,
                dispatch_role=s.dispatch_role,
            )
            for s in decision.scores
        ],
        policies_applied=decision.policies_applied,
    )

    # Log comparison
    comparison = ShadowComparison(
        envelope_id=envelope.envelope_id,
        rule_based_agent=rule_agent,
        intelligent_agent=intelligent_agent,
        intelligent_confidence=decision.confidence,
        intelligent_score=decision.scores[0].score if decision.scores else None,
        agreed=agreed,
        scores_snapshot={
            "scores": [
                {"agent_id": s.agent_id, "score": s.score, "dimensions": s.dimension_scores}
                for s in decision.scores[:5]  # top 5 only
            ]
        },
    )
    db.add(comparison)
    await db.flush()
    comparison_id = comparison.id
    await db.commit()

    return ShadowResult(
        rule_based=rule_result,
        intelligent=intelligent_response,
        agreed=agreed,
        comparison_id=comparison_id,
    )


@intelligent_router.get("/route/shadow/report", response_model=ShadowReportResponse)
async def shadow_report_endpoint(
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
):
    """Summary report of shadow mode comparisons."""
    from sqlalchemy import func as sa_func

    # Total comparisons
    total_q = await db.execute(select(sa_func.count(ShadowComparison.id)))
    total = total_q.scalar() or 0

    # Agreement count
    agreed_q = await db.execute(
        select(sa_func.count(ShadowComparison.id)).where(ShadowComparison.agreed == True)
    )
    agreed_count = agreed_q.scalar() or 0

    agreement_rate = round(agreed_count / total, 4) if total > 0 else 0.0
    disagreements = total - agreed_count

    # Confidence distribution
    conf_q = await db.execute(
        select(ShadowComparison.intelligent_confidence, sa_func.count(ShadowComparison.id))
        .group_by(ShadowComparison.intelligent_confidence)
    )
    confidence_distribution = {row[0]: row[1] for row in conf_q.all()}

    # Recent disagreements
    disagree_q = await db.execute(
        select(ShadowComparison)
        .where(ShadowComparison.agreed == False)
        .order_by(ShadowComparison.timestamp.desc())
        .limit(limit)
    )
    recent = [
        {
            "id": c.id,
            "envelope_id": c.envelope_id,
            "rule_based_agent": c.rule_based_agent,
            "intelligent_agent": c.intelligent_agent,
            "intelligent_confidence": c.intelligent_confidence,
            "intelligent_score": c.intelligent_score,
            "timestamp": c.timestamp.isoformat() if c.timestamp else None,
        }
        for c in disagree_q.scalars().all()
    ]

    return ShadowReportResponse(
        total_comparisons=total,
        agreement_rate=agreement_rate,
        disagreements=disagreements,
        confidence_distribution=confidence_distribution,
        recent_disagreements=recent,
    )
