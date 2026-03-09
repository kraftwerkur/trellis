"""Benchmark harness for Classification Engine experiments.

Qwopus reads this, runs experiments, measures results, and iterates.
"""
import sys
import time
import json
from pathlib import Path

# Add trellis to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from trellis.schemas import Envelope, Payload, RoutingHints, Metadata

# ── Test Envelopes ────────────────────────────────────────────────────────
# Ground truth: what category/department/severity SHOULD be assigned

TEST_ENVELOPES = [
    # Clear security
    {
        "input": {"source_type": "", "text": "Critical vulnerability CVE-2026-1234 in CrowdStrike Falcon agent allows remote code execution. CVSS 9.8. Exploited in wild.", "data": {}},
        "expected": {"category": "security", "department": "Information Security", "severity": "critical"},
    },
    # Clear IT incident
    {
        "input": {"source_type": "", "text": "Ticket INC0012345: VPN connection dropping for remote users in Building 3. Multiple reports since 8am.", "data": {}},
        "expected": {"category": "incident", "department": "IT", "severity": "normal"},
    },
    # Clear HR
    {
        "input": {"source_type": "", "text": "Employee John Smith requesting FMLA leave for 6 weeks starting March 15. Benefits coordinator needs to review.", "data": {}},
        "expected": {"category": "hr", "department": "HR", "severity": "normal"},
    },
    # Clear revenue cycle
    {
        "input": {"source_type": "", "text": "Claim denial CO-16 from Medicare for patient encounter 20260301. Missing modifier on CPT 99213.", "data": {}},
        "expected": {"category": "revenue", "department": "Revenue Cycle", "severity": "normal"},
    },
    # Ambiguous: security + clinical
    {
        "input": {"source_type": "", "text": "Patient portal vulnerability found. PHI exposure risk for 2000 patients through Epic MyChart integration. Need immediate patch.", "data": {}},
        "expected": {"category": "security", "department": "Information Security", "severity": "critical"},
    },
    # Ambiguous: IT + clinical
    {
        "input": {"source_type": "", "text": "Epic Hyperspace crashing on nurse workstations in ICU. Cannot access patient medication orders. Server error 500.", "data": {}},
        "expected": {"category": "incident", "department": "IT", "severity": "critical"},
    },
    # Ambiguous: HR + compliance
    {
        "input": {"source_type": "", "text": "HIPAA training completion rates below 80% threshold. HR needs to send reminders. OIG audit coming in April.", "data": {}},
        "expected": {"category": "compliance", "department": "Compliance", "severity": "high"},
    },
    # Source-type override (should use source_type map)
    {
        "input": {"source_type": "cisa_kev", "text": "New entry added to Known Exploited Vulnerabilities catalog.", "data": {}},
        "expected": {"category": "security", "department": "Information Security", "severity": "normal"},
    },
    # Revenue + compliance overlap
    {
        "input": {"source_type": "", "text": "CMS announced new billing compliance rules for 2027. Impact on claim coding for outpatient services. Payer reimbursement changes.", "data": {}},
        "expected": {"category": "revenue", "department": "Revenue Cycle", "severity": "normal"},
    },
    # Completely unknown / general
    {
        "input": {"source_type": "", "text": "Meeting scheduled for Tuesday to discuss Q2 budget allocations across departments.", "data": {}},
        "expected": {"category": None, "department": None, "severity": "normal"},
    },
    # Network outage — critical incident
    {
        "input": {"source_type": "", "text": "CRITICAL: Core switch failure at Cape Canaveral Hospital. Network down for entire facility. Patient care systems offline.", "data": {}},
        "expected": {"category": "incident", "department": "IT", "severity": "critical"},
    },
    # Ransomware — critical security
    {
        "input": {"source_type": "", "text": "Ransomware detected on 3 workstations in radiology department. Files encrypted. CrowdStrike containment activated.", "data": {}},
        "expected": {"category": "security", "department": "Information Security", "severity": "critical"},
    },
    # Workers comp — HR
    {
        "input": {"source_type": "", "text": "Workers comp claim filed by maintenance staff. Injury occurred during equipment installation. ADA accommodation may be needed.", "data": {}},
        "expected": {"category": "hr", "department": "HR", "severity": "normal"},
    },
    # Subtle clinical
    {
        "input": {"source_type": "", "text": "Lab results interface between Quest Diagnostics and Epic showing 4-hour delay. Physicians requesting manual entry.", "data": {}},
        "expected": {"category": "clinical", "department": "Clinical", "severity": "high"},
    },
    # UKG scheduling
    {
        "input": {"source_type": "ukg", "text": "Schedule sync error for nursing department. 15 shifts unassigned for next week.", "data": {}},
        "expected": {"category": "hr", "department": "HR", "severity": "normal"},
    },
]


def make_envelope(test_case: dict) -> Envelope:
    """Build an Envelope from test case input."""
    inp = test_case["input"]
    return Envelope(
        source="benchmark",
        source_type=inp.get("source_type", ""),
        payload=Payload(text=inp.get("text", ""), data=inp.get("data", {})),
        routing_hints=RoutingHints(),
        metadata=Metadata(),
    )


def run_benchmark(classify_fn=None):
    """Run benchmark against current or custom classifier. Returns results dict."""
    if classify_fn is None:
        from trellis.classification import classify_envelope
        classify_fn = classify_envelope

    results = {
        "total": len(TEST_ENVELOPES),
        "correct_category": 0,
        "correct_department": 0,
        "correct_severity": 0,
        "correct_all": 0,
        "failures": [],
        "latency_ms": [],
    }

    for i, tc in enumerate(TEST_ENVELOPES):
        envelope = make_envelope(tc)
        expected = tc["expected"]

        start = time.perf_counter()
        enriched = classify_fn(envelope)
        elapsed_ms = (time.perf_counter() - start) * 1000
        results["latency_ms"].append(elapsed_ms)

        # Extract actual results
        classification = (enriched.payload.data or {}).get("_classification", {})
        actual_cat = classification.get("category")
        actual_dept = classification.get("department")
        actual_sev = classification.get("severity", "normal")

        cat_ok = actual_cat == expected["category"]
        dept_ok = actual_dept == expected["department"]
        sev_ok = actual_sev == expected["severity"]

        if cat_ok:
            results["correct_category"] += 1
        if dept_ok:
            results["correct_department"] += 1
        if sev_ok:
            results["correct_severity"] += 1
        if cat_ok and dept_ok and sev_ok:
            results["correct_all"] += 1
        else:
            results["failures"].append({
                "index": i,
                "text": tc["input"]["text"][:80],
                "expected": expected,
                "actual": {"category": actual_cat, "department": actual_dept, "severity": actual_sev},
                "cat_ok": cat_ok, "dept_ok": dept_ok, "sev_ok": sev_ok,
            })

    # Summary stats
    n = results["total"]
    results["accuracy"] = {
        "category": results["correct_category"] / n,
        "department": results["correct_department"] / n,
        "severity": results["correct_severity"] / n,
        "all": results["correct_all"] / n,
    }
    results["avg_latency_ms"] = sum(results["latency_ms"]) / len(results["latency_ms"])
    results["max_latency_ms"] = max(results["latency_ms"])

    return results


def print_results(results: dict):
    """Pretty-print benchmark results."""
    print(f"\n{'='*60}")
    print(f"CLASSIFICATION ENGINE BENCHMARK")
    print(f"{'='*60}")
    print(f"Total test cases: {results['total']}")
    print(f"Category accuracy:   {results['accuracy']['category']:.1%} ({results['correct_category']}/{results['total']})")
    print(f"Department accuracy: {results['accuracy']['department']:.1%} ({results['correct_department']}/{results['total']})")
    print(f"Severity accuracy:   {results['accuracy']['severity']:.1%} ({results['correct_severity']}/{results['total']})")
    print(f"All-correct:         {results['accuracy']['all']:.1%} ({results['correct_all']}/{results['total']})")
    print(f"Avg latency: {results['avg_latency_ms']:.3f}ms")
    print(f"Max latency: {results['max_latency_ms']:.3f}ms")

    if results["failures"]:
        print(f"\n{'─'*60}")
        print(f"FAILURES ({len(results['failures'])}):")
        for f in results["failures"]:
            print(f"\n  #{f['index']}: {f['text']}...")
            print(f"    Expected: {f['expected']}")
            print(f"    Actual:   {f['actual']}")
            flags = []
            if not f["cat_ok"]: flags.append("CAT")
            if not f["dept_ok"]: flags.append("DEPT")
            if not f["sev_ok"]: flags.append("SEV")
            print(f"    Wrong: {', '.join(flags)}")

    print(f"\n{'='*60}")


if __name__ == "__main__":
    results = run_benchmark()
    print_results(results)
    # Save results for Qwopus to read
    with open(Path(__file__).parent / "baseline_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to baseline_results.json")
