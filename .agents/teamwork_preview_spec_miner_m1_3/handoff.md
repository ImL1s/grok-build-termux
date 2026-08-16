# Specification Mining Report: Milestone 1 (Platform Capability & Dependency Isolation)

## 1. Observation

### Authoritative Specification Sources Probed
- `/Users/iml1s/Documents/mine/grok-build-termux/ORIGINAL_REQUEST.md` (Requirements R1–R5, Acceptance Criteria)
- `/Users/iml1s/Documents/mine/grok-build-termux/PROJECT.md` (Architecture, Feature Inventory 1–5, Interface Contracts)
- Upstream Codebase at `/Users/iml1s/Documents/mine/grok-build` (tracking `eb267feff13129e568df38fb6fdf0ceb65f735d6`)
- `crates/codegen/xai-grok-config/src/paths.rs` & `crates/codegen/xai-grok-config/src/state_dir.rs`
- `crates/codegen/xai-grok-shared/Cargo.toml` & `crates/codegen/xai-grok-shared/src/clipboard.rs`
- `crates/codegen/xai-grok-voice/Cargo.toml` & `crates/codegen/xai-grok-voice/src/`
- `crates/codegen/xai-grok-sandbox/Cargo.toml` & `crates/codegen/xai-grok-sandbox/src/lib.rs`
- `crates/codegen/xai-grok-pager-bin/Cargo.toml` & `crates/codegen/xai-grok-pager-bin/src/main.rs`

### Direct Codebase Findings

1. **System Config Path Hardcoding** (`crates/codegen/xai-grok-config/src/paths.rs:78-85`):
   ```rust
   pub fn system_config_dir() -> Option<PathBuf> {
       if cfg!(unix) {
           Some(PathBuf::from("/etc/grok"))
       } else {
           None
       }
   }
   ```
   *Issue*: On Android (which satisfies `cfg!(unix)`), `/etc/grok` does not exist or is unwritable. On Termux, it must resolve to `$PREFIX/etc/grok` dynamically.

2. **Jemalloc / Memory Allocator Gating** (`crates/codegen/xai-grok-pager-bin/Cargo.toml:64-77`, `src/main.rs:8-10`):
   ```toml
   [target.'cfg(unix)'.dependencies]
   tikv-jemallocator = { workspace = true, optional = true, features = ["stats"] }
   tikv-jemalloc-sys = { workspace = true, optional = true }
   tikv-jemalloc-ctl = { workspace = true, optional = true, features = ["stats", "use_std"] }
   ```
   ```rust
   #[cfg(all(feature = "jemalloc", unix))]
   #[global_allocator]
   static GLOBAL: tikv_jemallocator::Jemalloc = tikv_jemallocator::Jemalloc;
   ```
   *Issue*: On `aarch64-linux-android`, `unix` is true, so default compilation attempts to link `tikv-jemallocator` which fails on Android Bionic libc. Android must use Bionic's system allocator.

3. **Desktop Clipboard Dependency (`arboard`)** (`crates/codegen/xai-grok-shared/Cargo.toml:47-49`, `src/clipboard.rs:1194`):
   ```toml
   [target.'cfg(not(target_os = "macos"))'.dependencies]
   arboard = { workspace = true, features = ["wayland-data-control"] }
   ```
   *Issue*: Android matches `not(target_os = "macos")`, pulling in `arboard` (and X11/Wayland dependencies) on Android builds.

4. **Voice / Audio Dependency (`cpal`)** (`crates/codegen/xai-grok-voice/Cargo.toml:45, 50-52`):
   ```toml
   audio = ["dep:cpal"]
   [target.'cfg(not(target_os = "linux"))'.dependencies.cpal]
   version = "0.15"
   optional = true
   ```
   *Issue*: Android matches `not(target_os = "linux")`, so the default `audio` feature pulls in `cpal` and attempts to link desktop ALSA/OpenSL audio libraries.

5. **Sandbox Enforcement Dependency (`nono`)** (`crates/codegen/xai-grok-sandbox/Cargo.toml:22-34`):
   ```toml
   [target.'cfg(unix)'.dependencies]
   nono = { version = "=0.53.0", default-features = false }
   globset = { workspace = true }
   ```
   *Issue*: `nono` is unconditionally pulled into all Unix builds. On unprivileged Android/Termux, kernel Landlock/Seatbelt sandboxing cannot be enforced and must be gated.

---

## 2. Logic Chain

1. **Centralized Platform Truth**:
   Instead of ad-hoc `cfg!(unix)` and `cfg!(target_os = "android")` scattered across crates, an injectable `PlatformCapabilities` struct (in `xai-grok-config` or `xai-grok-platform`) must act as the single source of truth for runtime OS detection, dynamic `$PREFIX`, display server presence, audio availability, and sandboxing mode.

2. **Dynamic `$PREFIX` Resolution & Fallback**:
   - On Android/Termux, `$PREFIX` must be read from environment (`std::env::var("PREFIX")`).
   - If `$PREFIX` is valid, system configuration resolves to `$PREFIX/etc/grok`, binaries to `$PREFIX/bin`, and temporary files to `$TMPDIR` (defaulting to `$PREFIX/tmp`).
   - If `$PREFIX` is unset or empty on an Android target, it must **fail closed** with `PlatformError::MissingPrefix` rather than falling back to desktop `/etc` or `/usr`.

3. **Dependency Tree Isolation**:
   - `tikv-jemallocator`, `tikv-jemalloc-sys`, and `tikv-jemalloc-ctl` must be gated under `cfg(all(unix, not(target_os = "android")))`.
   - `arboard` must be gated under `cfg(not(any(target_os = "macos", target_os = "android")))`.
   - `cpal` must be gated under `cfg(not(any(target_os = "linux", target_os = "android")))`.
   - `nono` must be gated under `cfg(all(unix, not(target_os = "android")))`.
   - On Android, `aarch64-linux-android` builds will cleanly link Bionic's system allocator, Termux CLI clipboard/OSC 52, voice disabled/stubbed, and policy-only sandboxing.

4. **Mock Platform Injection for Deterministic Testing**:
   To test Android behaviors on macOS or Linux host environments without needing an on-device runner, `PlatformContext` must support mock instantiation (`PlatformContext::mock(...)`) accepting synthetic environment maps, OS kinds, and filesystem predicates.

---

## 3. Features Discovered

| # | Category | Feature | Description | Inputs | Outputs | Error Behavior | Discovered Via |
|---|----------|---------|-------------|--------|---------|----------------|----------------|
| 1 | M1: Platform | Centralized Platform Capability Layer | Unified, injectable runtime struct (`PlatformCapabilities`) identifying OS kind, ABI, display presence, audio, and sandbox | Environment variables, OS target (`cfg(target_os = "android")`) | `PlatformCapabilities` struct | Fails closed with descriptive error if `$PREFIX` is invalid on Android | `ORIGINAL_REQUEST.md:12-14`, `PROJECT.md:28-34, 75-84` |
| 2 | M1: Platform | Dynamic `$PREFIX` Discovery | Dynamically resolves Termux root path instead of hardcoding `/data/data/com.termux/files/usr` | `std::env::var("PREFIX")` | `PathBuf` representing Termux prefix | Returns `Err(PlatformError::MissingPrefix)` if unset on Android | `ORIGINAL_REQUEST.md:13`, `PROJECT.md:78` |
| 3 | M1: Dependency | Allocator Gating (Bionic vs Jemalloc) | Uses Bionic's system memory allocator on Android; excludes `tikv-jemallocator` from dependency tree | `cfg(target_os = "android")` | System allocator linked | Compile error if jemalloc is forced on Android | `ORIGINAL_REQUEST.md:13, 30`, `xai-grok-pager-bin/Cargo.toml` |
| 4 | M1: Dependency | Desktop Clipboard Gating (`arboard`) | Excludes `arboard` and X11/Wayland dependencies from Android target builds | `cfg(target_os = "android")` | Termux clipboard adapter seam | Prevents X11/Wayland linkage errors | `ORIGINAL_REQUEST.md:13, 30`, `xai-grok-shared/Cargo.toml` |
| 5 | M1: Dependency | Voice / Microphone Gating (`cpal`) | Excludes `cpal` and ALSA dependencies on Android; disables microphone UI cleanly | `cfg(target_os = "android")` | Feature disabled / voice stub | Graceful error if voice command invoked; no panic | `ORIGINAL_REQUEST.md:13, 30`, `xai-grok-voice/Cargo.toml` |
| 6 | M1: Security | Shared Storage Quarantine Hook | Intercepts `GROK_HOME` and private state paths before creation, rejecting `/sdcard` | Path candidate | `Result<(), StorageSafetyError>` | Returns `Err(StorageSafetyError::SharedStorageRejected)` for `/sdcard` | `ORIGINAL_REQUEST.md:19, 36`, `PROJECT.md:83` |
| 7 | M1: Testing | Mock Platform Injection Context | Allows unit tests to inject arbitrary OS kinds, prefixes, and environment variables | `MockPlatformEnv` | Injected `PlatformCapabilities` | Deterministic simulation without process-wide env mutation | `PROJECT.md:75-84`, `TEST_INFRA.md:43-50` |

---

## 4. Edge Cases

| # | Feature | Input / Condition | Observed / Required Behavior |
|---|---------|-------------------|-----------------------------|
| 1 | Dynamic `$PREFIX` | `$PREFIX` environment variable unset or empty (`""`) on Android | Fail closed with explicit error: `PlatformError::MissingPrefix("PREFIX environment variable is unset or empty on Android")`. Do NOT fall back to `/usr` or `/etc`. |
| 2 | Dynamic `$PREFIX` | `$PREFIX` set to all whitespace (`"   "`) on Android | Treat as unset; fail closed with `PlatformError::MissingPrefix`. |
| 3 | Dynamic `$PREFIX` | Custom Termux prefix (e.g. `PREFIX="/data/data/com.custom.pkg/files/usr"`) | Dynamically construct config path `$PREFIX/etc/grok` and binaries `$PREFIX/bin` matching custom prefix without assuming `com.termux`. |
| 4 | Dynamic `$PREFIX` | `$PREFIX` with trailing slashes (e.g. `/data/data/com.termux/files/usr///`) | Lexically normalize so joined paths like `$PREFIX/etc/grok` do not contain duplicate slashes or break path comparisons. |
| 5 | Non-Termux Android | `target_os = "android"`, but running in ADB shell or standard Android app without `$PREFIX` | Classify as `OsKind::AndroidUnsupported`. `is_android_termux()` returns `false`. System config returns `None`. |
| 6 | Display Detection | Desktop Linux with `DISPLAY=":0"` vs headless Termux | Desktop Linux: `display_server_present() == true`. Termux (no `DISPLAY`/`WAYLAND_DISPLAY`): `display_server_present() == false`, `url_opener_kind()` defaults to `UrlOpenerKind::TermuxOpenUrl`. |
| 7 | Audio Detection | Voice capture probe invoked on Android | `audio_capture_available() == false`. `voice::probe_audio()` returns `Err(VoiceError::UnsupportedPlatform)` cleanly without crashing or initializing audio hardware. |
| 8 | Shared Storage Quarantine | User sets `GROK_HOME="/sdcard/.grok"` or `"/storage/emulated/0/grok"` | `validate_storage_safety` rejects path with `StorageSafetyError::SharedStorageRejected` explaining missing POSIX 0700 permissions. |
| 9 | Shared Storage Quarantine | Path containing symlink pointing to `/sdcard` | Canonicalize path before validation to detect hidden symlink targets leading to shared storage. |
| 10 | Mock Platform Injection | Multi-threaded test runner executing parallel tests with different mock environments | Mock context is scoped (passed explicitly or thread-local), avoiding process-global `std::env::set_var` race conditions. |

---

## 5. Detailed Answers to Core Assignment Questions

### Q1. Exact Unit Tests to Verify `PlatformCapabilities`

The following unit tests must be implemented and pass in the test suite:

```rust
#[cfg(test)]
mod platform_capabilities_tests {
    use super::*;
    use std::path::{Path, PathBuf};

    #[test]
    fn test_stock_termux_platform_capabilities() {
        let env = MockEnv::builder()
            .os(OsKind::AndroidTermux)
            .var("PREFIX", "/data/data/com.termux/files/usr")
            .var("HOME", "/data/data/com.termux/files/home")
            .var("TMPDIR", "/data/data/com.termux/files/usr/tmp")
            .build();
        let caps = PlatformCapabilities::from_context(&env);

        assert!(caps.is_android_termux());
        assert_eq!(caps.prefix_dir().unwrap(), Path::new("/data/data/com.termux/files/usr"));
        assert_eq!(caps.system_config_dir(), Some(PathBuf::from("/data/data/com.termux/files/usr/etc/grok")));
        assert_eq!(caps.bin_dir().unwrap(), PathBuf::from("/data/data/com.termux/files/usr/bin"));
        assert_eq!(caps.temp_dir(), PathBuf::from("/data/data/com.termux/files/usr/tmp"));
        assert_eq!(caps.sandbox_kind(), SandboxKind::PolicyOnly);
        assert!(!caps.display_server_present());
        assert!(!caps.audio_capture_available());
    }

    #[test]
    fn test_custom_prefix_termux_platform_capabilities() {
        let env = MockEnv::builder()
            .os(OsKind::AndroidTermux)
            .var("PREFIX", "/data/data/custom.terminal.app/files/usr")
            .var("HOME", "/data/data/custom.terminal.app/files/home")
            .build();
        let caps = PlatformCapabilities::from_context(&env);

        assert!(caps.is_android_termux());
        assert_eq!(caps.prefix_dir().unwrap(), Path::new("/data/data/custom.terminal.app/files/usr"));
        assert_eq!(caps.system_config_dir(), Some(PathBuf::from("/data/data/custom.terminal.app/files/usr/etc/grok")));
    }

    #[test]
    fn test_missing_prefix_on_android_fails_closed() {
        let env = MockEnv::builder()
            .os(OsKind::AndroidTermux)
            // No PREFIX set
            .build();
        let caps = PlatformCapabilities::from_context(&env);

        assert!(caps.prefix_dir().is_err());
        assert_eq!(caps.system_config_dir(), None);
        // Must NOT return /etc/grok or /usr/etc/grok
        assert_ne!(caps.system_config_dir(), Some(PathBuf::from("/etc/grok")));
    }

    #[test]
    fn test_empty_or_whitespace_prefix_fails_closed() {
        let env = MockEnv::builder()
            .os(OsKind::AndroidTermux)
            .var("PREFIX", "   ")
            .build();
        let caps = PlatformCapabilities::from_context(&env);

        assert!(caps.prefix_dir().is_err());
        assert_eq!(caps.system_config_dir(), None);
    }

    #[test]
    fn test_desktop_linux_platform_capabilities() {
        let env = MockEnv::builder()
            .os(OsKind::Linux)
            .var("HOME", "/home/alice")
            .var("DISPLAY", ":0")
            .build();
        let caps = PlatformCapabilities::from_context(&env);

        assert!(!caps.is_android_termux());
        assert_eq!(caps.system_config_dir(), Some(PathBuf::from("/etc/grok")));
        assert_eq!(caps.temp_dir(), PathBuf::from("/tmp"));
        assert!(caps.display_server_present());
    }

    #[test]
    fn test_macos_platform_capabilities() {
        let env = MockEnv::builder()
            .os(OsKind::MacOs)
            .var("HOME", "/Users/alice")
            .build();
        let caps = PlatformCapabilities::from_context(&env);

        assert!(!caps.is_android_termux());
        assert_eq!(caps.system_config_dir(), None);
        assert!(caps.display_server_present());
    }

    #[test]
    fn test_display_detection_combinations() {
        // DISPLAY present
        let env1 = MockEnv::builder().os(OsKind::Linux).var("DISPLAY", ":1").build();
        assert!(PlatformCapabilities::from_context(&env1).display_server_present());

        // WAYLAND_DISPLAY present
        let env2 = MockEnv::builder().os(OsKind::Linux).var("WAYLAND_DISPLAY", "wayland-1").build();
        assert!(PlatformCapabilities::from_context(&env2).display_server_present());

        // Neither present on Linux
        let env3 = MockEnv::builder().os(OsKind::Linux).build();
        assert!(!PlatformCapabilities::from_context(&env3).display_server_present());
    }

    #[test]
    fn test_storage_safety_quarantine_rejections() {
        assert!(validate_storage_safety(Path::new("/sdcard/.grok")).is_err());
        assert!(validate_storage_safety(Path::new("/storage/emulated/0/.grok")).is_err());
        assert!(validate_storage_safety(Path::new("/mnt/sdcard/grok")).is_err());
        assert!(validate_storage_safety(Path::new("/data/data/com.termux/files/home/.grok")).is_ok());
    }
}
```

---

### Q2. Cargo Check & Dependency Tree Invariant Assertions

To guarantee that desktop dependencies (`jemalloc`, `cpal`, `arboard`, `nono`) are strictly absent from `aarch64-linux-android` builds:

#### 1. Shell / CI Assertions:
```bash
# 1. Verify cargo check succeeds for target aarch64-linux-android
cargo check --target aarch64-linux-android --workspace --all-targets

# 2. Assert tikv-jemallocator is absent from binary package
! cargo tree --target aarch64-linux-android -p xai-grok-pager-bin | grep -E "tikv-jemalloc"

# 3. Assert cpal and alsa-sys are absent from voice / workspace graph
! cargo tree --target aarch64-linux-android --workspace | grep -E "\bcpal\b|\balsa-sys\b"

# 4. Assert arboard and wl-clipboard-rs are absent from shared / pager graph
! cargo tree --target aarch64-linux-android -p xai-grok-shared | grep -E "\barboard\b|\bwl-clipboard-rs\b"

# 5. Assert nono kernel sandbox is absent from android graph
! cargo tree --target aarch64-linux-android -p xai-grok-sandbox | grep -E "\bnono\b"
```

#### 2. Programmatic Cargo Metadata Test (`tests/dependency_isolation.rs`):
```rust
#[test]
fn test_android_target_dependency_tree_excludes_desktop_crates() {
    let metadata = cargo_metadata::MetadataCommand::new()
        .other_options(["--filter-platform".to_string(), "aarch64-linux-android".to_string()])
        .exec()
        .expect("cargo metadata failed");

    let package_names: Vec<&str> = metadata
        .packages
        .iter()
        .map(|p| p.name.as_str())
        .collect();

    assert!(
        !package_names.contains(&"tikv-jemallocator"),
        "tikv-jemallocator must NOT be present in aarch64-linux-android dependencies"
    );
    assert!(
        !package_names.contains(&"tikv-jemalloc-sys"),
        "tikv-jemalloc-sys must NOT be present in aarch64-linux-android dependencies"
    );
    assert!(
        !package_names.contains(&"cpal"),
        "cpal must NOT be present in aarch64-linux-android dependencies"
    );
    assert!(
        !package_names.contains(&"arboard"),
        "arboard must NOT be present in aarch64-linux-android dependencies"
    );
}
```

---

### Q3. Edge Cases for Missing $PREFIX, Custom $PREFIX, and Mock Platform Injection

1. **Missing `$PREFIX`**:
   - Condition: Android environment where `$PREFIX` is unset.
   - Requirement: `prefix_dir()` returns `Err(PlatformError::MissingPrefix)`. `system_config_dir()` returns `None`. Diagnostic guidance advises: `"PREFIX environment variable is not set. Ensure Grok Build is running inside a valid Termux installation."`
   - Security Invariant: Must NEVER default to `/usr` or `/etc`.

2. **Custom `$PREFIX`**:
   - Condition: Non-standard Termux installations (e.g. customized forks or secondary app instances) where `PREFIX="/custom/path/usr"`.
   - Requirement: Dynamically derives all system directories:
     - Config: `/custom/path/usr/etc/grok`
     - Binaries: `/custom/path/usr/bin`
     - Temp/Sockets: `/custom/path/usr/tmp`
   - Invariant: Zero occurrences of hardcoded string `com.termux` across path resolution logic.

3. **Mock Platform Injection**:
   - Condition: Running test suite on host macOS (`aarch64-apple-darwin`) or Linux CI runners (`x86_64-unknown-linux-gnu`).
   - Requirement: `PlatformContext` trait / struct with `PlatformContext::new_mock(os, env_map)` allowing tests to override target OS, environment variables, and filesystem checks without modifying global process environment (`std::env::set_var`), preventing race conditions in parallel tests.

---

## 6. Caveats

1. **Root vs Unprivileged Termux**:
   Even if Termux is run as root or in proot, `PlatformCapabilities` should maintain `policy-only` sandboxing status unless Landlock/namespaces are explicitly verified at runtime.
2. **Upstream Root Cargo.toml**:
   The upstream root manifest is generated; crate-level `[target.'...'.dependencies]` in `xai-grok-config`, `xai-grok-shared`, `xai-grok-voice`, `xai-grok-sandbox`, and `xai-grok-pager-bin` must be used to keep merge conflicts minimal during upstream rebase.

---

## 7. Conclusion

Milestone 1 specification mining is complete:
- The centralized `PlatformCapabilities` / `PlatformContext` interface is specified with full dynamic `$PREFIX` resolution and fail-closed safety.
- Exact unit test cases covering Termux stock, custom `$PREFIX`, missing `$PREFIX`, desktop Linux, macOS, display/audio detection, and storage safety have been designed.
- Exact `cargo tree` and `cargo metadata` assertions for isolating `jemalloc`, `cpal`, `arboard`, and `nono` on `aarch64-linux-android` are established.

---

## 8. Verification Method

1. **Verify Mined Contracts against Upstream Codebase**:
   - Inspect `crates/codegen/xai-grok-config/src/paths.rs`
   - Inspect `crates/codegen/xai-grok-shared/Cargo.toml`
   - Inspect `crates/codegen/xai-grok-voice/Cargo.toml`
   - Inspect `crates/codegen/xai-grok-pager-bin/Cargo.toml`
2. **Run Dependency Validation Command**:
   - `cargo tree --target aarch64-linux-android` (once workspace is prepared)
3. **Run Platform Unit Tests**:
   - `cargo test --package xai-grok-config platform_capabilities`
