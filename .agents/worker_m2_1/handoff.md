# Milestone 2: Native Bionic Build & Toolchain Alignment — Handoff Report

## 1. Observation

- **Toolchain Target Configuration**:
  - `.cargo/config.toml` lacked entries for `[target.aarch64-linux-android]` and `[target.x86_64-linux-android]`. Without 16 KiB page size linker configuration (`-C link-arg=-Wl,-z,max-page-size=16384`), compiled binaries on Android 15+ kernels fail ELF loading.
  - `rust-toolchain.toml` lacked Android targets in the `targets` array.
- **Build Script Desktop Download Bypass**:
  - `crates/codegen/xai-grok-tools/build.rs` and `crates/codegen/xai-grok-shell/build.rs` downloaded pre-compiled glibc desktop binaries (`ripgrep`, `fd`, `bfs`, `ugrep`) during build, which fail to link or run on Android Bionic.
- **Cross-Compilation Incompatibility**:
  - In `crates/codegen/xai-grok-pager-render/src/theme/system_appearance.rs:114`, `detect_desktop()` called `dark_light::detect()`. When cross-compiling for Android, `dark-light` 2.0.0 is unsupported and failed compilation.
- **Runtime Tool Resolution**:
  - `crates/codegen/xai-grok-config/src/shell.rs` looked only in standard Linux/macOS directories (`/bin`, `/usr/bin`, `/usr/local/bin`, `/opt/homebrew/bin`) and failed on Termux where binaries live in `$PREFIX/bin` or `/data/data/com.termux/files/usr/bin` or Android `/system/bin`.
  - There was no unified `ToolResolver` providing package installation remediation hints (`pkg install ripgrep`, `pkg install fd`, etc.) when tools are missing.

---

## 2. Logic Chain

1. **Linker & ELF Configuration**:
   - Added `[target.aarch64-linux-android]` and `[target.x86_64-linux-android]` to `.cargo/config.toml` specifying `-C link-arg=-Wl,-z,max-page-size=16384`, `-C link-arg=-Wl,-z,relro,-z,now,-z,noexecstack`, and `-C force-unwind-tables=yes`.
   - Added `aarch64-linux-android` and `x86_64-linux-android` to `rust-toolchain.toml`.
2. **Bypassing Desktop Downloads**:
   - In `crates/codegen/xai-grok-tools/build.rs` and `crates/codegen/xai-grok-shell/build.rs`, added checks for `target_os == "android"` to early-return `Ok(())` unless explicit environment variable overrides are provided (`GROK_TOOLS_BUNDLE_*_PATH`).
3. **Appearance Compatibility Fix**:
   - In `crates/codegen/xai-grok-pager-render/src/theme/system_appearance.rs`, gated `detect_desktop()` with `#[cfg(not(target_os = "android"))]` and added a `#[cfg(target_os = "android")]` branch returning `None` gracefully.
4. **Termux Shell & Runtime Tool Resolution**:
   - In `crates/codegen/xai-grok-config/src/shell.rs`, updated `resolve_unix_shell_path()` to check `$PREFIX/bin`, `/data/data/com.termux/files/usr/bin`, `/system/bin`, and `/system/xbin`.
   - Created `crates/codegen/xai-grok-tools/src/resolver.rs` (`ToolResolver`) supporting:
     - `rg` (`ripgrep`), `fd` (`fd`), `git` (`git`), `bash` (`bash`), `bfs` (`bfs`), `ugrep` (`ugrep`).
     - Resolution cascade: explicit path override $\rightarrow$ bundled vendor path $\rightarrow$ `$GROK_TOOLS_DIR` $\rightarrow$ `$PATH` $\rightarrow$ `$PREFIX/bin` $\rightarrow$ `/data/data/com.termux/files/usr/bin` $\rightarrow$ `/system/bin`.
     - Environment-aware remediation hints (`pkg install <pkg>` for Termux, `apt install <pkg>` for Debian/Ubuntu, `brew install <pkg>` for macOS).
   - Integrated `ToolResolver` into `ripgrep.rs` and `grep/mod.rs` error handling.
5. **Cross-Compilation & Test Verification**:
   - Android target check with NDK 28: `cargo ndk -t arm64-v8a -P 24 check -p xai-grok-config -p xai-grok-shared -p xai-grok-tools -p xai-grok-pager-render -p xai-grok-shell` compiled all native C/C++ sys dependencies (`aws-lc-sys`, `ring`, `libsqlite3-sys`, `libz-sys`, `tree-sitter-*`) and checked crates with 0 errors.
   - Host `cargo check` passed with 0 errors.
   - Resolver unit tests passed (3/3).
   - Grep unit tests passed (39/39).
   - E2E test suite passed (366/366).
   - ELF validator self-test passed (6/6).

---

## 3. Caveats

- Full binary linking for Android targets requires the Android NDK clang sysroot (`cargo ndk` or NDK standalone toolchain). On environments without NDK installed, `cargo check` on host target validates compilation syntax and crate interface contracts, while `cargo ndk check` validates Android Bionic C-binding compatibility.
- On non-Android hosts, `ToolResolver` continues to resolve system tools from `$PATH` or embedded locations, maintaining 100% backward compatibility with existing desktop workflows.

---

## 4. Conclusion

Milestone 2 (Features 6–9) is fully implemented, verified, and committed to the `termux-native` branch:
- **Feature 6 (Target Config & 16 KiB Alignment)**: `.cargo/config.toml` and `rust-toolchain.toml` configured.
- **Feature 7 (Build Script Bypass)**: `xai-grok-tools` and `xai-grok-shell` build scripts bypass desktop downloads on Android.
- **Feature 8 (Cross-compilation Fixes)**: `dark-light` appearance incompatibility on Android fixed.
- **Feature 9 (Runtime Tool Resolution & Remediation)**: `xai-grok-config` shell resolution updated and `ToolResolver` implemented with Termux `pkg install` hints.

Commit hash: `2aac966` ("feat(toolchain): configure Android targets, 16 KiB alignment, build bypass, and runtime tool resolver (Milestone 2)").

---

## 5. Verification Method

1. **Host Build Check**:
   ```bash
   cargo check -p xai-grok-config -p xai-grok-shared -p xai-grok-tools -p xai-grok-pager-render -p xai-grok-shell
   ```
   *Expected result*: Exit code 0, all crates checked successfully.

2. **Android Bionic Cross-Compilation Check**:
   ```bash
   export ANDROID_NDK_HOME=/Users/iml1s/Library/Android/sdk/ndk/28.1.13356709
   cargo ndk -t arm64-v8a -P 24 check -p xai-grok-config -p xai-grok-shared -p xai-grok-tools -p xai-grok-pager-render -p xai-grok-shell
   ```
   *Expected result*: Exit code 0, all C sys crates and Rust crates compile and pass checks.

3. **Resolver & Grep Unit Tests**:
   ```bash
   cargo test -p xai-grok-tools --lib resolver
   cargo test -p xai-grok-tools --lib implementations::grok_build::grep
   ```
   *Expected result*: All unit tests pass (`test result: ok`).

4. **E2E Suite & ELF Validator Self-Tests**:
   ```bash
   python3 tests/e2e/runner.py
   python3 scripts/validate_elf.py --self-test
   ```
   *Expected result*: 366/366 E2E tests pass, 6/6 ELF self-tests pass.
