# Empirical Challenge Report: Milestone 1 Verification

**Verdict**: **REQUEST_CHANGES**

---

## 1. Observation

### 1.1 Platform Capabilities & Edge Case Evaluation
Directly observed via `crates/codegen/xai-grok-config/tests/platform_adversarial.rs` (`cargo test --test platform_adversarial -- --nocapture`):
- **Unset `$PREFIX`**: `PlatformCapabilities::probe(&env)` produces `kind: UnsupportedAndroid`, `prefix_dir() -> Err(PlatformError::MissingPrefix)`, `system_config_dir() -> None`, `sandbox_kind() -> SandboxKind::PolicyOnly`.
- **Empty & Whitespace `$PREFIX`**: `PREFIX=""`, `PREFIX="   "`, `PREFIX="\t\n"` correctly fail closed to `UnsupportedAndroid`.
- **Custom `$PREFIX`**: Custom paths like `/opt/termux/usr` correctly resolve `bin_dir()` to `/opt/termux/usr/bin` and `system_config_dir()` to `Some("/opt/termux/usr/etc/grok")`.
- **Trailing Slashes**: `PREFIX="/data/data/com.termux/files/usr///"` correctly resolves without truncation or panic.
- **Concurrency**: 50 concurrent threads executing 100 `MockEnv` probe cycles completed in 0.03s without data races or panics.
- **Socket Path Limits**: Socket paths >= 108 bytes properly return `Err(PlatformError::SocketPathTooLong)`.

### 1.2 Dependency Gating on Android Target (`aarch64-linux-android`)
Directly observed via `cargo tree` and `cargo check`:
- `cargo check --target aarch64-linux-android -p xai-grok-config -p xai-grok-shared -p xai-grok-voice -p xai-grok-sandbox`: exited 0.
- `cargo tree --target aarch64-linux-android -i tikv-jemallocator`: 0 occurrences.
- `cargo tree --target aarch64-linux-android -p xai-grok-shared -i arboard`: 0 occurrences.
- `cargo tree --target aarch64-linux-android -i cpal`: 0 occurrences.
- `cargo tree --target aarch64-linux-android -i nono`: 0 occurrences.

### 1.3 Tier 2 E2E Suite Execution
Directly observed via `python3 tests/e2e/runner.py --tier tier2`:
```
[✓] Tier 2: Boundary & Corner Cases                         Tests: 160 | Passed: 160 | Failed:  0 | Time: 2.52s
Summary: 160/160 passed in 2.587s | Result: SUCCESS (100% PASSED)
```

### 1.4 Storage Quarantine Vulnerabilities in `crates/codegen/xai-grok-config/src/platform.rs`
Inspected `platform.rs:403-440` (`validate_storage_safety`):
```rust
pub fn validate_storage_safety(path: &Path) -> Result<(), StorageSafetyError> {
    let path_str = path.to_string_lossy();
    let norm = path_str.replace('\\', "/");

    for prefix in ANDROID_SHARED_STORAGE_PREFIXES {
        if norm == *prefix
            || norm.starts_with(&format!("{prefix}/"))
            || norm.starts_with(prefix)
            || norm.contains("/sdcard")
            || norm.contains("/storage/emulated/0")
        {
            return Err(StorageSafetyError::SharedStorageQuarantine { ... });
        }
    }

    // If the path exists on disk, also check its canonicalized target in case of symlinks
    if let Ok(canon) = std::fs::canonicalize(path) {
        let canon_str = canon.to_string_lossy().replace('\\', "/");
        for prefix in ANDROID_SHARED_STORAGE_PREFIXES {
            if canon_str == *prefix ...
        }
    }

    Ok(())
}
```

Direct empirical findings from `cargo test --test platform_adversarial -- --nocapture`:
1. **Dangling Symlink Bypass**:
   When `path` is a symlink pointing to `/sdcard/.grok` (where the target directory does not yet exist on disk), `std::fs::canonicalize(path)` returns `Err(NotFound)`. Because `validate_storage_safety` only handles `if let Ok(canon)`, it fails to inspect `std::fs::read_link(path)` or handle the `Err`. Output:
   `Result of validate_storage_safety on dangling symlink to /sdcard/.grok: Ok(())` -> **SECURITY BYPASS**.
2. **Relative Path & Traversal Bypass**:
   `norm` is not lexically normalized (e.g. resolving `.` and `..` without requiring disk existence). Output:
   - `Result of validate_storage_safety for traversal '/data/data/com.termux/files/home/../../../../storage/emulated/1/.grok': Ok(())` -> **SECURITY BYPASS**.
   - `Result of validate_storage_safety for traversal '/data/data/com.termux/files/home/../../../../storage/1234-5678/.grok': Ok(())` -> **SECURITY BYPASS**.
   - `Result of validate_storage_safety for traversal 'sdcard/.grok': Ok(())` -> **SECURITY BYPASS**.
   - `Result of validate_storage_safety for traversal 'storage/emulated/0/.grok': Ok(())` -> **SECURITY BYPASS**.
3. **Case Sensitivity Bypass**:
   `validate_storage_safety` uses case-sensitive comparisons on filesystems that are case-insensitive on Android shared storage (FAT/sdcardfs/FUSE). Output:
   - `Result of validate_storage_safety for case variant '/SDCARD/.grok': Ok(())` -> **SECURITY BYPASS**.
   - `Result of validate_storage_safety for case variant '/STORAGE/EMULATED/0/.grok': Ok(())` -> **SECURITY BYPASS**.
   - `Result of validate_storage_safety for case variant '/MNT/SDCARD/.grok': Ok(())` -> **SECURITY BYPASS**.

---

## 2. Logic Chain

1. **Requirement R3 & Feature 13 Specification**: `PROJECT.md` lines 18-20, 42, 83 require:
   *"Strictly reject housing GROK_HOME or credentials on Android shared storage (/sdcard, /storage/emulated/0) to preserve owner-only permissions."*
2. **Observation 1.4**: `validate_storage_safety` relies solely on exact case string prefix matching and `std::fs::canonicalize(path)`.
3. **Flaw A (Symlinks)**: On Android, creating a symlink `~/.grok -> /sdcard/.grok` prior to the existence of `/sdcard/.grok` causes `std::fs::canonicalize` to fail with `NotFound`. The function ignores the failure and returns `Ok(())`. When the process subsequently creates files inside `~/.grok`, it writes directly to world-readable shared storage.
4. **Flaw B (Lexical Traversal & Relative Paths)**: Paths using relative prefixes (`sdcard/...`) or dot-dot components (`/data/../storage/emulated/1/...`) do not trigger `starts_with("/storage")` or `contains("/storage/emulated/0")`, bypassing quarantine.
5. **Flaw C (Case Variations)**: Android shared storage often utilizes case-insensitive file systems. Passing `/SDCARD/.grok` or `/Storage/Emulated/0/.grok` bypasses the check while still mapping to external shared storage.
6. **Conclusion**: While PlatformCapabilities and dependency gating are well implemented, `validate_storage_safety` fails to provide the required storage quarantine guarantees and must be hardened before Milestone 1 can be approved.

---

## 3. Caveats

- Android audio capture and Landlock sandbox cannot be verified with live kernel primitives on macOS; verification was conducted via dependency tree exclusion (`cargo tree`), compilation checks (`cargo check --target aarch64-linux-android`), and unit/e2e tests.
- Physical device tests with real Android permissions are deferred to Milestone 5 / M_FINAL.

---

## 4. Conclusion & Required Changes

**Verdict**: **REQUEST_CHANGES**

### Required Remediations in `crates/codegen/xai-grok-config/src/platform.rs`:
1. **Dangling Symlink Inspection**:
   In `validate_storage_safety`, if `path.is_symlink()` or `std::fs::read_link(path).is_ok()`, validate the symlink target path against `validate_storage_safety` recursively or check the uncanonicalized link destination.
2. **Lexical Path Normalization & Lowercasing**:
   Normalize path components lexically (resolving `.` and `..` without requiring disk existence) and perform case-insensitive checking (`to_lowercase()`) against the quarantine prefixes (`/sdcard`, `/storage`, `/mnt/sdcard`, `/mnt/media_rw`, `sdcard`).
3. **Relative Path Safety**:
   Ensure relative paths starting with `sdcard` or `storage` are caught (e.g. by checking `norm.starts_with("sdcard")` or resolving against current working directory).

---

## 5. Verification Method

To independently verify these findings and check fixes:

```bash
# 1. Run the empirical adversarial test suite demonstrating the findings
cargo test --test platform_adversarial -- --nocapture

# 2. Run Tier 2 boundary E2E suite
python3 tests/e2e/runner.py --tier tier2

# 3. Verify Android dependency isolation
cargo check --target aarch64-linux-android -p xai-grok-config -p xai-grok-shared -p xai-grok-voice -p xai-grok-sandbox
cargo tree --target aarch64-linux-android -i tikv-jemallocator
cargo tree --target aarch64-linux-android -p xai-grok-shared -i arboard
cargo tree --target aarch64-linux-android -i cpal
cargo tree --target aarch64-linux-android -i nono
```
