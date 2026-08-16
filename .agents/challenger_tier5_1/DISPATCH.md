# Challenger 1 Task: Tier 5 Adversarial Coverage Hardening (Storage, Platform & Filesystem Boundaries)

## Mission
Conduct white-box adversarial testing and coverage hardening on:
1. Platform capability detection (`xai-grok-config`, `xai-grok-paths`, `xai-grok-sandbox`)
2. Shared storage quarantine (`/sdcard`, `/storage/emulated/0`, symlink escapes, relative path tricks, uncanonicalized paths)
3. Socket path constraints (<108 bytes, stale socket cleanup, permission masks `0700`)
4. Dynamic `$PREFIX` manipulation and validation failures

## Instructions
1. Read `ORIGINAL_REQUEST.md`, `PROJECT.md`, `TEST_INFRA.md`, and all relevant crate implementations.
2. Formulate hostile inputs, stress cases, and edge cases.
3. Write / execute adversarial test cases (e.g., in `tests/e2e/tier5_adversarial/test_adversarial_storage_platform.py`).
4. Document all findings, coverage gaps, and test results in `/Users/iml1s/Documents/mine/grok-build-termux/.agents/challenger_tier5_1/handoff.md`.
5. Send completion message back to orchestrator.

## 2026-08-15T19:11:20Z
You are teamwork_preview_challenger (Challenger 1) for Milestone M_FINAL Phase 2 (Tier 5 Adversarial Hardening).
Your working directory is /Users/iml1s/Documents/mine/grok-build-termux/.agents/challenger_tier5_1.
Your task is defined in /Users/iml1s/Documents/mine/grok-build-termux/.agents/challenger_tier5_1/DISPATCH.md.

MANDATORY: Read /Users/iml1s/Documents/mine/grok-build-termux/ORIGINAL_REQUEST.md, PROJECT.md, TEST_INFRA.md, and TEST_READY.md before starting.

Focus on white-box adversarial analysis:
- Platform detection & capabilities spoofing
- Shared storage quarantine (/sdcard traversal, symlink loops, relative path tricks)
- Unix socket constraints (<108 bytes, stale socket cleanup, permission masks)
- In-process path enforcement & policy-only sandbox validation

Create adversarial test suite in `tests/e2e/tier5_adversarial/test_adversarial_storage_platform.py` and run it.
Document all findings, coverage gaps, and test execution results in /Users/iml1s/Documents/mine/grok-build-termux/.agents/challenger_tier5_1/handoff.md.
Send a completion message back when done.
