#!/usr/bin/env bash
# autoresearch.sh — Trellis benchmark runner
# Outputs METRIC lines for autoresearch loop consumption.
# Format: METRIC name=<name> value=<float> unit=<unit> direction=<lower|higher>
#
# Usage:
#   ./autoresearch.sh              # run all benchmarks
#   ./autoresearch.sh test         # test suite only
#   ./autoresearch.sh bundle       # dashboard bundle only
#   ./autoresearch.sh api          # API latency only
#   ./autoresearch.sh phi          # PHI Shield accuracy only
#   ./autoresearch.sh lint         # lint warning count only
#
# Results are printed to stdout AND appended to autoresearch.jsonl
# as JSON records with timestamp.
#
# Dependencies: uv, node/npm (for bundle), jq (optional, for JSON output)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

JSONL_FILE="$SCRIPT_DIR/autoresearch.jsonl"
TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
TARGET="${1:-all}"

# ── Helpers ─────────────────────────────────────────────────────────────────

emit_metric() {
    local name="$1"
    local value="$2"
    local unit="$3"
    local direction="$4"
    echo "METRIC name=$name value=$value unit=$unit direction=$direction"
    # Append to JSONL
    echo "{\"ts\":\"$TS\",\"metric\":\"$name\",\"value\":$value,\"unit\":\"$unit\",\"direction\":\"$direction\"}" \
        >> "$JSONL_FILE"
}

emit_error() {
    local name="$1"
    local msg="$2"
    echo "METRIC_ERROR name=$name msg=\"$msg\""
}

separator() {
    echo ""
    echo "── $1 ─────────────────────────────────────────────"
}

# ── Target 1: Test Suite Speed ───────────────────────────────────────────────

bench_tests() {
    separator "Test Suite Speed"
    echo "Running 525-test suite (this takes ~30-60s)..."

    if ! command -v uv &>/dev/null; then
        emit_error "test_suite_seconds" "uv not found"
        return 1
    fi

    # Run pytest with timing, capture wall time
    START=$(date +%s%3N)
    uv run pytest tests/ -q --tb=no --no-header 2>&1 | tail -5
    END=$(date +%s%3N)
    ELAPSED=$(awk "BEGIN {printf \"%.3f\", ($END - $START) / 1000}")

    emit_metric "test_suite_seconds" "$ELAPSED" "seconds" "lower"

    # Also emit per-file timings if pytest-json-report is available
    if uv run python -c "import pytest_json_report" 2>/dev/null; then
        echo "(per-file breakdown available via: uv run pytest --json-report --json-report-file=bench_tests.json)"
    else
        echo "(install pytest-json-report for per-file breakdown)"
    fi
}

# ── Target 2: Dashboard Bundle Size ─────────────────────────────────────────

bench_bundle() {
    separator "Dashboard Bundle Size"

    if [ ! -d "$SCRIPT_DIR/dashboard" ]; then
        emit_error "dashboard_bundle_kb" "dashboard/ directory not found"
        return 1
    fi

    cd "$SCRIPT_DIR/dashboard"

    if ! command -v npm &>/dev/null; then
        emit_error "dashboard_bundle_kb" "npm not found"
        cd "$SCRIPT_DIR"
        return 1
    fi

    echo "Building Next.js dashboard (this takes ~60s)..."
    BUILD_OUTPUT=$(npm run build 2>&1)

    # Extract total First Load JS from Next.js build output
    # Format: "○ /page  X.X kB  Y kB" — we want the shared JS column
    SHARED_JS=$(echo "$BUILD_OUTPUT" | grep "First Load JS shared by all" | \
        grep -oE '[0-9]+\.?[0-9]* kB' | head -1 | tr -d ' kB')

    if [ -z "$SHARED_JS" ]; then
        # Fallback: sum all .js files in .next/static/chunks
        TOTAL_KB=$(find .next/static/chunks -name "*.js" 2>/dev/null | \
            xargs wc -c 2>/dev/null | tail -1 | awk '{printf "%.1f", $1/1024}')
        if [ -z "$TOTAL_KB" ]; then
            emit_error "dashboard_bundle_kb" "Could not parse build output"
        else
            emit_metric "dashboard_bundle_kb" "$TOTAL_KB" "kilobytes" "lower"
        fi
    else
        emit_metric "dashboard_bundle_kb" "$SHARED_JS" "kilobytes" "lower"
    fi

    cd "$SCRIPT_DIR"
}

# ── Target 3: API Latency ────────────────────────────────────────────────────

bench_api() {
    separator "API Latency"

    # Start server in background if not already running
    SERVER_PID=""
    if ! curl -sf http://localhost:8000/health/infra > /dev/null 2>&1; then
        echo "Starting Trellis server..."
        uv run uvicorn trellis.main:app --host 0.0.0.0 --port 8000 &
        SERVER_PID=$!
        sleep 3  # Wait for startup
        echo "Server started (PID $SERVER_PID)"
    else
        echo "Using existing server on :8000"
    fi

    # Helper to time a curl request (returns ms)
    time_route() {
        local method="$1"
        local path="$2"
        local data="${3:-}"
        local content_type="${4:-application/json}"

        if [ -n "$data" ]; then
            TIME_MS=$(curl -s -o /dev/null -w "%{time_total}" \
                -X "$method" "http://localhost:8000$path" \
                -H "Content-Type: $content_type" \
                -d "$data" 2>/dev/null | \
                awk '{printf "%.0f", $1 * 1000}')
        else
            TIME_MS=$(curl -s -o /dev/null -w "%{time_total}" \
                -X "$method" "http://localhost:8000$path" 2>/dev/null | \
                awk '{printf "%.0f", $1 * 1000}')
        fi
        echo "$TIME_MS"
    }

    # Benchmark key routes (5 samples each, take median)
    benchmark_route() {
        local label="$1"
        local method="$2"
        local path="$3"
        local data="${4:-}"
        local SAMPLES=5
        local TIMES=()

        for i in $(seq 1 $SAMPLES); do
            MS=$(time_route "$method" "$path" "$data")
            TIMES+=("$MS")
        done

        # Sort and take median (sample 3 of 5)
        SORTED=($(echo "${TIMES[@]}" | tr ' ' '\n' | sort -n))
        MEDIAN="${SORTED[2]}"
        echo "  $label: ${MEDIAN}ms (samples: ${TIMES[*]})"
        emit_metric "api_latency_${label}" "$MEDIAN" "milliseconds" "lower"
    }

    benchmark_route "health" "GET" "/health/infra"
    benchmark_route "agents_list" "GET" "/api/agents"
    benchmark_route "rules_list" "GET" "/api/rules"
    benchmark_route "audit_list" "GET" "/api/audit?limit=50"
    benchmark_route "costs_summary" "GET" "/api/costs/summary"
    benchmark_route "gateway_stats" "GET" "/api/gateway/stats"

    # POST envelope (requires an agent to exist — skip if 404)
    ENVELOPE_DATA='{"source":"bench","type":"test","payload":{"text":"Hello benchmark"}}'
    RESP=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/envelopes \
        -H "Content-Type: application/json" -d "$ENVELOPE_DATA" 2>/dev/null || echo "000")
    if [ "$RESP" != "000" ]; then
        benchmark_route "envelope_post" "POST" "/envelopes" "$ENVELOPE_DATA"
    fi

    # Cleanup
    if [ -n "$SERVER_PID" ]; then
        kill "$SERVER_PID" 2>/dev/null || true
        echo "Server stopped (PID $SERVER_PID)"
    fi
}

# ── Target 4: PHI Shield Accuracy ───────────────────────────────────────────

bench_phi() {
    separator "PHI Shield Accuracy"

    if ! uv run python -c "from trellis.phi_shield import redact" 2>/dev/null; then
        emit_error "phi_false_positive_rate" "phi_shield module not importable"
        return 1
    fi

    uv run python - <<'PYEOF'
import sys
import time
sys.path.insert(0, '.')

from trellis.phi_shield import PhiShield

shield = PhiShield()

# ── Test corpus ──────────────────────────────────────────────────────────
# Each entry: (text, should_redact: bool, description)
corpus = [
    # TRUE PHI — must be redacted
    ("Patient John Smith, DOB 01/15/1968, MRN 4872910", True, "full PHI combo"),
    ("SSN: 123-45-6789", True, "SSN"),
    ("Call me at 321-555-0192", True, "phone number"),
    ("Insurance ID: UHC-A8827731", True, "insurance ID"),
    ("Her address is 1234 Palm Bay Rd, Melbourne FL 32905", True, "home address"),
    ("Patient DOB: March 3, 1972", True, "date of birth"),

    # TRUE NON-PHI — must NOT be redacted
    ("Dr. Sarah Chen ordered the procedure", False, "physician name in clinical context"),
    ("Patient was seen in the Cardiology department", False, "department name"),
    ("Holmes Regional Medical Center", False, "facility name"),
    ("Admitted to Cape Canaveral Hospital for observation", False, "Health First facility"),
    ("Diagnosis: Type 2 Diabetes (ICD-10: E11.9)", False, "diagnosis code"),
    ("Prescribed metformin 500mg twice daily", False, "medication order"),
    ("The attending RN documented vitals at 0800", False, "clinical role"),
    ("Prior auth submitted for CPT 99214", False, "procedure code"),

    # EDGE CASES
    ("Dr. James Martinez, attending physician, saw patient #28847", False, "physician + MRN-like"),
    ("Room 412, 3 North ICU", False, "room number (not address)"),
    ("The case was reviewed by Dr. Patel and approved", False, "physician review context"),
]

true_positives = 0    # PHI correctly redacted
false_negatives = 0   # PHI missed (dangerous!)
true_negatives = 0    # non-PHI correctly preserved
false_positives = 0   # non-PHI wrongly redacted

details = []

for text, should_redact, desc in corpus:
    try:
        result = shield.redact(text)
        was_redacted = result.redacted_text != text

        if should_redact and was_redacted:
            true_positives += 1
        elif should_redact and not was_redacted:
            false_negatives += 1
            details.append(f"  FALSE NEG [{desc}]: {text[:60]}")
        elif not should_redact and not was_redacted:
            true_negatives += 1
        else:
            false_positives += 1
            details.append(f"  FALSE POS [{desc}]: {text[:60]} → {result.redacted_text[:60]}")
    except Exception as e:
        details.append(f"  ERROR [{desc}]: {e}")

total = len(corpus)
phi_count = sum(1 for _, s, _ in corpus if s)
non_phi_count = sum(1 for _, s, _ in corpus if not s)

fp_rate = false_positives / non_phi_count if non_phi_count > 0 else 0
fn_rate = false_negatives / phi_count if phi_count > 0 else 0
precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0
recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 0

print(f"  Corpus: {total} cases ({phi_count} PHI, {non_phi_count} non-PHI)")
print(f"  TP={true_positives} FP={false_positives} TN={true_negatives} FN={false_negatives}")
print(f"  Precision: {precision:.3f}  Recall: {recall:.3f}")
if details:
    print("  Issues found:")
    for d in details:
        print(d)

fp_pct = round(fp_rate * 100, 2)
fn_pct = round(fn_rate * 100, 2)

print(f"METRIC name=phi_false_positive_rate value={fp_pct} unit=percent direction=lower")
print(f"METRIC name=phi_false_negative_rate value={fn_pct} unit=percent direction=lower")
print(f"METRIC name=phi_precision value={round(precision*100,2)} unit=percent direction=higher")
print(f"METRIC name=phi_recall value={round(recall*100,2)} unit=percent direction=higher")
PYEOF
}

# ── Target 5: Lint Warning Count ─────────────────────────────────────────────

bench_lint() {
    separator "Code Quality (Lint)"

    if ! command -v uv &>/dev/null; then
        emit_error "lint_warning_count" "uv not found"
        return 1
    fi

    # Count total warnings (ruff check, exit 0 even if warnings exist)
    COUNT=$(uv run ruff check trellis/ tests/ --statistics 2>&1 | \
        grep -E "^[0-9]" | awk '{sum += $1} END {print sum+0}')

    echo "  Total lint warnings: $COUNT"
    uv run ruff check trellis/ tests/ --statistics 2>&1 | head -20

    emit_metric "lint_warning_count" "$COUNT" "warnings" "lower"
}

# ── Main ─────────────────────────────────────────────────────────────────────

echo "╔══════════════════════════════════════════════════════════╗"
echo "║       Trellis Autoresearch — Benchmark Run               ║"
echo "║       $(date -u '+%Y-%m-%d %H:%M:%S UTC')                        ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "Results will append to: $JSONL_FILE"
echo ""

case "$TARGET" in
    test)   bench_tests ;;
    bundle) bench_bundle ;;
    api)    bench_api ;;
    phi)    bench_phi ;;
    lint)   bench_lint ;;
    all)
        bench_tests
        bench_bundle
        bench_api
        bench_phi
        bench_lint
        ;;
    *)
        echo "Unknown target: $TARGET"
        echo "Valid targets: all, test, bundle, api, phi, lint"
        exit 1
        ;;
esac

echo ""
echo "── Done ────────────────────────────────────────────────────"
echo "JSONL results: $(wc -l < "$JSONL_FILE") total records in autoresearch.jsonl"
