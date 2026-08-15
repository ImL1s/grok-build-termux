# E2E Test Infra: grok-build-termux

## Test Philosophy
- Opaque-box, requirement-driven. Derived from `ORIGINAL_REQUEST.md` and user-facing specs, independent of internal implementation details.
- Methodology: Category-Partition + Boundary Value Analysis (BVA) + Pairwise Combinatorial Testing + Real-World Workload Testing.

## Feature Inventory (from PROJECT.md)
| # | Feature | Source (requirement) | Tier 1 | Tier 2 | Tier 3 |
|---|---------|---------------------|:------:|:------:|:------:|
| 1 | Centralized Platform Capability Layer | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ |
| 2 | Dynamic $PREFIX Discovery | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ |
| 3 | Allocator Gating (Bionic vs Jemalloc) | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ |
| 4 | Desktop Clipboard Gating (arboard) | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ |
| 5 | Voice / Microphone Gating (cpal) | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ |
| 6 | Native Bionic Build Profile | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ |
| 7 | 16 KiB ELF Page-Size Alignment | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ |
| 8 | Native CLI Tool Resolution | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ |
| 9 | Optional Search Tools Fallback | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ |
| 10 | System Configuration Resolution ($PREFIX/etc/grok) | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ |
| 11 | User Home Directory Resolution ($HOME/.grok) | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ |
| 12 | Runtime Temporary & Sockets ($TMPDIR, <108B) | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ |
| 13 | Shared Storage Quarantine (/sdcard refuse) | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ |
| 14 | Shared-Storage Workspace Protection | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ |
| 15 | Termux OAuth Browser Handoff (termux-open-url) | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ |
| 16 | Loopback Callback Server (127.0.0.1) | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ |
| 17 | Manual Code / URL Paste Fallback | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ |
| 18 | Native Bionic DNS & TLS Resolution | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ |
| 19 | Termux:API Text Clipboard | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ |
| 20 | OSC 52 Terminal Clipboard Fallback | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ |
| 21 | Unsupported Clipboard/Voice Graceful Degradation | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ |
| 22 | Truthful Sandbox Reporting (policy-only) | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ |
| 23 | In-Process Policy Enforcement | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ |
| 24 | Conservative Concurrency & Defaults | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ |
| 25 | Termux Wake Lock Integration | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ |
| 26 | Durable Session Checkpoint & Recovery | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ |
| 27 | Package-Managed Install Mode | ORIGINAL_REQUEST §R5 | 5 | 5 | ✓ |
| 28 | Standalone Install Mode & Updater Isolation | ORIGINAL_REQUEST §R5 | 5 | 5 | ✓ |
| 29 | `grok doctor` for Android/Termux | ORIGINAL_REQUEST §R5 | 5 | 5 | ✓ |
| 30 | CI Cross-Compilation & ELF Validator | ORIGINAL_REQUEST §R5 | 5 | 5 | ✓ |
| 31 | Real-Device / Emulator Test Matrix | ORIGINAL_REQUEST §R5 | 5 | 5 | ✓ |
| 32 | Low-Conflict Upstream Sync Strategy | ORIGINAL_REQUEST §R5 | 5 | 5 | ✓ |

## Test Architecture
- Test runner: `cargo test --test e2e_test_suite` and `python3 scripts/validate_elf.py`
- Test case format: Rust integration tests with mock `PlatformContext` and isolated temp directories simulating Termux filesystem, plus ELF static analysis.
- Directory layout:
  - `tests/e2e/tier1_features/`: Feature coverage unit & integration tests
  - `tests/e2e/tier2_boundaries/`: Boundary, corner cases, error-prone inputs
  - `tests/e2e/tier3_cross_feature/`: Cross-feature combinations and pairwise tests
  - `tests/e2e/tier4_real_world/`: Real-world end-to-end scenarios (Doctor, CLI, OAuth simulation, Storage quarantine)

## Real-World Application Scenarios (Tier 4)
| # | Scenario | Features Exercised | Complexity |
|---|----------|--------------------|------------|
| 1 | Full `grok doctor` Diagnostic Execution on Termux | F1, F2, F8, F10, F18, F22, F29 | High |
| 2 | Complete OAuth Login Flow with Browser Handoff & Loopback Callback | F15, F16, F17, F18, F11 | High |
| 3 | Shared Storage (/sdcard) Quarantine & Workspace Access | F10, F11, F13, F14, F23 | High |
| 4 | Clipboard Read/Write with Termux:API and OSC 52 Fallback | F4, F19, F20, F21 | Medium |
| 5 | Cross-Compiled Bionic ELF Header & 16 KiB Alignment Validation | F6, F7, F30 | High |
| 6 | Package-Managed vs Standalone Update Gating | F27, F28 | Medium |

## Coverage Thresholds
- Tier 1: ≥5 per feature (32 features × 5 = 160 cases)
- Tier 2: ≥5 per feature (32 features × 5 = 160 cases)
- Tier 3: ≥32 pairwise cross-feature tests
- Tier 4: ≥6 realistic application scenarios
- **Total Minimum Test Cases**: ~358 tests
