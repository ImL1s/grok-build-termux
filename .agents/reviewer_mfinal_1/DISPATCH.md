# Reviewer 1 Task: Milestone M_FINAL Full Project Review (Platform, Toolchain & Storage)

## Mission
Conduct an independent code and test review on:
1. Platform capability detection (`PlatformCapabilities`, dynamic `$PREFIX`, lack of display, audio exclusion)
2. Native Bionic build & 16 KiB ELF alignment (`.cargo/config.toml`, NDK setup, `scripts/validate_elf.py`)
3. Storage safety boundaries & quarantine (`$PREFIX/etc/grok`, `$HOME/.grok`, `/sdcard` quarantine, Unix socket path length bounds)
4. Verify tests and build pass (`python3 tests/e2e/runner.py --tier all`, `python3 scripts/validate_elf.py --self-test`).

## Output
Deliver verdict (APPROVE or REQUEST_CHANGES) with rationale and evidence in `/Users/iml1s/Documents/mine/grok-build-termux/.agents/reviewer_mfinal_1/handoff.md`.
Send completion message back.
