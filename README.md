<div align="center">

<h1>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://media.x.ai/v1/website/spacexai-symbol-white-transparent-0c31957f.png">
    <source media="(prefers-color-scheme: light)" srcset="https://media.x.ai/v1/website/spacexai-symbol-black-transparent-6435cf42.png">
    <img alt="SpaceXAI logo" src="https://media.x.ai/v1/website/spacexai-symbol-black-transparent-6435cf42.png" width="96">
  </picture>
  <br>
  Grok Build for Android / Termux (<code>grok</code>)
</h1>

[![Termux Port CI](https://github.com/ImL1s/grok-build-termux/actions/workflows/ci.yml/badge.svg)](https://github.com/ImL1s/grok-build-termux/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Platform: Android Termux](https://img.shields.io/badge/platform-Android%20%7C%20Termux-brightgreen.svg)](#architecture--bionic-runtime)
[![Page Size: 16 KiB Ready](https://img.shields.io/badge/page_size-16_KiB_aligned-orange.svg)](#16-kib-page-size-alignment)

**Grok Build for Android / Termux** is an unofficial native port of SpaceXAI's terminal-based AI coding agent (`grok`), engineered specifically for Android Bionic libc and modern 16 KiB page-size kernels.

[Installation](#installation) ·
[Quick Start & Auth](#quick-start--authentication) ·
[Architecture & Bionic Runtime](#architecture--bionic-runtime) ·
[Capability Matrix](#capability-differences--platform-matrix) ·
[Diagnostics](#diagnostics--troubleshooting) ·
[Building from Source](#building-from-source) ·
[Upstream Sync Policy](#upstream-sync-policy) ·
[License](#license)

</div>

---

> [!IMPORTANT]
> **Unofficial Community Port**: This repository is a native Android/Termux port tracking upstream [`xai-org/grok-build`](https://github.com/xai-org/grok-build). It is not officially endorsed or supported by xAI.

---

## Installation

### Method 1: Termux Package Manager (Recommended)

Install `grok-build` and essential runtime dependencies directly inside Termux:

```sh
# 1. Update package lists
pkg update -y

# 2. Install required CLI tools & Termux:API helpers
pkg install -y git ripgrep fd bash termux-api

# 3. Install Grok Build (when available in Termux APT repositories)
pkg install -y grok-build
```

> [!TIP]
> Make sure the **Termux:API** companion application is installed on your Android device (available on F-Droid or GitHub Releases) to enable native clipboard integration and URL browser dispatch.

### Method 2: Prebuilt Binary (GitHub Releases)

Download the native `aarch64-linux-android` release binary directly:

```sh
# Download latest release binary
curl -fsSL -o "$PREFIX/bin/grok" \
  https://github.com/ImL1s/grok-build-termux/releases/latest/download/xai-grok-pager-aarch64-linux-android

# Grant executable permissions
chmod +x "$PREFIX/bin/grok"

# Verify installation
grok --version
```

---

## Quick Start & Authentication

1. **Launch Grok Build**:
   ```sh
   grok
   ```

2. **Authenticate with xAI**:
   - On first launch, Grok Build automatically triggers `termux-open-url` to open your default Android web browser for OAuth login.
   - After authorizing, the browser redirects back to the local loopback server (`http://127.0.0.1:<port>/oauth/callback`).
   - **Manual Fallback**: If the browser redirect does not complete automatically, copy the authorization code or full callback URL from your browser address bar and paste it into the terminal prompt.

3. **Verify Environment with `grok doctor`**:
   ```sh
   grok doctor
   ```

---

## Architecture & Bionic Runtime

The Android/Termux port is engineered for native performance, zero glibc/proot overhead, and full hardware compatibility.

### 1. Native Bionic Dynamic Linker
Unlike desktop Linux ports that require glibc emulation or `proot`, `grok-build-termux` links directly against Android Bionic libc (`/system/bin/linker64` on 64-bit ARM).

### 2. 16 KiB Page-Size Alignment (Android 15+ Compatibility)
Android 15 introduces support for 16 KiB memory page sizes on flagship devices (e.g., Google Pixel 8/9, Samsung Galaxy S24). Legacy 4 KiB ELF binaries fail to execute or crash on 16 KiB kernels.

All release binaries in this repository are compiled with:
```toml
rustflags = [
    "-C", "link-arg=-Wl,-z,relro,-z,now,-z,noexecstack",
    "-C", "link-arg=-Wl,-z,max-page-size=16384",
]
```
Ensuring all `PT_LOAD` segments satisfy `p_align >= 0x4000` and ELF congruence (`p_vaddr % p_align == p_offset % p_align`).

You can independently verify ELF compliance using the bundled validator:
```sh
python3 scripts/validate_elf.py "$PREFIX/bin/grok"
```

### 3. Dynamic `$PREFIX` & Storage Quarantine
- **Dynamic Configuration**: Resolves system configurations under `$PREFIX/etc/grok` and user configurations under `$HOME/.grok`.
- **Shared Storage Quarantine**: Strictly prevents placing `GROK_HOME`, session state, or credentials on Android shared storage (`/sdcard`, `/storage/emulated/0`) because FAT/FUSE filesystems do not enforce POSIX file permissions (`0700`).
- **Safe Workspace Mode**: Editing project code residing on `/sdcard` is supported while keeping security credentials isolated in private app storage.

---

## Capability Differences & Platform Matrix

| Subsystem | Desktop (macOS / Linux) | Termux / Android Port | Details |
|---|---|---|---|
| **Text Clipboard** | `arboard` / `pbcopy` | `termux-clipboard` & ANSI OSC 52 | Primary clipboard via `termux-clipboard-*`; falls back to terminal OSC 52 escape sequences. |
| **Image Clipboard** | System pasteboard | Gracefully disabled | Image paste is disabled in mobile TUI without crashing. |
| **Sandbox Kind** | Kernel-enforced (Landlock / Seatbelt) | `policy-only` | Truthfully reports `policy-only` in `grok doctor`. Enforces file boundaries in-process. |
| **Voice / Dictation**| `cpal` / ALSA / CoreAudio | Gated off | ALSA/cpal dependencies excluded on Android to prevent build and runtime crashes. |
| **Browser Handoff** | `xdg-open` / `open` | `termux-open-url` | Dispatches system Android browser for OAuth and external documentation. |
| **CLI Search Tools** | Auto-downloaded binaries | Native `$PATH` resolution | Uses Termux `ripgrep` (`rg`), `fd`, `git`, and `bash` from `$PREFIX/bin`. |
| **Self-Updater** | In-app binary update | Package-aware isolation | Package installs delegate updates to `pkg upgrade grok-build`; standalone installs use isolated channels. |
| **Wake Lock** | N/A | `termux-wake-lock` | Optionally acquires Android wake lock during long-running background agent tasks. |

---

## Diagnostics & Troubleshooting

Run built-in diagnostics to check your Termux environment:

```sh
# Human-readable diagnostic overview
grok doctor

# Machine-readable JSON output for automated diagnostics
grok doctor --json
```

### Common Issues & Remedies

| Issue | Cause | Resolution |
|---|---|---|
| `Required tool 'rg' not found` | Missing ripgrep | Run `pkg install ripgrep` |
| `Required tool 'fd' not found` | Missing fd | Run `pkg install fd` |
| `Clipboard unavailable` | Missing Termux:API package or app | Run `pkg install termux-api` and install Termux:API APK from F-Droid |
| `Storage safety quarantine error` | `$HOME` or `GROK_HOME` set to `/sdcard` | Set `GROK_HOME` inside Termux internal storage (`/data/data/com.termux/files/home/.grok`) |
| `OAuth browser handoff failed` | `termux-open-url` failed or blocked | Paste the manual authorization code or callback URL into the terminal prompt |

---

## Building from Source

### Option A: Cross-Compiling from Host (macOS / Linux)

#### Prerequisites

1. **Rust Toolchain**: Pinned in `rust-toolchain.toml` (or latest stable Rust):
   ```sh
   rustup target add aarch64-linux-android x86_64-linux-android
   ```
2. **Android NDK**: NDK r28b or newer (API level 24+ recommended).
   - **macOS**: Install via Android Studio SDK Manager (`$HOME/Library/Android/sdk/ndk/28.*`) or Homebrew (`brew install --cask android-ndk`).
   - **Linux**: Download from [Android NDK Downloads](https://developer.android.com/ndk/downloads) or install via SDK manager (`sdkmanager "ndk;28.1.13356709"`).
3. **Protocol Buffers Compiler (`protoc`)**: Required by `xai-grok-tools-api` code generation.
   - **macOS (Homebrew)**:
     ```sh
     brew install protobuf
     ```
   - **Ubuntu / Debian**:
     ```sh
     sudo apt-get update && sudo apt-get install -y protobuf-compiler
     ```
   - **Arch Linux**:
     ```sh
     sudo pacman -S protobuf
     ```
   - **Fedora / RHEL**:
     ```sh
     sudo dnf install -y protobuf-compiler
     ```
   - *Custom protoc location*: Set `export PROTOC=/path/to/bin/protoc`.
4. **Python 3.10+**: Required for `scripts/validate_elf.py` ELF alignment validation.

---

#### Method 1: Automated Cross-Compilation (Recommended)

Use the built-in helper script `scripts/build_android.sh` to automatically detect host NDK paths, configure target linkers, compile release binaries, strip debug symbols, and validate 16 KiB ELF alignment:

```sh
# Ensure helper script is executable
chmod +x scripts/build_android.sh

# Build aarch64 release binary (default target, API 24)
./scripts/build_android.sh --arch aarch64

# Build x86_64 release binary (for Android emulators / x86_64 devices)
./scripts/build_android.sh --arch x86_64

# Build both architectures in a single run
./scripts/build_android.sh --arch all
```

**CLI Flags for `scripts/build_android.sh`**:
- `--arch <aarch64|x86_64|all>`: Target architecture (default: `aarch64`).
- `--api <24..35>`: Android API level (default: `24`).
- `--check`: Run `cargo check` only instead of full release compilation.
- `--no-strip`: Skip symbol stripping (retains unstripped debug symbols).
- `--no-validate`: Skip `scripts/validate_elf.py` post-build ELF verification.
- `--ndk <PATH>`: Explicit path to Android NDK root.
- `-v, --verbose`: Enable verbose diagnostic output.
- `-h, --help`: Display help and options.

---

#### Method 2: Manual Cross-Compilation

If you prefer to configure your environment manually or integrate with custom build pipelines:

1. **Configure NDK Toolchain Path**:
   Set `ANDROID_NDK_HOME` and export the LLVM prebuilt binary directory to your `$PATH`:

   - **On macOS (Darwin)**:
     ```sh
     export ANDROID_NDK_HOME="${ANDROID_NDK_HOME:-$HOME/Library/Android/sdk/ndk/28.2.13676358}"
     export PATH="${ANDROID_NDK_HOME}/toolchains/llvm/prebuilt/darwin-x86_64/bin:$PATH"
     ```

   - **On Linux (x86_64)**:
     ```sh
     export ANDROID_NDK_HOME="${ANDROID_NDK_HOME:-/opt/android-ndk}"
     export PATH="${ANDROID_NDK_HOME}/toolchains/llvm/prebuilt/linux-x86_64/bin:$PATH"
     ```

2. **Set Target Compilers & Linkers (API Level 24+)**:

   - **For ARM64 (`aarch64-linux-android`)**:
     ```sh
     export CC_aarch64_linux_android="aarch64-linux-android24-clang"
     export CXX_aarch64_linux_android="aarch64-linux-android24-clang++"
     export AR_aarch64_linux_android="llvm-ar"
     export CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER="aarch64-linux-android24-clang"
     ```

   - **For x86_64 (`x86_64-linux-android`)**:
     ```sh
     export CC_x86_64_linux_android="x86_64-linux-android24-clang"
     export CXX_x86_64_linux_android="x86_64-linux-android24-clang++"
     export AR_x86_64_linux_android="llvm-ar"
     export CARGO_TARGET_X86_64_LINUX_ANDROID_LINKER="x86_64-linux-android24-clang"
     ```

3. **Compile Release Binary**:
   ```sh
   # Build aarch64 binary
   cargo build --target aarch64-linux-android -p xai-grok-pager-bin --release

   # Build x86_64 binary
   cargo build --target x86_64-linux-android -p xai-grok-pager-bin --release
   ```

4. **Strip Symbols**:
   ```sh
   # Strip aarch64 binary
   llvm-strip target/aarch64-linux-android/release/xai-grok-pager

   # Strip x86_64 binary
   llvm-strip target/x86_64-linux-android/release/xai-grok-pager
   ```

5. **Validate 16 KiB Page Alignment & Bionic Dynamic Linker**:
   ```sh
   # Validate aarch64 binary
   python3 scripts/validate_elf.py target/aarch64-linux-android/release/xai-grok-pager \
     --target-arch aarch64 --strict-16k --bionic-only

   # Validate x86_64 binary
   python3 scripts/validate_elf.py target/x86_64-linux-android/release/xai-grok-pager \
     --target-arch x86_64 --strict-16k --bionic-only
   ```

### Option B: Compiling Directly Inside Termux

```sh
# 1. Install build toolchain
pkg install -y rust clang binutils-is-llvm protobuf make git

# 2. Clone repository
git clone https://github.com/ImL1s/grok-build-termux.git
cd grok-build-termux

# 3. Build release binary
cargo build -p xai-grok-pager-bin --release

# 4. Install binary to Termux bin
cp target/release/xai-grok-pager "$PREFIX/bin/grok"
```

---

## Upstream Sync Policy

This repository actively tracks the upstream [`xai-org/grok-build`](https://github.com/xai-org/grok-build) monorepo.

- **Source Tracking**: The `SOURCE_REV` file at the repository root contains the exact upstream monorepo commit SHA (`e6a67a5408288c98380cd13f3b1fe1fbc01c9f1f`).
- **Low-Conflict Patch Architecture**: Downstream modifications are organized in isolated modular layers (`crates/codegen/xai-grok-config`, `xai-grok-shared`, `xai-grok-sandbox`, `xai-grok-tools`, `xai-grok-update`) to minimize merge conflicts during upstream rebases.
- **Sync Workflow**: Periodic upstream snapshots are synchronized to a dedicated tracking branch and merged into `termux-native` via reviewable Pull Requests.

---

## Testing & Quality Assurance

The port is verified by a 5-tier test suite covering all 32 inventoried features:

```sh
# Run full E2E test suite (459 tests)
python3 tests/e2e/runner.py --tier all && python3 tests/e2e/runner.py --tier tier5

# Run ELF alignment self-tests
python3 scripts/validate_elf.py --self-test
```

See [`TEST_READY.md`](TEST_READY.md) and [`PROJECT.md`](PROJECT.md) for full architectural specifications and verification matrices.

---

## License

This project is licensed under the **Apache License, Version 2.0** — see [`LICENSE`](LICENSE).

Third-party and upstream vendored notices are preserved in [`THIRD-PARTY-NOTICES`](THIRD-PARTY-NOTICES) and [`crates/codegen/xai-grok-tools/THIRD_PARTY_NOTICES.md`](crates/codegen/xai-grok-tools/THIRD_PARTY_NOTICES.md).
