## 2026-08-15T15:38:02Z

You are teamwork_preview_worker_m1.
Your working directory is: /Users/iml1s/Documents/mine/grok-build-termux/.agents/teamwork_preview_worker_m1
Your parent orchestrator is: f8a62484-7465-4198-a94f-7093afe162ee

Read:
- /Users/iml1s/Documents/mine/grok-build-termux/ORIGINAL_REQUEST.md
- /Users/iml1s/Documents/mine/grok-build-termux/PROJECT.md
- /Users/iml1s/Documents/mine/grok-build-termux/.agents/teamwork_preview_explorer_m1_1/handoff.md
- /Users/iml1s/Documents/mine/grok-build-termux/.agents/teamwork_preview_explorer_m1_2/handoff.md
- /Users/iml1s/Documents/mine/grok-build-termux/.agents/teamwork_preview_spec_miner_m1_3/handoff.md

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Scope & Ownership for Milestone 1 (Platform Capability & Dependency Isolation, R1):
1. **Workspace Initialization**:
   - In `/Users/iml1s/Documents/mine/grok-build-termux`, initialize a Git repository with upstream tracking from `/Users/iml1s/Documents/mine/grok-build` at commit `eb267feff13129e568df38fb6fdf0ceb65f735d6`, creating branch `termux-native`.
   - Preserve existing management and agent files.
2. **Platform Capabilities Implementation (`xai-grok-config`)**:
   - Implement `crates/codegen/xai-grok-config/src/platform.rs` with `PlatformCapabilities`, `PlatformKind`, `SandboxKind`, `EnvLookup`, `MockEnv`, dynamic `$PREFIX` resolution (failing closed if unset on Android), and `validate_storage_safety` (rejecting `/sdcard` and `/storage/emulated/0`).
   - Wire `platform.rs` into `xai-grok-config/src/lib.rs`, `paths.rs` (`system_config_dir` -> `$PREFIX/etc/grok`), and `state_dir.rs`.
   - Add comprehensive unit tests in `xai-grok-config/src/platform.rs` covering stock Termux, custom prefix, missing prefix, desktop Unix, macOS, display/audio detection, and storage quarantine.
3. **Dependency Gating**:
   - **`tikv-jemallocator`**: In `crates/codegen/xai-grok-pager-bin/Cargo.toml` and `src/main.rs`, gate `tikv-jemallocator` to `all(unix, not(target_os = "android"))` so Android uses Bionic's system allocator.
   - **`arboard`**: In `crates/codegen/xai-grok-shared/Cargo.toml`, exclude `target_os = "android"`. In `src/clipboard.rs`, add `#[cfg(target_os = "android")] mod platform` implementing `termux-clipboard-*` with OSC 52 fallback.
   - **`cpal`**: In `crates/codegen/xai-grok-voice/Cargo.toml` and `src/`, gate `cpal` to exclude Android and stub voice cleanly without panic.
   - **`nono` / Landlock**: In `crates/codegen/xai-grok-sandbox/Cargo.toml` and `src/`, gate `nono` to exclude Android and truthfully record sandbox as `policy-only`.
4. **Verification**:
   - Run tests: `cargo test -p xai-grok-config`, `cargo test -p xai-grok-shared`.
   - Verify `cargo tree` / `cargo check` for `aarch64-linux-android` (e.g. `cargo check --target aarch64-linux-android -p xai-grok-config -p xai-grok-shared -p xai-grok-voice -p xai-grok-sandbox -p xai-grok-pager-bin --no-default-features`).
   - Document all build and test command outputs in your handoff report.

Write your handoff report to `/Users/iml1s/Documents/mine/grok-build-termux/.agents/teamwork_preview_worker_m1/handoff.md`.
When finished, send a message to parent f8a62484-7465-4198-a94f-7093afe162ee.
