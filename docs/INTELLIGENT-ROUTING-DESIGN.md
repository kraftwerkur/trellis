# Intelligent Routing Architecture — Phase 13 Design
**Trellis Platform | Health First**
**Author:** Reef (Design Session 2026-03-08)
**Status:** Design — Pending Eric Review
**Replaces:** Phase 13 sketch in ARCHITECTURE.md

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [Architecture Overview](#3-architecture-overview)
4. [Detailed Component Design](#4-detailed-component-design)
5. [Data Model Changes](#5-data-model-changes)
6. [API Changes](#6-api-changes)
7. [Implementation Stories](#7-implementation-stories)
8. [Migration Plan](#8-migration-plan)
9. [Performance Budget](#9-performance-budget)
10. [Risk Analysis](#10-risk-analysis)
11. [Open Questions](#11-open-questions)

---

## 1. Executive Summary

The current routing system uses static, manually-authored rules. It works for five agents. It will not work for fifty. The rules engine is fundamentally the wrong abstraction for a system that grows organically — every new agent requires someone to understand the global rule hierarchy, avoid conflicts, and test priority ordering. That doesn't scale, and it teaches nothing.

This design replaces primary routing logic with **multi-dimensional scoring**: agents declare what they handle, the platform scores every envelope against every agent simultaneously, and the best match wins. Rules evolve into a **policy layer** — a small set of constraints that enforce governance, not routing logic. A **feedback loop** lets the system improve over time.

The result: a new agent with a well-written intake declaration routes correctly on day one, without anyone authoring rules. The system gets smarter as it sees more traffic. The policy layer remains small and auditable. Healthcare compliance requirements are enforced structurally, not by convention.

**What changes:**
- Agents declare intake criteria (what they handle) at registration time
- The Classification Engine's output feeds a scoring engine instead of rules
- Rules become policies: vetoes, mandatory inclusions, regulatory overrides
- Routing decisions are logged with scores for auditability and feedback
- A daily feedback loop updates agent reliability weights

**What stays the same:**
- The envelope spec — untouched
- The Classification Engine — still runs, still enriches
- The audit trail — every routing decision logged
- Existing agents — fall back to rules-based routing if no intake declared

**Estimated implementation time:** 8-10 days (broken into stories below)

---

## 2. Problem Statement

### 2.1 The Scaling Wall

Today's routing works like this:

```
Envelope → Classification Engine (adds category/tags) → Rules Engine (pattern match) → Agent
```

The rules engine is a priority-ordered list of JSON conditions. First match wins. To add a new agent, someone must:

1. Understand what category/tag values the Classification Engine produces
2. Write conditions that match the right envelopes
3. Choose a priority that doesn't conflict with existing rules
4. Test every combination
5. Repeat for every input type the agent handles

At 5 agents: manageable. At 15 agents: a project. At 50 agents: a full-time job, and still wrong half the time.

### 2.2 Concrete Health First Examples

**Example A — The Server Breach Problem**

A CrowdStrike alert comes in: endpoint detected lateral movement consistent with ransomware. The Classification Engine correctly tags it as `category=security`. Now what?

Both the **Security Triage Agent** and the **IT Help Desk Agent** could legitimately handle this. Security wants it for threat analysis; IT needs it to pull the affected machine from the network. Today: one rule matches, the other agent doesn't know. Tomorrow: we add a fan-out rule, but now every security event goes to both, which is wrong for routine vulnerability patching.

The problem is that rules can't express "send to both when it's infrastructure-threatening, but only Security when it's an external vulnerability." That requires understanding the envelope semantics, not just pattern matching category strings.

**Example B — Clinical vs. Compliance for a HIPAA Incident**

A Teams message comes in: "Patient asked why we sent their records to the wrong insurance company." The Classification Engine tags it `category=clinical` (because it mentions "patient"). But this is a HIPAA breach incident. It should go to the Compliance agent, not the Clinical Operations agent.

The rule for this would have to check the text for HIPAA-related language AND override the category classification. Now you're writing regex patterns in rule conditions — fragile, unreadable, impossible to test comprehensively.

**Example C — Cold Start for Revenue Cycle Agent**

The Revenue Cycle team builds a claims denials agent. They hand it to the platform team for registration. The platform engineer needs to figure out: which source types should trigger it? What categories does the Classification Engine produce for claims data? What priority range? They have to read code they didn't write, ask questions, get things wrong the first time, iterate.

This delays every new agent by days. At scale, the platform team becomes a routing-rules bottleneck.

**Example D — The Broken Category Rename**

The Classification Engine's `KEYWORD_MAP` has `"revenue"` as a category. Three rules check `routing_hints.category == "revenue"`. A developer refactors the Classification Engine to use `"revenue_cycle"` for clarity. Three rules silently stop matching. The Revenue Cycle agent stops receiving traffic. No error — just silence.

This fragile coupling between classifier output and rule conditions is a latent failure mode that gets worse as the system grows.

### 2.3 What We Actually Need

A system where:
- An agent can describe itself — "I handle security vulnerabilities from NVD and CISA, focused on systems in the Health First stack"
- A new envelope is scored against all agents simultaneously — "this envelope is 0.82 likely for Security Triage, 0.34 for IT Help Desk"
- The best-matching agent gets the envelope, with confidence recorded
- If two agents are both good matches (server breach scenario), both get it — with explicit roles
- The system learns: if Security Triage consistently succeeds on ransomware alerts, its score for those goes up
- Governance is enforced separately from routing logic: "PHI envelopes never go to external agents" is a policy, not a rule

---

## 3. Architecture Overview

### 3.1 New Routing Flow

```
                        ┌─────────────────────────────────────────────────┐
                        │                ROUTING PIPELINE                  │
                        │                                                  │
  Envelope IN           │                                                  │
      │                 │  ┌─────────────────────┐                        │
      ▼                 │  │ Classification Engine│                        │
  ┌───────┐             │  │ (unchanged)          │                        │
  │Adapter│ ──────────► │  │ • category           │                        │
  └───────┘             │  │ • department         │                        │
                        │  │ • severity/priority  │                        │
                        │  │ • tags / CVE IDs     │                        │
                        │  │ • system names       │                        │
                        │  │ • phi_detected       │                        │
                        │  └──────────┬──────────┘                        │
                        │             │ enriched envelope                  │
                        │             ▼                                    │
                        │  ┌─────────────────────┐                        │
                        │  │   Pre-Score Policy   │                        │
                        │  │   Filter             │                        │
                        │  │ • PHI gate           │                        │
                        │  │ • Maturity gate      │                        │
                        │  │ • Department scope   │                        │
                        │  │ • Time-of-day        │                        │
                        │  └──────────┬──────────┘                        │
                        │             │ eligible agents list               │
                        │             ▼                                    │
                        │  ┌─────────────────────┐                        │
                        │  │   Agent Scorer       │                        │
                        │  │                      │                        │
                        │  │ For each eligible    │                        │
                        │  │ agent:               │                        │
                        │  │ • category score     │                        │
                        │  │ • source type score  │                        │
                        │  │ • keyword score      │                        │
                        │  │ • system score       │                        │
                        │  │ • priority score     │                        │
                        │  │ × historical weight  │                        │
                        │  │ × load factor        │                        │
                        │  │                      │                        │
                        │  │ → ranked agent list  │                        │
                        │  └──────────┬──────────┘                        │
                        │             │ ranked candidates                  │
                        │             ▼                                    │
                        │  ┌─────────────────────┐                        │
                        │  │   Post-Score Policy  │                        │
                        │  │   Enforcement        │                        │
                        │  │ • Mandatory fan-out  │                        │
                        │  │ • Regulatory override│                        │
                        │  │ • Anti-circular      │                        │
                        │  │ • Threshold check    │                        │
                        │  └──────────┬──────────┘                        │
                        │             │ final routing decision             │
                        │             ▼                                    │
                        │  ┌─────────────────────┐                        │
                        │  │   Dispatcher         │                        │
                        │  │ (unchanged logic)    │                        │
                        │  └──────────┬──────────┘                        │
                        │             │                                    │
                        └────────────┼────────────────────────────────────┘
                                     │
                     ┌───────────────┼───────────────┐
                     ▼               ▼               ▼
               ┌──────────┐  ┌──────────┐  ┌──────────────┐
               │  Agent A │  │  Agent B │  │ Dead Letter  │
               │ (primary)│  │  (CC'd)  │  │   Queue      │
               └──────────┘  └──────────┘  └──────────────┘
                     │               │
                     ▼               ▼
               ┌────────────────────────┐
               │    Feedback Collector  │
               │  • success / failure   │
               │  • resolution time     │
               │  • re-route events     │
               └────────────────────────┘
                            │
                    (batch, daily)
                            ▼
               ┌────────────────────────┐
               │  Historical Weight     │
               │  Updater               │
               │  (per agent/category)  │
               └────────────────────────┘
```

### 3.2 Hybrid Transition Architecture

During migration, both systems run simultaneously:

```
Envelope IN
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│                    ROUTING MODE CHECK                    │
│              (env var: ROUTING_MODE)                     │
│                                                          │
│  "rules"   ─────────────────────────► Rules Engine      │
│                                           │              │
│  "scored"  ─────────────────────────► Scorer Engine     │
│                                           │              │
│  "shadow"  ──── Rules Engine (live) ──► Dispatcher ◄── │
│             └── Scorer Engine (log) ──► (score only,   │
│                                          no dispatch)   │
│                                                          │
│  "hybrid"  ──── Scorer (primary) ─────► Dispatcher      │
│             └── Rules fallback if                        │
│                 score < threshold                        │
└─────────────────────────────────────────────────────────┘
```

---

## 4. Detailed Component Design

### 4.1 Agent Intake Declarations

#### 4.1.1 Schema

Intake is a new JSON field on the Agent model. It is **optional and backward compatible** — agents without intake declarations continue to use rules-based routing.

```python
# New Pydantic model: trellis/schemas.py

class TimeConstraints(BaseModel):
    business_hours_only: bool = False
    # If True, after-hours traffic redirected to fallback_agent_id
    fallback_agent_id: str | None = None
    # Timezone for business hours calculation (defaults to platform setting)
    timezone: str = "America/New_York"
    # Hours considered "business hours" (24h format)
    business_hours_start: int = 8   # 8 AM
    business_hours_end: int = 18    # 6 PM

class AgentIntake(BaseModel):
    # WHAT TYPES OF WORK
    # Dot-notation hierarchy: "security", "security.vulnerability", "security.vulnerability.cvss_critical"
    categories: list[str] = Field(default_factory=list)
    
    # Explicit exclusions — these veto routing regardless of score
    # "I handle security but NOT clinical security incidents"
    negative_categories: list[str] = Field(default_factory=list)
    
    # Source types this agent handles
    source_types: list[str] = Field(default_factory=list)
    
    # Keywords that indicate this agent's domain
    # Used for Jaccard similarity scoring against envelope payload
    keywords: list[str] = Field(default_factory=list)
    
    # Named systems this agent specializes in
    # Matched against Classification Engine's extracted system tags
    systems: list[str] = Field(default_factory=list)
    
    # Priority levels this agent handles ("low", "normal", "high", "critical")
    priority_range: list[str] = Field(default_factory=lambda: ["low", "normal", "high", "critical"])
    
    # Human-readable description — used for semantic matching (future: embeddings)
    description: str = ""
    
    # CAPACITY CONSTRAINTS
    # Max envelopes being processed simultaneously (for load factor calculation)
    max_concurrent: int = 10
    
    # Expected processing time SLA in seconds
    sla_seconds: int = 300
    
    # TIME CONSTRAINTS
    time_constraints: TimeConstraints = Field(default_factory=TimeConstraints)
    
    # COMPLIANCE ATTRIBUTES
    # True if this agent is authorized to receive PHI-containing envelopes
    phi_allowed: bool = False
    
    # Department/facility scoping (empty = enterprise-wide)
    department_scope: list[str] = Field(default_factory=list)
    facility_scope: list[str] = Field(default_factory=list)
```

#### 4.1.2 Example Declarations

**Security Triage Agent:**
```json
{
  "intake": {
    "categories": ["security", "security.vulnerability", "security.compliance"],
    "negative_categories": ["clinical", "hr", "revenue"],
    "source_types": ["nvd", "cisa_kev", "nist", "crowdstrike", "sentinel"],
    "keywords": ["cve", "exploit", "breach", "ransomware", "malware", "patch", 
                 "firewall", "vulnerability", "threat", "attack", "zero-day",
                 "lateral movement", "phishing", "credential"],
    "systems": ["CrowdStrike", "Sentinel", "Defender", "SailPoint", "Checkpoint",
                "Arista", "Nutanix"],
    "priority_range": ["high", "critical"],
    "description": "Handles security vulnerability alerts, threat intelligence, and compliance incidents affecting Health First infrastructure. Cross-references against HF tech stack. Generates structured risk advisories.",
    "max_concurrent": 5,
    "sla_seconds": 600,
    "phi_allowed": false,
    "time_constraints": {
      "business_hours_only": false
    }
  }
}
```

**IT Help Desk Agent:**
```json
{
  "intake": {
    "categories": ["incident", "incident.infrastructure", "incident.desktop"],
    "negative_categories": [],
    "source_types": ["ivanti", "servicenow", "teams"],
    "keywords": ["outage", "printer", "vpn", "password", "network", "server",
                 "laptop", "email", "access", "ticket", "slow", "down", "broken"],
    "systems": ["Ivanti", "LogicMonitor", "xMatters", "8x8"],
    "priority_range": ["low", "normal", "high"],
    "description": "Handles IT help desk requests: desktop support, infrastructure incidents, access management, software issues. Primary triage for IT service tickets.",
    "max_concurrent": 20,
    "sla_seconds": 3600,
    "phi_allowed": false,
    "time_constraints": {
      "business_hours_only": false,
      "fallback_agent_id": "it-oncall"
    }
  }
}
```

**Clinical Operations Agent:**
```json
{
  "intake": {
    "categories": ["clinical", "clinical.adt", "clinical.orders"],
    "negative_categories": ["security", "hr", "revenue"],
    "source_types": ["epic", "hl7", "fhir"],
    "keywords": ["patient", "admission", "discharge", "transfer", "order",
                 "medication", "lab", "radiology", "bed", "adt"],
    "systems": ["Epic"],
    "priority_range": ["normal", "high", "critical"],
    "description": "Processes Epic/HL7 clinical events. ADT notifications, bed management, order routing, patient flow optimization.",
    "max_concurrent": 50,
    "sla_seconds": 60,
    "phi_allowed": true,
    "department_scope": [],
    "facility_scope": []
  }
}
```

#### 4.1.3 Hierarchical Category Matching

Categories use dot-notation for hierarchy. The matching algorithm handles three cases:

| Agent declares | Envelope category | Score |
|---|---|---|
| `security` | `security` | 1.0 (exact) |
| `security` | `security.vulnerability` | 0.8 (agent is parent — handles all children) |
| `security.vulnerability` | `security` | 0.4 (agent is child — probably handles this, but specialized) |
| `security.vulnerability` | `security.compliance` | 0.2 (sibling — same parent, different domain) |
| `hr` | `security` | 0.0 (no relation) |

This is computed with a simple tree traversal — no external libraries needed.

```python
def category_match_score(agent_categories: list[str], envelope_category: str) -> float:
    """
    Returns the best category match score [0.0, 1.0].
    """
    if not agent_categories or not envelope_category:
        return 0.0
    
    best = 0.0
    env_parts = envelope_category.split(".")
    
    for agent_cat in agent_categories:
        ag_parts = agent_cat.split(".")
        
        if ag_parts == env_parts:
            # Exact match
            best = max(best, 1.0)
        elif env_parts[:len(ag_parts)] == ag_parts:
            # Agent is parent of envelope category
            # e.g., agent="security", envelope="security.vulnerability"
            depth_ratio = len(ag_parts) / len(env_parts)
            best = max(best, 0.5 + 0.3 * depth_ratio)  # 0.65 for 1-level deep
        elif ag_parts[:len(env_parts)] == env_parts:
            # Agent is child (specialized), envelope is broader
            # e.g., agent="security.vulnerability", envelope="security"
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
                # Siblings sharing a common parent
                best = max(best, 0.1 * common)
    
    return round(best, 3)
```

#### 4.1.4 Negative Declarations

If an envelope's category matches any item in `negative_categories`, the agent's score is **forced to zero** — not lowered, zeroed. This is a hard exclusion, not a penalty.

Why hard zero instead of penalty? Because "I handle everything EXCEPT clinical" is an absolute business rule, not a preference. A HIPAA-protected clinical event going to the wrong agent is a compliance incident, not a score optimization opportunity.

#### 4.1.5 Overlap Validation

When an agent's intake is updated or created:

1. Compare new intake against all existing active agents
2. Calculate an **overlap score** between intake declarations:
   - Shared categories / total combined categories × 0.4
   - Shared source types / total combined × 0.3
   - Keyword Jaccard similarity × 0.3
3. If overlap > 0.7 with any existing agent: **warning** (not error) returned in registration response
4. If overlap > 0.9: **error** — registration blocked pending admin review

The dashboard shows an **overlap heatmap** per agent pair. This helps platform admins identify when two agents are doing the same thing.

---

### 4.2 Scoring Engine

#### 4.2.1 Score Dimensions

```
Final Score = (
    category_score    × w_category    +   # 0.30
    source_score      × w_source      +   # 0.25
    keyword_score     × w_keyword     +   # 0.20
    system_score      × w_system      +   # 0.15
    priority_score    × w_priority        # 0.10
) × historical_multiplier × load_multiplier
```

The base weights sum to 1.0. Multipliers can boost or penalize the total score but don't change the relative balance of dimensions.

**Default weights:**

| Dimension | Weight | Rationale |
|---|---|---|
| Category | 0.30 | Highest: categories represent the semantic domain of the work |
| Source type | 0.25 | Strong signal: agent declared it handles this exact source |
| Keyword | 0.20 | Good signal: measures lexical overlap of actual content |
| System | 0.15 | Medium: which named systems are involved |
| Priority | 0.10 | Lowest: most agents handle multiple priority levels |

Weights are configurable via platform settings — not hardcoded. A future admin UI could expose weight tuning.

#### 4.2.2 Dimension Calculations

**Category Score (0.0 - 1.0)**
Uses the hierarchical match algorithm from §4.1.3. Best match across all agent declared categories.

**Source Type Score (0.0 - 1.0)**
```python
def source_type_score(agent_source_types: list[str], envelope_source_type: str) -> float:
    if not agent_source_types:
        return 0.3  # Neutral: agent didn't declare, not a disqualifier
    if envelope_source_type in agent_source_types:
        return 1.0
    return 0.0
```

Note: If agent declares no source types, it gets 0.3 (neutral) rather than 0.0. Agents shouldn't be penalized for not specifying — some agents (generic triage) might legitimately handle any source.

**Keyword Score (0.0 - 1.0)**
Jaccard similarity between the set of significant words in the envelope (extracted by Classification Engine tags + payload text tokenization) and the agent's declared keywords.

```python
def keyword_score(agent_keywords: list[str], envelope_tags: list[str], 
                  envelope_text: str) -> float:
    if not agent_keywords:
        return 0.2  # Neutral
    
    # Build envelope keyword set from tags + significant text tokens
    # Significant = >4 chars, not stop words, lowercase
    envelope_words = set(envelope_tags)
    envelope_words.update(_tokenize_significant(envelope_text))
    
    agent_set = set(kw.lower() for kw in agent_keywords)
    
    if not envelope_words:
        return 0.0
    
    intersection = agent_set & envelope_words
    union = agent_set | envelope_words
    
    # Jaccard, but capped at 1.0 and boosted for exact CVE/system name matches
    jaccard = len(intersection) / len(union)
    
    # Bonus: exact match on high-value terms (CVE IDs, system names)
    high_value_terms = {t for t in intersection if t.startswith("cve-") or len(t) > 8}
    bonus = min(0.2, len(high_value_terms) * 0.05)
    
    return min(1.0, jaccard + bonus)
```

**System Score (0.0 - 1.0)**
```python
def system_score(agent_systems: list[str], envelope_system_tags: list[str]) -> float:
    """
    Envelope system tags come from Classification Engine's _TECH_STACK_NAMES extraction.
    """
    if not agent_systems or not envelope_system_tags:
        return 0.2  # Neutral when no system info available
    
    agent_system_lower = {s.lower() for s in agent_systems}
    env_system_lower = set(envelope_system_tags)
    
    matches = agent_system_lower & env_system_lower
    if not matches:
        return 0.0
    
    # Score increases with more system matches, max at 3+ matches
    return min(1.0, len(matches) * 0.4)
```

**Priority Score (0.0 - 1.0)**
```python
def priority_score(agent_priority_range: list[str], envelope_priority: str) -> float:
    if not agent_priority_range:
        return 0.5  # Neutral
    envelope_p = (envelope_priority or "normal").lower()
    if envelope_p in [p.lower() for p in agent_priority_range]:
        return 1.0
    return 0.0  # Agent explicitly doesn't handle this priority level
```

#### 4.2.3 Historical Multiplier

```python
def historical_multiplier(agent_id: str, category: str, 
                           stats_cache: dict) -> float:
    """
    Returns a multiplier in [0.70, 1.30].
    
    Cold start: 1.0 (neutral, no boost or penalty)
    Excellent track record: up to 1.30
    Poor track record: as low as 0.70
    """
    key = f"{agent_id}:{category}"
    stats = stats_cache.get(key)
    
    if not stats or stats["sample_count"] < 10:
        return 1.0  # Cold start
    
    success_rate = stats["success_rate"]  # 0.0 - 1.0
    
    # Map success_rate to multiplier:
    # 1.0 success → 1.30 multiplier
    # 0.5 success → 1.00 multiplier (neutral)
    # 0.0 success → 0.70 multiplier
    multiplier = 0.70 + (success_rate * 0.60)
    return round(multiplier, 3)
```

**Why [0.70, 1.30] and not [0.0, ∞)?**

Historical accuracy should *influence* routing, not *control* it. If we let it go to zero, a temporarily struggling agent could be permanently starved of traffic, preventing recovery. If we let it go to infinity, we create winner-takes-all dynamics that make the system fragile to single-agent failures.

The 0.70 floor means even a failing agent with a great intake declaration still competes — just at a penalty. The 1.30 ceiling means excellent history is rewarded but can't overwhelm a genuinely better match on the base dimensions.

#### 4.2.4 Load Multiplier

```python
def load_multiplier(agent_id: str, load_cache: dict) -> float:
    """
    Penalizes overloaded agents.
    
    Returns 1.0 at ≤50% capacity
    Returns 0.0 at 100% capacity
    """
    load_info = load_cache.get(agent_id, {})
    in_flight = load_info.get("in_flight", 0)
    max_concurrent = load_info.get("max_concurrent", 10)
    
    utilization = in_flight / max(max_concurrent, 1)
    
    if utilization <= 0.5:
        return 1.0
    elif utilization >= 1.0:
        return 0.0  # Agent at capacity — effectively excluded
    else:
        # Linear falloff from 0.5 to 1.0 utilization
        return round(2.0 * (1.0 - utilization), 3)
```

Load data is stored in a fast in-memory cache (see §9 Performance Budget), updated every 10 seconds by the Health Auditor.

#### 4.2.5 Scoring Pipeline

```python
async def score_all_agents(
    envelope: Envelope,
    eligible_agents: list[Agent],
    stats_cache: dict,
    load_cache: dict,
) -> list[ScoredAgent]:
    """
    Scores all eligible agents against envelope.
    Returns list of ScoredAgent, sorted by score descending.
    All scores logged regardless of outcome (for shadow mode).
    """
    classification = envelope.payload.data.get("_classification", {})
    env_category = classification.get("category") or envelope.routing_hints.category or ""
    env_source = envelope.source_type
    env_tags = list(envelope.routing_hints.tags or [])
    env_text = envelope.payload.text or ""
    env_priority = envelope.metadata.priority or "normal"
    env_systems = [t for t in env_tags if _is_system_tag(t)]
    
    scores = []
    
    for agent in eligible_agents:
        intake = agent.intake or {}  # JSON field, may be None for legacy agents
        
        if not intake:
            # Legacy agent: no intake declaration
            # Will be handled by rules fallback (hybrid mode)
            continue
        
        # Negative category check (hard veto)
        negative_cats = intake.get("negative_categories", [])
        if any(env_category.startswith(neg) for neg in negative_cats):
            scores.append(ScoredAgent(
                agent_id=agent.agent_id,
                score=0.0,
                excluded_by="negative_category",
                dimension_scores={}
            ))
            continue
        
        # Compute dimensions
        cat = category_match_score(intake.get("categories", []), env_category)
        src = source_type_score(intake.get("source_types", []), env_source)
        kw = keyword_score(intake.get("keywords", []), env_tags, env_text)
        sys = system_score(intake.get("systems", []), env_systems)
        pri = priority_score(intake.get("priority_range", []), env_priority)
        
        # Weighted base score
        base = (
            cat * WEIGHTS["category"] +
            src * WEIGHTS["source_type"] +
            kw  * WEIGHTS["keyword"] +
            sys * WEIGHTS["system"] +
            pri * WEIGHTS["priority"]
        )
        
        # Apply multipliers
        hist = historical_multiplier(agent.agent_id, env_category, stats_cache)
        load = load_multiplier(agent.agent_id, load_cache)
        
        final_score = round(base * hist * load, 4)
        
        scores.append(ScoredAgent(
            agent_id=agent.agent_id,
            score=final_score,
            dimension_scores={
                "category": cat, "source_type": src, "keyword": kw,
                "system": sys, "priority": pri,
                "historical_multiplier": hist, "load_multiplier": load,
                "base_score": base,
            },
            cold_start=(stats_cache.get(f"{agent.agent_id}:{env_category}", {})
                       .get("sample_count", 0) < 10)
        ))
    
    return sorted(scores, key=lambda s: s.score, reverse=True)
```

#### 4.2.6 Confidence Thresholds and Routing Decisions

| Score Range | Routing Action | Rationale |
|---|---|---|
| < 0.20 | Dead letter → Human triage queue | Below noise floor. No confident match exists. |
| 0.20 - 0.40 | Route to best match, flag for review | Possible match but uncertain. Human should verify. |
| 0.40 - 0.65 | Route to best match, normal processing | Reasonable match. Log score for feedback. |
| ≥ 0.65 | Route to best match, high confidence | Strong match. Automated processing appropriate. |

**Multi-dispatch trigger:**
If the top TWO agents both score ≥ 0.55 AND their score difference is ≤ 0.15, AND their categories overlap (both in category map defined below), route to both:

```python
MULTI_DISPATCH_CATEGORY_PAIRS = {
    # Category pair: (primary, secondary) OR (co-equal)
    ("security", "incident"):        "co_primary",  # server breach
    ("incident", "security"):        "co_primary",
    ("compliance", "clinical"):      "cc_only",     # compliance CC'd, clinical primary
    ("clinical", "compliance"):      "cc_only",
    ("hr", "compliance"):            "cc_only",     # HIPAA HR incidents
}
```

`co_primary`: both agents get the full envelope, expected to coordinate.
`cc_only`: secondary agent gets a read-only notification copy.

This resolves the "server breach" problem explicitly: Security Triage and IT Help Desk both score 0.72 and 0.68 respectively → both are co-primaries. They both receive the envelope. The audit log records this as a deliberate co-primary dispatch, not a fan-out error.

#### 4.2.7 Tie-Breaking

When scores are equal (or within 0.01):
1. Higher agent priority field value wins (existing field on Agent model)
2. Lower current load wins (fewer envelopes in flight)
3. Earlier registration date wins (most proven agent)

---

### 4.3 Policy Layer

Policies replace rules as the governance mechanism. Rules were routing logic + governance tangled together. Policies are *only* governance.

#### 4.3.1 Policy Types

**VETO** — Prevents routing to specific agents or categories of agents.
**REQUIRE** — Forces inclusion of an agent regardless of score.
**REDIRECT** — Changes the destination from what scoring chose.
**CC** — Adds an agent to all routings of a specific type (read-only copy).

```python
class Policy(BaseModel):
    policy_id: str
    name: str
    description: str
    policy_type: Literal["veto", "require", "redirect", "cc"]
    active: bool = True
    priority: int = 100  # Lower number = evaluated first
    
    # Trigger conditions (what envelopes does this policy apply to?)
    trigger_conditions: dict[str, Any]  # Same JSON query syntax as current rules
    
    # Policy action
    action: dict[str, Any]
    
    # Audit requirement (all policy applications logged)
    audit_reason: str  # Human-readable why this policy exists
    created_by: str
    created: datetime
    last_modified: datetime
```

#### 4.3.2 Healthcare-Specific Policies

**Policy 1: PHI Isolation**
```json
{
  "name": "PHI Isolation — No External Agents",
  "policy_type": "veto",
  "trigger_conditions": {
    "payload.data._classification.phi_detected": true
  },
  "action": {
    "veto_if": {"phi_allowed": false},
    "reason": "HIPAA: PHI-containing envelopes may not be routed to agents without phi_allowed=true"
  },
  "audit_reason": "HIPAA Privacy Rule — 45 CFR 164.502"
}
```

**Policy 2: Compliance Mandatory CC**
```json
{
  "name": "Regulatory Events — Compliance CC",
  "policy_type": "cc",
  "trigger_conditions": {
    "routing_hints.category": {"$in": ["compliance", "regulatory"]}
  },
  "action": {
    "cc_agent": "compliance-agent",
    "cc_role": "notify_only"
  },
  "audit_reason": "HIPAA Audit Controls — 45 CFR 164.312(b)"
}
```

**Policy 3: After-Hours Redirect**
```json
{
  "name": "After-Hours IT — On-Call Redirect",
  "policy_type": "redirect",
  "trigger_conditions": {
    "routing_hints.department": "IT",
    "_time_context.is_business_hours": false,
    "metadata.priority": {"$in": ["high", "critical"]}
  },
  "action": {
    "redirect_to": "it-oncall",
    "notify_original": true
  },
  "audit_reason": "IT Operations on-call rotation policy"
}
```

**Policy 4: Shadow Agent Gate**
```json
{
  "name": "Shadow Agents — No Production Traffic",
  "policy_type": "veto",
  "trigger_conditions": {},
  "action": {
    "veto_if_maturity": "shadow"
  },
  "audit_reason": "Maturity model: shadow agents receive no live traffic"
}
```

**Policy 5: Anti-Circular Routing**
```json
{
  "name": "Anti-Circular — No Re-routing to Visited Agents",
  "policy_type": "veto",
  "trigger_conditions": {
    "routing_hints.routing_path": {"$exists": true}
  },
  "action": {
    "veto_if_in_routing_path": true
  },
  "audit_reason": "Prevent infinite routing loops"
}
```

#### 4.3.3 Policy Evaluation Order

```
Pre-scoring policies (filter agent pool):
  Priority 1: Anti-circular (routing_path check)
  Priority 2: Shadow agent gate (maturity check)
  Priority 3: PHI isolation (phi_detected × phi_allowed check)
  Priority 4: Department/facility scope (scope check)
  Priority 5: Time-of-day restrictions (business hours check)

  → Produces: eligible_agents list (filtered)

[SCORING RUNS HERE]

Post-scoring policies (modify scored result):
  Priority 10: Regulatory override (force route regardless of score)
  Priority 20: Mandatory CC (add agents to dispatch list)
  Priority 30: After-hours redirect (change primary destination)
  Priority 40: Threshold check (no match → dead letter)
  Priority 50: Multi-dispatch resolution (apply co-primary/cc_only rules)
```

**Policy conflict resolution:**
- Two VETOs don't conflict (both apply)
- Two REQUIREs don't conflict (both apply, fan-out)
- VETO + REQUIRE for same agent: REQUIRE wins (governance overrides score, explicit inclusion wins exclusion)
- Two REDIRECTs: first by priority wins, second is logged as "overridden"

All policy evaluations are logged in audit trail with policy_id, trigger reason, and outcome.

#### 4.3.4 Policies vs. Rules Migration

The key distinction: current rules do two things. Some are routing logic ("Epic ADT events go to bed management agent") — these become intake declarations on the bed management agent. Some are governance ("never send PHI to external agents") — these become policies.

During migration:
1. Audit all existing rules
2. Classify each as: intake candidate vs. policy candidate
3. Convert policies → Policy model
4. Convert routing rules → intake declarations on appropriate agents
5. Delete converted rules from rules table
6. Target: ≤10 active policies, 0 pure routing rules

---

### 4.4 Feedback Loop

#### 4.4.1 What Constitutes Good Routing

Good routing signals (increase `success_rate`):
- Agent returns `status="completed"` AND does NOT immediately delegate to another agent
- If `maturity=assisted`, human reviewer marks routing as "correct"
- Envelope resolved within agent's declared `sla_seconds`
- No re-submission of same `trace_id` to different agent after completion

Bad routing signals (decrease `success_rate`):
- Agent returns `status="not_my_domain"` — explicit rejection
- Agent immediately delegates to a different agent with the SAME category (strong signal: wrong agent)
- Envelope times out at agent (dispatch_status = "timeout")
- Agent errors on the envelope (dispatch_status = "error")
- If `maturity=assisted`, human reviewer marks routing as "incorrect"
- Same `trace_id` re-submitted to different agent within 60 minutes (re-routing event)

#### 4.4.2 Feedback Collection

Each `EnvelopeLog` entry gets a new `routing_outcome` field populated after dispatch:

```python
class RoutingOutcome(str, Enum):
    PENDING = "pending"        # Not yet resolved
    SUCCESS = "success"        # Agent completed successfully
    REJECTED = "rejected"      # Agent returned not_my_domain
    TIMEOUT = "timeout"        # Agent didn't respond
    ERROR = "error"            # Agent errored
    REROUTED = "rerouted"      # Sent to different agent after this one
    HUMAN_CORRECT = "human_correct"   # Maturity=assisted, human confirmed
    HUMAN_INCORRECT = "human_incorrect"  # Maturity=assisted, human rejected
```

A lightweight background task watches for outcome signals:

```python
async def collect_routing_feedback(envelope_id: str, outcome: RoutingOutcome, db: AsyncSession):
    """
    Called by:
    - Dispatcher (on agent response)
    - Human review API (on reviewer action)  
    - Re-routing detection (when same trace routes to different agent)
    
    Updates routing_feedback table. Never blocks the main routing path.
    """
    log = await db.get(EnvelopeLog, envelope_id)
    if not log or not log.routing_score_id:
        return
    
    feedback = RoutingFeedback(
        score_id=log.routing_score_id,
        agent_id=log.target_agent_id,
        envelope_category=log.envelope_data.get("routing_hints", {}).get("category"),
        outcome=outcome,
        resolution_seconds=(datetime.now(timezone.utc) - log.timestamp).total_seconds(),
    )
    db.add(feedback)
    await db.flush()
```

#### 4.4.3 Daily Weight Update

A scheduled job (2:00 AM daily, runs as a platform housekeeping agent) recalculates `agent_routing_stats`:

```python
async def update_routing_stats(db: AsyncSession):
    """
    Calculates success_rate per (agent_id, category) from the last 90 days.
    Uses exponential moving average to prevent sudden shifts.
    Minimum 10 samples required to influence weights.
    """
    # Aggregate outcomes per agent/category (last 90 days)
    raw_stats = await _aggregate_feedback(db, lookback_days=90)
    
    for (agent_id, category), outcomes in raw_stats.items():
        if len(outcomes) < 10:
            continue  # Insufficient data — keep current rate or 0.5
        
        # Raw success rate
        successes = sum(1 for o in outcomes if o in [RoutingOutcome.SUCCESS, RoutingOutcome.HUMAN_CORRECT])
        raw_rate = successes / len(outcomes)
        
        # Fetch current stats
        current = await _get_current_stats(db, agent_id, category)
        
        if current is None:
            new_rate = raw_rate
        else:
            # Exponential moving average: α=0.15 (conservative)
            # New data influences 15% of weight
            alpha = 0.15
            new_rate = alpha * raw_rate + (1 - alpha) * current.success_rate
        
        # Hard bounds: [0.10, 0.98]
        # Even terrible agents stay above 0.10 (can recover)
        # Perfect agents are capped at 0.98 (not gaming)
        new_rate = max(0.10, min(0.98, new_rate))
        
        await _upsert_routing_stats(db, agent_id, category, new_rate, len(outcomes))
```

**Why α=0.15 (not 0.5 or 0.01)?**

- α=0.5: Too fast. A week of bad routing could drop an agent's score dramatically. An agent handling a surge of unusual traffic could be permanently penalized.
- α=0.01: Too slow. Would take months to reflect sustained improvement.
- α=0.15: New data takes about 2 weeks to substantially shift the weight. Stable enough to ignore noise, responsive enough to detect real problems.

#### 4.4.4 Cold Start Strategy

New agents start with `success_rate = None` (not 0.0 or 1.0). When calculating historical_multiplier:
- `None` → returns 1.0 (neutral)
- This means new agents compete purely on their intake declaration quality
- A well-written intake declaration should produce competitive scores immediately
- After 10 successful routings, historical data starts influencing scores

Cold start is flagged in the scoring log (`cold_start: true`) so the Rule Optimizer can distinguish "agent underperforming" from "agent has no data yet."

The platform team should do a manual review of cold-start agents after their first 50 routings to validate the intake declaration is accurate.

#### 4.4.5 Anti-Reinforcement Safeguards

Problem: If scoring always picks Agent A, Agent A gets all the feedback, its score goes up, it gets more traffic, repeat. Other agents starve.

Safeguards:
1. **Historical multiplier cap at 1.30**: No agent can more than 30% above a purely declaration-based score
2. **Minimum 10% score floor from base dimensions**: If an agent has a good intake declaration but poor history, it can still compete
3. **Load factor**: At high utilization, even top-scoring agents get penalized, giving other agents a chance
4. **Monthly audit**: Rule Optimizer checks for agents with >80% market share in any category, flags for review
5. **Manual override**: Platform admin can reset an agent's historical stats (nuclear option for stuck situations)

---

### 4.5 In-Flight Envelope Tracking (Load Factor Data)

To compute load factors, the platform needs to know how many envelopes each agent is currently processing. This is a new lightweight tracking system.

```python
class AgentLoad:
    """
    In-memory, per-process cache of agent in-flight counts.
    Updated by dispatcher on envelope start/end.
    Refreshed from DB on startup.
    """
    _counts: dict[str, int] = {}  # agent_id → in_flight count
    _lock: asyncio.Lock
    
    async def increment(self, agent_id: str) -> None:
        async with self._lock:
            self._counts[agent_id] = self._counts.get(agent_id, 0) + 1
    
    async def decrement(self, agent_id: str) -> None:
        async with self._lock:
            self._counts[agent_id] = max(0, self._counts.get(agent_id, 0) - 1)
    
    def get_load(self, agent_id: str, max_concurrent: int) -> dict:
        in_flight = self._counts.get(agent_id, 0)
        return {"in_flight": in_flight, "max_concurrent": max_concurrent}
```

This is intentionally simple and in-memory. At 1000 envelopes/minute and sub-second processing, exact precision isn't critical — an approximation is fine for load factor calculation. If the process restarts, counts reset to zero (acceptable: brief under-reporting of load).

---

## 5. Data Model Changes

### 5.1 Modified Tables

**`agents` table — new columns:**

```sql
ALTER TABLE agents ADD COLUMN intake JSON;               -- IntakeDeclaration (nullable)
ALTER TABLE agents ADD COLUMN phi_allowed BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE agents ADD COLUMN max_concurrent INTEGER NOT NULL DEFAULT 10;
ALTER TABLE agents ADD COLUMN tags JSON;                 -- list[str], for overlap detection
```

**`envelope_log` table — new columns:**

```sql
ALTER TABLE envelope_log ADD COLUMN routing_mode VARCHAR(20) DEFAULT 'rules';
  -- 'rules' | 'scored' | 'shadow_scored' | 'hybrid_rules' | 'hybrid_scored'
ALTER TABLE envelope_log ADD COLUMN routing_score FLOAT;        -- Top agent's score
ALTER TABLE envelope_log ADD COLUMN routing_confidence VARCHAR(20);
  -- 'high' | 'medium' | 'low' | 'unroutable'
ALTER TABLE envelope_log ADD COLUMN routing_path JSON;          -- list[str] agent_ids visited
ALTER TABLE envelope_log ADD COLUMN routing_outcome VARCHAR(30) DEFAULT 'pending';
  -- RoutingOutcome enum value
ALTER TABLE envelope_log ADD COLUMN outcome_recorded_at TIMESTAMP WITH TIME ZONE;
```

**`rules` table — new column:**

```sql
ALTER TABLE rules ADD COLUMN rule_class VARCHAR(20) DEFAULT 'routing';
  -- 'routing' (old-style, to be migrated) | 'policy' (new)
```

### 5.2 New Tables

**`routing_scores` — log of all scoring decisions:**

```sql
CREATE TABLE routing_scores (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    envelope_id VARCHAR(36) NOT NULL,
    trace_id    VARCHAR(36),
    scored_at   TIMESTAMP WITH TIME ZONE NOT NULL,
    routing_mode VARCHAR(20) NOT NULL,  -- same as envelope_log.routing_mode
    
    -- All agent scores as a JSON blob (list of {agent_id, score, dimensions})
    -- Stored as JSON for query flexibility without excessive rows
    scores_json JSON NOT NULL,
    
    -- Top result summary (for quick queries without parsing JSON)
    top_agent_id    VARCHAR(100),
    top_score       FLOAT,
    second_agent_id VARCHAR(100),
    second_score    FLOAT,
    
    threshold_used  FLOAT NOT NULL DEFAULT 0.20,
    unroutable      BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX idx_routing_scores_envelope ON routing_scores(envelope_id);
CREATE INDEX idx_routing_scores_top_agent ON routing_scores(top_agent_id, scored_at);
```

**`routing_feedback` — outcome observations:**

```sql
CREATE TABLE routing_feedback (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    score_id        INTEGER REFERENCES routing_scores(id),
    envelope_id     VARCHAR(36) NOT NULL,
    agent_id        VARCHAR(100) NOT NULL,
    envelope_category VARCHAR(100),
    outcome         VARCHAR(30) NOT NULL,  -- RoutingOutcome
    resolution_seconds FLOAT,
    reviewer_id     VARCHAR(100),          -- For maturity=assisted human reviews
    recorded_at     TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_routing_feedback_agent ON routing_feedback(agent_id, envelope_category, recorded_at);
```

**`agent_routing_stats` — materialized success rates (updated daily):**

```sql
CREATE TABLE agent_routing_stats (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        VARCHAR(100) NOT NULL,
    category        VARCHAR(100) NOT NULL,
    success_rate    FLOAT NOT NULL DEFAULT 0.5,
    sample_count    INTEGER NOT NULL DEFAULT 0,
    last_updated    TIMESTAMP WITH TIME ZONE NOT NULL,
    
    UNIQUE(agent_id, category)
);

CREATE INDEX idx_routing_stats_lookup ON agent_routing_stats(agent_id, category);
```

**`routing_policies` — the new Policy model:**

```sql
CREATE TABLE routing_policies (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_id           VARCHAR(100) NOT NULL UNIQUE,
    name                VARCHAR(200) NOT NULL,
    description         TEXT,
    policy_type         VARCHAR(20) NOT NULL,  -- veto|require|redirect|cc
    active              BOOLEAN NOT NULL DEFAULT TRUE,
    priority            INTEGER NOT NULL DEFAULT 100,
    trigger_conditions  JSON NOT NULL,
    action              JSON NOT NULL,
    audit_reason        TEXT NOT NULL,
    created_by          VARCHAR(100) NOT NULL,
    created             TIMESTAMP WITH TIME ZONE NOT NULL,
    last_modified       TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE INDEX idx_routing_policies_active ON routing_policies(active, priority);
```

### 5.3 Alembic Migration

One migration file: `alembic/versions/XXXX_phase13_intelligent_routing.py`

```python
def upgrade() -> None:
    # 1. agents — new columns with safe defaults
    op.add_column('agents', sa.Column('intake', sa.JSON(), nullable=True))
    op.add_column('agents', sa.Column('phi_allowed', sa.Boolean(), 
                                       nullable=False, server_default='0'))
    op.add_column('agents', sa.Column('max_concurrent', sa.Integer(), 
                                       nullable=False, server_default='10'))
    op.add_column('agents', sa.Column('tags', sa.JSON(), nullable=True))
    
    # 2. envelope_log — new columns
    op.add_column('envelope_log', sa.Column('routing_mode', sa.String(20), 
                                             nullable=True))
    op.add_column('envelope_log', sa.Column('routing_score', sa.Float(), 
                                             nullable=True))
    op.add_column('envelope_log', sa.Column('routing_confidence', sa.String(20),
                                             nullable=True))
    op.add_column('envelope_log', sa.Column('routing_path', sa.JSON(), 
                                             nullable=True))
    op.add_column('envelope_log', sa.Column('routing_outcome', sa.String(30),
                                             nullable=True))
    op.add_column('envelope_log', sa.Column('outcome_recorded_at', 
                                             sa.DateTime(timezone=True),
                                             nullable=True))
    
    # 3. rules — classification column
    op.add_column('rules', sa.Column('rule_class', sa.String(20),
                                      nullable=True, server_default='routing'))
    
    # 4. New tables
    op.create_table('routing_scores', ...)    # see §5.2
    op.create_table('routing_feedback', ...)
    op.create_table('agent_routing_stats', ...)
    op.create_table('routing_policies', ...)

def downgrade() -> None:
    # Drop new tables
    op.drop_table('routing_policies')
    op.drop_table('agent_routing_stats')
    op.drop_table('routing_feedback')
    op.drop_table('routing_scores')
    
    # Drop new columns (SQLite limitation: can't drop columns without recreating table)
    # For SQLite, downgrade is: recreate tables without new columns
    # For PostgreSQL: straightforward DROP COLUMN
```

---

## 6. API Changes

### 6.1 Agent Registration — Intake Field

**PATCH `/api/agents/{agent_id}`** — extended to accept `intake`:

```json
{
  "intake": {
    "categories": ["security", "security.vulnerability"],
    "negative_categories": ["clinical"],
    "source_types": ["nvd", "cisa_kev"],
    "keywords": ["cve", "exploit", "patch"],
    "systems": ["CrowdStrike", "Sentinel"],
    "priority_range": ["high", "critical"],
    "description": "Security vulnerability triage",
    "max_concurrent": 5,
    "sla_seconds": 600,
    "phi_allowed": false
  }
}
```

**POST `/api/agents`** — same extension to `AgentCreate`. Intake is optional; omitting it = rules-based routing only.

**Response additions for both create and update:**
```json
{
  "agent_id": "security-triage",
  "intake_warnings": [
    "High overlap (0.73) with agent 'it-help-desk' on categories: ['incident', 'security']"
  ],
  "intake_errors": []
}
```

### 6.2 New: Policy CRUD

**`GET /api/policies`** — list all routing policies.

**`POST /api/policies`** — create a new policy. Requires management auth.
```json
{
  "policy_id": "phi-isolation",
  "name": "PHI Isolation — No External Agents",
  "policy_type": "veto",
  "trigger_conditions": {"payload.data._classification.phi_detected": true},
  "action": {"veto_if": {"phi_allowed": false}},
  "audit_reason": "HIPAA Privacy Rule — 45 CFR 164.502",
  "created_by": "eric.obrien@hf.org"
}
```

**`PUT /api/policies/{policy_id}`** — update policy (active flag, conditions, etc.)

**`DELETE /api/policies/{policy_id}`** — deactivate (soft delete).

### 6.3 New: Routing Score Inspection

**`GET /api/routing/scores/{envelope_id}`** — returns the full scoring breakdown for a given envelope:
```json
{
  "envelope_id": "abc-123",
  "scored_at": "2026-03-08T12:00:00Z",
  "routing_mode": "scored",
  "scores": [
    {
      "agent_id": "security-triage",
      "score": 0.847,
      "dimensions": {
        "category": 1.0,
        "source_type": 1.0,
        "keyword": 0.72,
        "system": 0.8,
        "priority": 1.0,
        "historical_multiplier": 1.18,
        "load_multiplier": 0.95,
        "base_score": 0.904
      },
      "cold_start": false,
      "selected": true,
      "dispatch_role": "primary"
    },
    {
      "agent_id": "it-help-desk",
      "score": 0.312,
      "dimensions": {...},
      "selected": false
    }
  ],
  "routing_decision": {
    "primary": "security-triage",
    "cc": [],
    "confidence": "high",
    "policies_applied": ["shadow-gate"]
  }
}
```

This endpoint is critical for debugging and operator trust-building.

### 6.4 New: Routing Mode Control

**`GET /api/routing/mode`** — returns current routing mode.

**`PUT /api/routing/mode`** — changes routing mode. Requires management auth.
```json
{
  "mode": "shadow",          // "rules" | "scored" | "shadow" | "hybrid"
  "shadow_percentage": 100,  // % of traffic scored in shadow mode
  "hybrid_threshold": 0.40   // Below this score, fall back to rules (hybrid mode only)
}
```

Mode is stored in the database (not env var alone) so it survives process restarts. The env var `ROUTING_MODE` is the startup default; DB value overrides it.

### 6.5 New: Feedback Submission

**`POST /api/routing/feedback/{envelope_id}`** — submit manual routing outcome (for human review in assisted maturity):
```json
{
  "outcome": "human_correct",    // or "human_incorrect"
  "reviewer_id": "kim.alkire@hf.org",
  "notes": "Correctly routed to security triage"
}
```

### 6.6 New: Shadow Mode Comparison Report

**`GET /api/routing/shadow-report`** — aggregated comparison of shadow scorer vs. rules engine:
```json
{
  "period": "last_7_days",
  "total_envelopes": 2847,
  "agreement_rate": 0.92,
  "disagreements": {
    "count": 228,
    "scorer_would_choose_differently": [
      {
        "source_type": "teams",
        "rules_routed_to": "it-help-desk",
        "scorer_would_route_to": "sam-hr",
        "frequency": 47,
        "avg_score_difference": 0.23
      }
    ]
  },
  "unroutable_by_scorer": 12,
  "unroutable_by_rules": 8
}
```

---

## 7. Implementation Stories

Stories are ordered by dependency. A developer can pick up any story and implement it without asking clarifying questions — all design decisions are made here.

---

### Story 13.1 — Agent Intake Schema + Storage
**Effort:** 0.5 day  
**Depends on:** Nothing

**What:** Add `intake` JSON field to Agent model, validate on registration, store, and return.

**Acceptance Criteria:**
- `AgentCreate` and `AgentUpdate` schemas accept optional `intake: AgentIntake | None`
- `AgentIntake` Pydantic model validates all fields (types, enum values for priority_range)
- `intake` stored as JSON in `agents.intake` column (Alembic migration provided)
- `AgentRead` response includes `intake` field
- If `intake.negative_categories` overlaps with `intake.categories`, validation error

**Tests:**
- `test_agent_intake_schema`: valid intake round-trips through API
- `test_agent_intake_validation`: negative_categories overlapping categories → 422
- `test_agent_intake_optional`: agents without intake accepted (backward compat)
- `test_agent_intake_hierarchical_categories`: dot-notation categories stored correctly

**Files to create/modify:**
- `trellis/schemas.py` — add `AgentIntake`, `TimeConstraints`; update `AgentCreate`, `AgentUpdate`, `AgentRead`
- `trellis/models.py` — add `intake`, `phi_allowed`, `max_concurrent`, `tags` columns
- `alembic/versions/XXXX_phase13_intelligent_routing.py` — migration

---

### Story 13.2 — Overlap Validation
**Effort:** 0.5 day  
**Depends on:** 13.1

**What:** When registering or updating an agent's intake, compute overlap against all existing agents and return warnings or errors.

**Acceptance Criteria:**
- On `POST /api/agents` and `PATCH /api/agents/{agent_id}`, response includes `intake_warnings: list[str]` and `intake_errors: list[str]`
- Overlap score ≥ 0.70: warning message (registration succeeds)
- Overlap score ≥ 0.90: error message (registration blocked; returns 409 with detail)
- Overlap score formula implemented as specified in §4.1.5
- Overlap only computed when intake is provided

**Tests:**
- `test_overlap_no_agents`: no other agents → no warnings
- `test_overlap_warning`: second agent with 0.75 overlap → warning returned
- `test_overlap_error`: second agent with 0.91 overlap → 409 error
- `test_overlap_skips_self`: updating agent doesn't compare against itself

**Files to create/modify:**
- `trellis/api.py` — agent create/update endpoints
- New `trellis/scoring/overlap.py` — `compute_intake_overlap(intake_a, intake_b) -> float`

---

### Story 13.3 — Scoring Engine (Core)
**Effort:** 1.5 days  
**Depends on:** 13.1

**What:** Implement the multi-dimensional scoring engine. Score all agents against an envelope. Return ranked list.

**Acceptance Criteria:**
- All 5 dimension functions implemented per §4.2.2 spec
- Hierarchical category matching per §4.1.3 (exact, parent, child, sibling)
- Negative category hard-zero per §4.1.4
- Historical multiplier: returns 1.0 for agents with < 10 samples
- Load multiplier: returns 1.0 at ≤50% utilization, 0.0 at ≥100%
- Weights configurable via `settings.scoring_weights` (dict with 5 keys, must sum to 1.0)
- `score_all_agents()` runs in < 10ms for 100 agents (pure computation, no DB calls in hot path)
- Returns `list[ScoredAgent]` sorted by score descending

**Tests:**
- `test_score_exact_category_match`: agent with exact category gets 1.0 category score
- `test_score_parent_category`: agent declares "security", envelope is "security.vulnerability" → 0.8
- `test_score_negative_category_veto`: agent with negative_category matching → score=0.0
- `test_score_no_intake`: agent with no intake → excluded from scored results
- `test_score_cold_start_neutral`: agent with 0 history → historical_multiplier=1.0
- `test_score_load_penalty`: agent at 90% capacity → score reduced
- `test_score_full_pipeline`: end-to-end with 5 agents, verify ranking order
- `test_score_performance`: 100 agents scored in < 10ms (pytest benchmark)

**Files to create:**
- `trellis/scoring/__init__.py`
- `trellis/scoring/dimensions.py` — all 5 dimension functions
- `trellis/scoring/engine.py` — `score_all_agents()`, `ScoredAgent` dataclass
- `trellis/scoring/categories.py` — `category_match_score()`, hierarchy logic

---

### Story 13.4 — Policy Layer
**Effort:** 1 day  
**Depends on:** 13.1

**What:** Implement the Policy model, CRUD API, and pre/post-score evaluation.

**Acceptance Criteria:**
- `routing_policies` table created via migration
- `Policy` Pydantic schema and SQLAlchemy model
- CRUD endpoints: GET list, POST, PUT, DELETE (soft delete: sets `active=False`)
- Pre-score filter: `apply_pre_score_policies(envelope, all_agents, policies) -> eligible_agents`
  - PHI veto: agents without phi_allowed filtered if phi_detected=true
  - Shadow gate: maturity=shadow agents always filtered
  - Anti-circular: agents in routing_path filtered
  - Department/facility scope filtering
- Post-score enforcement: `apply_post_score_policies(envelope, scored_agents, policies) -> RoutingDecision`
  - Mandatory CC: append to dispatch list
  - Regulatory override: replace primary with policy-specified agent
  - After-hours redirect: replace primary if time condition matches
  - Threshold check: if top score < threshold → return unroutable decision
- All policy applications logged with `emit_audit("policy_applied", details={"policy_id": ...})`

**Tests:**
- `test_policy_phi_veto`: phi_detected envelope → non-phi_allowed agents excluded
- `test_policy_shadow_gate`: shadow agent never in eligible list
- `test_policy_anti_circular`: agent in routing_path → excluded
- `test_policy_mandatory_cc`: compliance event → compliance agent added to dispatch
- `test_policy_after_hours`: mocked 2 AM → redirect to on-call agent
- `test_policy_threshold_unroutable`: all scores < 0.20 → unroutable decision
- `test_policy_conflict_require_wins_veto`: require policy overrides veto for same agent

**Files to create:**
- `trellis/scoring/policies.py` — Policy evaluation
- Update `trellis/models.py` — RoutingPolicy model
- Update `trellis/schemas.py` — Policy Pydantic schemas
- Update `trellis/api.py` — Policy CRUD endpoints

---

### Story 13.5 — Routing Decision + Score Logging
**Effort:** 0.5 day  
**Depends on:** 13.3, 13.4

**What:** Wire scoring + policy into the routing pipeline. Log scoring decisions. Return `RoutingDecision`.

**Acceptance Criteria:**
- New `RoutingDecision` dataclass: `{primary: str | None, cc: list[str], confidence: str, unroutable: bool, scores: list[ScoredAgent], policies_applied: list[str]}`
- `route_scored(envelope, db) -> RoutingDecision` implemented
- `routing_scores` table populated for every scored routing attempt
- `envelope_log` columns `routing_mode`, `routing_score`, `routing_confidence` populated
- Shadow mode: `route_scored()` called but `RoutingDecision.shadow_only=True` → not dispatched
- `GET /api/routing/scores/{envelope_id}` returns full score breakdown

**Tests:**
- `test_route_scored_basic`: envelope with matching agent → correct primary selected
- `test_route_scored_multi_dispatch`: server breach scenario → co-primary dispatch
- `test_route_scored_shadow`: shadow mode → score logged, no dispatch
- `test_route_scored_unroutable`: no agents above threshold → unroutable logged

**Files to modify:**
- `trellis/router.py` — add `route_scored()`, modify `route_envelope()` to check ROUTING_MODE
- `trellis/api.py` — add `GET /api/routing/scores/{envelope_id}` endpoint

---

### Story 13.6 — Feedback Collection
**Effort:** 0.5 day  
**Depends on:** 13.5

**What:** Capture routing outcomes and expose human review API.

**Acceptance Criteria:**
- `collect_routing_feedback()` called by dispatcher after each dispatch (outcome: success, timeout, error)
- Agent returning `status="not_my_domain"` → outcome=rejected
- Re-routing detection: if same trace_id routed to different agent within 60 min → outcome=rerouted on first agent
- `POST /api/routing/feedback/{envelope_id}` for human review submissions
- `routing_feedback` table populated

**Tests:**
- `test_feedback_success`: completed dispatch → success feedback recorded
- `test_feedback_rejection`: agent returns not_my_domain → rejected feedback recorded
- `test_feedback_human_review`: POST to feedback endpoint updates outcome
- `test_feedback_rerouting`: same trace routed twice → first gets rerouted outcome

**Files to modify:**
- `trellis/router.py` — call `collect_routing_feedback()` after dispatch
- `trellis/api.py` — add `POST /api/routing/feedback/{envelope_id}`
- New `trellis/scoring/feedback.py` — feedback collection logic

---

### Story 13.7 — Daily Weight Updater
**Effort:** 0.5 day  
**Depends on:** 13.6

**What:** Implement the daily batch job that recalculates `agent_routing_stats`.

**Acceptance Criteria:**
- `update_routing_stats()` aggregates `routing_feedback` for last 90 days
- Exponential moving average with α=0.15
- Minimum 10 samples before updating (below 10: leave as-is or initialize at 0.5)
- Hard bounds [0.10, 0.98] enforced
- Runs as a scheduled task at 2 AM daily (add to Rule Optimizer's schedule OR new housekeeping entry)
- `agent_routing_stats` table updated atomically (transaction: all updates or none)

**Tests:**
- `test_weight_update_cold_start`: < 10 samples → stats not updated
- `test_weight_update_ema`: verifies EMA formula with known inputs
- `test_weight_update_bounds`: raw_rate=0.0 → stored as 0.10; raw_rate=1.0 → stored as 0.98
- `test_weight_update_atomic`: simulated DB error mid-update → no partial updates

**Files to create/modify:**
- New `trellis/scoring/weight_updater.py`
- Update housekeeping agent schedule (or add new housekeeping agent entry)

---

### Story 13.8 — Agent Load Tracking
**Effort:** 0.5 day  
**Depends on:** 13.5

**What:** Track in-flight envelope counts per agent for load factor calculation.

**Acceptance Criteria:**
- `AgentLoad` singleton initialized on startup
- `increment(agent_id)` called when dispatch starts
- `decrement(agent_id)` called when dispatch completes (success, error, timeout — always)
- Load data available to scoring engine via `load_cache` parameter
- Health Auditor exposes `get_load_snapshot() -> dict[str, dict]` for external use
- Thread/coroutine safe (asyncio.Lock)

**Tests:**
- `test_load_increment_decrement`: count goes up and down correctly
- `test_load_always_decrement`: even on exception, decrement called
- `test_load_thread_safe`: concurrent increments don't corrupt count

**Files to create:**
- New `trellis/scoring/load_tracker.py`

---

### Story 13.9 — Routing Mode API + Shadow Report
**Effort:** 0.5 day  
**Depends on:** 13.5

**What:** Implement routing mode control API and shadow comparison report.

**Acceptance Criteria:**
- `routing_mode` persisted in a simple `platform_config` key-value table (not env-var only)
- `GET /api/routing/mode` returns current mode
- `PUT /api/routing/mode` changes mode (management auth required)
- Shadow mode: every envelope processed by both rules and scorer; logs comparison
- `GET /api/routing/shadow-report` aggregates last 7 days of shadow comparisons
- Agreement rate calculation: scored top agent == rules target agent

**Tests:**
- `test_routing_mode_persistence`: set mode via API, survives process context
- `test_shadow_mode_both_run`: shadow mode runs both, only rules dispatches
- `test_shadow_report_agreement`: mock data → correct agreement rate calculation

**Files to create/modify:**
- Update `trellis/api.py` — routing mode endpoints, shadow report endpoint
- New `trellis/scoring/shadow.py` — shadow comparison logic

---

### Story 13.10 — Intake Declaration for Existing Agents
**Effort:** 0.5 day  
**Depends on:** 13.1

**What:** Add intake declarations to all existing native agents and seed policies.

**Acceptance Criteria:**
- Security Triage Agent: intake declared per §4.1.2 example
- IT Help Desk Agent: intake declared
- SAM HR Agent: intake declared (`categories: ["hr"]`, `source_types: ["hr_system", "ukg", "peoplesoft", "teams"]`, etc.)
- Rev Cycle Agent: intake declared
- All housekeeping agents: `categories: ["platform"]`, `department_scope: ["platform"]`
- Seed policies created via `alembic/seed_policies.py` script:
  - PHI Isolation policy
  - Shadow Agent Gate policy
  - Anti-Circular policy
  - (Compliance CC and After-Hours: placeholder, marked inactive pending Eric review)

**Tests:**
- `test_existing_agents_have_intake`: all agents in seed data have intake
- `test_seed_policies_loaded`: PHI and Shadow Gate policies exist and active

**Files to modify:**
- Agent seed data / registration scripts
- New `alembic/seed_policies.py`

---

### Story 13.11 — Dashboard: Routing Intelligence Tab
**Effort:** 1 day  
**Depends on:** 13.5, 13.9

**What:** Add routing intelligence visibility to the Next.js dashboard.

**Acceptance Criteria:**
- New "Routing" tab in dashboard sidebar
- **Mode indicator**: current routing mode with toggle (requires admin)
- **Score explorer**: pick any envelope from recent log → show full score breakdown table
- **Shadow report**: bar chart showing agreement rate over last 7 days
- **Policy list**: table of active policies with name, type, trigger summary, last triggered count
- **Agent overlap heatmap**: matrix of agent pairs with overlap scores (hover for detail)
- All data fetched from new API endpoints (§6)

**Tests:**
- Visual review (manual) — screenshots in PR description
- E2E: score explorer shows correct dimensions for a test envelope

**Files to create:**
- `dashboard/src/app/routing/page.tsx`
- `dashboard/src/components/ScoreExplorer.tsx`
- `dashboard/src/components/PolicyList.tsx`
- `dashboard/src/components/AgentOverlapMatrix.tsx`

---

## 8. Migration Plan

### Phase 1: Foundation (Stories 13.1, 13.2, 13.3)
**Timeline:** Days 1-3  
**Risk:** Low — pure additions, nothing changes for existing routing

Deploy with `ROUTING_MODE=rules`. The scorer runs but nothing uses it yet. Add intake declarations to agents via API. Run overlap validation against all existing agents — fix any surprises.

Smoke test: all existing tests still pass. New scoring tests pass.

### Phase 2: Infrastructure + Shadow (Stories 13.4-13.9)
**Timeline:** Days 4-6  
**Risk:** Low — shadow mode logs but doesn't affect traffic

Deploy with `ROUTING_MODE=shadow`. Real traffic still routes through rules. Scorer runs on every envelope, logs what it would have done.

Monitor for 5-7 days:
- Check `GET /api/routing/shadow-report` daily
- Target: ≥90% agreement rate before switching
- Investigate every disagreement category — is the scorer right or wrong?
- Tune intake declarations if scorer is systematically wrong on specific event types

If agreement rate < 80% after 7 days: investigate, fix intake declarations, extend shadow period. Don't switch early.

### Phase 3: Hybrid Mode (Day 7-8)
**Timeline:** Days 7-8  
**Risk:** Medium — scorer handles some traffic

Switch to `ROUTING_MODE=hybrid` with `hybrid_threshold=0.40`. Envelopes where scorer is confident (top score ≥ 0.40) use scored routing. Envelopes below threshold fall back to rules.

Monitor:
- `routing_mode` breakdown in envelope logs (what % is "hybrid_scored" vs "hybrid_rules"?)
- Error rates per routing mode
- Any increase in dead-letter rate?

If no regressions after 48 hours: raise threshold to 0.25 (more traffic to scorer).

### Phase 4: Full Scored Routing (Day 9-10)
**Timeline:** Days 9-10  
**Risk:** Low if Phase 3 went well

Switch to `ROUTING_MODE=scored`. Rules engine still exists as fallback (agents without intake declarations still use rules).

**Rollback procedure:**
1. `PUT /api/routing/mode {"mode": "rules"}` — instant, survives no restarts
2. Or set env var `ROUTING_MODE=rules` and restart — slightly slower but equally safe
3. All scored routing data is preserved for post-mortem analysis

**Phase 5: Policy Migration + Rule Cleanup (Post Phase 4)**

Once scored routing is stable:
1. Audit all remaining rules in DB
2. Convert remaining routing rules to intake declarations
3. Convert governance rules to policies
4. Deprecate pure routing rules
5. Target: 0 active rules of `rule_class=routing`, ≤10 active policies

### Rollback Triggers

Immediately roll back to `ROUTING_MODE=rules` if:
- Dead-letter rate increases by > 2x compared to rules baseline
- Any envelope type that was previously routing successfully starts failing
- Agent error rates increase materially (> 20% increase)
- A HIPAA/PHI policy is bypassed (audit alert)

The rollback is one API call. We're never more than one config change from safety.

### Proving Success Metrics

| Metric | Baseline (Rules) | Target (Scored) | How Measured |
|---|---|---|---|
| Routing accuracy | N/A (no ground truth) | ≥92% vs human label | Manual review of 100-envelope test set |
| Dead-letter rate | Measure pre-Phase 2 | ≤ baseline | `routing_outcome=unroutable` count |
| New agent onboard time | ~2 days (rule authoring) | < 2 hours (intake + test) | Track manually |
| Rules count | Current count | < 10 policies | `SELECT COUNT(*) FROM rules WHERE active=true` |
| Re-routing rate | Measure pre-Phase 2 | < 5% of envelopes | `routing_outcome=rerouted` count |
| Shadow agreement | N/A | ≥90% before switch | Shadow report API |

---

## 9. Performance Budget

### Current Baseline
- Rule matching: < 1ms (pure in-memory, sorted list scan)
- Classification Engine: < 5ms (pure computation, no I/O)
- Total routing path (pre-dispatch): < 10ms

### Target (Scored Routing)
- Pre-score policy filter: < 2ms
- Scoring 100 agents: < 15ms
- Post-score policy enforcement: < 3ms
- Score logging (async, non-blocking): < 1ms visible latency
- **Total routing path target: < 25ms**

### Why 25ms is Acceptable
The 25ms is for the routing decision itself. Actual agent processing (LLM inference, tool calls) takes 100ms-10,000ms. Adding 15ms to the routing decision is imperceptible.

If scoring grows beyond 50ms, we have a problem. See caching strategy.

### Caching Strategy

**Agent intake cache** (hot path)
- In-memory dict: `agent_id → AgentIntake`
- Populated on startup, invalidated on agent registration/update
- Refresh: triggered by API changes, NOT time-based
- Cost: ~100 bytes per agent × 100 agents = 10KB (trivial)

**Routing stats cache** (historical weights)
- In-memory dict: `"{agent_id}:{category}" → {success_rate, sample_count}`
- Populated on startup from `agent_routing_stats` table
- Refresh: daily at 2 AM (when batch update runs) + on-demand via API
- Cost: ~100 agents × 20 categories × 50 bytes = 100KB (trivial)

**Agent load cache** (load factors)
- In-memory `AgentLoad` singleton (see §4.5)
- Updated in real-time by dispatcher (increment/decrement)
- No DB reads in hot path
- Cost: `int × 100 agents` = negligible

**Policy cache**
- In-memory list of active policies
- Populated on startup, invalidated on policy CRUD
- Cost: < 10 policies × 500 bytes = 5KB (trivial)

**What is NOT cached**
- Agent eligibility (which agents are eligible for a given envelope) — computed per-envelope from cached data, no DB query
- Score results — not cached; envelopes are unique, caching buys nothing
- Classification Engine output — already computed in request path, passed to scorer directly

### Scaling to 1000 Envelopes/Minute

1000/min = ~17/second. With 100ms average routing path:
- 17 concurrent routing operations at steady state
- Peak handling: FastAPI async, no blocking in scoring path, negligible CPU per envelope
- DB load: 17 writes/second to `routing_scores` + `envelope_log` — SQLite handles ~10K writes/second in WAL mode; PostgreSQL handles millions
- Bottleneck will be agent dispatch (LLM inference), not routing itself

At 10,000/minute, review: batch score logging, connection pooling, and potentially move score logging to a separate async queue.

---

## 10. Risk Analysis

### Risk 1: Intake Declarations Are Wrong
**Likelihood:** Medium (especially at first)  
**Impact:** Medium (wrong routing until corrected)  
**Mitigation:**
- Shadow mode run of 5-7 days before switching. We'll see disagreements before they affect traffic.
- Score explorer API lets operators inspect why any envelope was routed a certain way.
- Overlap validation catches obviously conflicting declarations at registration time.
- Cold start is neutral (1.0 multiplier), so a new agent with a bad declaration just loses to better-declared agents rather than stealing traffic aggressively.

### Risk 2: Historical Feedback Loop Destabilizes Routing
**Likelihood:** Low  
**Impact:** High (if one agent monopolizes all traffic)  
**Mitigation:**
- Multiplier hard bounds [0.70, 1.30] prevent runaway scores.
- Monthly Rule Optimizer check for category monopolies.
- Batch updates (daily, not real-time) add damping.
- Load factor naturally distributes traffic when any agent approaches capacity.

### Risk 3: PHI Policy Bypass
**Likelihood:** Very Low (structural enforcement, not convention)  
**Impact:** Critical (HIPAA incident)  
**Mitigation:**
- PHI veto is a pre-score filter, not a score penalty. If phi_detected=true AND agent.phi_allowed=false, the agent is excluded before scoring even begins. There is no score high enough to route around it.
- `phi_detected` comes from the Classification Engine (PHI Shield), which already exists.
- Every policy application audit logged. PHI-related policy applications should alert to CISO dashboard.
- **Risk residual:** Classification Engine failing to detect PHI in an envelope. This is a Classification Engine risk, not a routing risk. Existing PHI Shield testing covers this.

### Risk 4: Circular Routing Loop
**Likelihood:** Low  
**Impact:** Medium (envelope stuck in loop, resource waste)  
**Mitigation:**
- `routing_path` tracked in envelope, anti-circular policy enforced before scoring.
- Maximum routing depth: 3 hops (configurable). Beyond 3: dead letter automatically.
- Circular detection in Policy Layer (pre-score, so it can't score its way past it).

### Risk 5: No Agent Above Threshold (Unroutable)
**Likelihood:** Medium for unusual envelope types  
**Impact:** Low-Medium (envelope lost until human triage)  
**Mitigation:**
- Unroutable envelopes go to dead-letter queue (existing), not dropped.
- Dashboard alert when dead-letter queue grows.
- Every unroutable event logs full scoring breakdown — easy to diagnose which intake declarations need updating.
- Hybrid mode keeps rules as fallback for envelopes scoring below threshold.

### Risk 6: Cold Start for Platform Itself (Day 1 of Scored Routing)
**Likelihood:** Certain (all agents start cold)  
**Impact:** Low (shadow mode runs first, gives us data)  
**Mitigation:**
- Shadow mode period seeds `routing_feedback` with outcomes.
- Day 1 of scored routing: all agents have history from shadow period.
- The scorer isn't cold — agents are. Scorer runs on intake declarations from Day 1.

### Risk 7: Performance Regression Under Load
**Likelihood:** Low  
**Impact:** Medium (routing latency increases)  
**Mitigation:**
- Performance test in Story 13.3 (< 10ms for 100 agents, pure compute).
- All caches are in-memory with O(1) or O(n) lookup where n ≤ 200.
- Load testing before Phase 4 switch.
- Monitor p95 routing latency in Application Insights.

---

## 11. Open Questions

These require Eric's input before implementation can be finalized.

**Q1: After-Hours Routing — Do We Have On-Call Agents?**
The Policy Layer design includes time-based routing (`business_hours_only` + `fallback_agent_id`). This only works if there IS an after-hours fallback agent for IT and clinical routing. Does Health First have a designated on-call agent (or human-escalation path) we should route to after hours? Or should after-hours critical events just go to the same agent with a priority flag?

**Q2: PHI in Envelope Payloads — Current Exposure Level?**
The Classification Engine has a PHI Shield (mode: audit_only by default). For the PHI isolation policy to work, we need `phi_detected: true` to be reliable. Is the PHI Shield currently in audit_only mode or active detection? Should we activate it before Phase 13 ships? This affects whether the PHI isolation policy is structural protection or theater.

**Q3: Human Review Queue — Who Reviews?**
For `maturity=assisted` agents, the feedback loop includes human reviewer confirmation. Who in the org reviews these? Is this a platform team function, department function, or will we build a reviewer assignment system? The feedback submission API (`POST /api/routing/feedback/{envelope_id}`) assumes we know who the reviewer is. If there's no review process defined, assisted-maturity feedback just won't come in, and we'll only have automated signals.

**Q4: Facilities Scoping — Which Departments/Facilities Need It?**
The intake schema includes `department_scope` and `facility_scope` lists. If empty, the agent is enterprise-wide. Are there current or planned agents that should only serve specific hospitals (e.g., a Rockledge FSED-specific agent, or a Cape Canaveral-specific clinical agent)? If yes, what are the scope identifiers we should use (facility codes from Epic? IDs from PeopleSoft?).

**Q5: Regulatory Override Policy — Which Source Types Are Mandatory to Compliance?**
The design includes a policy that routes certain events to the Compliance agent regardless of score. Which source types or categories should trigger this? CMS and OIG events are obvious. What about CISA KEV alerts (they could be HIPAA-relevant)? Revenue Cycle denials? This policy should be defined with Kim Alkire (CISO).

**Q6: Scoring Weights — Accept Defaults or Tune First?**
Default weights are: Category 30%, Source Type 25%, Keyword 20%, System 15%, Priority 10%. These were derived logically but not empirically. Should we run the shadow mode comparison with these weights first and tune based on disagreement analysis? Or does Eric have a gut feel for whether, say, Source Type should be weighted higher than Keyword in Health First's specific context?

**Q7: Target: Zero Rules or Coexistence?**
The current design targets eventual elimination of pure routing rules (replacing them with intake declarations + policies). Is that the right goal? Or should we keep rules as a power-user escape hatch for unusual routing needs that don't fit the intake model? My recommendation is keep rules available but deprecated — a rules engine that nobody uses is harmless, but removing it eliminates an escape hatch we might regret losing. But Eric should decide.

**Q8: Scoring Transparency to Departments?**
Should department admins see score breakdowns for their agents' envelopes? Currently the Score Explorer is platform-admin only (in the design). Making it visible to department admins could help them tune their intake declarations but also creates confusion if they don't understand the scoring dimensions. Should we expose a simplified "why did this go to my agent?" view to department admins?

---

## Appendix A: File Layout

```
trellis/
├── scoring/
│   ├── __init__.py
│   ├── engine.py          # score_all_agents(), ScoredAgent dataclass
│   ├── dimensions.py      # 5 dimension functions
│   ├── categories.py      # category_match_score(), hierarchy logic
│   ├── policies.py        # Policy evaluation (pre/post score)
│   ├── feedback.py        # collect_routing_feedback()
│   ├── weight_updater.py  # Daily batch: update_routing_stats()
│   ├── load_tracker.py    # AgentLoad singleton
│   ├── overlap.py         # compute_intake_overlap()
│   └── shadow.py          # Shadow mode comparison
├── models.py              # + RoutingPolicy, RoutingScore, RoutingFeedback, AgentRoutingStats
├── schemas.py             # + AgentIntake, TimeConstraints, Policy schemas
├── router.py              # + route_scored(), routing mode check
└── api.py                 # + Policy CRUD, Score Inspector, Mode Control, Feedback endpoints
```

## Appendix B: Scoring Worked Example

**Scenario:** CrowdStrike alert — lateral movement detected on `WIN-HOSP-EMR-07`, CVSS 9.3

**After Classification Engine:**
```
routing_hints.category = "security"
routing_hints.tags = ["crowdstrike", "lateral movement", "cve-2025-1234", "epic", "win-hosp"]
metadata.priority = "CRITICAL"
```

**Agents being scored:**

| Agent | Categories | Source Types | Keywords | Systems | Priority Range |
|---|---|---|---|---|---|
| security-triage | security, security.vulnerability | nvd, cisa_kev, crowdstrike | cve, exploit, breach, malware | CrowdStrike, Sentinel | high, critical |
| it-help-desk | incident | ivanti, servicenow, teams | outage, printer, vpn, password | Ivanti, LogicMonitor | low, normal, high |
| clinical-ops | clinical | epic, hl7 | patient, order, medication | Epic | normal, high, critical |

**Scoring:**

Security Triage:
- Category: "security" vs "security" = 1.0 × 0.30 = 0.300
- Source: "crowdstrike" in [nvd, cisa_kev, crowdstrike] = 1.0 × 0.25 = 0.250
- Keyword: envelope_tags={"crowdstrike","lateral movement","cve-2025-1234"} ∩ agent_keywords={"cve","exploit","breach","malware"} → "cve" matches, Jaccard ≈ 0.10, + CVE bonus 0.05 = 0.15 × 0.20 = 0.030
- System: {"crowdstrike","epic","win-hosp"} ∩ {"crowdstrike","sentinel"} = {"crowdstrike"} = 0.40 × 0.15 = 0.060
- Priority: "CRITICAL" in ["high","critical"] = 1.0 × 0.10 = 0.100
- **Base: 0.740**
- Historical: success_rate=0.91 → multiplier=1.246
- Load: 2/5 in-flight = 40% utilization → multiplier=1.0
- **Final: 0.740 × 1.246 × 1.0 = 0.922**

IT Help Desk:
- Category: "security" vs "incident" = 0.0 × 0.30 = 0.000
- Source: "crowdstrike" not in [ivanti, servicenow, teams] = 0.0 × 0.25 = 0.000
- Keyword: {"crowdstrike","lateral movement"} ∩ {"outage","printer","vpn","password"} = {} → Jaccard = 0.0 × 0.20 = 0.000
- System: no overlap = 0.0 × 0.15 = 0.000
- Priority: "CRITICAL" not in ["low","normal","high"] = 0.0 × 0.10 = 0.000
- **Base: 0.000**
- **Final: 0.000**

Clinical Ops:
- Category: "security" vs "clinical" = 0.0 × 0.30 = 0.000
- But "epic" appears in tags AND "security" is in clinical-ops negative_categories = **HARD ZERO**
- **Final: 0.000** (excluded by negative_category)

**Decision:**
- Security Triage: 0.922 (high confidence)
- IT Help Desk: 0.000
- Clinical Ops: 0.000

No multi-dispatch trigger (only one agent scored above threshold). Route to Security Triage. Confidence: "high".

The "server breach" example is actually straightforward for Security Triage because CrowdStrike is a declared source. The ambiguous case is a Teams message saying "server is down and I think we've been hacked" — that's where co-primary dispatch would trigger (IT Help Desk and Security both score 0.6+).

---

*Design document complete. Ready for Eric review of Open Questions before implementation begins.*

*Next step: Eric reviews §11, makes decisions, implementation begins with Story 13.1.*
