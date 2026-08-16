# Plan — grok-build-termux Orchestrator

## Objective
Deliver a verified, clean, native Android/Termux port of Grok Build (`xai-org/grok-build@eb267feff13129e568df38fb6fdf0ceb65f735d6`) meeting all requirements R1-R5 and passing rigorous tests and forensic audit.

## Steps

### Step 0: Survey & Map Full Scope
- Dispatch 3 parallel Explorers / Spec Miners:
  - `explorer_1`: Survey upstream repository structure, current codebase status in workspace, Rust toolchain, and dependency tree (identifying `jemalloc`, `arboard`, `cpal`, etc.).
  - `spec_miner_1`: Extract all functional requirements, CLI flags, OAuth flows, config paths, Termux APIs, and sandboxing behavior from `ORIGINAL_REQUEST.md`, `bootstrap-grok-build-termux.sh`, and upstream code.
  - `explorer_2`: Investigate Bionic toolchain, NDK requirements, 16 KiB ELF page alignment, cross-compilation targets (`aarch64-linux-android`), and test harness possibilities.
- Aggregate survey reports into `PROJECT.md` Feature Inventory & Architecture.

### Step 1: Initialize Global Project State & Dual Track
- Author `PROJECT.md`, `TEST_INFRA.md`, `DEAD_ENDS.md`, `GATE_STATUS.md`.
- Establish Implementation Track & E2E Testing Track.

### Step 2: Execute Implementation Milestones
- M1: Platform Capability & Dependency Isolation (R1)
- M2: Native Bionic Build & Toolchain Alignment (R2)
- M3: Filesystem Safety & Storage Boundaries (R3)
- M4: Termux Auth, UX & Truthful Sandboxing (R4)
- M5: Distribution, Diagnostics & Upstream Synchronization (R5)

### Step 3: Dual Track E2E Testing & Hardening
- Build 4-Tier E2E test suite (Opaque-box) -> Publish `TEST_READY.md`.
- Implementation Track passes 100% of Tiers 1-4 tests.
- Tier 5 Adversarial Coverage Hardening (Challenger-driven).
- Forensic Integrity Audit (`teamwork_preview_auditor`).

### Step 4: Verification & Handoff
- Deliver structured handoff report to Sentinel with evidence and verification.
