## 2026-08-15T16:05:43Z

Formulate the exact hardening patch for `validate_storage_safety` in `crates/codegen/xai-grok-config/src/platform.rs`:
1. **Dangling Symlinks**: When checking symlinks, if `path.is_symlink()` or `std::fs::read_link(path)` succeeds, check the link destination with `validate_storage_safety` even if the target does not exist on disk yet (handling `NotFound` from `canonicalize`).
2. **Lexical Normalization**: Lexically normalize paths (resolving `.` and `..` components cleanly without requiring disk existence) before checking prefixes.
3. **Case Insensitivity**: Use case-insensitive matching (`to_lowercase()`) against quarantine prefixes: `/sdcard`, `/storage`, `/mnt/sdcard`, `/mnt/media_rw`, `sdcard`, `storage`.
4. **Relative Path Prefixes**: Catch relative paths such as `sdcard/...`, `storage/emulated/...`.

Write the exact code diff and verification tests to /Users/iml1s/Documents/mine/grok-build-termux/.agents/teamwork_preview_explorer_m1_remediation/handoff.md.
When finished, send a message to parent f8a62484-7465-4198-a94f-7093afe162ee.
