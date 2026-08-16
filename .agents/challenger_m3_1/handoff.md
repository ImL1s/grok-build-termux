# Milestone 3 Empirical Challenger Report: Filesystem Safety & Storage Boundaries

**Author**: Challenger for Milestone 3 (`challenger_m3_1`)  
**Roles**: critic, specialist  
**Scope**: Adversarial Stress Testing & Empirical Verification of Features 10–14 (System Config, User Home, Temp & Sockets, Shared Storage Quarantine, Workspace Protection)  
**Target Commit**: `4d266db` (`feat(filesystem): implement dynamic temp sockets, system config, and storage boundaries (Milestone 3)`)  
**Verdict**: **`APPROVE`**  
**Date**: 2026-08-16  

---

## 1. Observation

### 1.1 Scope and Threat Vectors Challenged
Per `ORIGINAL_REQUEST.md`, `PROJECT.md`, and the Dispatch mandate, the following threat vectors and properties were empirically challenged:

1. **Storage Safety Bypass Vectors (Feature 13)**:
   - **Relative Path Traversal**: `..` escaping out of private home (`/data/data/com.termux/files/home/../../../../sdcard/.grok`), nested backtracking, multiple redundant `./` components, and double slashes (`//sdcard`).
   - **Case Variations**: Uppercase and mixed-case prefixes (`/SDCARD`, `/Storage/Emulated/0`, `/MNT/SDCARD`, `/sDcArD/auth.json`, `/STORAGE/SELF/PRIMARY`, `/STORAGE/1234-5678`).
   - **Direct Dangling Symlinks**: Symlinks on disk pointing to non-existent `/sdcard` or `/storage/emulated/0` paths.
   - **Multi-Hop Symlink Chains**: Chains of symlinks (`link_a -> link_b -> link_c -> /storage/emulated/0/.grok`).
   - **Ancestor Directory Symlinks**: Symlinks pointing to `/sdcard`, with non-existent nested target paths (`link_dir/nested/sub/credentials.json`).
   - **Relative Symlinks**: Symlinks pointing to relative targets (`../../../sdcard/.grok`).
   - **Symlink Recursion Loops**: Circular symlinks (`link_x <-> link_y`) to test unbounded recursion resistance.

2. **Dual-Track Workspace Isolation (Feature 14)**:
   - Editing a repository located on Android shared storage (`/sdcard/Download/my-cool-app`).
   - Confinement of session state (`sessions/`), auth tokens (`auth.json`), MCP credentials, and worktree databases to `$HOME/.grok/` with `0700` permissions.
   - Confinement of runtime temporary sockets to `$TMPDIR` / `$PREFIX/tmp` (length < 108 bytes, never on `/sdcard`).
   - Long `/sdcard` path (>255 bytes) slug-hash encoding, `.cwd` metadata recovery, and `0700` POSIX mode enforcement.

3. **System Config & Temporary Sockets (Features 10, 11, 12)**:
   - `$PREFIX/etc/grok` on Termux vs `/etc/grok` on desktop Linux, and fail-closed behavior when `$PREFIX` is unset on Android.
   - Blake3 8-hex character session hash socket path generation (< 108 bytes) and stale socket cleanup.
   - High concurrency stress test across 100 threads.

### 1.2 Verbatim Test Execution Results

1. **Workspace Typecheck**:
   ```
   cargo check --workspace -> Finished with exit code 0
   ```

2. **Challenger Rust Integration Test Suite (`crates/codegen/xai-grok-config/tests/challenger_m3_adversarial.rs`)**:
   ```
   running 12 tests
   test test_challenger_case_variations ... ok
   test test_challenger_mixed_separators_and_double_slashes ... ok
   test test_challenger_dual_track_workspace_isolation ... ok
   test test_challenger_relative_path_traversals ... ok
   test test_challenger_symlink_chains_multi_hop ... ok
   test test_challenger_ancestor_directory_symlink ... ok
   test test_challenger_dangling_and_existing_symlinks ... ok
   test test_challenger_deep_symlink_chain_bound ... ok
   test test_challenger_long_sdcard_workspace_slug_hash_roundtrip ... ok
   test test_challenger_relative_symlink_to_shared_storage ... ok
   test test_challenger_concurrency_stress_100_threads ... ok
   test test_challenger_symlink_recursion_loop ... ok

   test result: ok. 12 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.14s
   ```

3. **Challenger Python Adversarial Suite (`tests/test_adversarial_challenger_m3.py`)**:
   ```
   .......
   ----------------------------------------------------------------------
   Ran 7 tests in 0.010s

   OK
   ```

4. **All Rust Test Suites in `xai-grok-config`**:
   - `src/lib.rs` unit tests: 213 passed, 0 failed.
   - `tests/challenger_m3_adversarial.rs`: 12 passed, 0 failed.
   - `tests/platform_adversarial.rs`: 15 passed, 0 failed.
   - `tests/shell_adversarial.rs`: 2 passed, 0 failed.
   - `tests/socket_adversarial.rs`: 5 passed, 0 failed.
   - **Total**: 247 passed, 0 failed.

5. **Milestone 3 Python Stress Test Suite (`tests/stress_test_milestone3.py`)**:
   ```
   .....
   ----------------------------------------------------------------------
   Ran 5 tests in 0.014s

   OK
   ```

6. **4-Tier E2E Test Suite (`tests/e2e/runner.py`)**:
   ```
   [✓] Tier 1: Feature Coverage (32 Features × 5)              Tests: 160 | Passed: 160 | Failed:  0 | Time: 3.41s
   [✓] Tier 2: Boundary & Corner Cases (32 Features × 5)       Tests: 160 | Passed: 160 | Failed:  0 | Time: 1.67s
   [✓] Tier 3: Pairwise Cross-Feature Interactions             Tests:  34 | Passed:  34 | Failed:  0 | Time: 0.59s
   [✓] Tier 4: Real-World Application Scenarios                Tests:  12 | Passed:  12 | Failed:  0 | Time: 0.53s
   Summary: 366/366 passed in 6.262s | Result: SUCCESS (100% PASSED)
   ```

7. **ELF Validator Self-Test (`scripts/validate_elf.py --self-test`)**:
   ```
   Running ELF Validator internal self-tests...
     [✓] Valid 16 KiB Bionic aarch64 binary (Result: VALID, Expected: VALID)
     [✓] 4 KiB page size Bionic binary (should fail strict 16K) (Result: INVALID, Expected: INVALID)
     [✓] glibc ld-linux.so interpreter binary (should fail Bionic check) (Result: INVALID, Expected: INVALID)
     [✓] Misaligned PT_LOAD segment congruence violation (Result: INVALID, Expected: INVALID)
     [✓] Corrupt ELF magic header (Result: INVALID, Expected: INVALID)
     [✓] Statically linked 16 KiB aarch64 binary (Result: VALID, Expected: VALID)
   All self-tests passed successfully.
   ```

---

## 2. Logic Chain

1. **Storage Quarantine Robustness (Feature 13)**:
   - `validate_storage_safety` uses a 4-stage layered pipeline:
     1. Lexical normalization (`normalize_lexical`) collapsing `.` and `..` without disk dependency.
     2. Case-insensitive string inspection (`is_quarantined_str`) against all known Android shared storage mount points (`/sdcard`, `/storage`, `/mnt/sdcard`, `/mnt/media_rw`, `/data/sdcard`, `/data/media`).
     3. Direct symlink inspection (`std::fs::read_link`) with recursive destination checking.
     4. Canonicalization (`dunce::canonicalize`) and ancestor directory walk for non-existent targets inside symlinked directories.
   - Attack testing with relative traversals, uppercase/mixed-case paths, dangling symlinks, multi-hop symlink chains (up to 25 hops), relative symlinks (`../../../sdcard`), and ancestor directory symlinks consistently failed closed with `StorageSafetyError::SharedStorageQuarantine`.
   - Circular symlinks (`link_x <-> link_y`) cleanly terminate within the 32-hop recursion limit without stack exhaustion.

2. **Dual-Track Workspace Protection (Feature 14)**:
   - When editing project code located on `/sdcard/Download/...`:
     - Project source code is read/written at the working directory `cwd`.
     - All session history, chat transcripts, and search indexes are stored under `$HOME/.grok/sessions/{dirname}` created with `0700` (`rwx------`) owner-only POSIX permissions via `create_dir_all_owner_only`.
     - Authentication credentials (`auth.json`) and MCP tokens remain strictly under `$HOME/.grok/` with `0700` protection.
     - Long `/sdcard` paths (>255 bytes) are encoded into compact slug-hashes `<= 57 bytes` (`{slug}-{hash16}`) with a `.cwd` recovery file, successfully round-tripping through `decode_cwd_from_dirname`.

3. **Dynamic Path Resolution & Socket Length Bounds (Features 10, 11, 12)**:
   - `PlatformCapabilities::system_config_dir()` correctly resolves `$PREFIX/etc/grok` on Termux and `/etc/grok` on desktop Linux.
   - Temporary sockets created by `create_socket_path` compress arbitrary session IDs into 8-character Blake3 hashes (`grok-12345678.sock` = 18 bytes), resulting in 53-byte socket paths in Termux `$PREFIX/tmp`—well below the 108-byte `sockaddr_un.sun_path` boundary.
   - 100 concurrent threads probing capabilities and validating paths completed with zero race conditions or panics.

---

## 3. Caveats

1. **Android `/sdcard` `noexec` Mount Constraint**:
   - The Android kernel mounts shared storage (`/sdcard`) with `noexec`. Any executable binaries compiled or extracted directly onto `/sdcard` cannot be executed directly by the OS. Binaries must reside in `$HOME` or `$PREFIX/bin`.
2. **Root User / Kernel Sandbox Limits**:
   - In a non-rooted Termux environment, DAC permissions (0700) protect `$HOME/.grok` from other non-root applications. On a rooted device, root processes can bypass DAC boundaries. This is truthful to Android's `policy-only` security model.

---

## 4. Conclusion

**Verdict: `APPROVE`**

Milestone 3 (Filesystem Safety & Storage Boundaries, Features 10–14) has been rigorously challenged across all attack surfaces (path traversal, case insensitivity, direct and ancestor symlinks, multi-hop chains, circular symlinks, dual-track workspace isolation, and socket length bounds).

All defenses hold firm, fail closed with explicit diagnostic error messages, and maintain 100% test pass rates across all 247 Rust unit/integration tests and 366 E2E tests.

---

## 5. Verification Method

To independently reproduce the empirical findings:

```bash
# 1. Run workspace typecheck
cargo check --workspace

# 2. Run all Rust unit and adversarial test suites for xai-grok-config
cargo test -p xai-grok-config

# 3. Run Challenger Rust Adversarial Suite
cargo test -p xai-grok-config --test challenger_m3_adversarial

# 4. Run Challenger Python Adversarial Suite
python3 tests/test_adversarial_challenger_m3.py

# 5. Run Milestone 3 Stress Test Suite
python3 tests/stress_test_milestone3.py

# 6. Run 4-Tier E2E Test Suite (366 tests)
python3 tests/e2e/runner.py

# 7. Run ELF Validator Self-Test
python3 scripts/validate_elf.py --self-test
```
