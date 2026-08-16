# Handoff Report: Codebase Survey & Dependency Analysis for Native Android/Termux Port

**Author**: teamwork_preview_explorer_survey_1  
**Working Directory**: `/Users/iml1s/Documents/mine/grok-build-termux/.agents/teamwork_preview_explorer_survey_1`  
**Parent Orchestrator**: `f8a62484-7465-4198-a94f-7093afe162ee`  
**Date**: 2026-08-15  

---

## 1. Observation

### 1.1 Files in Workspace (`/Users/iml1s/Documents/mine/grok-build-termux`)
Inspection of `/Users/iml1s/Documents/mine/grok-build-termux` revealed:
- `ORIGINAL_REQUEST.md`: Authoritative specification for native Android/Termux port.
- `bootstrap-grok-build-termux.sh` (610 lines): Script for creating/syncing GitHub fork `ImL1s/grok-build-termux` against `xai-org/grok-build@eb267feff13129e568df38fb6fdf0ceb65f735d6`, setting up milestone `v0.1.0-termux-native`, labels, and 1 Epic + 12 linked sub-issues (P0/P1/P2).
- `grok-build-termux-issue-plan.md`: Plan summary referencing target `ImL1s/grok-build-termux` tracking upstream head `eb267feff13129e568df38fb6fdf0ceb65f735d6`.
- `.agents/`: Agent metadata directory holding subagent workspaces.

### 1.2 Upstream Repository State
- The target upstream commit `eb267feff13129e568df38fb6fdf0ceb65f735d6` is verified in the sibling clone `/Users/iml1s/Documents/mine/grok-build` on `upstream/main` (`git fetch upstream` succeeded).
- In the immediate directory `/Users/iml1s/Documents/mine/grok-build-termux`, the full Rust repository tree has not yet been initialized (currently contains the bootstrap script and issue plan).

### 1.3 Rust Workspace & Crate Structure
Inspection of `eb267feff13129e568df38fb6fdf0ceb65f735d6:Cargo.toml` shows a cargo workspace with 92 member crates across 4 primary layers:
1. **Application & Binaries**:
   - `crates/codegen/xai-grok-pager-bin`: Main executable (`grok`) composition root.
   - `crates/codegen/ptyctl-cli`, `crates/codegen/xai-grok-pager-pty-harness`.
2. **Interactive UI & Terminal (TUI)**:
   - `crates/codegen/xai-grok-pager`: TUI application core and dispatch loop.
   - `crates/codegen/xai-grok-pager-render`: Markdown & terminal widget rendering, hyperlink openers (`src/link_opener.rs`).
   - `crates/codegen/xai-grok-pager-diff`, `xai-grok-pager-minimal`, `xai-ratatui-inline`, `xai-ratatui-textarea`, `xai-tty-utils`, `ptyctl`.
3. **Agent, Shell & Tool Execution**:
   - `crates/codegen/xai-grok-shell`: Agent loop, OIDC auth (`src/auth/oidc/login.rs`), heap profile monitoring, build-time ripgrep downloader (`build.rs`).
   - `crates/codegen/xai-grok-tools`: Tool runner, filesystem tools, search tool bundling (`build.rs`).
   - `crates/codegen/xai-grok-agent`, `xai-grok-models`, `xai-grok-sampler`, `xai-grok-mcp`, `xai-grok-memory`, `xai-grok-hooks`, `xai-grok-workflow`, `xai-grok-workspace`, `xai-grok-workspace-daemon`.
4. **Platform, Security & Infrastructure**:
   - `crates/codegen/xai-grok-config`: Configuration paths (`src/paths.rs`).
   - `crates/codegen/xai-grok-shared`: System clipboard access (`src/clipboard.rs`).
   - `crates/codegen/xai-grok-sandbox`: Landlock / Seatbelt / Seccomp sandbox (`src/child_net.rs`, `src/types.rs`, `src/lib.rs`).
   - `crates/codegen/xai-grok-voice`: Audio capture (`src/audio/capture.rs`).
   - `crates/codegen/xai-grok-update`: Self-updater and release channel manager (`src/auto_update.rs`).
   - `crates/codegen/xai-system-power`: Suspend/resume notification listener (`src/lib.rs`).

### 1.4 Desktop-Only Dependencies & Locations
The following desktop-only dependencies were identified in `eb267feff13129e568df38fb6fdf0ceb65f735d6`:

1. **`jemalloc` (`tikv-jemallocator`, `tikv-jemalloc-sys`, `tikv-jemalloc-ctl`)**:
   - `Cargo.toml` lines 260–262 & `[profile.release-dist-jemalloc]`.
   - `crates/codegen/xai-grok-pager-bin/Cargo.toml` lines 68–98 (gated under `jemalloc` feature).
   - `crates/codegen/xai-grok-pager/Cargo.toml` line 295 (`default = ["jemalloc", "sandbox-enforce"]`).
   - `crates/codegen/xai-grok-pager-bin/src/main.rs` line 8:
     ```rust
     #[cfg(all(feature = "jemalloc", unix))]
     #[global_allocator]
     static GLOBAL: tikv_jemallocator::Jemalloc = tikv_jemallocator::Jemalloc;
     ```
   - *Issue*: `unix` is true on Android (`aarch64-linux-android`). Activating jemalloc causes build and runtime allocator mismatches on Bionic libc.

2. **`cpal` (Audio Capture)**:
   - `crates/codegen/xai-grok-voice/Cargo.toml` lines 44–47:
     ```toml
     [target.'cfg(not(target_os = "linux"))'.dependencies.cpal]
     ```
   - *Issue*: On Android, `not(target_os = "linux")` evaluates to true, pulling in `cpal` and requiring ALSA/AAudio headers.

3. **`arboard` (Desktop Clipboard)**:
   - `crates/codegen/xai-grok-shared/Cargo.toml` lines 37–39:
     ```toml
     [target.'cfg(not(target_os = "macos"))'.dependencies]
     arboard = { workspace = true, features = ["wayland-data-control"] }
     ```
   - `crates/codegen/xai-grok-shared/src/clipboard.rs` line 1194:
     ```rust
     #[cfg(not(target_os = "macos"))]
     mod platform { ... }
     ```
   - *Issue*: On Android, `not(target_os = "macos")` evaluates to true, pulling in `arboard` with X11/Wayland dependencies.

4. **Kernel Sandbox (`nono`, Landlock, Seccomp BPF)**:
   - `crates/codegen/xai-grok-sandbox/Cargo.toml` lines 18–26 (unconditionally includes `nono = "=0.53.0"` on `cfg(unix)`).
   - `crates/codegen/xai-grok-sandbox/src/child_net.rs` line 105: uses raw Linux syscalls `SYS_seccomp` and `PR_SET_NO_NEW_PRIVS` to install thread-synchronous BPF filters.
   - `crates/codegen/xai-grok-sandbox/src/types.rs` line 71: reports platform string as `linux/landlock` or `macos/seatbelt`.

5. **Release Tool Auto-Bundling (`rg`, `fd`)**:
   - `crates/codegen/xai-grok-shell/build.rs` lines 67–80:
     ```rust
     let asset_triple = match (target_os.as_str(), target_arch.as_str()) {
         ("macos", "aarch64") => "aarch64-apple-darwin",
         ("macos", "x86_64") => "x86_64-apple-darwin",
         ("linux", "x86_64") => "x86_64-unknown-linux-musl",
         ("linux", "aarch64") => "aarch64-unknown-linux-gnu",
         _ => return Err(format!("Unsupported target for ripgrep bundling: {os}-{arch}").into()),
     };
     ```
   - `crates/codegen/xai-grok-tools/build.rs` (identical error for ripgrep and fd download).
   - *Issue*: Release builds for `aarch64-linux-android` fail during compilation unless explicitly exempted.

6. **Filesystem Paths**:
   - `crates/codegen/xai-grok-config/src/paths.rs` line 59:
     ```rust
     pub fn system_config_dir() -> Option<PathBuf> {
         if cfg!(unix) {
             Some(PathBuf::from("/etc/grok"))
         } else {
             None
         }
     }
     ```
   - *Issue*: Termux requires `$PREFIX/etc/grok` and user private storage under `$HOME/.grok`, strictly forbidding credentials on Android shared storage (`/sdcard`, `/storage/emulated/0`).

7. **Browser / URL Opener**:
   - `crates/codegen/xai-grok-pager-render/src/link_opener.rs` lines 32–43: checks for `DISPLAY` or `WAYLAND_DISPLAY` on Unix. On Termux, this returns false, failing to launch the browser even when `termux-open-url` is available.
   - `crates/codegen/xai-grok-shell/src/auth/oidc/login.rs` line 423: calls `webbrowser::open(&auth_url)`.

8. **Updater**:
   - `crates/codegen/xai-grok-update/src/auto_update.rs` lines 993–1014:
     ```rust
     pub(crate) fn detect_platform() -> Result<(&'static str, &'static str)> {
         let os = if cfg!(target_os = "macos") { "macos" }
         else if cfg!(target_os = "linux") { "linux" }
         else if cfg!(target_os = "windows") { "windows" }
         else { anyhow::bail!("Unsupported OS"); };
         ...
     ```
   - *Issue*: Panics/fails on `target_os = "android"`.

---

## 2. Logic Chain

1. **Target Identification**: Android targets (`aarch64-linux-android`) are Unix (`cfg(unix) == true`), but are NOT desktop Linux distributions (`target_os == "android"`, not `"linux"`).
2. **Negative Inversion Gotchas**: Upstream code frequently uses `cfg(not(target_os = "macos"))` or `cfg(not(target_os = "linux"))` under the assumption that only macOS, Linux, and Windows exist.
   - `not(target_os = "macos")` incorrectly pulled `arboard` onto Android.
   - `not(target_os = "linux")` incorrectly pulled `cpal` onto Android.
   - `cfg(unix)` incorrectly activated `tikv-jemallocator` and `nono` (Landlock) onto Android.
3. **Allocator Selection**: Bionic libc provides its own hardened, optimized memory allocator (Scudo / jemalloc-variant in Bionic). Forcing `tikv_jemallocator` on Android creates linking issues, 16 KiB page size incompatibility, and symbol collisions. Gating out jemalloc on `target_os = "android"` allows Bionic's allocator to take over cleanly.
4. **Clipboard & UX Strategy**:
   - Desktop display servers (X11, Wayland) are absent in standard Termux.
   - Android text clipboard can be accessed via `termux-clipboard-get` / `termux-clipboard-set` (when Termux:API is installed) or fallback to OSC 52 terminal escape codes.
   - Image and file clipboards should degrade gracefully (`Ok(None)`) rather than crashing or attempting to link AppKit/X11.
5. **Sandbox Truthfulness**:
   - Linux Landlock and Seccomp syscalls cannot be presumed available or safe under non-root Android application sandboxes.
   - Android must report its sandbox capability as `policy-only` rather than `kernel-enforced`.
6. **Toolchain & Runtime Executables**:
   - Downloading desktop Linux glibc musl `rg`/`fd` binaries inside `build.rs` produces binaries incompatible with Android Bionic ABI.
   - Skipping auto-bundling on Android (like Windows) allows Grok Build to resolve native Termux packages (`pkg install ripgrep fd git bash`) from `$PATH`.
7. **16 KiB Page Size Alignment**:
   - Setting `-C link-arg=-Wl,-z,max-page-size=16384` for `aarch64-linux-android` in `.cargo/config.toml` guarantees compatibility with both 4 KiB and 16 KiB Android kernels (Android 15+ requirement).

---

## 3. Caveats

- **No Active Cloned Source in Current Directory**: `/Users/iml1s/Documents/mine/grok-build-termux` is currently an orchestrator workspace containing bootstrap scripts and plans. The upstream repository `xai-org/grok-build` was surveyed directly from `/Users/iml1s/Documents/mine/grok-build` at commit `eb267feff13129e568df38fb6fdf0ceb65f735d6`.
- **Termux:API Dependency**: Full clipboard and URL opening features depend on optional Termux helper packages (`termux-tools`, `termux-api`). Fallbacks (OSC 52, manual URL printing) must always be present.

---

## 4. Conclusion

The upstream `xai-org/grok-build` codebase at commit `eb267feff13129e568df38fb6fdf0ceb65f735d6` is well-structured and modular, but currently contains multiple inverted `cfg` gates and desktop assumptions that prevent clean `aarch64-linux-android` compilation and runtime execution.

### Recommended Code & Manifest Changes:
1. **`.cargo/config.toml`**:
   Add `[target.aarch64-linux-android]` and `[target.x86_64-linux-android]` with flags `-C link-arg=-Wl,-z,relro,-z,now,-z,noexecstack,-z,max-page-size=16384`.
2. **`Cargo.toml` Files**:
   - `xai-grok-shared/Cargo.toml`: Gate `arboard` with `cfg(all(not(target_os = "macos"), not(target_os = "android")))`.
   - `xai-grok-voice/Cargo.toml`: Gate `cpal` with `cfg(all(not(target_os = "linux"), not(target_os = "android")))`.
   - `xai-grok-pager-bin/Cargo.toml` & `xai-grok-pager/Cargo.toml`: Gate `tikv-jemallocator` so it is disabled on Android.
3. **Rust Source Files**:
   - `xai-grok-pager-bin/src/main.rs`: Change allocator gate to `#[cfg(all(feature = "jemalloc", unix, not(target_os = "android")))]`.
   - `xai-grok-shared/src/clipboard.rs`: Add dedicated `#[cfg(target_os = "android")] mod platform` implementation supporting `termux-clipboard-*` and OSC 52 fallback.
   - `xai-grok-pager-render/src/link_opener.rs`: Support `termux-open-url` without requiring `DISPLAY`/`WAYLAND_DISPLAY`.
   - `xai-grok-config/src/paths.rs`: Resolve `system_config_dir()` to `$PREFIX/etc/grok` when `$PREFIX` is set, and enforce private storage boundaries rejecting `/sdcard`.
   - `xai-grok-sandbox/src/`: Report status as `policy-only` and skip unsupported Landlock/Seccomp syscalls on Android.
   - `xai-grok-shell/build.rs` & `xai-grok-tools/build.rs`: Treat `target_os == "android"` as an external tool target (skip auto-downloading desktop `rg`/`fd`).
   - `xai-grok-update/src/auto_update.rs`: Add Android target detection, suppress in-app self-update for package-managed installations, and direct users to `pkg upgrade`.

---

## 5. Verification Method

To independently verify these findings:
1. **Inspect Target Commit & Tree**:
   ```bash
   git -C /Users/iml1s/Documents/mine/grok-build show eb267feff13129e568df38fb6fdf0ceb65f735d6:Cargo.toml
   ```
2. **Verify Desktop Gating Locations**:
   - Jemalloc: `git -C /Users/iml1s/Documents/mine/grok-build grep -n "tikv-jemalloc" eb267feff13129e568df38fb6fdf0ceb65f735d6`
   - Cpal: `git -C /Users/iml1s/Documents/mine/grok-build grep -n "cpal" eb267feff13129e568df38fb6fdf0ceb65f735d6 -- '**/Cargo.toml'`
   - Arboard: `git -C /Users/iml1s/Documents/mine/grok-build grep -n "arboard" eb267feff13129e568df38fb6fdf0ceb65f735d6 -- '**/Cargo.toml'`
   - Ripgrep bundling: `git -C /Users/iml1s/Documents/mine/grok-build grep -n "Unsupported target for ripgrep bundling" eb267feff13129e568df38fb6fdf0ceb65f735d6`
3. **Cross-Compilation Dry Run (once patched)**:
   ```bash
   cargo check --target aarch64-linux-android --no-default-features -p xai-grok-pager-bin
   ```
