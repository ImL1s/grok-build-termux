# DISPATCH

## 2026-08-16T00:46:35+08:00

You are Worker for Milestone 2 (Native Bionic Build & Toolchain Alignment).

Your working directory is `/Users/iml1s/Documents/mine/grok-build-termux/.agents/worker_m2_1`.
Create your directory and write your `progress.md` and `handoff.md` there.

Read the authoritative files:
- `/Users/iml1s/Documents/mine/grok-build-termux/ORIGINAL_REQUEST.md` (MANDATORY)
- `/Users/iml1s/Documents/mine/grok-build-termux/PROJECT.md`
- `/Users/iml1s/Documents/mine/grok-build-termux/.agents/explorer_m2_1/handoff.md`
- `/Users/iml1s/Documents/mine/grok-build-termux/.agents/explorer_m2_2/handoff.md`
- `/Users/iml1s/Documents/mine/grok-build-termux/.agents/explorer_m2_3/handoff.md`

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Your Tasks for Milestone 2 (Features 6–9):
1. **Target Toolchain Configuration**:
   - Update `.cargo/config.toml` to configure `[target.aarch64-linux-android]` and `[target.x86_64-linux-android]` with `-C link-arg=-Wl,-z,max-page-size=16384`, `-C link-arg=-Wl,-z,relro,-z,now,-z,noexecstack`, and `-C force-unwind-tables=yes`.
   - Update `rust-toolchain.toml` to include `aarch64-linux-android` and `x86_64-linux-android`.
2. **Build Scripts Desktop Download Bypass**:
   - Update `crates/codegen/xai-grok-tools/build.rs` and `crates/codegen/xai-grok-shell/build.rs` to bypass desktop binary downloads and embeddings when `target_os == "android"` (unless an explicit override is provided).
3. **Cross-Compilation Fix**:
   - In `crates/codegen/xai-grok-pager-render/src/theme/system_appearance.rs`, handle `target_os = "android"` gracefully (return `None` for desktop appearance).
4. **Runtime Tool Resolution**:
   - Update `crates/codegen/xai-grok-config/src/shell.rs` to include `$PREFIX/bin`, `/system/bin`, and system paths in Unix shell resolution.
   - Ensure tool resolution in `xai-grok-tools` resolves native tools (`rg`, `fd`, `git`, `bash`) from `$PATH` / `$PREFIX/bin` and provides actionable hints (`pkg install <package>`).
5. **Verification**:
   - Run `cargo check` / `cargo check --target aarch64-linux-android`
   - Run `cargo test -p xai-grok-config -p xai-grok-shared`
   - Run `python3 tests/e2e/runner.py` (verify 366/366 tests pass)
   - Run `python3 scripts/validate_elf.py --self-test`
6. **Commit**:
   - Commit all Milestone 2 changes cleanly to `termux-native` branch with a clear message.

Deliver a detailed handoff report in `/Users/iml1s/Documents/mine/grok-build-termux/.agents/worker_m2_1/handoff.md`.
Use `send_message` to notify the orchestrator when complete.
