## 2026-08-16T01:37:51Z
You are Worker for Milestone 3 (Filesystem Safety & Storage Boundaries).

Your working directory is `/Users/iml1s/Documents/mine/grok-build-termux/.agents/worker_m3_1`.
Create your directory and write your `progress.md` and `handoff.md` there.

Read the authoritative files:
- `/Users/iml1s/Documents/mine/grok-build-termux/ORIGINAL_REQUEST.md` (MANDATORY)
- `/Users/iml1s/Documents/mine/grok-build-termux/PROJECT.md`
- `/Users/iml1s/Documents/mine/grok-build-termux/.agents/explorer_m3_1/handoff.md`
- `/Users/iml1s/Documents/mine/grok-build-termux/.agents/explorer_m3_2/handoff.md`
- `/Users/iml1s/Documents/mine/grok-build-termux/.agents/explorer_m3_3/handoff.md`

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Your Tasks for Milestone 3 (Features 10–14):
1. **System Config & User Home Boundaries (Features 10 & 11)**:
   - Verify and ensure `$PREFIX/etc/grok` on Android/Termux vs `/etc/grok` on Linux, and user state strictly in `$HOME/.grok`.
2. **Temporary Files & Unix Domain Sockets (Feature 12)**:
   - Ensure `$TMPDIR` (or `$PREFIX/tmp`) is used dynamically, avoiding hardcoded `/tmp`.
   - Ensure `xai-grok-diag-server` supports dynamic `temp_dir()` socket paths.
   - Ensure Unix domain socket paths stay strictly under the 108-byte `sun_path` limit with Blake3 short hash and stale socket cleanup.
3. **Shared Storage Quarantine & Workspace Protection (Features 13 & 14)**:
   - Ensure `validate_storage_safety` strictly rejects credentials on `/sdcard`, `/storage/emulated/0`, etc.
   - Ensure editing workspaces on `/sdcard` keeps sessions, tokens, and caches safely inside `$HOME/.grok` and `$TMPDIR`.
4. **Verification**:
   - Run `cargo check --workspace`
   - Run `cargo test -p xai-grok-config`
   - Run `cargo test -p xai-grok-shared`
   - Run `python3 tests/e2e/runner.py` (verify 366/366 pass)
   - Run `python3 scripts/validate_elf.py --self-test`
5. **Commit**:
   - Commit all Milestone 3 changes cleanly to `termux-native` branch with a clear message.

Deliver a detailed handoff report in `/Users/iml1s/Documents/mine/grok-build-termux/.agents/worker_m3_1/handoff.md`.
Use `send_message` to notify the orchestrator when complete.
