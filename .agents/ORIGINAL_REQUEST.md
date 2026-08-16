# Original User Request

## Initial Request — 2026-08-15T15:28:58Z

Build a first-class, unofficial native Android/Termux port of Grok Build (`xai-org/grok-build` tracking baseline `eb267feff13129e568df38fb6fdf0ceb65f735d6`) targeting `aarch64-linux-android` with Bionic libc, clean platform capability gating, isolated updater/packaging, and low-conflict upstream synchronization.

Working directory: /Users/iml1s/Documents/mine/grok-build-termux
Integrity mode: development

## Requirements

### R1. Platform Capability & Dependency Isolation
Establish a centralized, injectable source of truth for Android/Termux platform detection and capability probing (identifying dynamic `$PREFIX`, lack of display server, audio capabilities, and hard sandbox constraints). Gate desktop-only dependencies (`jemalloc`, `arboard`, `cpal`, kernel sandbox) out of Android targets, using Bionic's allocator and graceful fallbacks.

### R2. Native Bionic Build & Toolchain
Configure reproducible `aarch64-linux-android` (and optional `x86_64-linux-android`) build profiles using Android NDK and Bionic libc, ensuring 16 KiB ELF page-size alignment without binary byte patches, glibc loaders, or PRoot requirements. Resolve native CLI tools (`git`, `rg`, `fd`, `bash`) directly from Termux `$PATH`.

### R3. Filesystem Safety & Storage Boundaries
Ensure configuration, credentials, sockets, and cache directories resolve to Termux-owned private paths (`$PREFIX/etc/grok`, `$HOME/.grok`, `$TMPDIR`). Strictly reject housing `GROK_HOME` or credentials on Android shared storage (`/sdcard`, `/storage/emulated/0`) to preserve owner-only permissions.

### R4. Termux-Native Auth, UX & Truthful Sandboxing
Route OAuth browser verification via `termux-open-url` with loopback callback and manual code fallback, using native Bionic DNS/TLS resolution. Integrate Termux:API text clipboard with OSC 52 fallback. Truthfully report sandbox status as `policy-only` rather than kernel-enforced.

### R5. Distribution, Diagnostics & Upstream Synchronization
Implement distinct install modes (package-managed vs standalone) to prevent auto-updating into upstream Linux binaries. Provide `grok doctor` diagnostics for Termux environments, CI cross-compilation/ELF validation, a real-device test matrix, and a low-conflict patch/rebase strategy against upstream `xai-org/grok-build`.

## Acceptance Criteria

### Build & Toolchain Integrity
- [ ] `cargo check` / `cargo build` for `aarch64-linux-android` succeeds without glibc, `jemalloc`, `cpal`, or `arboard` in the dependency tree.
- [ ] ELF binary header validation confirms Bionic loader compatibility and 16 KiB page-size alignment.
- [ ] Runtime smoke tests pass (`--version`, `--help`, and headless execution).

### Filesystem & Security Boundaries
- [ ] System config resolves to `$PREFIX/etc/grok` and user state resolves to `$HOME/.grok`.
- [ ] Credential/token writes to Android shared storage are refused with explicit error messages.
- [ ] `grok doctor` and security reporting truthfully identify the sandbox as `policy-only` (or degraded) on Android.

### Authentication & UX Integration
- [ ] OAuth flow initiates via `termux-open-url` or falls back gracefully to manual code entry without DNS/network panics.
- [ ] Text clipboard read/write works when Termux:API is present, and degrades gracefully to OSC 52 or manual paste when absent.

### Synchronization & Upstream Maintenance
- [ ] Downstream patches apply cleanly on top of `xai-org/grok-build@eb267feff13129e568df38fb6fdf0ceb65f735d6`.
- [ ] Workspace manifest modifications are minimized to avoid recurring merge conflicts with upstream generated manifests.
