# grok-build-termux bootstrap plan

Target repository: `ImL1s/grok-build-termux`
Official upstream: `xai-org/grok-build`
Verified upstream head: `eb267feff13129e568df38fb6fdf0ceb65f735d6` (`main`)

The bootstrap script queries the upstream head again when executed, forks it with the `-termux` suffix, verifies the parent repository, synchronizes a fresh fork exactly to upstream, configures repository metadata, creates labels and the `v0.1.0-termux-native` milestone, then opens one epic plus twelve linked sub-issues.

## Backlog

1. **[EPIC] Native Android/Termux port of Grok Build**
2. **[P0] Add a centralized Android/Termux platform capability layer**
3. **[P0] Build a native aarch64-linux-android Bionic binary**
4. **[P0] Gate desktop-only allocators, sandbox, clipboard, and voice dependencies on Android**
5. **[P0] Make config, runtime, socket, and storage paths Termux-safe**
6. **[P0] Make OAuth login and network diagnostics native to Termux**
7. **[P0] Use native Termux runtime tools instead of bundled Linux executables**
8. **[P1] Integrate Termux browser and text clipboard with graceful capability fallbacks**
9. **[P1] Provide truthful policy-only sandboxing and Android security guards**
10. **[P1] Harden process lifecycle, concurrency, wake locks, and session resume on Android**
11. **[P1] Add Termux-native packaging, release artifacts, and updater isolation**
12. **[P1] Add Android cross-build CI and a real-device Termux release matrix**
13. **[P2] Document the Termux port and maintain a low-conflict upstream sync workflow**

## Execution
```bash
pkg install gh jq
gh auth login
bash bootstrap-grok-build-termux.sh
```
The script is idempotent by exact issue title. It will reuse an existing valid fork and existing issues instead of duplicating them. It never force-resets an existing diverged fork; only a newly created fork is hard-synced to the current upstream head.
