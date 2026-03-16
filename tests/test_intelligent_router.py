"""Tests for intelligent routing — scored matching with agent intake declarations."""

import pytest

from trellis.intelligent_router import (
    AgentIntake,
    ScoredAgent,
    category_match_score,
    source_type_score,
    keyword_score,
    system_score,
    priority_score,
    score_agent,
    score_all_agents,
    make_routing_decision,
    compute_intake_overlap,
    check_intake_overlaps,
    historical_multiplier,
    load_multiplier,
    update_stats_cache,
    set_agent_max_concurrent,
    increment_load,
    decrement_load,
    _load_cache,
    _stats_cache,
    _tokenize_significant,
    _dimension_success_counts,
    DEFAULT_WEIGHTS,
    update_ema,
    record_dimension_success,
    compute_adaptive_weights,
    get_adaptive_weights,
    _outcome_to_score,
    FeedbackRequest,
)
from trellis.schemas import Envelope


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_caches():
    """Reset in-memory caches between tests."""
    _stats_cache.clear()
    _load_cache.clear()
    _dimension_success_counts.clear()
    yield
    _stats_cache.clear()
    _load_cache.clear()
    _dimension_success_counts.clear()


def _make_envelope(
    category: str = "",
    source_type: str = "api",
    text: str = "",
    tags: list[str] | None = None,
    priority: str = "normal",
    systems: list[str] | None = None,
) -> Envelope:
    data = {}
    if category or systems:
        classification = {}
        if category:
            classification["category"] = category
        if systems:
            classification["systems"] = systems
        data["_classification"] = classification

    return Envelope(
        source_type=source_type,
        payload={"text": text, "data": data},
        routing_hints={"category": category, "tags": tags or []},
        metadata={"priority": priority},
    )


def _security_intake() -> AgentIntake:
    return AgentIntake(
        categories=["security", "security.vulnerability"],
        negative_categories=["clinical", "hr"],
        source_types=["nvd", "cisa_kev", "crowdstrike"],
        keywords=["cve", "exploit", "breach", "ransomware", "malware", "patch"],
        systems=["CrowdStrike", "Sentinel"],
        priority_range=["high", "critical"],
        max_concurrent=5,
    )


def _it_helpdesk_intake() -> AgentIntake:
    return AgentIntake(
        categories=["incident", "incident.infrastructure"],
        source_types=["ivanti", "servicenow", "teams"],
        keywords=["outage", "printer", "vpn", "password", "network", "server"],
        systems=["Ivanti", "LogicMonitor"],
        priority_range=["low", "normal", "high"],
        max_concurrent=20,
    )


def _clinical_intake() -> AgentIntake:
    return AgentIntake(
        categories=["clinical", "clinical.adt"],
        negative_categories=["security", "hr"],
        source_types=["epic", "hl7", "fhir"],
        keywords=["patient", "admission", "discharge", "transfer", "medication"],
        systems=["Epic"],
        priority_range=["normal", "high", "critical"],
        phi_allowed=True,
        max_concurrent=50,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Category Match Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestCategoryMatchScore:
    def test_exact_match(self):
        assert category_match_score(["security"], "security") == 1.0

    def test_parent_match(self):
        """Agent declares 'security', envelope is 'security.vulnerability'."""
        score = category_match_score(["security"], "security.vulnerability")
        assert 0.6 <= score <= 0.9  # parent match

    def test_child_match(self):
        """Agent declares 'security.vulnerability', envelope is 'security'."""
        score = category_match_score(["security.vulnerability"], "security")
        assert score == 0.4

    def test_sibling_match(self):
        """Same parent, different leaf."""
        score = category_match_score(["security.vulnerability"], "security.compliance")
        assert 0.05 <= score <= 0.2  # sibling, weak match

    def test_no_match(self):
        assert category_match_score(["hr"], "security") == 0.0

    def test_empty_categories(self):
        assert category_match_score([], "security") == 0.0

    def test_empty_envelope_category(self):
        assert category_match_score(["security"], "") == 0.0

    def test_multiple_agent_categories_best_wins(self):
        score = category_match_score(
            ["hr", "security", "security.vulnerability"], "security"
        )
        assert score == 1.0  # exact match on "security"


# ═══════════════════════════════════════════════════════════════════════════
# Source Type Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestSourceTypeScore:
    def test_exact_match(self):
        assert source_type_score(["nvd", "cisa_kev"], "nvd") == 1.0

    def test_no_match(self):
        assert source_type_score(["nvd", "cisa_kev"], "teams") == 0.0

    def test_empty_agent_sources_neutral(self):
        assert source_type_score([], "nvd") == 0.3


# ═══════════════════════════════════════════════════════════════════════════
# Keyword Score Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestKeywordScore:
    def test_matching_keywords(self):
        score = keyword_score(
            ["exploit", "breach", "ransomware"],
            ["exploit", "lateral-movement"],
            "detected ransomware activity",
        )
        assert score > 0.0

    def test_no_matching_keywords(self):
        score = keyword_score(
            ["printer", "vpn", "password"],
            ["exploit", "ransomware"],
            "detected breach",
        )
        assert score == 0.0 or score < 0.1

    def test_empty_agent_keywords_neutral(self):
        assert keyword_score([], ["exploit"], "text") == 0.2

    def test_cve_bonus(self):
        """CVE IDs should get a bonus."""
        score_with_cve = keyword_score(
            ["cve-2025-1234", "exploit"],
            ["cve-2025-1234"],
            "",
        )
        score_without = keyword_score(
            ["exploit", "test"],
            ["test"],
            "",
        )
        assert score_with_cve >= score_without


# ═══════════════════════════════════════════════════════════════════════════
# System Score Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestSystemScore:
    def test_matching_systems(self):
        score = system_score(["CrowdStrike", "Sentinel"], ["crowdstrike", "epic"])
        assert score >= 0.4

    def test_no_match(self):
        score = system_score(["Ivanti"], ["epic", "crowdstrike"])
        assert score == 0.0

    def test_empty_neutral(self):
        assert system_score([], ["epic"]) == 0.2
        assert system_score(["Epic"], []) == 0.2


# ═══════════════════════════════════════════════════════════════════════════
# Priority Score Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestPriorityScore:
    def test_in_range(self):
        assert priority_score(["high", "critical"], "critical") == 1.0

    def test_out_of_range(self):
        assert priority_score(["high", "critical"], "low") == 0.0

    def test_empty_neutral(self):
        assert priority_score([], "normal") == 0.5


# ═══════════════════════════════════════════════════════════════════════════
# Historical Multiplier Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestHistoricalMultiplier:
    def test_cold_start_neutral(self):
        assert historical_multiplier("agent-1", "security") == 1.0

    def test_insufficient_samples(self):
        update_stats_cache("agent-1", "security", 0.9, 5)
        assert historical_multiplier("agent-1", "security") == 1.0

    def test_good_history_boost(self):
        update_stats_cache("agent-1", "security", 0.95, 50)
        mult = historical_multiplier("agent-1", "security")
        assert mult > 1.0
        assert mult <= 1.30

    def test_bad_history_penalty(self):
        update_stats_cache("agent-1", "security", 0.1, 50)
        mult = historical_multiplier("agent-1", "security")
        assert mult < 1.0
        assert mult >= 0.70


# ═══════════════════════════════════════════════════════════════════════════
# Load Multiplier Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestLoadMultiplier:
    def test_low_load_no_penalty(self):
        set_agent_max_concurrent("agent-1", 10)
        _load_cache["agent-1"]["in_flight"] = 3
        assert load_multiplier("agent-1") == 1.0

    def test_high_load_penalty(self):
        set_agent_max_concurrent("agent-1", 10)
        _load_cache["agent-1"]["in_flight"] = 9
        mult = load_multiplier("agent-1")
        assert 0.0 < mult < 1.0

    def test_full_load_zero(self):
        set_agent_max_concurrent("agent-1", 10)
        _load_cache["agent-1"]["in_flight"] = 10
        assert load_multiplier("agent-1") == 0.0

    def test_unknown_agent_no_penalty(self):
        assert load_multiplier("unknown-agent") == 1.0


@pytest.mark.asyncio
class TestLoadTracking:
    async def test_increment_decrement(self):
        set_agent_max_concurrent("agent-1", 10)
        await increment_load("agent-1")
        assert _load_cache["agent-1"]["in_flight"] == 1
        await decrement_load("agent-1")
        assert _load_cache["agent-1"]["in_flight"] == 0

    async def test_decrement_floor_zero(self):
        set_agent_max_concurrent("agent-1", 10)
        await decrement_load("agent-1")
        assert _load_cache["agent-1"]["in_flight"] == 0


# ═══════════════════════════════════════════════════════════════════════════
# Score Agent Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestScoreAgent:
    def test_score_exact_category_match(self):
        intake = _security_intake()
        _make_envelope(
            category="security",
            source_type="nvd",
            priority="critical",
        )
        signals = {
            "category": "security",
            "source_type": "nvd",
            "tags": [],
            "text": "",
            "priority": "critical",
            "systems": [],
        }
        scored = score_agent(intake, "security-triage", signals)
        assert scored.score > 0.5
        assert scored.dimension_scores["category"] == 1.0

    def test_negative_category_veto(self):
        intake = _security_intake()
        signals = {
            "category": "clinical",
            "source_type": "epic",
            "tags": [],
            "text": "",
            "priority": "normal",
            "systems": [],
        }
        scored = score_agent(intake, "security-triage", signals)
        assert scored.score == 0.0
        assert scored.excluded_by == "negative_category"

    def test_no_intake_not_scored(self):
        """Agents without intake are handled separately (rules fallback)."""
        # This is tested at the score_all_agents level
        pass


# ═══════════════════════════════════════════════════════════════════════════
# Full Pipeline Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestScoreAllAgents:
    def test_security_envelope_ranks_correctly(self):
        agents = [
            ("security-triage", _security_intake()),
            ("it-helpdesk", _it_helpdesk_intake()),
            ("clinical-ops", _clinical_intake()),
        ]
        envelope = _make_envelope(
            category="security",
            source_type="crowdstrike",
            text="CrowdStrike detected lateral movement consistent with ransomware",
            tags=["crowdstrike", "lateral-movement", "cve-2025-1234"],
            priority="critical",
            systems=["crowdstrike"],
        )
        scores = score_all_agents(envelope, agents)
        assert scores[0].agent_id == "security-triage"
        assert scores[0].score > 0.5

    def test_clinical_envelope_ranks_correctly(self):
        agents = [
            ("security-triage", _security_intake()),
            ("it-helpdesk", _it_helpdesk_intake()),
            ("clinical-ops", _clinical_intake()),
        ]
        envelope = _make_envelope(
            category="clinical",
            source_type="epic",
            text="Patient admission ADT event from Epic",
            tags=["epic", "admission", "patient"],
            priority="high",
            systems=["epic"],
        )
        scores = score_all_agents(envelope, agents)
        # Security should be vetoed (negative_category=clinical)
        assert scores[0].agent_id == "clinical-ops"
        security_score = next(s for s in scores if s.agent_id == "security-triage")
        assert security_score.score == 0.0

    def test_empty_agents_list(self):
        envelope = _make_envelope(category="security")
        scores = score_all_agents(envelope, [])
        assert scores == []


# ═══════════════════════════════════════════════════════════════════════════
# Routing Decision Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestMakeRoutingDecision:
    def test_high_confidence_routing(self):
        scores = [
            ScoredAgent(agent_id="agent-a", score=0.85, dimension_scores={}),
            ScoredAgent(agent_id="agent-b", score=0.30, dimension_scores={}),
        ]
        decision = make_routing_decision(scores)
        assert decision.primary == "agent-a"
        assert decision.confidence == "high"
        assert not decision.unroutable

    def test_unroutable_below_threshold(self):
        scores = [
            ScoredAgent(agent_id="agent-a", score=0.15, dimension_scores={}),
        ]
        decision = make_routing_decision(scores)
        assert decision.unroutable
        assert decision.confidence == "unroutable"
        assert decision.primary is None

    def test_empty_scores_unroutable(self):
        decision = make_routing_decision([])
        assert decision.unroutable

    def test_medium_confidence(self):
        scores = [
            ScoredAgent(agent_id="agent-a", score=0.50, dimension_scores={}),
        ]
        decision = make_routing_decision(scores)
        assert decision.confidence == "medium"

    def test_low_confidence(self):
        scores = [
            ScoredAgent(agent_id="agent-a", score=0.25, dimension_scores={}),
        ]
        decision = make_routing_decision(scores)
        assert decision.confidence == "low"


# ═══════════════════════════════════════════════════════════════════════════
# Overlap Detection Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestOverlapDetection:
    def test_no_overlap(self):
        a = _security_intake()
        b = _clinical_intake()
        overlap = compute_intake_overlap(a, b)
        assert overlap < 0.3

    def test_high_overlap(self):
        a = _security_intake()
        b = AgentIntake(
            categories=["security", "security.vulnerability"],
            source_types=["nvd", "cisa_kev"],
            keywords=["cve", "exploit", "breach", "malware", "patch"],
        )
        overlap = compute_intake_overlap(a, b)
        assert overlap > 0.5

    def test_identical_intake_max_overlap(self):
        a = _security_intake()
        overlap = compute_intake_overlap(a, a)
        assert overlap >= 0.9

    def test_check_overlaps_warning(self):
        a = _security_intake()
        # Create a very similar intake to trigger overlap
        similar = AgentIntake(
            categories=["security", "security.vulnerability"],
            source_types=["nvd", "cisa_kev", "crowdstrike"],
            keywords=["cve", "exploit", "breach", "ransomware", "malware", "patch"],
            systems=["CrowdStrike", "Sentinel"],
        )
        warnings, errors = check_intake_overlaps(
            "new-agent", similar, [("security-triage", a)]
        )
        assert len(warnings) > 0 or len(errors) > 0

    def test_check_overlaps_skips_self(self):
        a = _security_intake()
        warnings, errors = check_intake_overlaps(
            "security-triage", a, [("security-triage", a)]
        )
        assert warnings == []
        assert errors == []


# ═══════════════════════════════════════════════════════════════════════════
# Intake Validation Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestIntakeValidation:
    def test_valid_intake(self):
        intake = _security_intake()
        assert intake.validate_no_overlap() == []

    def test_negative_overlaps_categories(self):
        intake = AgentIntake(
            categories=["security", "security.vulnerability"],
            negative_categories=["security"],
        )
        errors = intake.validate_no_overlap()
        assert len(errors) > 0

    def test_intake_optional_fields(self):
        intake = AgentIntake()
        assert intake.categories == []
        assert intake.max_concurrent == 10
        assert intake.phi_allowed is False


# ═══════════════════════════════════════════════════════════════════════════
# Tokenizer Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestTokenizer:
    def test_filters_short_words(self):
        tokens = _tokenize_significant("the cat sat on a mat")
        assert "the" not in tokens
        assert "cat" not in tokens  # 3 chars, filtered

    def test_extracts_significant(self):
        tokens = _tokenize_significant("detected ransomware lateral movement")
        assert "ransomware" in tokens
        assert "lateral" in tokens
        assert "detected" in tokens

    def test_empty_string(self):
        assert _tokenize_significant("") == set()


# ═══════════════════════════════════════════════════════════════════════════
# Feedback & EMA Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestOutcomeToScore:
    def test_success(self):
        assert _outcome_to_score("success") == 1.0

    def test_failure(self):
        assert _outcome_to_score("failure") == 0.0

    def test_partial(self):
        assert _outcome_to_score("partial") == 0.5

    def test_unknown_defaults(self):
        assert _outcome_to_score("bogus") == 0.5


class TestUpdateEma:
    def test_first_feedback_sets_rate(self):
        rate = update_ema("agent-1", "security", "success")
        assert rate == 1.0
        assert _stats_cache["agent-1:security"]["sample_count"] == 1

    def test_ema_smoothing(self):
        """Multiple successes then a failure should decrease rate gradually."""
        for _ in range(10):
            update_ema("agent-1", "security", "success")
        rate_before = _stats_cache["agent-1:security"]["success_rate"]
        rate_after = update_ema("agent-1", "security", "failure")
        assert rate_after < rate_before

    def test_ema_recovery(self):
        """After failures, successes should bring rate back up."""
        for _ in range(5):
            update_ema("agent-1", "security", "failure")
        low_rate = _stats_cache["agent-1:security"]["success_rate"]
        for _ in range(5):
            update_ema("agent-1", "security", "success")
        recovered_rate = _stats_cache["agent-1:security"]["success_rate"]
        assert recovered_rate > low_rate

    def test_partial_gives_middle_score(self):
        rate = update_ema("agent-1", "security", "partial")
        assert rate == 0.5

    def test_ema_updates_historical_multiplier(self):
        """After enough samples, EMA should affect historical_multiplier."""
        for _ in range(15):
            update_ema("agent-1", "security", "success")
        mult = historical_multiplier("agent-1", "security")
        assert mult > 1.0


class TestDimensionSuccessTracking:
    def test_records_success(self):
        dims = {"category": 0.8, "source_type": 0.6, "keyword": 0.3}
        record_dimension_success(dims, "success")
        assert _dimension_success_counts["category"]["hits"] == 1
        assert _dimension_success_counts["category"]["total"] == 1
        assert _dimension_success_counts["source_type"]["hits"] == 1
        # keyword < 0.5 threshold, not counted
        assert _dimension_success_counts["keyword"]["total"] == 0

    def test_records_failure(self):
        dims = {"category": 0.8, "source_type": 0.6}
        record_dimension_success(dims, "failure")
        assert _dimension_success_counts["category"]["total"] == 1
        assert _dimension_success_counts["category"]["hits"] == 0

    def test_get_adaptive_weights_returns_defaults(self):
        weights = get_adaptive_weights()
        assert weights == DEFAULT_WEIGHTS


class TestComputeAdaptiveWeights:
    def test_insufficient_data_returns_defaults(self):
        weights = compute_adaptive_weights()
        assert weights == DEFAULT_WEIGHTS

    def test_with_enough_data_adjusts(self):
        """With enough samples, weights should shift toward high-hit dimensions."""
        # category always succeeds
        for _ in range(60):
            record_dimension_success({"category": 0.9, "source_type": 0.1}, "success")
        weights = compute_adaptive_weights()
        # category had 60 hits/60 total, source_type had 0/0
        # Only category has enough samples, so it gets adjusted
        assert "category" in weights
        assert abs(sum(weights.values()) - 1.0) < 0.01  # normalized


class TestFeedbackRequest:
    def test_valid_outcomes(self):
        for outcome in ["success", "failure", "partial"]:
            req = FeedbackRequest(
                envelope_id="env-1", agent_id="agent-1", outcome=outcome
            )
            assert req.outcome == outcome

    def test_invalid_outcome_rejected(self):
        with pytest.raises(Exception):
            FeedbackRequest(
                envelope_id="env-1", agent_id="agent-1", outcome="invalid"
            )
