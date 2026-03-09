# Classification Engine Research Program

## Objective
Improve Trellis's Classification Engine (`trellis/classification.py`) — the middleware that auto-routes healthcare IT envelopes to the right agent without senders needing to know Trellis internals.

## Current State
- 4-stage pipeline: source_type map → keyword analysis → severity inference → tag extraction
- ~0.1ms per envelope, 338 lines, zero LLM calls
- Keyword matching is naive (substring, first-wins-on-tie)
- No learning from historical routing decisions
- No fuzzy matching, no weighting, no context awareness
- 50 tests passing

## Research Questions
1. Can TF-IDF or BM25 scoring replace naive keyword counting for better classification accuracy?
2. What confidence calibration methods work for rule-based classifiers without ML training data?
3. How should multi-label classification work (envelope touches both security AND clinical)?
4. Can we build a feedback loop from agent responses (did the agent successfully handle it?) to tune weights?
5. What's the optimal keyword/phrase vocabulary for healthcare IT routing?

## Constraints
- Must remain zero-LLM (no API calls in the hot path)
- Must stay under 1ms per envelope
- Must be deterministic (same input → same output)
- Python 3.13+, no heavy ML dependencies (no torch, no sklearn in production)
- Can use numpy for scoring if needed
- All improvements must have tests

## Experiment Plan

### Experiment 1: TF-IDF Scoring
Replace naive keyword counting with TF-IDF weighted scoring.
- Build category document profiles from keyword lists
- Score incoming text against each profile
- Return category with highest cosine similarity
- Measure: accuracy on test envelopes, latency

### Experiment 2: Multi-label Classification
Allow envelopes to match multiple categories with confidence scores.
- Return ranked list of (category, score) tuples
- Primary category = highest score
- Secondary categories available for routing fallback
- Measure: does multi-label improve routing for ambiguous envelopes?

### Experiment 3: Confidence Calibration
Better confidence scoring than "high/medium/low" strings.
- Numeric confidence (0.0-1.0)
- Based on: score margin between top-2 categories, keyword density, source_type reliability
- Threshold for "uncertain" → flag for human review
- Measure: calibration curve on test data

### Experiment 4: Expanded Vocabulary
Research healthcare IT terminology for better coverage.
- HIPAA-specific terms
- Epic/EHR workflow terms
- Revenue cycle management terms
- Clinical informatics terms
- Build from: CMS glossary, HL7 terminology, HITRUST framework

## Results Log
(Qwopus fills this in as experiments complete)

---
*Research program for autonomous iteration. Each experiment produces code + benchmarks.*
