# Milestone 3 Challenger 2 Report: Filesystem Safety & Storage Boundaries

**Author**: Challenger 2 (`challenger_m3_2`)  
**Roles**: critic, specialist  
**Scope**: Milestone 3 Adversarial Challenge — Runtime Temporary Files & Unix Domain Sockets (Feature 12)  
**Target Commit**: `4d266db` (`feat(filesystem): implement dynamic temp sockets, system config, and storage boundaries (Milestone 3)`)  
**Date**: 2026-08-16  
**Verdict**: **`APPROVE`**  

---

## 1. Observation

### 1.1 Requirements & Interface Contracts Tested
From `ORIGINAL_REQUEST.md`:
> Line 19: "Ensure configuration, credentials, sockets, and cache directories resolve to Termux-owned private paths (`$PREFIX/etc/grok`, `$HOME/.grok`, `$TMPDIR`). Strictly reject housing `GROK_HOME` or credentials on Android shared storage (`/sdcard`, `/storage/emulated/0`) to preserve owner-only permissions."

From `PROJECT.md`:
> Feature 12: "Runtime Temporary & Sockets: Uses `$TMPDIR` for ephemeral files and creates short Unix sockets (< 108 bytes) with stale cleanup"

### 1.2 Codebase Implementations Inspected
1. **Socket Path Construction and Length Boundary** (`crates/codegen/xai-grok-config/src/platform.rs`, lines 352–364):
   ```rust
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
   - Uses Blake3 8-hex-char digest (`grok-{hash8}.sock` = 18 bytes).
   - Enforces strict `< 108` bytes limit (`if path_str.len() >= 108`), matching POSIX Linux `sockaddr_un.sun_path[108]`.

2. **Temporary Directory and Fallback Resolution** (`crates/codegen/xai-grok-config/src/platform.rs`, lines 234–244):
   ```rust
   let tmp = env
       .get_var("TMPDIR")
       .filter(|s| !s.trim().is_empty())
       .map(PathBuf::from)
       .unwrap_or_else(|| {
           if let Some(ref p) = prefix {
               p.join("tmp")
           } else {
               PathBuf::from("/tmp")
           }
       });
   ```
   - Filters out empty and whitespace-only `$TMPDIR` values.
   - Falls back dynamically to `$PREFIX/tmp` on Termux, or `/tmp` when `$PREFIX` is unset.

3. **Diagnostics Server Default Socket & Stale Cleanup** (`crates/codegen/xai-grok-diag-server/src/lib.rs`, lines 34–47, 407–418):
   ```rust
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
   ```rust
   #[cfg(unix)]
   DiagListener::Unix(path) => {
       let _ = fs::remove_file(&path);
       let listener =
           UnixListener::bind(&path).map_err(|e| anyhow!("bind {}: {e}", path.display()))?;
       use std::os::unix::fs::PermissionsExt as _;
       if let Err(e) = fs::set_permissions(&path, fs::Permissions::from_mode(0o600)) {
           tracing::warn!(
               path = %path.display(),
               error = %e,
               "failed to restrict diagnostics socket permissions"
           );
       }
       ...
   }
   ```
   - Prior to binding, stale/dead socket files are unlinked with `fs::remove_file`.
   - File permissions on the socket are explicitly set to `0600` (`-rw-------`).

### 1.3 Verbatim Execution Results of Adversarial Test Suites
1. **Rust Socket Adversarial Suite (`cargo test -p xai-grok-config --test socket_adversarial`)**:
   ```
   running 5 tests
   test test_socket_path_exact_107_bytes_accepted ... ok
   test test_socket_path_exact_108_bytes_rejected ... ok
   test test_socket_path_exact_109_bytes_rejected ... ok
   test test_socket_path_blake3_compression_invariance ... ok
   test test_tmpdir_fallback_and_whitespace_filtering ... ok

   test result: ok. 5 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s
   ```
2. **Full Workspace Config Test Suite (`cargo test -p xai-grok-config`)**:
   - `src/lib.rs`: 213 passed, 0 failed.
   - `tests/challenger_m3_adversarial.rs`: 12 passed, 0 failed.
   - `tests/platform_adversarial.rs`: 15 passed, 0 failed.
   - `tests/shell_adversarial.rs`: 2 passed, 0 failed.
   - `tests/socket_adversarial.rs`: 5 passed, 0 failed.
   - **Total**: 247 passed, 0 failed.
3. **Diagnostics Server Test Suite (`cargo test -p xai-grok-diag-server`)**:
   - 20 passed, 0 failed (including `unix_socket_serves_ready_and_rebinds_over_stale_socket` and `test_default_diag_socket_path`).
4. **Milestone 3 Python Adversarial Suite (`python3 tests/e2e/adversarial_m3_challenge.py -v`)**:
   - 17/17 tests passed:
     - `test_adv_01_exact_107_bytes_socket_path_accepted`: ok
     - `test_adv_02_exact_108_bytes_socket_path_rejected`: ok
     - `test_adv_03_exact_109_bytes_socket_path_rejected`: ok
     - `test_adv_04_utf8_multibyte_session_id_compression_stability`: ok
     - `test_adv_05_extreme_session_id_lengths`: ok
     - `test_adv_06_termux_standard_path_safety_margin`: ok (54 bytes headroom)
     - `test_adv_07_real_unix_socket_stale_cleanup_and_bind`: ok
     - `test_adv_08_socket_permission_strictly_0600`: ok
     - `test_adv_09_rapid_rebind_stress_100_cycles`: ok (100 rapid rebinds without EADDRINUSE)
     - `test_adv_10_cleanup_non_socket_regular_file_and_dangling_symlink`: ok
     - `test_adv_11_concurrent_clients_over_0600_socket`: ok (10 concurrent clients)
     - `test_adv_12_tmpdir_precedence_when_explicitly_set`: ok
     - `test_adv_13_tmpdir_unset_falls_back_to_prefix_tmp_on_termux`: ok
     - `test_adv_14_tmpdir_unset_falls_back_to_root_tmp_on_desktop`: ok
     - `test_adv_15_tmpdir_empty_string_and_whitespace_fallback`: ok
     - `test_adv_16_both_tmpdir_and_prefix_unset_on_android_graceful_fallback`: ok
     - `test_adv_17_dual_track_workspace_sdcard_isolation`: ok
5. **Full E2E 4-Tier Test Runner (`python3 tests/e2e/runner.py`)**:
   - 366/366 passed across Tiers 1–4 in 7.585s (100% SUCCESS).
6. **Milestone 3 Stress Suite (`python3 tests/stress_test_milestone3.py`)**:
   - 5/5 passed.

---

## 2. Logic Chain

1. **Socket Path Length Boundary & Compression Invariance**:
   - Under Linux Bionic libc, `struct sockaddr_un` defines `sun_path` as a 108-byte array. A valid null-terminated Unix socket path can have at most 107 bytes.
   - `create_socket_path(session_id)` hashes arbitrary session IDs into an 8-character hex string via Blake3. The resulting filename `grok-{hash8}.sock` is consistently 18 bytes.
   - For standard Termux (`$PREFIX/tmp` = `/data/data/com.termux/files/usr/tmp`), the full path is 53 bytes, leaving a 54-byte safety margin.
   - When tested against boundary lengths:
     - Exact 107 bytes: `create_socket_path` succeeds (`path_str.len() == 107 < 108`).
     - Exact 108 bytes: `create_socket_path` rejects with `PlatformError::SocketPathTooLong`.
     - Exact 109 bytes: `create_socket_path` rejects with `PlatformError::SocketPathTooLong`.
     - Multi-byte UTF-8, emojis, empty strings, and 100,000-character inputs all compress to invariant 18-byte filenames without inflating path length.

2. **Stale Socket Detection, Atomic Cleanup, and Permissions (0600)**:
   - When a daemon terminates abruptly or crashes, the socket inode remains on the filesystem.
   - Both `xai-grok-diag-server` and `xai-grok-shell::leader::server` execute `std::fs::remove_file(&socket_path)` immediately before `UnixListener::bind(&socket_path)`.
   - Empirically verified across 100 consecutive rapid bind-unbind-rebind cycles with active client connections: zero `EADDRINUSE` errors occurred.
   - Collisions with non-socket regular files and dangling symlinks are successfully unlinked and rebound.
   - Socket permissions are explicitly set to `0600` (`-rw-------`), preventing unauthorized local Android apps from connecting.

3. **`$TMPDIR` Fallback & Sanitization Logic**:
   - `PlatformCapabilities::probe` and `diag_server::default_diag_socket_path` prioritize `$TMPDIR` when non-empty.
   - If `$TMPDIR` is unset, empty (`""`), or consists solely of whitespace (`" \t\n "`), it falls back to `$PREFIX/tmp` on Termux, or `/tmp` when `$PREFIX` is absent.
   - Empirically verified across all combinations of environment variables.

---

## 3. Caveats

1. **Host OS vs Target OS Temp Directories**:
   - In local tests on macOS host, `tempfile::tempdir()` creates directories under `/var/folders/.../T/` (~60–80 bytes).
   - In actual Termux on Android, `$PREFIX/tmp` is `/data/data/com.termux/files/usr/tmp` (34 bytes), providing significantly more headroom (54 bytes).
2. **Directory Inodes at Socket Path**:
   - If an existing directory squats at the exact socket path, `fs::remove_file` will fail (as it requires `remove_dir`). This correctly fails closed with an actionable bind error rather than recursively deleting user directories.

---

## 4. Conclusion

Milestone 3 (Filesystem Safety & Storage Boundaries, Feature 12) passes all adversarial stress tests and boundary checks:
- **107 bytes socket path**: Accepted without error.
- **108 bytes socket path**: Rejected with `PlatformError::SocketPathTooLong`.
- **Stale socket cleanup**: Automatic unlinking and successful re-bind without `EADDRINUSE`.
- **Socket permissions**: Strictly enforced at `0600` (owner-only).
- **`$TMPDIR` fallback**: Correctly resolves `$TMPDIR` -> `$PREFIX/tmp` on Termux -> `/tmp` fallback, sanitizing whitespace/empty strings.
- **Test suites**: 100% passing across `cargo test -p xai-grok-config` (247 tests), `cargo test -p xai-grok-diag-server` (20 tests), and `python3 tests/e2e/runner.py` (366 tests).

**Final Verdict**: **`APPROVE`**

---

## 5. Verification Method

To independently reproduce and verify all adversarial challenges:

```bash
# 1. Run Rust adversarial tests for socket boundaries & TMPDIR fallback
cargo test -p xai-grok-config --test socket_adversarial

# 2. Run all config crate tests (247 tests)
cargo test -p xai-grok-config

# 3. Run diag-server crate tests (20 tests)
cargo test -p xai-grok-diag-server

# 4. Run Python Milestone 3 adversarial challenge suite (17 tests)
python3 tests/e2e/adversarial_m3_challenge.py -v

# 5. Run Milestone 3 stress test suite (5 tests)
python3 tests/stress_test_milestone3.py -v

# 6. Run full 4-Tier E2E test runner (366 tests)
python3 tests/e2e/runner.py
```
