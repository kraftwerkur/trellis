"""
Prompt complexity scorer — ports Manifest's 23-dimension scoring engine.

Routes LLM requests to the cheapest viable model tier:
  simple → standard → complex → reasoning

Single-file, stdlib-only. Direct port from TypeScript with healthcare keywords added.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Literal

# ── Types ──

Tier = Literal["simple", "standard", "complex", "reasoning"]
TIERS: list[Tier] = ["simple", "standard", "complex", "reasoning"]

ScoringReason = Literal[
    "scored", "formal_logic_override", "tool_detected", "large_context",
    "short_message", "momentum", "ambiguous", "heartbeat",
]


@dataclass
class DimensionScore:
    name: str
    raw_score: float
    weight: float
    weighted_score: float
    matched_keywords: list[str] | None = None


@dataclass
class MomentumInfo:
    history_length: int
    history_avg_score: float
    momentum_weight: float
    applied: bool


@dataclass
class ScoringResult:
    tier: Tier
    score: float
    confidence: float
    reason: ScoringReason
    dimensions: list[DimensionScore]
    momentum: MomentumInfo | None


@dataclass
class TierBoundaries:
    simple_max: float = -0.10
    standard_max: float = 0.08
    complex_max: float = 0.35


@dataclass
class DimensionConfig:
    name: str
    weight: float
    direction: Literal["up", "down"]
    keywords: list[str] | None = None


@dataclass
class ScorerConfig:
    dimensions: list[DimensionConfig] = field(default_factory=list)
    boundaries: TierBoundaries = field(default_factory=TierBoundaries)
    confidence_k: float = 8.0
    confidence_midpoint: float = 0.15
    confidence_threshold: float = 0.45


# ── Keywords ──

DEFAULT_KEYWORDS: dict[str, list[str]] = {
    "formalLogic": [
        "prove", "proof", "derive", "derivation", "theorem", "lemma",
        "corollary", "if and only if", "iff", "contradiction",
        "contrapositive", "induction", "deduction", "axiom", "postulate",
        "qed", "formally verify", "satisfiability", "soundness",
        "completeness", "undecidable", "reducible",
        "irrational", "rational", "conjecture", "hypothesis",
    ],
    "analyticalReasoning": [
        "compare", "contrast", "evaluate", "assess", "trade-offs",
        "tradeoffs", "pros and cons", "advantages and disadvantages",
        "weigh", "critically analyze", "strengths and weaknesses",
        "implications", "ramifications", "nuance", "on the other hand",
        "counterargument", "analyze", "analysis", "explain",
    ],
    "codeGeneration": [
        "write a function", "implement", "create a class",
        "build a component", "write code", "write a script", "code this",
        "program this", "create an api", "build a module", "scaffold",
        "boilerplate", "write a test", "write tests", "generate code",
        "component", "endpoint", "handler", "controller",
        "write a component", "create a component", "build a service",
        "implementing", "implemented", "implementation",
    ],
    "codeReview": [
        "fix this bug", "debug", "why does this fail",
        "review this code", "what's wrong with", "code review", "refactor",
        "optimize this code", "find the error", "stack trace", "exception",
        "segfault", "memory leak", "race condition", "deadlock",
        "off by one", "typeerror", "referenceerror", "syntaxerror",
        "vulnerabilities", "vulnerability",
    ],
    "technicalTerms": [
        "algorithm", "kubernetes", "distributed", "microservice",
        "database", "architecture", "infrastructure", "deployment",
        "pipeline", "middleware", "encryption", "authentication",
        "authorization", "latency", "throughput", "concurrency",
        "parallelism", "serialization", "deserialization",
        "react", "graphql", "typescript", "docker", "sql", "redis",
        "frontend", "backend", "server", "api", "oauth",
        "repositories", "repository", "security",
        # Healthcare-specific
        "hl7", "fhir", "hipaa", "phi", "ehr", "emr", "epic",
        "dicom", "icd-10", "snomed", "loinc", "cerner", "meditech",
        "interoperability", "clinical", "telehealth",
    ],
    "simpleIndicators": [
        "what is", "define", "translate", "thanks", "thank you", "yes",
        "no", "ok", "okay", "sure", "got it", "hi", "hello", "hey",
        "bye", "goodbye", "how are you", "good morning", "good night",
        "please", "help", "what time", "where is", "who is",
    ],
    "multiStep": [
        "first", "then", "after that", "finally", "step 1", "step 2",
        "step 3", "next", "subsequently", "once you", "followed by",
        "in sequence", "phase 1", "phase 2", "stage 1", "stage 2",
        "workflow", "pipeline",
    ],
    "creative": [
        "story", "poem", "creative", "brainstorm", "imagine", "fiction",
        "narrative", "character", "plot", "dialogue", "write a song",
        "compose", "artistic", "metaphor", "allegory",
    ],
    "questionComplexity": [
        "how does x relate to y", "what are the implications",
        "why would", "what happens if", "under what conditions",
        "how would you approach", "what is the relationship between",
    ],
    "imperativeVerbs": [
        "build", "create", "update", "deploy", "send", "check", "run",
        "install", "configure", "set up", "launch", "publish", "submit",
        "execute", "start", "stop", "restart", "delete", "remove",
        "review", "optimize", "scan",
    ],
    "outputFormat": [
        "as json", "in json", "as yaml", "in yaml", "as csv", "markdown",
        "as a table", "in a table", "as xml", "formatted as", "output as",
        "return as", "in the format",
    ],
    "domainSpecificity": [
        "p-value", "confidence interval", "regression", "hipaa", "gdpr",
        "sec filing", "tort", "liability", "fiduciary", "amortization",
        "eigenvalue", "fourier transform", "bayesian", "posterior",
        "genome", "phenotype", "pharmacokinetics",
        "distribution", "probability", "statistics", "calculate",
        # Healthcare-specific
        "hl7", "fhir", "phi", "epic", "ehr", "emr", "dicom",
        "icd-10", "snomed", "loinc", "drg", "cpt", "ndc",
        "clinical trial", "adverse event", "formulary",
        "prior authorization", "claims adjudication", "revenue cycle",
        "meaningful use", "cms", "joint commission", "sdoh",
    ],
    "agenticTasks": [
        "triage", "audit", "investigate", "monitor", "orchestrate",
        "coordinate", "schedule", "prioritize", "delegate",
        "batch process", "scan all", "check all", "review all",
        "update all", "migrate", "remediation",
    ],
    "relay": [
        "forward to", "escalate", "transfer to", "pass along", "relay",
        "just say", "tell them", "send this to", "notify", "ping",
        "acknowledge", "confirm receipt", "mark as read",
    ],
}

# ── Default config ──

DEFAULT_CONFIG = ScorerConfig(
    dimensions=[
        DimensionConfig("formalLogic", 0.07, "up", DEFAULT_KEYWORDS["formalLogic"]),
        DimensionConfig("analyticalReasoning", 0.06, "up", DEFAULT_KEYWORDS["analyticalReasoning"]),
        DimensionConfig("codeGeneration", 0.06, "up", DEFAULT_KEYWORDS["codeGeneration"]),
        DimensionConfig("codeReview", 0.05, "up", DEFAULT_KEYWORDS["codeReview"]),
        DimensionConfig("technicalTerms", 0.07, "up", DEFAULT_KEYWORDS["technicalTerms"]),
        DimensionConfig("simpleIndicators", 0.08, "down", DEFAULT_KEYWORDS["simpleIndicators"]),
        DimensionConfig("multiStep", 0.07, "up", DEFAULT_KEYWORDS["multiStep"]),
        DimensionConfig("creative", 0.03, "up", DEFAULT_KEYWORDS["creative"]),
        DimensionConfig("questionComplexity", 0.03, "up", DEFAULT_KEYWORDS["questionComplexity"]),
        DimensionConfig("imperativeVerbs", 0.02, "up", DEFAULT_KEYWORDS["imperativeVerbs"]),
        DimensionConfig("outputFormat", 0.02, "up", DEFAULT_KEYWORDS["outputFormat"]),
        DimensionConfig("domainSpecificity", 0.05, "up", DEFAULT_KEYWORDS["domainSpecificity"]),
        DimensionConfig("agenticTasks", 0.03, "up", DEFAULT_KEYWORDS["agenticTasks"]),
        DimensionConfig("relay", 0.02, "down", DEFAULT_KEYWORDS["relay"]),
        DimensionConfig("tokenCount", 0.05, "up"),
        DimensionConfig("nestedListDepth", 0.03, "up"),
        DimensionConfig("conditionalLogic", 0.03, "up"),
        DimensionConfig("codeToProse", 0.02, "up"),
        DimensionConfig("constraintDensity", 0.03, "up"),
        DimensionConfig("expectedOutputLength", 0.04, "up"),
        DimensionConfig("repetitionRequests", 0.02, "up"),
        DimensionConfig("toolCount", 0.04, "up"),
        DimensionConfig("conversationDepth", 0.03, "up"),
    ],
    boundaries=TierBoundaries(-0.10, 0.08, 0.35),
    confidence_k=8.0,
    confidence_midpoint=0.15,
    confidence_threshold=0.45,
)


# ── Keyword Trie ──

@dataclass
class _TrieMatch:
    keyword: str
    dimension: str
    position: int


class _TrieNode:
    __slots__ = ("children", "terminals")

    def __init__(self) -> None:
        self.children: dict[str, _TrieNode] = {}
        self.terminals: list[tuple[str, str]] = []  # (keyword, dimension)


def _is_word_char(c: str) -> bool:
    o = ord(c)
    return (48 <= o <= 57) or (65 <= o <= 90) or (97 <= o <= 122) or o == 95


class KeywordTrie:
    MAX_SCAN_LENGTH = 100_000

    def __init__(self, dimensions: list[tuple[str, list[str]]]) -> None:
        self._root = _TrieNode()
        self._count = 0
        for dim_name, keywords in dimensions:
            for kw in keywords:
                self._insert(kw.lower(), dim_name)

    def _insert(self, keyword: str, dimension: str) -> None:
        node = self._root
        for ch in keyword:
            if ch not in node.children:
                node.children[ch] = _TrieNode()
            node = node.children[ch]
        node.terminals.append((keyword, dimension))
        self._count += 1

    def scan(self, text: str) -> list[_TrieMatch]:
        matches: list[_TrieMatch] = []
        lower = text.lower()
        length = min(len(lower), self.MAX_SCAN_LENGTH)

        for i in range(length):
            if i > 0 and _is_word_char(lower[i - 1]):
                continue
            node = self._root
            for j in range(i, length):
                child = node.children.get(lower[j])
                if child is None:
                    break
                node = child
                if node.terminals:
                    after_idx = j + 1
                    if after_idx < length and _is_word_char(lower[after_idx]):
                        continue
                    for kw, dim in node.terminals:
                        matches.append(_TrieMatch(kw, dim, i))
        return matches

    @property
    def size(self) -> int:
        return self._count


# ── Text Extractor ──

@dataclass
class _ExtractedText:
    text: str
    position_weight: float
    message_index: int


_EXCLUDED_ROLES = frozenset(("system", "developer"))


def _extract_text_from_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for el in content:
            if isinstance(el, dict) and isinstance(el.get("text"), str):
                parts.append(el["text"])
        return " ".join(parts)
    return str(content)


def _extract_user_texts(messages: list[dict[str, Any]]) -> list[_ExtractedText]:
    user_msgs: list[tuple[str, int]] = []
    for i, msg in enumerate(messages):
        role = msg.get("role", "")
        if role in _EXCLUDED_ROLES or role != "user":
            continue
        text = _extract_text_from_content(msg.get("content"))
        if text:
            user_msgs.append((text, i))

    total = len(user_msgs)
    result: list[_ExtractedText] = []
    for idx, (text, msg_idx) in enumerate(user_msgs):
        reverse_idx = total - 1 - idx
        if reverse_idx == 0:
            weight = 1.0
        elif reverse_idx == 1:
            weight = 0.5
        else:
            weight = 0.25
        result.append(_ExtractedText(text, weight, msg_idx))
    return result


def _count_conversation_messages(messages: list[dict[str, Any]]) -> int:
    return sum(1 for m in messages if m.get("role", "") not in _EXCLUDED_ROLES)


def _combined_text(extracted: list[_ExtractedText]) -> str:
    return "\n".join(e.text for e in extracted)


# ── Sigmoid / Tier mapping ──

TIER_ORDER: dict[Tier, int] = {"simple": 0, "standard": 1, "complex": 2, "reasoning": 3}


def _score_to_tier(score: float, b: TierBoundaries) -> Tier:
    if score < b.simple_max:
        return "simple"
    if score < b.standard_max:
        return "standard"
    if score < b.complex_max:
        return "complex"
    return "reasoning"


def _compute_confidence(score: float, b: TierBoundaries, k: float = 8.0) -> float:
    boundaries = [b.simple_max, b.standard_max, b.complex_max]
    min_dist = min(abs(score - bv) for bv in boundaries)
    return 1.0 / (1.0 + math.exp(-k * min_dist))


def _max_tier(a: Tier, b: Tier) -> Tier:
    return a if TIER_ORDER[a] >= TIER_ORDER[b] else b


# ── Overrides ──

def _has_word_boundary_match(text: str, keyword: str) -> bool:
    kw_lower = keyword.lower()
    idx = text.find(kw_lower)
    while idx != -1:
        before_ok = idx == 0 or not _is_word_char(text[idx - 1])
        after_end = idx + len(kw_lower)
        after_ok = after_end >= len(text) or not _is_word_char(text[after_end])
        if before_ok and after_ok:
            return True
        idx = text.find(kw_lower, idx + 1)
    return False


def _check_formal_logic_override(config: ScorerConfig, last_user_text: str) -> bool:
    formal_dim = next((d for d in config.dimensions if d.name == "formalLogic"), None)
    if not formal_dim or not formal_dim.keywords or not last_user_text:
        return False
    last_lower = last_user_text.lower()
    return any(_has_word_boundary_match(last_lower, kw) for kw in formal_dim.keywords)


def _estimate_total_tokens(messages: list[dict[str, Any]]) -> float:
    chars = 0
    for msg in messages:
        content = msg.get("content")
        if content is None:
            continue
        if isinstance(content, str):
            chars += len(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    chars += len(block["text"])
        else:
            chars += len(str(content))
    return chars / 4.0


# ── Momentum ──

_TIER_SCORES: dict[Tier, float] = {
    "simple": -0.2, "standard": 0.0, "complex": 0.2, "reasoning": 0.4,
}
_MAX_HISTORY = 5


@dataclass
class MomentumInput:
    recent_tiers: list[Tier]


def _apply_momentum(
    raw_score: float,
    last_msg_len: int,
    momentum: MomentumInput | None,
) -> tuple[float, MomentumInfo]:
    if not momentum or not momentum.recent_tiers:
        return raw_score, MomentumInfo(0, 0.0, 0.0, False)

    if last_msg_len > 100:
        mw = 0.0
    elif last_msg_len >= 30:
        mw = 0.3 * (1.0 - (last_msg_len - 30) / 70.0)
    else:
        mw = 0.3 + 0.3 * (1.0 - last_msg_len / 30.0)

    recent = momentum.recent_tiers[:_MAX_HISTORY]
    avg = sum(_TIER_SCORES.get(t, 0.0) for t in recent) / len(recent)
    effective = (1.0 - mw) * raw_score + mw * avg

    return effective, MomentumInfo(
        history_length=len(recent),
        history_avg_score=avg,
        momentum_weight=mw,
        applied=mw > 0 and effective != raw_score,
    )


# ── Keyword dimension scoring ──

_DENSITY_WINDOW = 200
_DENSITY_THRESHOLD = 3
_DENSITY_BONUS = 1.5


def _has_density_cluster(matches: list[_TrieMatch], window: int) -> bool:
    if len(matches) < _DENSITY_THRESHOLD:
        return False
    positions = sorted(m.position for m in matches)
    for i in range(len(positions) - _DENSITY_THRESHOLD + 1):
        if positions[i + _DENSITY_THRESHOLD - 1] - positions[i] <= window:
            return True
    return False


def _score_keyword_dimension(
    dim_name: str,
    all_matches: list[_TrieMatch],
    extracted: list[_ExtractedText],
    direction: Literal["up", "down"],
) -> tuple[float, list[str]]:
    dim_matches = [m for m in all_matches if m.dimension == dim_name]
    if not dim_matches:
        return 0.0, []

    unique_kws = list({m.keyword for m in dim_matches})
    density_active = _has_density_cluster(dim_matches, _DENSITY_WINDOW)

    weighted_sum = 0.0
    for ext in extracted:
        text_lower = ext.text.lower()
        chunk_count = sum(1 for m in dim_matches if m.keyword in text_lower)
        if chunk_count > 0:
            contribution = chunk_count * ext.position_weight
            if density_active:
                contribution *= _DENSITY_BONUS
            weighted_sum += contribution

    normalizer = max(1, len(dim_matches))
    raw = max(-1.0, min(1.0, weighted_sum / normalizer))
    if direction == "down":
        raw = -raw
    return raw, unique_kws


# ── Structural dimensions ──

def _lerp(value: float, in_min: float, in_max: float, out_min: float, out_max: float) -> float:
    t = max(0.0, min(1.0, (value - in_min) / (in_max - in_min)))
    return out_min + t * (out_max - out_min)


def _score_token_count(text: str) -> float:
    tokens = len(text) / 4.0
    if tokens < 50:
        return -0.5
    if tokens <= 200:
        return _lerp(tokens, 50, 200, -0.5, 0)
    if tokens <= 500:
        return _lerp(tokens, 200, 500, 0, 0.3)
    return 0.5


def _score_nested_list_depth(text: str) -> float:
    indent_levels: set[int] = set()
    for m in re.finditer(r"^(\s+)(?:[-*+]\s|\d+[.)]\s)", text, re.MULTILINE):
        indent_levels.add(len(m.group(1)))
    levels = len(indent_levels)
    if levels == 0:
        return 0.0
    if levels == 1:
        return 0.3
    if levels == 2:
        return 0.6
    return 0.9


_CONDITIONAL_PATTERNS = [
    re.compile(r"\bif\b.*?\bthen\b", re.I),
    re.compile(r"\botherwise\b", re.I),
    re.compile(r"\bunless\b", re.I),
    re.compile(r"\bdepending on\b", re.I),
    re.compile(r"\bwhen\b.*?\bhappens?\b", re.I),
    re.compile(r"\bin case\b", re.I),
    re.compile(r"\bprovided that\b", re.I),
    re.compile(r"\bassuming\b", re.I),
    re.compile(r"\bgiven that\b", re.I),
    re.compile(r"\bon condition\b", re.I),
]


def _score_conditional_logic(text: str) -> float:
    count = sum(len(p.findall(text)) for p in _CONDITIONAL_PATTERNS)
    if count == 0:
        return 0.0
    if count == 1:
        return 0.3
    if count == 2:
        return 0.6
    return 0.9


def _score_code_to_prose(text: str) -> float:
    if not text:
        return 0.0
    code_chars = 0
    for m in re.finditer(r"```[\s\S]*?(?:```|$)", text):
        inner = re.sub(r"^```[^\n]*\n?", "", m.group())
        inner = re.sub(r"```$", "", inner)
        code_chars += len(inner)
    for m in re.finditer(r"`([^`]+)`", text):
        code_chars += len(m.group(1)) * 0.5
    if code_chars == 0:
        return 0.0
    return min(0.9, (code_chars / len(text)) * 1.5)


_CONSTRAINT_PATTERNS = [
    re.compile(r"\bat most\b", re.I),
    re.compile(r"\bat least\b", re.I),
    re.compile(r"\bexactly\s+\d+", re.I),
    re.compile(r"\bno more than\b", re.I),
    re.compile(r"\bmust not\b", re.I),
    re.compile(r"\bmust be\b", re.I),
    re.compile(r"\bshould not\b", re.I),
    re.compile(r"\bcannot exceed\b", re.I),
    re.compile(r"\bwithin\s+\d+", re.I),
    re.compile(r"\bbetween\s+\S+\s+and\s+\S+", re.I),
    re.compile(r"O\([^)]{1,200}\)"),
    re.compile(r"/[^/\s]+/"),
]


def _score_constraint_density(text: str) -> float:
    if not text:
        return 0.0
    count = sum(len(p.findall(text)) for p in _CONSTRAINT_PATTERNS)
    words = len(text.split())
    if words == 0:
        return 0.0
    density = (count / words) * 100
    if density < 0.5:
        return 0.0
    return min(0.9, _lerp(density, 0.5, 3, 0, 0.9))


# ── Contextual dimensions ──

_LENGTH_SIGNALS = [
    "comprehensive", "detailed", "thorough", "exhaustive", "in-depth",
    "full report", "complete guide", "write a full", "cover all",
]


def _score_expected_output_length(text: str, max_tokens: int | None = None) -> float:
    lower = text.lower()
    signal_count = sum(1 for s in _LENGTH_SIGNALS if s in lower)
    score = 0.0
    if signal_count == 1:
        score = 0.3
    elif signal_count >= 2:
        score = 0.6
    if max_tokens is not None:
        if max_tokens > 8000:
            score += 0.3
        elif max_tokens > 4000:
            score += 0.2
    return min(0.9, score)


_REPETITION_PATTERN = re.compile(
    r"(\d{1,6})\s{0,10}(variations?|options?|alternatives?|versions?|examples?|ways?\s{1,10}to|times)",
    re.I,
)


def _score_repetition_requests(text: str) -> float:
    m = _REPETITION_PATTERN.search(text)
    if not m:
        return 0.0
    n = int(m.group(1))
    if n <= 1:
        return 0.0
    if n <= 3:
        return 0.3
    if n <= 9:
        return 0.6
    return 0.9


def _score_tool_count(tools: list[dict[str, Any]] | None, tool_choice: Any = None) -> float:
    if tool_choice == "none":
        return 0.0
    count = len(tools) if tools else 0
    if count == 0:
        return 0.0
    if count <= 2:
        score = 0.1
    elif count <= 5:
        score = 0.3
    elif count <= 10:
        score = 0.6
    else:
        score = 0.9
    is_specific = (
        (tool_choice is not None and isinstance(tool_choice, dict))
        or tool_choice in ("any", "required")
    )
    if is_specific:
        score += 0.2
    return min(0.9, score)


def _score_conversation_depth(message_count: int) -> float:
    if message_count <= 2:
        return 0.0
    if message_count <= 5:
        return 0.1
    if message_count <= 10:
        return 0.3
    if message_count <= 20:
        return 0.5
    return 0.7


# ── Structural dimension dispatch ──

def _score_structural_dimension(
    dim: DimensionConfig,
    combined: str,
    max_tokens: int | None,
    tools: list[dict[str, Any]] | None,
    tool_choice: Any,
    conversation_count: int,
) -> float:
    name = dim.name
    if name == "tokenCount":
        return _score_token_count(combined)
    if name == "nestedListDepth":
        return _score_nested_list_depth(combined)
    if name == "conditionalLogic":
        return _score_conditional_logic(combined)
    if name == "codeToProse":
        return _score_code_to_prose(combined)
    if name == "constraintDensity":
        return _score_constraint_density(combined)
    if name == "expectedOutputLength":
        return _score_expected_output_length(combined, max_tokens)
    if name == "repetitionRequests":
        return _score_repetition_requests(combined)
    if name == "toolCount":
        return _score_tool_count(tools, tool_choice)
    if name == "conversationDepth":
        return _score_conversation_depth(conversation_count)
    return 0.0


# ── Main scorer ──

_default_trie: KeywordTrie | None = None


def _get_default_trie() -> KeywordTrie:
    global _default_trie
    if _default_trie is None:
        _default_trie = _build_trie(DEFAULT_CONFIG)
    return _default_trie


def _build_trie(config: ScorerConfig) -> KeywordTrie:
    dims = [(d.name, d.keywords) for d in config.dimensions if d.keywords]
    return KeywordTrie(dims)


def _empty_dimensions(config: ScorerConfig) -> list[DimensionScore]:
    return [
        DimensionScore(
            name=d.name, raw_score=0.0, weight=d.weight, weighted_score=0.0,
            matched_keywords=[] if d.keywords else None,
        )
        for d in config.dimensions
    ]


def score_request(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    tool_choice: Any = None,
    max_tokens: int | None = None,
    config_override: ScorerConfig | None = None,
    momentum: MomentumInput | None = None,
) -> ScoringResult:
    """Score a request and return the recommended tier."""
    config = config_override or DEFAULT_CONFIG

    if not messages:
        return ScoringResult(
            "standard", 0.0, 0.4, "ambiguous", _empty_dimensions(config), None,
        )

    extracted = _extract_user_texts(messages)
    combined = _combined_text(extracted)
    last_user_text = extracted[-1].text if extracted else ""

    trie = _build_trie(config) if config_override else _get_default_trie()

    # Override: formal logic keywords → reasoning
    if _check_formal_logic_override(config, last_user_text):
        return ScoringResult(
            "reasoning", 0.5, 0.95, "formal_logic_override",
            _empty_dimensions(config), None,
        )

    # Override: short message → simple (unless momentum + no simple indicators)
    has_tools = bool(tools)
    has_momentum = bool(momentum and momentum.recent_tiers)
    if last_user_text and len(last_user_text) < 50 and not has_tools:
        if not has_momentum:
            return ScoringResult(
                "simple", -0.3, 0.9, "short_message",
                _empty_dimensions(config), None,
            )
        last_matches = trie.scan(last_user_text)
        if any(m.dimension == "simpleIndicators" for m in last_matches):
            return ScoringResult(
                "simple", -0.3, 0.9, "short_message",
                _empty_dimensions(config), None,
            )

    # Score all dimensions
    all_matches = trie.scan(combined) if combined else []
    conversation_count = _count_conversation_messages(messages)

    dimensions: list[DimensionScore] = []
    raw_score = 0.0

    for dim in config.dimensions:
        if dim.keywords:
            raw, matched = _score_keyword_dimension(
                dim.name, all_matches, extracted, dim.direction,
            )
            matched_kws: list[str] | None = matched
        else:
            raw = _score_structural_dimension(
                dim, combined, max_tokens, tools, tool_choice, conversation_count,
            )
            matched_kws = None

        weighted = raw * dim.weight
        raw_score += weighted
        dimensions.append(DimensionScore(dim.name, raw, dim.weight, weighted, matched_kws))

    # Apply momentum
    effective_score, mom_info = _apply_momentum(raw_score, len(last_user_text), momentum)

    # Determine tier
    tier = _score_to_tier(effective_score, config.boundaries)
    reason: ScoringReason = "scored"

    # Floor: tools → at least standard
    if has_tools and tool_choice != "none":
        floored = _max_tier(tier, "standard")
        if floored != tier:
            tier = floored
            reason = "tool_detected"

    # Floor: large context → at least complex
    if _estimate_total_tokens(messages) > 50_000:
        floored = _max_tier(tier, "complex")
        if floored != tier:
            tier = floored
            reason = "large_context"

    if mom_info.applied:
        reason = "momentum"

    # Confidence check
    confidence = _compute_confidence(effective_score, config.boundaries, config.confidence_k)
    if confidence < config.confidence_threshold and reason == "scored":
        tier = "standard"
        reason = "ambiguous"

    return ScoringResult(
        tier=tier,
        score=effective_score,
        confidence=confidence,
        reason=reason,
        dimensions=dimensions,
        momentum=mom_info if momentum else None,
    )
