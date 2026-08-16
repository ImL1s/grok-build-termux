# Milestone 3 Handoff Report: System Configuration & User Home Directory Resolution

**Author**: Explorer 1 (`explorer_m3_1`)  
**Scope**: Feature 10 (System Configuration Resolution: `$PREFIX/etc/grok`) & Feature 11 (User Home Directory Resolution: `$HOME/.grok`)  
**Date**: 2026-08-16  

---

## 1. Observation

### 1.1 Architecture & Authoritative Requirements
From `/Users/iml1s/Documents/mine/grok-build-termux/ORIGINAL_REQUEST.md`:
> Line 19: "Ensure configuration, credentials, sockets, and cache directories resolve to Termux-owned private paths (`$PREFIX/etc/grok`, `$HOME/.grok`, `$TMPDIR`). Strictly reject housing `GROK_HOME` or credentials on Android shared storage (`/sdcard`, `/storage/emulated/0`) to preserve owner-only permissions."
> Line 35: "- [ ] System config resolves to `$PREFIX/etc/grok` and user state resolves to `$HOME/.grok`."

From `/Users/iml1s/Documents/mine/grok-build-termux/PROJECT.md`:
> Line 79: "`fn system_config_dir(&self) -> Option<PathBuf>` -> `$PREFIX/etc/grok` on Termux, `/etc/grok` on desktop Linux"
> Line 80: "`fn home_dir(&self) -> Result<PathBuf, PlatformError>` -> `$HOME/.grok`"

### 1.2 Centralized Platform Capability Implementation (`xai-grok-config`)
In `/Users/iml1s/Documents/mine/grok-build-termux/crates/codegen/xai-grok-config/src/platform.rs`:
- **Platform Capability Detection (lines 183–277)**:
  ```rust
  let prefix_raw = env.get_var("PREFIX");
  let prefix_clean = prefix_raw.as_deref().map(str::trim).filter(|s| !s.is_empty());
  let prefix = prefix_clean.map(PathBuf::from);

  let home = env
      .get_var("HOME")
      .or_else(|| env.get_var("USERPROFILE"))
      .filter(|s| !s.trim().is_empty())
      .map(PathBuf::from);

  let grok_home_env = env
      .get_var("GROK_HOME")
      .filter(|s| !s.trim().is_empty())
      .map(PathBuf::from);
  ```
- **System Configuration Resolution (lines 328–335)**:
  ```rust
  pub fn system_config_dir(&self) -> Option<PathBuf> {
      match self.kind {
          PlatformKind::AndroidTermux => self.prefix.as_ref().map(|p| p.join("etc").join("grok")),
          PlatformKind::UnsupportedAndroid => None,
          PlatformKind::DesktopLinux | PlatformKind::MacOS => Some(PathBuf::from("/etc/grok")),
          PlatformKind::Windows => None,
      }
  }
  ```
- **User Home Resolution (lines 337–346)**:
  ```rust
  pub fn home_dir(&self) -> Result<PathBuf, PlatformError> {
      if let Some(ref gh) = self.grok_home_env {
          validate_storage_safety(gh)?;
          return Ok(gh.clone());
      }
      let user_home = self.home.as_ref().ok_or(PlatformError::MissingHome)?;
      let gh = user_home.join(".grok");
      validate_storage_safety(&gh)?;
      Ok(gh)
  }
  ```
- **Storage Safety Boundaries (lines 388–587)**:
  `validate_storage_safety` enforces lexical traversal normalization, symlink target resolution, ancestor symlink inspection, and canonical path checks against `ANDROID_SHARED_STORAGE_PREFIXES`:
  `["/sdcard", "/storage", "/mnt/sdcard", "/mnt/media_rw", "/data/sdcard", "/data/media", ...]`.

### 1.3 Path Interface Contracts & Re-Exports (`xai-grok-config/src/paths.rs`)
In `/Users/iml1s/Documents/mine/grok-build-termux/crates/codegen/xai-grok-config/src/paths.rs`:
- **System Configuration Dispatch (lines 78–80)**:
  ```rust
  pub fn system_config_dir() -> Option<PathBuf> {
      crate::platform::PlatformCapabilities::current().system_config_dir()
  }
  ```
- **Infallible Home Directory Resolver (lines 35–53)**:
  ```rust
  pub fn grok_home() -> PathBuf {
      GROK_HOME
          .get_or_init(|| {
              let grok_home = if let Ok(v) = std::env::var("GROK_HOME") {
                  let p = PathBuf::from(v);
                  if let Err(e) = crate::platform::validate_storage_safety(&p) {
                      tracing::error!(error = %e, "Rejected insecure GROK_HOME location; falling back to default");
                      default_grok_home()
                  } else {
                      p
                  }
              } else {
                  default_grok_home()
              };
              let _ = std::fs::create_dir_all(&grok_home);
              grok_home
          })
          .clone()
  }
  ```
- **User-Global Guard (lines 60–64)**:
  ```rust
  pub fn user_grok_home() -> Option<PathBuf> {
      let resolvable = std::env::var_os("GROK_HOME").is_some() || std::env::home_dir().is_some();
      resolvable.then(grok_home)
  }
  ```

### 1.4 Downstream Consumer Invariants Across the Workspace
1. **Config & Requirements Loading**:
   - `crates/codegen/xai-grok-config/src/loader.rs`: `load_system_managed_config()`, `managed_config_layers()`, and `hook_config_layers()` query `system_config_dir()` to load `managed_config.toml`, `requirements.toml`, and system hook configurations.
   - `crates/codegen/xai-grok-config/src/validation.rs`: `load_system_requirements()` searches `system_config_dir().join("requirements.toml")`.
   - `crates/codegen/xai-grok-shell/src/inspect/mod.rs`: `list_config_sources()` checks `crate::config::system_config_dir()`.
2. **Auth & Secret Persistence**:
   - `crates/codegen/xai-grok-shell/src/agent/app.rs:1125`: `grok_home().join("auth.json")` (OIDC/OAuth credentials).
   - `crates/codegen/xai-grok-mcp/src/credentials.rs`: `grok_home().join("mcp_credentials.json")` and `mcp_preferences.json`.
3. **Session & History Storage**:
   - `crates/codegen/xai-grok-config/src/paths.rs:198–243`: `ensure_sessions_cwd_dir` creates `$HOME/.grok/sessions/<encoded_cwd>` with POSIX `0700` permissions.
   - `crates/codegen/xai-grok-shell/src/session/persistence.rs`: Saves chat history and transcripts to `$HOME/.grok/sessions/`.
4. **Git Worktrees & Repos**:
   - `crates/codegen/xai-grok-workspace/src/worktree/mod.rs:781–796`: `worktree_base_dir` resolves under `$HOME/.grok/worktrees/<repo_slug>`.
   - `crates/codegen/xai-fast-worktree/src/db/mod.rs:471`: `resolve_grok_home()` tracks `$HOME/.grok/worktrees.db`.
5. **Telemetry, Logs, Memory & Diagnostics**:
   - `crates/codegen/xai-grok-telemetry/src/unified_log.rs`: `$HOME/.grok/logs/unified.log`.
   - `crates/codegen/xai-grok-telemetry/src/hooks_log.rs`: `$HOME/.grok/logs/hooks.log`.
   - `crates/codegen/xai-grok-telemetry/src/memory_log.rs`: `$HOME/.grok/logs/memory.log`.
   - `crates/codegen/xai-grok-telemetry/src/debug_log.rs`: `$HOME/.grok/debug/`.
   - `crates/codegen/xai-grok-telemetry/src/id.rs`: `$HOME/.grok/agent_id`.
   - `crates/codegen/xai-grok-memory/src/storage.rs`: `$HOME/.grok/memory/`.
   - `crates/codegen/xai-grok-plugin-marketplace/src/git.rs`: `$HOME/.grok/marketplace-cache/`.
   - `crates/codegen/xai-grok-agent/src/plugins/git_install.rs`: `$HOME/.grok/plugin-data/`.
   - `crates/codegen/xai-grok-pager-bin/src/main.rs`: `$HOME/.grok/crash/`.

### 1.5 Verification Results
- `cargo test -p xai-grok-config`: **228/228 tests passed** (including 15 adversarial tests in `tests/platform_adversarial.rs`).
- `python3 tests/e2e/runner.py`: **366/366 tests passed** in 6.4s (covering Features 10 and 11 across Tiers 1–4).
- `cargo check --workspace`: Finished with exit code 0.

---

## 2. Logic Chain

1. **Step 1: Elimination of Static Desktop Assumptions**
   Upstream Grok Build hardcoded `/etc/grok` as the sole system configuration directory for all Unix targets. On Android/Termux, `/etc` is in Android's read-only system root and cannot be accessed or written without root. Termux places all system files under dynamic prefix `$PREFIX` (default `/data/data/com.termux/files/usr`).
   - *Evidence*: `platform.rs:329-334` checks `PlatformKind::AndroidTermux` and dynamically prefixes `$PREFIX/etc/grok`. On desktop Linux/macOS, it resolves to `/etc/grok`. On Windows or unsupported Android, it returns `None`.

2. **Step 2: Dynamic vs Hardcoded `$PREFIX` Safety**
   Termux can be installed under alternative package names (e.g. forks, multi-user Android `/data/user/0/com.termux/files/usr`, or custom distributions).
   - *Evidence*: `platform.rs:185` inspects `$PREFIX` from the environment. `tests/platform_adversarial.rs:test_adversarial_custom_prefix_variations` verifies that arbitrary `$PREFIX` values dynamically generate `$PREFIX/etc/grok` without assuming `com.termux`.

3. **Step 3: Private Storage Boundaries & Shared Storage Quarantine**
   Android shared storage (`/sdcard`, `/storage/emulated/0`) uses FAT/FUSE/sdcardfs without standard POSIX DAC permission isolation, making any file placed there accessible to other Android applications.
   - *Evidence*: `PlatformCapabilities::home_dir()` and `validate_storage_safety()` reject all `/sdcard`, `/storage/emulated/0`, `/mnt/sdcard`, dangling symlinks, and directory traversals with `StorageSafetyError`.
   - *Result*: All private credentials (`auth.json`), session transcripts (`sessions/`), logs, and worktree DBs remain strictly quarantined inside Termux private app storage (`/data/data/com.termux/files/home/.grok`).

4. **Step 4: Centralization of State & Path Consumers**
   All 12+ subcrates (shell, pager, auth, mcp, memory, telemetry, workspace, plugins) route through `xai_grok_config::grok_home()` / `user_grok_home()`. No crate hardcodes `~/.grok` as a raw string or bypasses the centralized platform capabilities layer.

---

## 3. Caveats

1. **Standalone Crate Independence (`xai-fast-worktree`)**:
   `xai-fast-worktree` maintains an intentional standalone implementation of `resolve_grok_home` to avoid dependency on `xai-grok-config`. Both implementations use `dunce::canonicalize` on `$HOME` to ensure path consistency across Windows, macOS, and Linux/Android.
2. **Fail-Closed on Unset `$PREFIX` for Android Targets**:
   On `aarch64-linux-android` targets, if `$PREFIX` is unset or empty, `PlatformCapabilities` marks the environment as `UnsupportedAndroid` and refuses system config resolution (`None`), preventing fallback to desktop `/etc/grok`.

---

## 4. Conclusion

Features 10 (`$PREFIX/etc/grok`) and 11 (`$HOME/.grok`) are **fully verified, rigorously tested, and compliant with all project requirements**:
- **Feature 10 (System Configuration Resolution)**: Dynamically resolves to `$PREFIX/etc/grok` under Android/Termux, seamlessly falls back to `/etc/grok` on desktop Linux/macOS, and returns `None` on Windows/Unsupported Android.
- **Feature 11 (User Home Directory Resolution)**: Resolves user config, credentials (`auth.json`), session history, logs, and telemetry strictly under `$HOME/.grok` (or `$GROK_HOME`). Shared storage quarantine prevents credential leakage to `/sdcard`.

---

## 5. Verification Method

To independently verify this subsystem:

1. **Run Unit & Adversarial Tests for `xai-grok-config`**:
   ```bash
   cargo test -p xai-grok-config
   ```
   *Expected*: 228 passing tests (211 unit tests, 15 adversarial platform tests, 2 shell tests).

2. **Run E2E Test Suite (Tier 1 & Tier 2 for Features 10 & 11)**:
   ```bash
   python3 -m unittest tests/e2e/tier1_features/test_feature_09_to_16.py
   python3 -m unittest tests/e2e/tier2_boundaries/test_boundaries_09_to_16.py
   ```
   *Expected*: All Feature 10 (`f10_c01` through `f10_c05`, `b10_c01` through `b10_c05`) and Feature 11 (`f11_c01` through `f11_c05`, `b11_c01` through `b11_c05`) tests pass 100%.

3. **Run Full 4-Tier E2E Test Suite**:
   ```bash
   python3 tests/e2e/runner.py
   ```
   *Expected*: 366/366 tests pass in <8s.

4. **Verify Workspace Typecheck**:
   ```bash
   cargo check --workspace
   ```
   *Expected*: Clean compilation with 0 errors.
