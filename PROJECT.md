# Project: Native Android/Termux Port of Grok Build

## Architecture
The native Android/Termux port of Grok Build (`grok-build-termux`) targets `aarch64-linux-android` (with Bionic libc) tracking upstream `xai-org/grok-build@eb267feff13129e568df38fb6fdf0ceb65f735d6`. It establishes a clean modular architecture:
1. **Platform Capability Layer (`xai-grok-platform` / `PlatformCapabilities`)**: Central injectable source of truth for runtime environment detection (Termux vs Desktop, dynamic `$PREFIX`, lack of display server, audio gating, policy-only sandboxing).
2. **Build & Toolchain Configuration**: Android NDK (r28b, API 24) toolchain with explicit 16 KiB ELF page-size alignment (`-Wl,-z,max-page-size=16384`) and Bionic dynamic linker (`/system/bin/linker64`).
3. **Filesystem & Storage Boundary Enforcement**: Dynamic resolution of `$PREFIX/etc/grok`, `$HOME/.grok`, `$TMPDIR` (<108-byte sockets), and strict quarantine refusing credentials on Android shared storage (`/sdcard`, `/storage/emulated/0`).
4. **Termux-Native Auth & UX**: OAuth via `termux-open-url` with loopback callback and manual code fallback, native Bionic DNS/TLS, Termux:API text clipboard with OSC 52 fallback, and truthful `policy-only` sandbox reporting.
5. **Distribution, Diagnostics & Upstream Maintenance**: Install mode isolation (package-managed vs standalone), `grok doctor` for Termux, automated ELF validation (`scripts/validate_elf.py`), and low-conflict upstream rebase/patch structure.

## Code Layout
- `.cargo/config.toml`: Target configurations for `aarch64-linux-android` and `x86_64-linux-android` with 16 KiB page size linker flags.
- `crates/codegen/xai-grok-config/`: Configuration paths (`$PREFIX/etc/grok`, `$HOME/.grok`, `$TMPDIR`).
- `crates/codegen/xai-grok-home/`: Storage boundary validation (rejection of `/sdcard` for credentials).
- `crates/codegen/xai-grok-shared/`: Clipboard seam (`termux-clipboard-*`, OSC 52 fallback, exclusion of `arboard` on Android).
- `crates/codegen/xai-grok-voice/`: Audio capability gating (exclusion of `cpal` on Android).
- `crates/codegen/xai-grok-sandbox/`: Truthful `policy-only` sandbox reporting and in-process path validation.
- `crates/codegen/xai-grok-pager-render/`: Link opening via `termux-open-url`.
- `crates/codegen/xai-grok-shell/`: OIDC login with loopback callback, manual code fallback, and Bionic DNS resolution.
- `crates/codegen/xai-grok-tools/`: Native CLI tool resolution (`rg`, `fd`, `git`, `bash`) from Termux `$PATH`.
- `crates/codegen/xai-grok-update/`: Install mode detection and updater isolation.
- `crates/codegen/xai-grok-pager/`: `grok doctor` diagnostics for Termux.
- `crates/codegen/xai-grok-pager-bin/`: Entry point with Bionic allocator (exclusion of `tikv-jemallocator` on Android).
- `scripts/validate_elf.py`: Automated ELF header, Bionic interpreter, and 16 KiB page-size alignment validator.
- `tests/e2e/`: Requirement-driven 4-tier E2E test suite.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Centralized Platform Capability Layer | Unified, injectable runtime struct (`PlatformCapabilities`) identifying OS kind, ABI, display presence, audio, and sandbox | M1 | survey (R1) |
| 2 | Dynamic `$PREFIX` Discovery | Dynamically resolves Termux root path; fails closed if unset/invalid on Android | M1 | survey (R1) |
| 3 | Allocator Gating (Bionic vs Jemalloc) | Uses Bionic's system memory allocator on Android; excludes `tikv-jemallocator` | M1 | survey (R1) |
| 4 | Desktop Clipboard Gating (`arboard`) | Excludes `arboard` from Android target dependencies; provides Termux clipboard backend | M1 | survey (R1) |
| 5 | Voice / Microphone Gating (`cpal`) | Excludes `cpal` and ALSA dependencies on Android; disables microphone UI cleanly | M1 | survey (R1) |
| 6 | Native Bionic Build Profile | Cross-compiles native Rust binaries targeting `aarch64-linux-android` (and `x86_64-linux-android`) | M2 | survey (R2) |
| 7 | 16 KiB ELF Page-Size Alignment | Ensures ELF load segments align to 16 KiB page boundary (`p_align >= 0x4000`) for Android 15+ compatibility | M2 | survey (R2) |
| 8 | Native CLI Tool Resolution | Disables auto-download of desktop Linux `rg`/`fd` binaries; resolves `rg`, `fd`, `git`, `bash` from `$PATH` | M2 | survey (R2) |
| 9 | Optional Search Tools Fallback | Handles presence/absence of `bfs` and `ugrep` without hard dependency | M2 | survey (R2) |
| 10 | System Configuration Resolution | Resolves system-wide configuration under `$PREFIX/etc/grok` | M3 | survey (R3) |
| 11 | User Home Directory Resolution | Resolves user configuration, state, and credentials under `$HOME/.grok` | M3 | survey (R3) |
| 12 | Runtime Temporary & Sockets | Uses `$TMPDIR` for ephemeral files and creates short Unix sockets (< 108 bytes) with stale cleanup | M3 | survey (R3) |
| 13 | Shared Storage Quarantine | Detects and strictly rejects placing `GROK_HOME`, credentials, or state on Android shared storage (`/sdcard`) | M3 | survey (R3) |
| 14 | Shared-Storage Workspace Protection | Allows editing code on `/sdcard` while keeping sessions, auth tokens, hooks, and caches in private storage | M3 | survey (R3) |
| 15 | Termux OAuth Browser Handoff | Dispatches OAuth URL via `termux-open-url` to launch system Android browser | M4 | survey (R4) |
| 16 | Loopback Callback Server | Listens on `127.0.0.1:<port>` to capture browser redirect with OAuth authorization code | M4 | survey (R4) |
| 17 | Manual Code / URL Paste Fallback | Accepts bare authorization code or full callback URL via stdin / TUI input modal | M4 | survey (R4) |
| 18 | Native Bionic DNS & TLS Resolution | Resolves domain names via Android Bionic libc `getaddrinfo`; TLS via rustls with native roots | M4 | survey (R4) |
| 19 | Termux:API Text Clipboard | Reads and writes text clipboard using `termux-clipboard-get` and `termux-clipboard-set` | M4 | survey (R4) |
| 20 | OSC 52 Terminal Clipboard Fallback | Writes ANSI OSC 52 escape sequences to terminal stream for terminal-native copying | M4 | survey (R4) |
| 21 | Unsupported Clipboard / Voice Graceful Degradation | Disables image/file clipboard and voice capture without crashing or presenting fake UI | M4 | survey (R4) |
| 22 | Truthful Sandbox Reporting | Classifies Android sandbox as `policy-only` in UI, doctor, and logs; denies kernel enforcement | M4 | survey (R4) |
| 23 | In-Process Policy Enforcement | Enforces file allow/deny paths, hook write protection, sensitive directory barriers (`~/.ssh`, `~/.grok`) | M4 | survey (R4) |
| 24 | Conservative Concurrency & Defaults | Uses conservative thread pools and subagent concurrency for mobile thermal/memory limits | M4 | survey (R4) |
| 25 | Termux Wake Lock Integration | Acquires optional Android wake lock via `termux-wake-lock` during active long-running tasks | M4 | survey (R4) |
| 26 | Durable Session Checkpoint & Recovery | Saves atomic transaction checkpoints so interrupted tasks can resume seamlessly after process kill | M4 | survey (R4) |
| 27 | Package-Managed Install Mode | Detects installation via `pkg` / `apt`; disables in-app binary self-update | M5 | survey (R5) |
| 28 | Standalone Install Mode & Updater Isolation | Standalone updater targets Android/Termux release channel only (`termux-aarch64`), rejecting Linux binaries | M5 | survey (R5) |
| 29 | `grok doctor` for Android/Termux | Comprehensive environment diagnostic check tailored for Termux (packages, prefix, page size, DNS, sandbox) | M5 | survey (R5) |
| 30 | CI Cross-Compilation & ELF Validator | Hosted CI pipeline compiling `aarch64-linux-android` and validating ELF headers (Bionic, 16K alignment) | M5 | survey (R5) |
| 31 | Real-Device / Emulator Test Matrix | Comprehensive test suite running on Android devices (4 KiB & 16 KiB pages, Wi-Fi, Termux:API) | M5 | survey (R5) |
| 32 | Low-Conflict Upstream Sync Strategy | Modular patch architecture keeping upstream tracking branch synchronized with minimal workspace conflicts | M5 | survey (R5) |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Platform Capability & Dependency Isolation | Features 1–5: PlatformCapabilities, dynamic $PREFIX, allocator gating, desktop clipboard gating, voice gating | none | DONE |
| M2 | Native Bionic Build & Toolchain Alignment | Features 6–9: .cargo/config.toml, 16 KiB ELF alignment, build.rs tool download bypass, native CLI tool resolution | M1 | DONE |
| M3 | Filesystem Safety & Storage Boundaries | Features 10–14: $PREFIX/etc/grok, $HOME/.grok, $TMPDIR sockets, /sdcard quarantine & workspace protection | M1 | DONE |
| M4 | Termux Auth, UX & Truthful Sandboxing | Features 15–26: termux-open-url, loopback & manual code auth, Bionic DNS, Termux:API + OSC 52, policy-only sandbox, wake lock | M1, M2, M3 | DONE |
| M5 | Distribution, Diagnostics & Upstream Sync | Features 27–32: Install modes, updater isolation, grok doctor, ELF validator, upstream sync workflow | M1, M2, M3, M4 | DONE |
| M_E2E | E2E Testing Suite Track | Design & implement 4-Tier test suite (Tiers 1–4) independently, publishing TEST_READY.md | none (parallel) | DONE |
| M_FINAL | Final Verification & Hardening | Phase 1: Pass 100% of E2E test suite (Tiers 1–4). Phase 2: Tier 5 Adversarial Coverage Hardening. Forensic Audit. | M1–M5, M_E2E | DONE |

## Interface Contracts
### `PlatformCapabilities` (in `xai-grok-config` / `xai-grok-platform`)
- `fn current() -> &'static PlatformCapabilities`
- `fn is_android_termux(&self) -> bool`
- `fn prefix_dir(&self) -> Result<&Path, PlatformError>`
- `fn system_config_dir(&self) -> Option<PathBuf>` -> `$PREFIX/etc/grok` on Termux, `/etc/grok` on desktop Linux
- `fn home_dir(&self) -> Result<PathBuf, PlatformError>` -> `$HOME/.grok`
- `fn temp_dir(&self) -> PathBuf` -> `$TMPDIR` or `$PREFIX/tmp`
- `fn sandbox_kind(&self) -> SandboxKind` -> `SandboxKind::PolicyOnly` on Android
- `fn validate_storage_safety(path: &Path) -> Result<(), StorageSafetyError>` -> Refuses `/sdcard`, `/storage/emulated/0`, `/mnt/sdcard` for private credentials

### `Clipboard` (in `xai-grok-shared`)
- `fn get_text() -> Result<Option<String>, ClipboardError>` -> Tries `termux-clipboard-get`, falls back gracefully
- `fn set_text(text: &str) -> Result<(), ClipboardError>` -> Tries `termux-clipboard-set`, falls back to ANSI OSC 52 sequence

### `LinkOpener` (in `xai-grok-pager-render` / `xai-grok-shell`)
- `fn open_url(url: &str) -> Result<(), LinkOpenerError>` -> Uses `termux-open-url` on Termux, falls back to manual URL print

### `ToolResolver` (in `xai-grok-tools` / `xai-grok-shell`)
- `fn resolve_tool(name: &str) -> Result<PathBuf, ToolResolutionError>` -> Resolves from `$PATH` (`$PREFIX/bin`), hints `pkg install <name>` on missing
