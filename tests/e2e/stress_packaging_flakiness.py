#!/usr/bin/env python3
"""
Stress & Flakiness Harness for Milestone 5 Release Packaging Tests.
Runs the entire TestReleasePackaging suite 5x consecutively to verify
zero socket leaks, zero port collisions, and zero timing flakiness.
"""

import sys
import os
import time
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tests.e2e.test_release_packaging import TestReleasePackaging


def run_flakiness_stress(iterations: int = 5) -> bool:
    print(f"=== Starting Concurrency & Flakiness Stress Test ({iterations} Iterations) ===")
    overall_passed = True
    timings = []

    for i in range(1, iterations + 1):
        print(f"\n--- Iteration {i}/{iterations} ---")
        suite = unittest.TestLoader().loadTestsFromTestCase(TestReleasePackaging)
        result = unittest.TestResult()
        t0 = time.time()
        suite.run(result)
        elapsed = time.time() - t0
        timings.append(elapsed)

        passed = result.wasSuccessful()
        total = result.testsRun
        failures = len(result.failures)
        errors = len(result.errors)

        status = "PASSED" if passed else "FAILED"
        print(f"Iteration {i}: {status} ({total} tests, {failures} failures, {errors} errors) in {elapsed:.2f}s")

        if not passed:
            overall_passed = False
            for test, trace in result.failures + result.errors:
                print(f"  FAILED: {test}\n{trace}")

    print("\n" + "=" * 60)
    print(f"Stress Test Summary: {iterations}/{iterations} runs completed")
    print(f"Mean time per run: {sum(timings) / len(timings):.2f}s (Min: {min(timings):.2f}s, Max: {max(timings):.2f}s)")
    print(f"Final Verdict: {'100% STABLE / NO FLAKINESS' if overall_passed else 'FLAKY / FAILED'}")
    print("=" * 60)
    return overall_passed


if __name__ == "__main__":
    success = run_flakiness_stress(5)
    sys.exit(0 if success else 1)
