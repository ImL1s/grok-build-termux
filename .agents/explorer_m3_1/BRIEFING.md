# BRIEFING — 2026-08-16T01:38:00+08:00

## Mission
Investigate System Configuration Resolution (Feature 10: `$PREFIX/etc/grok`) and User Home Directory Resolution (Feature 11: `$HOME/.grok`) across the grok codebase for Android/Termux compatibility.

## 🔒 My Identity
- Archetype: Explorer
- Roles: Explorer, Synthesizer
- Working directory: /Users/iml1s/Documents/mine/grok-build-termux/.agents/explorer_m3_1
- Original parent: 3dce7972-86e7-48a1-b0cc-2b75c06411aa
- Milestone: Milestone 3 (Filesystem Safety & Storage Boundaries)

## 🔒 Key Constraints
- Read-only investigation — do NOT implement / modify source code directly.
- System configuration must resolve to `$PREFIX/etc/grok` (falling back to `/etc/grok` on desktop Linux).
- User state, credentials, auth tokens, logs, and telemetry resolve exclusively to `$HOME/.grok` (or `$GROK_HOME` if set).

## Current Parent
- Conversation ID: 3dce7972-86e7-48a1-b0cc-2b75c06411aa
- Updated: 2026-08-16T01:38:00+08:00

## Investigation State
- **Explored paths**:
  - `crates/codegen/xai-grok-config/src/platform.rs`
  - `crates/codegen/xai-grok-config/src/paths.rs`
  - `crates/codegen/xai-grok-config/src/loader.rs`
  - `crates/codegen/xai-grok-config/src/validation.rs`
  - `crates/codegen/xai-grok-config/src/global_hook_sources.rs`
  - `crates/codegen/xai-fast-worktree/src/db/mod.rs`
  - `crates/codegen/xai-grok-sandbox/src/paths.rs`
  - `crates/codegen/xai-grok-telemetry/` (`debug_log.rs`, `hooks_log.rs`, `memory_log.rs`, `unified_log.rs`, `id.rs`, `instrumentation.rs`)
  - `crates/codegen/xai-grok-shell/` (`inspect/mod.rs`, `agent/app.rs`, `extensions/marketplace.rs`, `session/persistence.rs`)
  - `crates/codegen/xai-grok-tools/src/util/grok_home.rs`
  - `crates/codegen/xai-grok-shell-base/src/util/grok_home.rs`
  - `tests/e2e/tier1_features/test_feature_09_to_16.py`
  - `tests/e2e/tier2_boundaries/test_boundaries_09_to_16.py`
  - `tests/e2e/harness/termux_sim.py`
  - `crates/codegen/xai-grok-config/tests/platform_adversarial.rs`
- **Key findings**:
  - Feature 10 (`$PREFIX/etc/grok`): `PlatformCapabilities::system_config_dir()` dynamically generates `prefix.join("etc").join("grok")` when `is_android_termux()` is true, and returns `/etc/grok` on desktop Linux/macOS. Hardcoded `/etc/grok` was fully eliminated and centralized.
  - Feature 11 (`$HOME/.grok`): All submodules, auth credentials (`auth.json`), session history (`sessions/`), worktrees (`worktrees/`), vector DB / memory (`memory/`), MCP server auth (`mcp_credentials.json`), telemetry (`logs/`, `agent_id`, `debug/`), crash dumps (`crash/`), and plugins (`marketplace-cache/`, `plugin-data/`) resolve strictly through `xai_grok_config::grok_home()` / `user_grok_home()`.
  - Storage Boundary Protection: `validate_storage_safety` strictly rejects `/sdcard`, `/storage/emulated/0`, `/mnt/sdcard`, and other shared external storage prefixes with `StorageSafetyError`.
- **Unexplored areas**: None for Features 10 & 11.

## Key Decisions Made
- Comprehensive analysis completed across all crates. Ready for handoff synthesis.

## Artifact Index
- `.agents/explorer_m3_1/DISPATCH.md` — Incoming task log
- `.agents/explorer_m3_1/BRIEFING.md` — Agent working memory
- `.agents/explorer_m3_1/progress.md` — Liveness & progress heartbeat
- `.agents/explorer_m3_1/handoff.md` — 5-component handoff report
