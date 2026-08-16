# Specification Mining Report: Native Android/Termux Port of Grok Build (R1–R5)

## 1. Observation

Authoritative specification sources probed:
- `/Users/iml1s/Documents/mine/grok-build-termux/ORIGINAL_REQUEST.md`
- `/Users/iml1s/Documents/mine/grok-build-termux/bootstrap-grok-build-termux.sh`
- `/Users/iml1s/Documents/mine/grok-build-termux/grok-build-termux-issue-plan.md`
- Upstream reference repository `xai-org/grok-build` tracking commit `eb267feff13129e568df38fb6fdf0ceb65f735d6` (`main`)

### Direct Codebase & Specification Observations

1. **Platform Detection & Paths** (`crates/codegen/xai-grok-config/src/paths.rs:20-25`):
   - `system_config_dir()` currently uses `if cfg!(unix) { Some(PathBuf::from("/etc/grok")) }`.
   - On Android/Termux, `/etc/grok` does not exist or is unwritable. The path must resolve dynamically to `$PREFIX/etc/grok`.
2. **Home Directory & Shared Storage Boundaries** (`crates/codegen/xai-grok-home/src/lib.rs:17-43`):
   - `resolve_grok_home_from()` accepts `$GROK_HOME` verbatim.
   - If a user sets `GROK_HOME` to `/sdcard/...` or `/storage/emulated/0/...`, the upstream code accepts it without checking permissions, leading to insecure credential storage on world-readable filesystems lacking POSIX `0700` permissions.
3. **Clipboard Backend Seam** (`crates/codegen/xai-grok-shared/src/clipboard.rs:24-60`, `310-330`):
   - On non-macOS Unix, upstream unconditionally attempts `arboard`, `wl-copy`, or `xclip`.
   - `arboard` fails or hangs in headless Android/Termux environments without X11 or Wayland.
   - Termux provides text clipboard utilities via `termux-clipboard-get` and `termux-clipboard-set` (when Termux:API is installed) and terminal OSC 52 write sequences.
4. **Voice & Audio Gating** (`crates/codegen/xai-grok-voice/Cargo.toml:35-43`):
   - `cpal` is gated with `[target.'cfg(not(target_os = "linux"))'.dependencies.cpal]`.
   - Since Android is `target_os = "android"` (which satisfies `not(target_os = "linux")`), `cpal` is inadvertently pulled into Android builds, causing compilation or runtime audio linkage failures.
5. **Tool Bundling in Build Scripts** (`crates/codegen/xai-grok-shell/build.rs:60-70`, `crates/codegen/xai-grok-tools/build.rs:180-210`):
   - `build.rs` auto-downloads desktop Linux tarballs (`x86_64-unknown-linux-musl` or `aarch64-unknown-linux-gnu`).
   - For `target_os = "android"`, `build.rs` errors with `Unsupported target for ripgrep bundling`. If overridden with Linux GNU binaries, it introduces incompatible glibc ELF binaries.
   - Native Termux packages (`pkg install ripgrep fd git bash`) reside in `$PREFIX/bin` and must be resolved from `$PATH`.
6. **URL Opening & Headless Browser Detection** (`crates/codegen/xai-grok-pager-render/src/link_opener.rs:28-40`, `70-95`):
   - `browser_open_likely_available_from_env()` on Linux checks for `DISPLAY`, `WAYLAND_DISPLAY`, or `BROWSER`.
   - Termux runs in a terminal without `DISPLAY`/`WAYLAND_DISPLAY`, but can open Android browsers via `termux-open-url` (using Android Intents).
7. **OIDC Authentication & DNS** (`crates/codegen/xai-grok-shell/src/auth/oidc/login.rs:65-150`):
   - Starts a loopback HTTP callback listener on `127.0.0.1:<port>`.
   - Supports manual paste of bare code or full callback URL.
   - Requires native Bionic DNS resolution via Android libc `getaddrinfo` without synthetic `/etc/resolv.conf` mutations.
8. **Sandbox & Confinement Reporting** (`crates/codegen/xai-grok-sandbox/src/lib.rs:40-75`):
   - Desktop uses `nono` (Landlock / Seatbelt) for kernel-enforced sandboxing.
   - On Android/Termux, unprivileged processes cannot enforce Landlock. Upstream reporting must distinguish `policy-only` from kernel-enforced, and PRoot must never be advertised as a security boundary.
9. **Update Isolation & Packaging** (`crates/codegen/xai-grok-update/src/auto_update.rs:993-1014`):
   - `detect_platform()` currently bails on `target_os = "android"`.
   - Package-managed installs (`pkg install grok-build`) must disable self-update and guide users to `pkg upgrade`.
   - Standalone installs must only target `grok-<version>-termux-aarch64.tar.gz`, never upstream desktop Linux artifacts.
10. **Composition Root & Allocator** (`crates/codegen/xai-grok-pager-bin/Cargo.toml:45-75`):
    - Default features include `jemalloc` and `sandbox-enforce`.
    - Android builds must omit `jemalloc` and link Bionic's system allocator.

---

## 2. Logic Chain

1. **From Observation 1 & 2 to Filesystem Safety (R3)**:
   - Termux is installed in an Android app private directory (e.g. `/data/data/com.termux/files`).
   - Hardcoding `/etc/grok` or `/tmp` causes permission errors or pollutes non-existent directories.
   - Storing configuration or credentials on `/sdcard` exposes OAuth tokens to every Android app with storage permission, violating least-privilege security.
   - Therefore, configuration must resolve to `$PREFIX/etc/grok`, home state to `$HOME/.grok`, temporary files to `$TMPDIR` (defaulting to `$PREFIX/tmp`), and any `GROK_HOME` pointing to shared storage must fail closed with an explicit error.

2. **From Observation 3, 4, 5, & 10 to Dependency Gating & Toolchain (R1 & R2)**:
   - Desktop Linux binaries rely on glibc, jemalloc, cpal, and arboard.
   - Android targets Bionic libc (`aarch64-linux-android`).
   - Android 15+ mandates 16 KiB ELF page alignment (`p_align >= 0x4000`).
   - Bundling glibc-based `rg`/`fd` binaries will fail at runtime on Bionic.
   - Therefore, build configurations must exclude desktop dependencies (`jemalloc`, `cpal`, `arboard`, `nono`), use Bionic system allocator, enforce 16 KiB ELF alignment via NDK linker flags, and resolve host tools (`rg`, `fd`, `git`, `bash`) directly from Termux `$PATH`.

3. **From Observation 6 & 7 to Auth & UX Integration (R4)**:
   - Termux terminal has no X11/Wayland display server, but the Android OS has a GUI browser.
   - `termux-open-url` bridges the terminal to Android's `Intent.ACTION_VIEW`.
   - The loopback callback on `127.0.0.1` receives OAuth tokens when the Android browser redirects.
   - If the browser fails to open or callback fails, the user can paste the authorization code manually.
   - DNS resolution on Android must rely on Bionic's netd socket resolver rather than `/etc/resolv.conf`.
   - Text clipboard operations must check for Termux:API (`termux-clipboard-get` / `termux-clipboard-set`) and fall back to ANSI OSC 52 sequences without crashing.

4. **From Observation 8 to Truthful Sandboxing (R4)**:
   - Android kernels restrict unprivileged namespace/Landlock manipulation.
   - Claiming "kernel-enforced sandbox" in Termux is deceptive and dangerous.
   - Therefore, Grok Build must classify Android sandboxing as `policy-only`, maintaining in-process path checks and tool prompts while truthfully reporting degradation in `grok doctor`.

5. **From Observation 9 to Distribution & Sync Strategy (R5)**:
   - Allowing `grok update` to download `linux-aarch64` replaces the working Bionic binary with an incompatible glibc binary.
   - Therefore, package-managed installs must delegate updates to `pkg upgrade`, and standalone installs must verify Termux ABI and release manifests.
   - Downstream changes must be modularized into clean feature gates and platform adapters to maintain clean rebase compatibility against upstream `xai-org/grok-build@eb267feff13129e568df38fb6fdf0ceb65f735d6`.

---

## 3. Features Discovered

| # | Category | Feature | Description | Inputs | Outputs | Error Behavior | Discovered Via |
|---|----------|---------|-------------|--------|---------|----------------|----------------|
| 1 | R1: Platform | Centralized Platform Capability Layer | Unified, injectable runtime struct (`PlatformCapabilities`) identifying OS kind, ABI, display presence, audio, and sandbox | Environment variables, OS detection (`cfg(target_os = "android")`) | `PlatformCapabilities` struct | Fails closed with descriptive error if `$PREFIX` is invalid on Android | `ORIGINAL_REQUEST.md:12-14`, `bootstrap.sh:200-235` |
| 2 | R1: Platform | Dynamic `$PREFIX` Discovery | Dynamically resolves Termux root path instead of hardcoded `/data/data/com.termux/files/usr` | `std::env::var("PREFIX")` | `PathBuf` representing Termux prefix | Returns `Err(MissingPrefix)` if unset on Android | `ORIGINAL_REQUEST.md:13`, `bootstrap.sh:209-223` |
| 3 | R1: Dependency | Allocator Gating (Bionic vs Jemalloc) | Uses Bionic's system memory allocator on Android; excludes `tikv-jemallocator` | Cargo feature `jemalloc` disabled on Android | System allocator linked | Build failure if jemalloc is forced on Bionic | `ORIGINAL_REQUEST.md:13`, `Cargo.toml`, `bootstrap.sh:271-304` |
| 4 | R1: Dependency | Desktop Clipboard Gating (`arboard`) | Excludes `arboard` from Android target dependencies; provides Termux clipboard backend | `target_os = "android"` | Termux clipboard adapter | Prevents X11/Wayland linkage errors | `ORIGINAL_REQUEST.md:13`, `xai-grok-shared/src/clipboard.rs` |
| 5 | R1: Dependency | Voice / Microphone Gating (`cpal`) | Excludes `cpal` and ALSA dependencies on Android; disables microphone UI cleanly | `target_os = "android"` | Feature disabled / voice stub | Graceful error if voice command invoked; no panic | `ORIGINAL_REQUEST.md:13`, `xai-grok-voice/Cargo.toml` |
| 6 | R2: Build | Native Bionic Build Profile | Cross-compiles native Rust binaries targeting `aarch64-linux-android` (and `x86_64-linux-android`) | `cargo build --target aarch64-linux-android` | Native Bionic ELF executable | Build failure if host glibc toolchain is used | `ORIGINAL_REQUEST.md:15-17`, `bootstrap.sh:236-269` |
| 7 | R2: Build | 16 KiB ELF Page-Size Alignment | Ensures ELF load segments align to 16 KiB page boundary for Android 15+ compatibility | Linker flags `-Wl,-z,max-page-size=16384` | ELF with `p_align >= 0x4000` | Rejected by Android 15 linker if misaligned | `ORIGINAL_REQUEST.md:16, 31`, `bootstrap.sh:247` |
| 8 | R2: Toolchain | Native CLI Tool Resolution | Disables automatic download of desktop Linux `rg`/`fd` binaries; resolves `rg`, `fd`, `git`, `bash` from `$PATH` | Environment `$PATH` (`$PREFIX/bin`) | Executable path `PathBuf` | Emits `pkg install <tool>` remediation hint if tool missing | `ORIGINAL_REQUEST.md:16`, `xai-grok-shell/build.rs`, `xai-grok-tools/build.rs` |
| 9 | R2: Toolchain | Optional Search Tools Fallback | Handles presence/absence of `bfs` and `ugrep` without hard dependency | CLI tool lookup | Optional tool handle or fallback to `fd`/`rg` | Graceful fallback to standard search tools | `bootstrap.sh:386-390` |
| 10 | R3: Filesystem | System Configuration Resolution | Resolves system-wide configuration under `$PREFIX/etc/grok` | `$PREFIX` environment | `$PREFIX/etc/grok` | Returns `None` if `$PREFIX` is unset or unwritable | `ORIGINAL_REQUEST.md:18-20`, `xai-grok-config/src/paths.rs` |
| 11 | R3: Filesystem | User Home Directory Resolution | Resolves user configuration, state, and credentials under `$HOME/.grok` | `$HOME` environment | `$HOME/.grok` | Falls back to private app storage; warns if unresolvable | `ORIGINAL_REQUEST.md:19`, `xai-grok-home/src/lib.rs` |
| 12 | R3: Filesystem | Runtime Temporary & Sockets | Uses `$TMPDIR` for ephemeral files and creates short hashed Unix sockets (`$TMPDIR/grok-<hash>.sock`) | `$TMPDIR` (or `$PREFIX/tmp`) | Socket path `PathBuf` (< 108 bytes) | Handles stale socket cleanup safely on startup | `ORIGINAL_REQUEST.md:19`, `bootstrap.sh:313-328` |
| 13 | R3: Security | Shared Storage Quarantine | Detects and strictly rejects placing `GROK_HOME`, credentials, or execution state on Android shared storage | Path prefix check against `/sdcard`, `/storage/emulated/0`, `/mnt/sdcard` | `Result<PathBuf, StorageError>` | Fails closed with error message explaining POSIX permission requirement | `ORIGINAL_REQUEST.md:19, 36`, `bootstrap.sh:318-326` |
| 14 | R3: Security | Shared-Storage Workspace Protection | Allows editing code on `/sdcard` while keeping sessions, auth tokens, hooks, and temp caches in private storage | Workspace path | Verified workspace handle | Refuses executable extraction or credential writes to shared storage | `ORIGINAL_REQUEST.md:19`, `bootstrap.sh:319` |
| 15 | R4: Auth | Termux OAuth Browser Handoff | Dispatches OAuth URL via `termux-open-url` to launch system Android browser | Auth URL string | Command spawn `termux-open-url <url>` | Falls back to printing URL for manual copying if opener missing | `ORIGINAL_REQUEST.md:21-23`, `xai-grok-pager-render/src/link_opener.rs` |
| 16 | R4: Auth | Loopback Callback Server | Listens on `127.0.0.1:<port>` to capture browser redirect with OAuth authorization code | HTTP GET `/callback?code=...` | Authorization code string | Times out after 10 min; races with manual paste | `ORIGINAL_REQUEST.md:22`, `xai-grok-shell/src/auth/oidc/login.rs` |
| 17 | R4: Auth | Manual Code / URL Paste Fallback | Accepts bare authorization code or full callback URL via stdin / TUI input modal | User text input | Parsed `(code, state)` | Displays `Invalid input` prompt and retries | `ORIGINAL_REQUEST.md:22`, `xai-grok-shell/src/auth/oidc/login.rs` |
| 18 | R4: Network | Native Bionic DNS & TLS Resolution | Resolves domain names via Android Bionic libc `getaddrinfo`; TLS via rustls with native roots | Hostnames (`auth.x.ai`, `api.x.ai`) | Resolved IP socket addresses & TLS stream | Detailed diagnostic error on failure without mutating `/etc/resolv.conf` | `ORIGINAL_REQUEST.md:22, 40`, `bootstrap.sh:350` |
| 19 | R4: UX | Termux:API Text Clipboard | Reads and writes text clipboard using `termux-clipboard-get` and `termux-clipboard-set` | String payload / clipboard request | Text copied to Android clipboard | If Termux:API is not installed, falls back to OSC 52 | `ORIGINAL_REQUEST.md:22, 41`, `bootstrap.sh:417-432` |
| 20 | R4: UX | OSC 52 Terminal Clipboard Fallback | Writes ANSI OSC 52 escape sequences to terminal stream for terminal-native copying | String payload | `\x1b]52;c;<base64>\x07` to stderr | No-op on paste (OSC 52 cannot read clipboard) | `ORIGINAL_REQUEST.md:22`, `xai-grok-shared/src/clipboard.rs` |
| 21 | R4: UX | Unsupported Clipboard / Voice Graceful Degradation | Disables image clipboard, file clipboard, and voice capture without crashing or presenting fake UI | User action | Clean error notice / UI hidden | Returns `Ok(None)` or explanatory message; no panic | `ORIGINAL_REQUEST.md:22`, `bootstrap.sh:421-432` |
| 22 | R4: Security | Truthful Sandbox Reporting | Classifies Android sandbox as `policy-only` in UI, doctor, and logs; explicitly denies kernel enforcement | Sandbox state query | Status string: `"policy-only"` | Fails security assertions if labeled `"sandbox-enforced"` | `ORIGINAL_REQUEST.md:22, 37`, `bootstrap.sh:448-460` |
| 23 | R4: Security | In-Process Policy Enforcement | Enforces file allow/deny paths, hook write protection, sensitive directory barriers (`~/.ssh`, `~/.grok`) | File operations | Allowed / Denied | Blocks access to protected resources; prompts user | `ORIGINAL_REQUEST.md:22`, `xai-grok-sandbox/src/lib.rs` |
| 24 | R4: Lifecycle | Conservative Concurrency & Defaults | Uses conservative thread pools, Tokio worker limits, and subagent concurrency for mobile thermal/memory limits | Process startup | Tuned Tokio runtime & worker config | Prevents Android low-memory killer (LMK) eviction | `ORIGINAL_REQUEST.md:21`, `bootstrap.sh:476-491` |
| 25 | R4: Lifecycle | Termux Wake Lock Integration | Acquires optional Android wake lock via `termux-wake-lock` during active long-running tasks and releases on idle/exit | Task lifecycle events | `termux-wake-lock` / `termux-wake-unlock` | Guaranteed release on cancel, panic, or exit | `bootstrap.sh:479-490` |
| 26 | R4: Lifecycle | Durable Session Checkpoint & Recovery | Saves atomic transaction checkpoints so interrupted tasks can resume seamlessly after process kill | Agent turns / tool executions | SQLite / JSON session log | Automatically recovers and repairs partial transactions | `ORIGINAL_REQUEST.md:21`, `bootstrap.sh:478, 486` |
| 27 | R5: Distribution | Package-Managed Install Mode | Detects installation via `pkg` / `apt`; disables in-app binary self-update | Process binary path / install marker | `"package-managed"` mode | `grok update` informs user to run `pkg upgrade grok-build` | `ORIGINAL_REQUEST.md:24-25`, `bootstrap.sh:505-520` |
| 28 | R5: Distribution | Standalone Install Mode & Updater Isolation | Standalone updater targets Android/Termux release channel only (`termux-aarch64`), rejecting Linux binaries | Release metadata & binary tarball | Staged, verified, atomic binary replacement | Rejects desktop Linux artifacts; rolls back on smoke failure | `ORIGINAL_REQUEST.md:24-25`, `bootstrap.sh:507-520` |
| 29 | R5: Diagnostics | `grok doctor` for Android/Termux | Comprehensive environment diagnostic check tailored for Termux | `grok doctor` [--json] | Diagnostic report table / JSON | Highlights missing packages (`git`, `rg`, `termux-api`) with remediation | `ORIGINAL_REQUEST.md:25, 37`, `bootstrap.sh:218` |
| 30 | R5: Testing | CI Cross-Compilation & ELF Validator | Hosted CI pipeline compiling `aarch64-linux-android` and validating ELF headers (Bionic, 16K alignment) | Source code + NDK | CI check verdict + verified release binaries | Blocks release if ELF has glibc dependency or 4K-only alignment | `ORIGINAL_REQUEST.md:25, 30-31`, `bootstrap.sh:542-564` |
| 31 | R5: Testing | Real-Device / Emulator Test Matrix | Comprehensive test suite running on Android devices (4 KiB and 16 KiB pages, Wi-Fi, mobile data, Termux:API) | Test runner on device | Test results matrix | Catches mobile-specific regressions before tagging releases | `ORIGINAL_REQUEST.md:25`, `bootstrap.sh:547-564` |
| 32 | R5: Upstream | Low-Conflict Upstream Sync Strategy | Modular patch architecture keeping upstream tracking branch synchronized with minimal workspace conflicts | Upstream commit `eb267feff13129e568df38fb6fdf0ceb65f735d6` | Clean patch stack & merge PRs | Sync automation opens reviewable PR without force-pushing over downstream work | `ORIGINAL_REQUEST.md:25, 44-45`, `bootstrap.sh:578-599` |

---

## 4. Edge Cases

| # | Feature | Input / Condition | Observed / Required Behavior |
|---|---------|-------------------|-----------------------------|
| 1 | Dynamic `$PREFIX` Discovery | `$PREFIX` environment variable unset or empty | Fail closed with explicit error: `"Environment variable PREFIX is not set. Grok Build requires a valid Termux environment."` Do NOT fall back to `/usr` or `/etc`. |
| 2 | Dynamic `$PREFIX` Discovery | Custom Termux prefix (e.g. non-standard installation path) | Dynamically construct config path `$PREFIX/etc/grok` and binaries `$PREFIX/bin/...` matching custom prefix. |
| 3 | Shared Storage Quarantine | User sets `GROK_HOME=/sdcard/.grok` or `/storage/emulated/0/grok` | Refuse startup with explicit error: `"GROK_HOME cannot reside on Android shared storage (/sdcard). Owner-only permissions (0700) are required for credentials."` |
| 4 | Shared Storage Quarantine | User sets `GROK_HOME=/data/data/com.termux/files/home/.grok` | Accept path and enforce `0700` permissions on private filesystem. |
| 5 | Shared Storage Workspace | User runs Grok Build in `/sdcard/Download/my-project` | Allow editing project files, but store all sessions, auth tokens, temporary files, and hooks in `$HOME/.grok`. Display warning regarding missing POSIX symlink/permission semantics. |
| 6 | 16 KiB ELF Alignment | Run binary on Android 15 device with 16 KiB kernel page size | Binary loads cleanly via Bionic dynamic linker (`linker64`). No `SIGSEGV` or `dlopen` page-alignment failure. |
| 7 | Host Tools Resolution | `ripgrep` (`rg`) is not installed in Termux (`$PATH` lacks `rg`) | Fall back to built-in search or fail tool call with actionable remediation message: `"ripgrep not found. Run: pkg install ripgrep"`. Never crash the TUI. |
| 8 | Host Tools Resolution | `fd` is not installed in Termux | Fall back to standard file traversal and suggest: `"fd not found. Run: pkg install fd"`. |
| 9 | OAuth Browser Launch | `termux-open-url` is available | Spawn `termux-open-url <auth_url>` detached. Browser opens login page; TUI waits on loopback callback. |
| 10 | OAuth Browser Launch | `termux-open-url` is missing or fails | Print full OAuth URL to terminal with copy instructions and present manual code entry prompt. |
| 11 | OAuth Callback | User completes login in browser | Browser redirects to `http://127.0.0.1:<port>/callback?code=...`, callback handler captures code, writes success HTML, and completes login. |
| 12 | OAuth Callback | Port `127.0.0.1:<port>` blocked by firewall or mobile browser isolation | User copies code from browser URL bar and pastes into TUI manual input prompt. Login succeeds. |
| 13 | Network & DNS Resolution | Android Private DNS or VPN active | Bionic `getaddrinfo` handles Android system DNS routes transparently. No network failure from missing `/etc/resolv.conf`. |
| 14 | Clipboard Text Copy | Termux:API package and app installed | `termux-clipboard-set` executes successfully and sets Android system clipboard. |
| 15 | Clipboard Text Copy | Termux:API not installed | `termux-clipboard-set` fails; gracefully fall back to emitting ANSI OSC 52 sequence to terminal stderr. |
| 16 | Clipboard Text Paste | Termux:API not installed | `termux-clipboard-get` fails; returns `Ok(None)` gracefully. Prompt informs user that paste requires Termux:API or terminal paste. |
| 17 | Clipboard Image Copy/Paste | User attempts image paste (Ctrl+V with image) | Returns `Ok(None)` / unsupported notification. No crash or attempt to link `arboard`/`AppKit`. |
| 18 | Voice Input | User presses voice hotkey or invokes voice command | Displays message: `"Voice input is not supported in the Android/Termux port."` No panic or audio device initialization failure. |
| 19 | Sandbox Status Query | User or `grok doctor` queries sandbox level | Reports `"policy-only"` (enforces file allow/deny and sensitive path blocks, but no kernel Landlock). Never claims `"sandbox-enforced"`. |
| 20 | Process Lifecycle / Kill | Android OS sends `SIGKILL` / low-memory kill during long session | On relaunch, durable session checkpoint detects unfinished turn, cleans up stale socket lock, and offers session resume. |
| 21 | Termux Wake Lock | Task running in background with wake lock enabled | Acquires `termux-wake-lock`. On completion, error, or Ctrl+C interrupt, releases via `termux-wake-unlock`. |
| 22 | Auto-Update in Package Mode | User runs `grok update` on package-managed build | Outputs: `"Grok Build was installed via Termux package manager. To update, run: pkg update && pkg upgrade grok-build"`. Refuses binary download. |
| 23 | Auto-Update in Standalone Mode | Upstream releases new desktop Linux version `v1.1.0` | Standalone updater queries Termux release channel; refuses to download `linux-aarch64` or `linux-x86_64` artifacts. Only downloads `grok-1.1.0-termux-aarch64.tar.gz`. |
| 24 | Unix Domain Sockets | `$TMPDIR` contains stale socket from crashed leader process | Startup checks socket liveness; unlinks stale socket file safely before binding new socket. |
| 25 | Terminal Resize & Interrupt | User rotates device screen or presses Ctrl+C in TUI | Handles `SIGWINCH` with proper viewport recalculation; Ctrl+C cleanly restores terminal mode, showing cursor and restoring standard buffer. |

---

## 5. Caveats

1. **Kernel Sandbox on Android**: Android kernels (especially non-rooted) restrict Landlock and namespace unsharing for third-party apps. Sandboxing in Termux is fundamentally **policy-only**; PRoot must not be treated as a security boundary.
2. **Termux:API Dependency**: Full text clipboard and wake lock integration rely on the optional `termux-api` package and Android companion app. The binary must function seamlessly when `termux-api` is absent.
3. **Android Shared Storage Limitations**: `/sdcard` uses FUSE/sdcardfs which does not support POSIX owner-only permissions (`chmod 0700`), hard links, or reliable Unix domain sockets.
4. **Upstream Generated Manifests**: The upstream root `Cargo.toml` is periodically regenerated from an internal monorepo. Downstream patches must minimize changes to the root manifest and rely on crate-level `Cargo.toml` conditional dependencies (`[target.'cfg(target_os = "android")'.dependencies]`).

---

## 6. Conclusion

The specification mining for the native Android/Termux port of Grok Build (`xai-org/grok-build@eb267feff13129e568df38fb6fdf0ceb65f735d6`) is complete. All requirements across R1 to R5 have been mapped to concrete architectural components, interface contracts, error behaviors, and acceptance criteria:

- **R1**: Platform capability abstraction (`PlatformCapabilities`), dynamic `$PREFIX` resolution, clean gating of `jemalloc`, `arboard`, `cpal`, and `nono`.
- **R2**: Native Bionic toolchain targeting `aarch64-linux-android`, 16 KiB ELF page-size alignment, resolution of native CLI tools (`rg`, `fd`, `git`, `bash`) via Termux `$PATH`.
- **R3**: Strict directory boundaries (`$PREFIX/etc/grok`, `$HOME/.grok`, `$TMPDIR`), Unix socket path safety (< 108 bytes), and strict fail-closed quarantine of `/sdcard` and `/storage/emulated/0`.
- **R4**: OAuth browser handoff via `termux-open-url`, loopback callback on `127.0.0.1`, manual code paste fallback, native Bionic DNS/TLS, Termux:API clipboard with OSC 52 fallback, and truthful `policy-only` sandbox reporting.
- **R5**: Dual install modes (package-managed vs standalone), updater isolation preventing desktop Linux binary overwrite, `grok doctor` diagnostics for Termux, CI cross-compilation & ELF validation, real-device test matrix, and low-conflict upstream sync workflow.

---

## 7. Verification Method

To independently verify the mined specifications:
1. **Inspect Path & Dependency Definitions**:
   - `view_file /Users/iml1s/Documents/mine/grok-build-termux/ORIGINAL_REQUEST.md`
   - `view_file /Users/iml1s/Documents/mine/grok-build-termux/bootstrap-grok-build-termux.sh`
   - `view_file /Users/iml1s/Documents/mine/grok-build-termux/grok-build-termux-issue-plan.md`
2. **Inspect Upstream Codebase Touch Points**:
   - `gh api repos/xai-org/grok-build/contents/crates/codegen/xai-grok-config/src/paths.rs`
   - `gh api repos/xai-org/grok-build/contents/crates/codegen/xai-grok-home/src/lib.rs`
   - `gh api repos/xai-org/grok-build/contents/crates/codegen/xai-grok-shared/src/clipboard.rs`
   - `gh api repos/xai-org/grok-build/contents/crates/codegen/xai-grok-voice/Cargo.toml`
   - `gh api repos/xai-org/grok-build/contents/crates/codegen/xai-grok-sandbox/src/lib.rs`
   - `gh api repos/xai-org/grok-build/contents/crates/codegen/xai-grok-pager-render/src/link_opener.rs`
   - `gh api repos/xai-org/grok-build/contents/crates/codegen/xai-grok-shell/src/auth/oidc/login.rs`
   - `gh api repos/xai-org/grok-build/contents/crates/codegen/xai-grok-shell/build.rs`
   - `gh api repos/xai-org/grok-build/contents/crates/codegen/xai-grok-tools/build.rs`
   - `gh api repos/xai-org/grok-build/contents/crates/codegen/xai-grok-update/src/auto_update.rs`
   - `gh api repos/xai-org/grok-build/contents/crates/codegen/xai-grok-pager-bin/Cargo.toml`
   - `gh api repos/xai-org/grok-build/contents/crates/codegen/xai-grok-pager/src/doctor_cmd/`
3. **Invalidation Conditions**:
   - Upstream alters the core authentication or path resolution architecture.
   - Android Bionic removes or changes standard `getaddrinfo` socket resolution.
   - NDK or rustc defaults change 16 KiB ELF alignment requirements.
