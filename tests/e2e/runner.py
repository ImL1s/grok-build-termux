#!/usr/bin/env python3
"""
Unified E2E Test Suite Runner for grok-build-termux.

Runs and reports:
- Tier 1: Feature Coverage (32 features × 5 cases = 160 tests)
- Tier 2: Boundary & Corner Cases (32 features × 5 cases = 160 tests)
- Tier 3: Pairwise Cross-Feature Interactions (34 tests)
- Tier 4: Real-World Application Scenarios (12 tests)
- Tier 5: Adversarial Hardening Suite (93 tests)
Standard full run (Tiers 1-4): 366 tests | Hardening (Tier 5): 93 tests | Total: 459 tests
"""

import argparse
import json
import os
import sys
import time
import unittest
from typing import Dict, List, Any

# Ensure repository root is on sys.path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def run_tier(tier_name: str, test_module_pattern: str, base_dir: str = "tests/e2e") -> Dict[str, Any]:
    loader = unittest.TestLoader()
    start_dir = os.path.join(REPO_ROOT, base_dir, tier_name)
    suite = loader.discover(start_dir=start_dir, pattern=test_module_pattern)
    
    result = unittest.TestResult()
    start_time = time.time()
    suite.run(result)
    elapsed = time.time() - start_time

    return {
        "tier": tier_name,
        "total": result.testsRun,
        "passed": result.testsRun - len(result.failures) - len(result.errors),
        "failures": len(result.failures),
        "errors": len(result.errors),
        "elapsed_seconds": round(elapsed, 3),
        "failure_details": [
            {"test": str(test), "trace": err} for test, err in result.failures + result.errors
        ],
    }


def main():
    parser = argparse.ArgumentParser(
        description="Unified 4-Tier E2E Test Suite Runner for grok-build-termux"
    )
    parser.add_argument(
        "--tier",
        choices=["tier1", "tier2", "tier3", "tier4", "tier5", "all"],
        default="all",
        help="Specify which tier to run (default: all)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit results as structured JSON",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose test execution output",
    )

    args = parser.parse_args()

    tiers_to_run = []
    if args.tier == "all":
        tiers_to_run = [
            ("tier1_features", "Tier 1: Feature Coverage (32 Features × 5)"),
            ("tier2_boundaries", "Tier 2: Boundary & Corner Cases (32 Features × 5)"),
            ("tier3_cross_feature", "Tier 3: Pairwise Cross-Feature Interactions"),
            ("tier4_real_world", "Tier 4: Real-World Application Scenarios"),
        ]
    elif args.tier == "tier1":
        tiers_to_run = [("tier1_features", "Tier 1: Feature Coverage")]
    elif args.tier == "tier2":
        tiers_to_run = [("tier2_boundaries", "Tier 2: Boundary & Corner Cases")]
    elif args.tier == "tier3":
        tiers_to_run = [("tier3_cross_feature", "Tier 3: Pairwise Cross-Feature Interactions")]
    elif args.tier == "tier4":
        tiers_to_run = [("tier4_real_world", "Tier 4: Real-World Application Scenarios")]
    elif args.tier == "tier5":
        tiers_to_run = [("tier5_adversarial", "Tier 5: Adversarial Hardening Suite")]

    results = []
    total_tests = 0
    total_passed = 0
    total_failed = 0
    total_errors = 0
    start_total = time.time()

    if not args.json:
        print("=" * 80)
        print(" grok-build-termux : 4-Tier E2E Test Suite Execution")
        print("=" * 80)

    for tier_dir, tier_label in tiers_to_run:
        res = run_tier(tier_dir, "test_*.py")
        res["label"] = tier_label
        results.append(res)
        total_tests += res["total"]
        total_passed += res["passed"]
        total_failed += res["failures"]
        total_errors += res["errors"]

        if not args.json:
            status_icon = "✓" if (res["failures"] == 0 and res["errors"] == 0) else "✗"
            print(
                f"[{status_icon}] {tier_label:<50} "
                f"Tests: {res['total']:>3} | Passed: {res['passed']:>3} | "
                f"Failed: {res['failures']:>2} | Errors: {res['errors']:>2} | Time: {res['elapsed_seconds']:.2f}s"
            )

    elapsed_total = round(time.time() - start_total, 3)
    overall_success = total_failed == 0 and total_errors == 0

    if args.json:
        report = {
            "success": overall_success,
            "total_tests": total_tests,
            "total_passed": total_passed,
            "total_failures": total_failed,
            "total_errors": total_errors,
            "elapsed_seconds": elapsed_total,
            "tier_results": results,
        }
        print(json.dumps(report, indent=2))
    else:
        print("=" * 80)
        status_str = "SUCCESS (100% PASSED)" if overall_success else "FAILED"
        print(f"Summary: {total_passed}/{total_tests} passed in {elapsed_total}s | Result: {status_str}")
        print("=" * 80)

    sys.exit(0 if overall_success else 1)


if __name__ == "__main__":
    main()
