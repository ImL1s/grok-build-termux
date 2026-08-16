# Milestone 3 Handoff Report: Filesystem Safety & Storage Boundaries

**Author**: Worker for Milestone 3 (`worker_m3_1`)  
**Roles**: implementer, qa, specialist  
**Scope**: Features 10–14 (System Config, User Home, Temp & Sockets, Shared Storage Quarantine, Workspace Protection)  
**Branch**: `termux-native`  
**Commit**: `4d266db` (`feat(filesystem): implement dynamic temp sockets, system config, and storage boundaries (Milestone 3)`)  
**Date**: 2026-08-16  

---

## 1. Observation

### 1.1 Requirements and Scope
From `ORIGINAL_REQUEST.md`:
> Line 19: "Ensure configuration, credentials, sockets, and cache directories resolve to Termux-owned private paths (`$PREFIX/etc/grok`, `$HOME/.grok`, `$TMPDIR`). Strictly reject housing `GROK_HOME` or credentials on Android shared storage (`/sdcard`, `/storage/emulated/0`) to preserve owner-only permissions."  
> Line 35: "- [ ] System config resolves to `$PREFIX/etc/grok` and user state resolves to `$HOME/.grok`."  
> Line 36: "- [ ] Credential/token writes to Android shared storage are refused with explicit error messages."

From `PROJECT.md`:
> Line 39–43:
> - Feature 10: System Configuration Resolution (`$PREFIX/etc/grok`)
> - Feature 11: User Home Directory Resolution (`$HOME/.grok`)
> - Feature 12: Runtime Temporary & Sockets (`$TMPDIR`, <108 bytes, blake3 hash, stale cleanup)
> - Feature 13: Shared Storage Quarantine (`/sdcard` rejection with owner-only 0700 requirement)
> - Feature 14: Shared-Storage Workspace Protection (dual-track isolation for `/sdcard` workspaces)

### 1.2 Implemented Changes & Codebase State
1. **Dynamic Diagnostics Socket Resolution (`xai-grok-diag-server`)**:
   - In `crates/codegen/xai-grok-diag-server/src/lib.rs` (lines 32–45):
     ```rust
     /// Resolves the default diagnostics socket path dynamically respecting `$TMPDIR` / `$PREFIX/tmp`.
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
   - In `crates/codegen/xai-grok-workspace/src/bin/workspace_server.rs` (lines 94–96):
     ```rust
     #[cfg(unix)]
     #[arg(long, default_value_os_t = diag_server::default_diag_socket_path())]
     diag_socket: PathBuf,
     ```
   - Replaced hardcoded `/tmp/workspace-server.sock` static CLI default with dynamic lookup honoring `$TMPDIR` and `$PREFIX/tmp`.

2. **Cross-Crate Path Helpers in `xai-grok-config::paths`**:
   - In `crates/codegen/xai-grok-config/src/paths.rs` (lines 82–90):
     ```rust
     /// Temporary directory: `$TMPDIR` or `$PREFIX/tmp` on Termux, `/tmp` on desktop Linux/macOS.
     pub fn temp_dir() -> PathBuf {
         crate::platform::PlatformCapabilities::current().temp_dir()
     }

     /// Create a Unix domain socket path with a Blake3 short hash to stay under 108 bytes.
     pub fn create_socket_path(session_id: &str) -> Result<PathBuf, crate::platform::PlatformError> {
         crate::platform::PlatformCapabilities::current().create_socket_path(session_id)
     }
     ```
   - Added unit tests `paths_temp_dir_resolves` and `paths_create_socket_path_bounds`.

3. **Shared Storage Quarantine & Dual-Track Workspace Protection**:
   - `validate_storage_safety` in `crates/codegen/xai-grok-config/src/platform.rs` enforces multi-layer defense:
     - Normalizes lexical traversal (`..`, `.`).
     - Inspects ancestor symlinks and direct symlinks to detect targets pointing into shared storage prefixes (`/sdcard`, `/storage`, `/mnt/sdcard`, `/mnt/media_rw`, `/data/sdcard`, `/data/media`).
     - Canonicalizes existing paths on disk via `dunce::canonicalize`.
     - Explicit error format: `"GROK_HOME cannot reside on Android shared storage ({path:?}). Owner-only permissions (0700) are required for credentials. Reason: {reason}"`.
   - Dual-track architecture keeps all sessions (`$HOME/.grok/sessions/{encoded_cwd}`), authentication credentials (`$HOME/.grok/auth.json`), MCP credentials (`$HOME/.grok/mcp_credentials.json`), worktree databases, and logs in private Termux storage (`$HOME/.grok` / 0700 permissions) even when user edits files on `/sdcard`.

4. **Test Harness & Stress Test Suite**:
   - Synchronized `tests/e2e/harness/termux_sim.py` `validate_storage_safety` with full case-insensitive prefix checking.
   - Created `tests/stress_test_milestone3.py` covering all 5 features under adversarial conditions.

### 1.3 Verbatim Execution Results
- `cargo check --workspace`: Finished with exit code 0.
- `cargo test -p xai-grok-config`:
  - `src/lib.rs`: 213 passed, 0 failed.
  - `tests/platform_adversarial.rs`: 15 passed, 0 failed.
  - `tests/shell_adversarial.rs`: 2 passed, 0 failed.
- `cargo test -p xai-grok-shared`: 99 passed, 0 failed, 4 ignored.
- `cargo test -p xai-grok-diag-server`: 20 passed, 0 failed.
- `python3 tests/e2e/runner.py`: 366/366 passed in 7.756s (100% SUCCESS across Tiers 1–4).
- `python3 scripts/validate_elf.py --self-test`: 6/6 checks passed.
- `python3 tests/stress_test_milestone3.py`: 5/5 passed.

---

## 2. Logic Chain

1. **System Config Path Disambiguation (Feature 10)**:
   - On Android/Termux, `/etc` is Android's read-only system root. Termux places software packages under dynamic `$PREFIX` (typically `/data/data/com.termux/files/usr`).
   - `PlatformCapabilities::system_config_dir()` maps `PlatformKind::AndroidTermux` to `$PREFIX/etc/grok`. On desktop Linux it maps to `/etc/grok`. On Windows or unsupported Android without `$PREFIX`, it fails closed (`None`).

2. **User State & Credentials Boundary (Feature 11)**:
   - All state, sessions, transcripts, logs, and tokens route through `PlatformCapabilities::home_dir()` and `paths::grok_home()`.
   - Any attempt to configure `GROK_HOME` on Android shared storage is intercepted by `validate_storage_safety` and rejected or reverted to safe `$HOME/.grok`.

3. **Temporary Files & Unix Domain Sockets (Feature 12)**:
   - Android lacks `/tmp` and restricts `/data/local/tmp` under SELinux for non-root apps.
   - `PlatformCapabilities::temp_dir()` prioritizes `$TMPDIR` and falls back to `$PREFIX/tmp` on Termux.
   - POSIX `sockaddr_un.sun_path` enforces a 108-byte hard limit. Termux `$PREFIX/tmp` is 34 bytes. `create_socket_path` compresses session IDs using Blake3 hex hashes (`grok-12345678.sock` = 18 bytes), creating 53-byte socket paths with >50 bytes of margin.
   - Diagnostics server (`xai-grok-diag-server` & `workspace_server`) now uses `default_diag_socket_path()` to dynamically create sockets in `$TMPDIR`/`$PREFIX/tmp`.

4. **Shared Storage Quarantine & Dual-Track Protection (Features 13 & 14)**:
   - Shared storage (`/sdcard`, `/storage/emulated/0`) lacks POSIX DAC permission isolation, allowing any app with storage permission to read files.
   - Grok Build separates code editing from state persistence: project code is read/written at `cwd` on `/sdcard`, while session state is saved under `$HOME/.grok/sessions/{hash_slug}` with strict `0700` permissions.

---

## 3. Caveats

1. **Android `/sdcard` `noexec` Mount Constraint**:
   - The Android kernel mounts `/sdcard` with `noexec`. Direct execution of compiled binary artifacts located on `/sdcard` will fail with `EACCES`. Binaries intended for execution must be built or placed in `$HOME`.
2. **Path Normalization**:
   - Socket path bounds checking (`< 108 bytes`) validates UTF-8 byte length to prevent buffer overruns on POSIX sockets.
3. **CWD Directory Slug Encoding**:
   - Long `/sdcard` paths (>255 bytes) are hashed with Blake3 to `40_char_slug-{hash16}` (<= 57 bytes) and store a `.cwd` recovery file inside the session folder.

---

## 4. Conclusion

Milestone 3 (Filesystem Safety & Storage Boundaries, Features 10–14) is **complete, verified, hardened against adversarial evasion, and committed to `termux-native` (commit `4d266db`)**:
- System configuration resolves cleanly to `$PREFIX/etc/grok`.
- User home and credentials resolve strictly inside `$HOME/.grok`.
- Temporary directory and Unix domain sockets dynamically resolve under `$TMPDIR` / `$PREFIX/tmp` and stay strictly under 108 bytes.
- Shared storage quarantine strictly prevents storing credentials or state on `/sdcard`.
- Dual-track workspace protection isolates all session data when editing repositories on `/sdcard`.

---

## 5. Verification Method

To independently verify Milestone 3:

```bash
# 1. Typecheck entire workspace
cargo check --workspace

# 2. Run unit & adversarial tests for config, shared, and diag crates
cargo test -p xai-grok-config
cargo test -p xai-grok-shared
cargo test -p xai-grok-diag-server

# 3. Run full 4-tier E2E test suite (366 tests)
python3 tests/e2e/runner.py

# 4. Run ELF self-test
python3 scripts/validate_elf.py --self-test

# 5. Run Milestone 3 adversarial stress test suite
python3 tests/stress_test_milestone3.py
```
