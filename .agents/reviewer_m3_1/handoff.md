# Milestone 3 Review & Adversarial Audit Report: Filesystem Safety & Storage Boundaries

**Author**: Reviewer 1 for Milestone 3 (`reviewer_m3_1`)  
**Roles**: reviewer, critic  
**Target Commit**: `4d266db` (`feat(filesystem): implement dynamic temp sockets, system config, and storage boundaries (Milestone 3)`)  
**Verdict**: **`APPROVE`**  
**Date**: 2026-08-16  

---

## 1. Observation

### 1.1 Evaluated Commits and Files
Inspected git commit `4d266db` and all modified files:
- `crates/codegen/xai-grok-config/src/platform.rs` (lines 323–385, 387–587, 589–950)
- `crates/codegen/xai-grok-config/src/paths.rs` (lines 35–91, 117–254, 496–506)
- `crates/codegen/xai-grok-diag-server/src/lib.rs` (lines 32–48)
- `crates/codegen/xai-grok-workspace/src/bin/workspace_server.rs` (lines 94–96)
- `crates/codegen/xai-grok-config/tests/platform_adversarial.rs` (lines 1–410)
- `crates/codegen/xai-grok-config/tests/shell_adversarial.rs` (lines 1–44)
- `tests/stress_test_milestone3.py` (lines 1–167)
- `tests/e2e/harness/termux_sim.py` (lines 188–218)

### 1.2 Verbatim Code Inspections

1. **System Config & Dynamic Prefix Resolution (`xai-grok-config::platform`)**:
   ```rust
   // crates/codegen/xai-grok-config/src/platform.rs:328-335
   pub fn system_config_dir(&self) -> Option<PathBuf> {
       match self.kind {
           PlatformKind::AndroidTermux => self.prefix.as_ref().map(|p| p.join("etc").join("grok")),
           PlatformKind::UnsupportedAndroid => None,
           PlatformKind::DesktopLinux | PlatformKind::MacOS => Some(PathBuf::from("/etc/grok")),
           PlatformKind::Windows => None,
       }
   }
   ```
   - Dynamically resolves to `$PREFIX/etc/grok` when running in Termux.
   - Fails closed (`None`) on Android when `$PREFIX` is unset or invalid.

2. **Temporary Directory & Unix Domain Socket Bound Safety (<108 bytes)**:
   ```rust
   // crates/codegen/xai-grok-config/src/platform.rs:352-365
   pub fn create_socket_path(&self, session_id: &str) -> Result<PathBuf, PlatformError> {
       let tmp = self.temp_dir();
       let hash = blake3::hash(session_id.as_bytes());
       let short_hash = &hash.to_hex()[..8];
       let sock_name = format!("grok-{short_hash}.sock");
       let sock_path = tmp.join(&sock_name);

       let path_str = sock_path.to_string_lossy();
       if path_str.len() >= 108 {
           return Err(PlatformError::SocketPathTooLong(path_str.into_owned()));
       }
       Ok(sock_path)
   }
   ```
   - Dynamically resolves `$TMPDIR` with fallback to `$PREFIX/tmp` on Termux.
   - Generates compact Blake3 hash socket names (`grok-{short_hash}.sock`), resulting in ~53-byte socket paths on Termux, well within the POSIX 108-byte `sockaddr_un.sun_path` limit.
   - Strictly validates `path_str.len() >= 108` and returns `PlatformError::SocketPathTooLong`.

3. **Diagnostics Server Dynamic Socket Resolution**:
   ```rust
   // crates/codegen/xai-grok-diag-server/src/lib.rs:33-47
   #[cfg(unix)]
   pub fn default_diag_socket_path() -> PathBuf {
       let tmp = std::env::var("TMPDIR")
           .ok()
           .filter(|s| !s.trim().is_empty())
           .map(PathBuf::from)
           .or_else(|| {
               std::env::var("PREFIX")
                   .ok()
                   .filter(|s| !s.trim().is_empty())
                   .map(|p| PathBuf::from(p).join("tmp"))
           })
           .unwrap_or_else(|| PathBuf::from("/tmp"));
       tmp.join("workspace-server.sock")
   }
   ```
   - In `workspace_server.rs:95`, `diag_socket` uses `default_value_os_t = diag_server::default_diag_socket_path()`, removing hardcoded `/tmp` paths on Android.

4. **Multi-Layer Shared Storage Quarantine (`validate_storage_safety`)**:
   - `normalize_lexical`: resolves `.` and `..` without disk access.
   - `is_quarantined_str`: matches `/sdcard`, `/storage`, `/mnt/sdcard`, `/mnt/media_rw`, `/data/sdcard`, `/data/media` with case-insensitivity.
   - Direct symlink and dangling symlink inspection via `std::fs::read_link`.
   - Ancestor directory inspection and disk canonicalization via `dunce::canonicalize`.
   - Dual-track workspace protection: Workspaces on `/sdcard` edit files in CWD, but all state, sessions (`$HOME/.grok/sessions/{hash_slug}`), tokens (`$HOME/.grok/auth.json`), and sockets remain in private Termux app storage with `0700` permissions.

### 1.3 Verbatim Execution of Verification Commands

| Command | Result | Details |
|---|---|---|
| `cargo check --workspace` | **PASS (0)** | Finished `dev` profile in 18.74s |
| `cargo test -p xai-grok-config` | **PASS (0)** | 213 unit + 15 platform_adversarial + 2 shell_adversarial (230 passed, 0 failed) |
| `cargo test -p xai-grok-diag-server` | **PASS (0)** | 20 passed, 0 failed |
| `python3 tests/e2e/runner.py` | **PASS (0)** | 366/366 passed across Tiers 1–4 in 6.92s (100% SUCCESS) |
| `python3 tests/stress_test_milestone3.py` | **PASS (0)** | 5/5 stress tests passed in 0.025s |
| `python3 scripts/validate_elf.py --self-test` | **PASS (0)** | 6/6 ELF validator tests passed |
| `cargo test -p xai-grok-shared` | **PASS (0)** | 99 passed, 0 failed, 4 ignored |

---

## 2. Logic Chain

1. **System Config Path Resolution (Feature 10)**:
   - Observation 1.2.1 confirms that on Android with Termux, `PlatformCapabilities::system_config_dir()` maps directly to `$PREFIX/etc/grok`.
   - When `$PREFIX` is unset or invalid, it returns `None` (fail-closed) rather than leaking desktop `/etc/grok`.
   - Directly satisfies Requirement R3 and Acceptance Criteria line 35.

2. **User Home and Credentials Resolution (Feature 11)**:
   - Observation 1.2.4 & `paths.rs` confirm that `PlatformCapabilities::home_dir()` and `paths::grok_home()` resolve to `$HOME/.grok`.
   - Custom `GROK_HOME` is validated through `validate_storage_safety`: any location on Android shared storage is rejected with `StorageSafetyError::SharedStorageQuarantine`.
   - `paths::grok_home()` intercepts unsafe `GROK_HOME`, logs an error, and falls back to safe `default_grok_home()`.
   - Directly satisfies Requirement R3 and Acceptance Criteria line 35.

3. **Temporary Files & Unix Domain Sockets (Feature 12)**:
   - Observation 1.2.2 & 1.2.3 confirm that `PlatformCapabilities::temp_dir()` and `default_diag_socket_path()` prioritize `$TMPDIR` and fall back to `$PREFIX/tmp` on Termux.
   - Sockets are named `grok-{short_hash}.sock` (8-byte Blake3 hex), producing paths ~53 bytes on Termux, strictly under the 108-byte POSIX limit.
   - Any path >= 108 bytes is rejected with `PlatformError::SocketPathTooLong`.
   - Directly satisfies Requirement R3 and PROJECT.md Feature 12.

4. **Shared Storage Quarantine & Dual-Track Workspace Protection (Features 13 & 14)**:
   - Observation 1.2.4 confirms that `validate_storage_safety` catches all attack vectors: direct shared storage paths, case variations (`/SDCARD`), path traversals (`/data/data/com.termux/files/home/../../../../sdcard`), dangling symlinks, ancestor directory symlinks, and canonical symlink chains.
   - Dual-track architecture allows editing code on `/sdcard` while session logs, chat transcripts, MCP credentials, and tokens are stored in `$HOME/.grok` with `0700` permissions.
   - Directly satisfies Requirement R3, PROJECT.md Features 13–14, and Acceptance Criteria line 36.

---

## 3. Integrity & Adversarial Audit

### 3.1 Integrity Verification
- **Hardcoded Results / Facades**: None. `PlatformCapabilities`, `validate_storage_safety`, `create_socket_path`, and `default_diag_socket_path` are complete, functional implementations with comprehensive error models.
- **Shortcuts & External Dependencies**: No external process delegation for path validation or socket creation. Uses pure Rust path operations, `blake3`, and `dunce`.
- **Verification Output Integrity**: All tests were independently executed during review and produced verified exit code 0.

### 3.2 Adversarial Challenge Analysis

| # | Challenge Scenario | Attack Vector / Edge Case | Observed System Defense | Assessment |
|---|---|---|---|---|
| 1 | Lexical Traversal to Shared Storage | `~/../../../../sdcard/.grok` or `~/../../../../storage/emulated/0/.grok` | `normalize_lexical` collapses parent traversal before prefix check; quarantined with `StorageSafetyError` | **PASS** |
| 2 | Dangling Symlink to Shared Storage | Symlink created in private directory pointing to non-existent `/sdcard/auth.json` | `read_link` detects symlink destination and recursively checks safety even when target does not exist on disk | **PASS** |
| 3 | Ancestor Directory Symlink | Symlink `/tmp/shared -> /sdcard`, accessing `/tmp/shared/sub/creds` | Ancestor walk checks each parent component with `read_link` and `canonicalize`; quarantined | **PASS** |
| 4 | Case-Insensitive Evasion | `/SDCARD/.grok`, `/Storage/Emulated/0/grok`, `/MNT/SDCARD/keys` | `is_quarantined_str` lowercases and normalizes slashes before matching; quarantined | **PASS** |
| 5 | Socket Path Overflow (>108 bytes) | Extremely deep `$TMPDIR` or long prefix causing socket path to exceed 108 bytes | `create_socket_path` checks `path_str.len() >= 108` and returns `PlatformError::SocketPathTooLong` | **PASS** |
| 6 | CWD Dirname Collision & Length | Very long workspace path (>255 bytes) on `/sdcard` | `encode_cwd_dirname` creates compact `{slug}-{blake3_16}` (<= 57 bytes) and writes `.cwd` metadata file | **PASS** |

---

## 4. Caveats

1. **Android `/sdcard` `noexec` Filesystem Flag**:
   - The Android kernel mounts `/sdcard` with `noexec`. Building or executing binaries directly within `/sdcard` will trigger `EACCES`. Source editing is supported, but compilation/execution of native binaries should target `$HOME`.
2. **Path Encoding**:
   - Socket length bounds enforcement explicitly measures byte length (`len()` on UTF-8 string) to conform with POSIX `sockaddr_un.sun_path` byte array bounds.

---

## 5. Conclusion

Milestone 3 (Filesystem Safety & Storage Boundaries, Features 10–14) has been thoroughly inspected, verified, and stress-tested against adversarial evasions. The implementation satisfies all criteria outlined in `ORIGINAL_REQUEST.md` (R3) and `PROJECT.md` (Features 10–14):
- System config resolves to `$PREFIX/etc/grok` on Android/Termux.
- User home and credentials resolve strictly within `$HOME/.grok` (0700 permissions).
- Temporary files and Unix sockets resolve under `$TMPDIR` / `$PREFIX/tmp` and stay strictly under 108 bytes.
- Storage quarantine refuses credentials on `/sdcard` across all traversal and symlink evasion attempts.
- Dual-track protection safely isolates session metadata for `/sdcard` workspaces.

**Explicit Verdict**: **`APPROVE`**

---

## 6. Verification Method

To independently reproduce the verification results:

```bash
# 1. Typecheck entire workspace
cargo check --workspace

# 2. Run unit & adversarial tests for config and diag crates
cargo test -p xai-grok-config
cargo test -p xai-grok-diag-server
cargo test -p xai-grok-shared

# 3. Run full 4-tier E2E test suite (366 tests)
python3 tests/e2e/runner.py

# 4. Run ELF self-test
python3 scripts/validate_elf.py --self-test

# 5. Run Milestone 3 adversarial stress test suite
python3 tests/stress_test_milestone3.py
```
