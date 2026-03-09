#!/bin/bash
# Autonomous research loop — Qwopus iterates on Classification Engine
# Usage: ./run.sh [max_iterations]

set -euo pipefail
cd "$(dirname "$0")"
TRELLIS_ROOT="$(cd ../.. && pwd)"
MAX_ITER="${1:-5}"
LOG="research_log.md"

echo "# Autonomous Research Log" > "$LOG"
echo "Started: $(date)" >> "$LOG"
echo "Model: qwopus-27b-q2" >> "$LOG"
echo "Max iterations: $MAX_ITER" >> "$LOG"
echo "" >> "$LOG"

for i in $(seq 1 "$MAX_ITER"); do
    echo "=== Iteration $i / $MAX_ITER ==="
    echo "## Iteration $i" >> "$LOG"
    echo "Time: $(date)" >> "$LOG"

    # Run benchmark first
    cd "$TRELLIS_ROOT"
    source .venv/bin/activate
    BENCH_OUTPUT=$(python research/autoresearch/benchmark.py 2>&1)
    echo "$BENCH_OUTPUT"
    echo '```' >> "research/autoresearch/$LOG"
    echo "$BENCH_OUTPUT" >> "research/autoresearch/$LOG"
    echo '```' >> "research/autoresearch/$LOG"

    cd research/autoresearch

    # Build prompt for Qwopus
    PROMPT="You are an autonomous AI researcher improving a healthcare IT classification engine.

CURRENT BENCHMARK RESULTS:
$BENCH_OUTPUT

READ THE RESEARCH PROGRAM:
$(cat program.md)

CURRENT CLASSIFICATION ENGINE CODE:
$(cat ../../trellis/classification.py)

BENCHMARK HARNESS (do not modify):
$(cat benchmark.py)

YOUR TASK FOR THIS ITERATION:
1. Analyze the benchmark failures above
2. Identify the root cause of each failure
3. Write an IMPROVED version of classification.py that fixes the failures
4. Focus on severity detection — it's the weakest area (66.7%)
5. Keep it zero-LLM, under 1ms, deterministic
6. Output ONLY the complete improved classification.py file content
7. After the code, write a brief analysis of what you changed and why

IMPORTANT: Output the COMPLETE file. Start with the triple-backtick python block. Do not skip any existing functionality."

    # Call Qwopus
    echo "Calling Qwopus for iteration $i..."
    RESPONSE=$(ollama run qwopus-27b-q2 "$PROMPT" 2>&1)

    # Extract Python code from response
    echo "$RESPONSE" | sed -n '/^```python/,/^```$/p' | sed '1d;$d' > proposed_classification.py

    if [ -s proposed_classification.py ]; then
        echo "Got proposed code ($(wc -l < proposed_classification.py) lines)"

        # Backup current
        cp ../../trellis/classification.py ../../trellis/classification.py.bak

        # Try the proposed version
        cp proposed_classification.py ../../trellis/classification.py

        # Run benchmark on proposed version
        cd "$TRELLIS_ROOT"
        source .venv/bin/activate
        NEW_BENCH=$(python research/autoresearch/benchmark.py 2>&1) || true
        echo "$NEW_BENCH"

        echo "### Proposed Changes Result" >> "research/autoresearch/$LOG"
        echo '```' >> "research/autoresearch/$LOG"
        echo "$NEW_BENCH" >> "research/autoresearch/$LOG"
        echo '```' >> "research/autoresearch/$LOG"

        # Check if it improved (crude: check all-correct percentage)
        OLD_SCORE=$(echo "$BENCH_OUTPUT" | grep "All-correct" | grep -oP '\d+\.\d+%' || echo "0%")
        NEW_SCORE=$(echo "$NEW_BENCH" | grep "All-correct" | grep -oP '\d+\.\d+%' || echo "0%")

        echo "Old: $OLD_SCORE → New: $NEW_SCORE"
        echo "Score change: $OLD_SCORE → $NEW_SCORE" >> "research/autoresearch/$LOG"

        # If it got worse or errored, revert
        if echo "$NEW_BENCH" | grep -q "Error\|Traceback\|ImportError"; then
            echo "REVERTED — code errors"
            cp ../../trellis/classification.py.bak ../../trellis/classification.py
            echo "**REVERTED** — code errors" >> "research/autoresearch/$LOG"
        fi

        cd research/autoresearch
    else
        echo "No valid code extracted from Qwopus response"
        echo "**No valid code extracted**" >> "$LOG"
    fi

    # Save Qwopus's full response
    echo "$RESPONSE" > "iteration_${i}_response.md"

    echo "" >> "$LOG"
    echo "---" >> "$LOG"
done

echo ""
echo "Research complete. See $LOG for full results."
echo "Finished: $(date)" >> "$LOG"
