# Dispatch

## 2026-08-15T15:33:24Z
Task: Build the complete, opaque-box, requirement-driven 4-tier E2E test suite for grok-build-termux:
- Tier 1: Feature coverage tests across all 32 inventoried features (≥5 cases per feature).
- Tier 2: Boundary and corner cases (≥5 cases per feature).
- Tier 3: Pairwise cross-feature interaction tests.
- Tier 4: Real-world application scenarios (grok doctor, OAuth login, storage quarantine, clipboard, ELF validation, install mode gating).
- Create `tests/e2e/` test cases and test runner.
- Create `scripts/validate_elf.py` standalone ELF validator.
- When the entire test suite is created and ready, publish `TEST_READY.md` at /Users/iml1s/Documents/mine/grok-build-termux/TEST_READY.md.
