#!/usr/bin/env bash
# ==============================================================================
# scripts/build_android.sh — Android / Termux Host Cross-Compilation Helper
# ==============================================================================
# Builds native Android Bionic release binaries with 16 KiB page-size alignment,
# symbol stripping, and automated ELF validation for grok-build-termux.
#
# Supported Host Platforms: macOS (Darwin x86_64/arm64), Linux (x86_64)
# Supported Targets: aarch64-linux-android, x86_64-linux-android
# ==============================================================================

set -euo pipefail

# ------------------------------------------------------------------------------
# Colors and Logging
# ------------------------------------------------------------------------------
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    COLOR_RESET="\033[0m"
    COLOR_BOLD="\033[1m"
    COLOR_RED="\033[0;31m"
    COLOR_GREEN="\033[0;32m"
    COLOR_YELLOW="\033[0;33m"
    COLOR_BLUE="\033[0;34m"
    COLOR_CYAN="\033[0;36m"
else
    COLOR_RESET=""
    COLOR_BOLD=""
    COLOR_RED=""
    COLOR_GREEN=""
    COLOR_YELLOW=""
    COLOR_BLUE=""
    COLOR_CYAN=""
fi

log_info() {
    printf "${COLOR_BLUE}[INFO]${COLOR_RESET} %s\n" "$*"
}

log_success() {
    printf "${COLOR_GREEN}[SUCCESS]${COLOR_RESET} %s\n" "$*"
}

log_warn() {
    printf "${COLOR_YELLOW}[WARN]${COLOR_RESET} %s\n" "$*" >&2
}

log_error() {
    printf "${COLOR_RED}[ERROR]${COLOR_RESET} %s\n" "$*" >&2
}

log_step() {
    printf "${COLOR_BOLD}${COLOR_CYAN}==>${COLOR_RESET} ${COLOR_BOLD}%s${COLOR_RESET}\n" "$*"
}

# ------------------------------------------------------------------------------
# Script Root & Defaults
# ------------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

ARCH="aarch64"
API_LEVEL="24"
CHECK_ONLY=false
DO_STRIP=true
DO_VALIDATE=true
EXPLICIT_NDK=""
VERBOSE=false

# ------------------------------------------------------------------------------
# Help Text
# ------------------------------------------------------------------------------
show_help() {
    cat <<EOF
${COLOR_BOLD}Usage:${COLOR_RESET} $(basename "$0") [OPTIONS]

Cross-compile grok-build-termux binaries for Android/Termux with 16 KiB ELF alignment.

${COLOR_BOLD}Options:${COLOR_RESET}
  --arch <ARCH>      Target architecture: 'aarch64', 'x86_64', or 'all'
                     (default: aarch64)
  --api <LEVEL>      Android API level between 24 and 35
                     (default: 24, Android 7.0 Nougat)
  --check            Run 'cargo check' instead of full release compilation
                     (skips stripping and ELF validation)
  --no-strip         Skip symbol stripping with llvm-strip
  --no-validate      Skip post-build ELF compliance validation
  --ndk <PATH>       Explicit path to Android NDK installation directory
  -v, --verbose      Enable verbose diagnostic output
  -h, --help         Display this help message and exit

${COLOR_BOLD}Environment Variables:${COLOR_RESET}
  ANDROID_NDK_HOME   Path to Android NDK installation directory
  ANDROID_NDK_ROOT   Alternative NDK root path
  PROTOC             Path to custom protoc binary
  NO_COLOR           Disable colored terminal output if set

${COLOR_BOLD}Examples:${COLOR_RESET}
  ./scripts/build_android.sh
  ./scripts/build_android.sh --arch all
  ./scripts/build_android.sh --arch x86_64 --api 28
  ./scripts/build_android.sh --check
  ./scripts/build_android.sh --arch aarch64 --no-strip
  ./scripts/build_android.sh --ndk /opt/android-ndk-r28b

${COLOR_BOLD}Exit Codes:${COLOR_RESET}
  0  Success
  1  Build, strip, or ELF validation failure
  2  Invalid CLI argument or option
  3  Missing prerequisite tools or Android NDK
EOF
}

# ------------------------------------------------------------------------------
# CLI Argument Parsing
# ------------------------------------------------------------------------------
parse_args() {
    while [ $# -gt 0 ]; do
        case "$1" in
            --arch)
                if [ -z "${2:-}" ]; then
                    log_error "Option '--arch' requires an argument (<aarch64|x86_64|all>)."
                    exit 2
                fi
                ARCH="$2"
                shift 2
                ;;
            --api)
                if [ -z "${2:-}" ]; then
                    log_error "Option '--api' requires an API level (24..35)."
                    exit 2
                fi
                API_LEVEL="$2"
                shift 2
                ;;
            --check)
                CHECK_ONLY=true
                shift
                ;;
            --no-strip)
                DO_STRIP=false
                shift
                ;;
            --no-validate)
                DO_VALIDATE=false
                shift
                ;;
            --ndk)
                if [ -z "${2:-}" ]; then
                    log_error "Option '--ndk' requires a directory path."
                    exit 2
                fi
                EXPLICIT_NDK="$2"
                shift 2
                ;;
            -v|--verbose)
                VERBOSE=true
                shift
                ;;
            -h|--help)
                show_help
                exit 0
                ;;
            -*)
                log_error "Unrecognized option: '$1'"
                printf "Run '%s --help' for usage information.\n" "$(basename "$0")" >&2
                exit 2
                ;;
            *)
                log_error "Unexpected positional argument: '$1'"
                printf "Run '%s --help' for usage information.\n" "$(basename "$0")" >&2
                exit 2
                ;;
        esac
    done

    # Validate --arch
    case "$ARCH" in
        aarch64|x86_64|all)
            ;;
        *)
            log_error "Invalid architecture: '$ARCH'. Must be one of 'aarch64', 'x86_64', or 'all'."
            exit 2
            ;;
    esac

    # Validate --api
    if ! [[ "$API_LEVEL" =~ ^[0-9]+$ ]]; then
        log_error "Invalid API level '$API_LEVEL': must be an integer between 24 and 35."
        exit 2
    fi
    if [ "$API_LEVEL" -lt 24 ] || [ "$API_LEVEL" -gt 35 ]; then
        log_error "API level '$API_LEVEL' out of range (24..35). Android 7.0 (API 24) is the minimum required version for grok-build-termux."
        exit 2
    fi
}

# ------------------------------------------------------------------------------
# Host Platform & Tool Detection
# ------------------------------------------------------------------------------
detect_host_tag() {
    local os
    os="$(uname -s)"
    case "$os" in
        Darwin)
            HOST_TAG="darwin-x86_64"
            ;;
        Linux)
            local arch_m
            arch_m="$(uname -m)"
            if [[ ("$arch_m" == "aarch64" || "$arch_m" == "arm64") ]]; then
                HOST_TAG="linux-aarch64"
            else
                HOST_TAG="linux-x86_64"
            fi
            ;;
        *)
            log_error "Unsupported host operating system: '$os'. Only macOS (Darwin) and Linux are supported."
            exit 3
            ;;
    esac
}

detect_ndk() {
    log_step "Detecting Android NDK..."

    # 1. Explicit NDK path via --ndk flag
    if [ -n "$EXPLICIT_NDK" ]; then
        if [ -d "$EXPLICIT_NDK" ] && [ -d "$EXPLICIT_NDK/toolchains/llvm/prebuilt/$HOST_TAG/bin" ]; then
            NDK_PATH="$EXPLICIT_NDK"
            NDK_BIN="$NDK_PATH/toolchains/llvm/prebuilt/$HOST_TAG/bin"
            log_info "Using explicitly specified Android NDK: $NDK_PATH"
            log_info "Toolchain bin: $NDK_BIN"
            return 0
        fi
        log_error "Specified NDK path '$EXPLICIT_NDK' does not contain a valid LLVM toolchain at:"
        log_error "  $EXPLICIT_NDK/toolchains/llvm/prebuilt/$HOST_TAG/bin"
        exit 3
    fi

    # 2. Environment variable candidates
    local env_candidates=()
    [ -n "${ANDROID_NDK_HOME:-}" ] && env_candidates+=("$ANDROID_NDK_HOME")
    [ -n "${ANDROID_NDK_ROOT:-}" ] && env_candidates+=("$ANDROID_NDK_ROOT")
    [ -n "${ANDROID_NDK:-}" ] && env_candidates+=("$ANDROID_NDK")
    [ -n "${NDK_HOME:-}" ] && env_candidates+=("$NDK_HOME")

    if [ ${#env_candidates[@]} -gt 0 ]; then
        for cand in "${env_candidates[@]}"; do
            if [ -d "$cand" ] && [ -d "$cand/toolchains/llvm/prebuilt/$HOST_TAG/bin" ]; then
                NDK_PATH="$cand"
                NDK_BIN="$NDK_PATH/toolchains/llvm/prebuilt/$HOST_TAG/bin"
                log_info "Using Android NDK from environment: $NDK_PATH"
                log_info "Toolchain bin: $NDK_BIN"
                return 0
            fi
        done
    fi

    # 3. Standard search paths across macOS and Linux
    local candidates=()
    if [ -n "${ANDROID_HOME:-}" ] && [ -d "${ANDROID_HOME}/ndk" ]; then
        for d in "${ANDROID_HOME}/ndk"/*; do [ -d "$d" ] && candidates+=("$d"); done
    fi
    if [ -n "${ANDROID_SDK_ROOT:-}" ] && [ -d "${ANDROID_SDK_ROOT}/ndk" ]; then
        for d in "${ANDROID_SDK_ROOT}/ndk"/*; do [ -d "$d" ] && candidates+=("$d"); done
    fi

    # Standard SDK NDK dirs
    for d in "${HOME}/Library/Android/sdk/ndk"/* \
             "/Library/Android/sdk/ndk"/* \
             "${HOME}/Android/Sdk/ndk"/* \
             "/opt/android-sdk/ndk"/* \
             "/opt/android-ndk"* \
             "/opt/homebrew/share/android-ndk"* \
             "/opt/homebrew/Caskroom/android-ndk"/* \
             "/usr/local/share/android-ndk"* \
             "/usr/local/Caskroom/android-ndk"/* \
             "/usr/lib/android-ndk"*; do
        [ -d "$d" ] && candidates+=("$d")
    done

    local valid_records=()
    if [ ${#candidates[@]} -gt 0 ]; then
        for dir in "${candidates[@]}"; do
            if [ -d "$dir/toolchains/llvm/prebuilt/$HOST_TAG/bin" ]; then
                local rev="0"
                if [ -f "$dir/source.properties" ]; then
                    rev=$(grep "^Pkg.Revision" "$dir/source.properties" 2>/dev/null | cut -d= -f2 | tr -d " \r\n" || echo "0")
                fi
                valid_records+=("${rev}|${dir}")
            fi
        done
    fi

    if [ ${#valid_records[@]} -eq 0 ]; then
        log_error "Android NDK not found in standard locations!"
        printf "\nPlease set ANDROID_NDK_HOME or pass --ndk <path> to specify your NDK installation.\n" >&2
        printf "Searched paths included:\n" >&2
        printf "  - \$ANDROID_NDK_HOME / \$ANDROID_NDK_ROOT\n" >&2
        printf "  - \$HOME/Library/Android/sdk/ndk/* (macOS default)\n" >&2
        printf "  - \$HOME/Android/Sdk/ndk/* (Linux default)\n" >&2
        printf "  - /opt/android-ndk*\n" >&2
        printf "\nTo install Android NDK:\n" >&2
        printf "  macOS: brew install --cask android-ndk  OR via Android Studio SDK Manager\n" >&2
        printf "  Linux: sdkmanager \"ndk;28.1.13356709\" OR https://github.com/android/ndk/releases\n" >&2
        exit 3
    fi

    # Sort descending by revision and select the highest version (e.g. r28b+)
    local best_entry
    best_entry=$(printf "%s\n" "${valid_records[@]}" | sort -u | sort -t"|" -k1,1Vr 2>/dev/null | head -n1 || printf "%s\n" "${valid_records[@]}" | head -n1)
    NDK_PATH=$(echo "$best_entry" | cut -d"|" -f2)
    NDK_BIN="$NDK_PATH/toolchains/llvm/prebuilt/$HOST_TAG/bin"

    log_info "Auto-detected Android NDK: $NDK_PATH"
    log_info "Toolchain bin: $NDK_BIN"
}

check_prerequisites() {
    log_step "Checking prerequisites..."

    # Check cargo and rustup
    if ! command -v cargo >/dev/null 2>&1; then
        log_error "'cargo' command not found. Please install Rust via https://rustup.rs"
        exit 3
    fi
    if ! command -v rustup >/dev/null 2>&1; then
        log_error "'rustup' command not found. Please install Rustup via https://rustup.rs"
        exit 3
    fi

    # Check protoc
    local protoc_found=false
    if [ -n "${PROTOC:-}" ] && [ -x "$PROTOC" ]; then
        log_info "Using custom PROTOC: $PROTOC"
        protoc_found=true
    elif command -v protoc >/dev/null 2>&1 && protoc --version >/dev/null 2>&1; then
        log_info "Found system protoc: $(protoc --version 2>&1)"
        protoc_found=true
    elif [ -x "$ROOT_DIR/bin/protoc" ] && "$ROOT_DIR/bin/protoc" --version >/dev/null 2>&1; then
        log_info "Found workspace protoc: $ROOT_DIR/bin/protoc"
        protoc_found=true
    fi

    if [ "$protoc_found" = false ]; then
        log_error "'protoc' (Protocol Buffer Compiler) is required for building xai-grok-pager-bin."
        printf "Please install protobuf compiler:\n" >&2
        printf "  macOS:          brew install protobuf\n" >&2
        printf "  Ubuntu/Debian:  sudo apt-get update && sudo apt-get install -y protobuf-compiler\n" >&2
        printf "  Arch Linux:     sudo pacman -S protobuf\n" >&2
        printf "  Fedora:         sudo dnf install -y protobuf-compiler\n" >&2
        printf "  Custom:         export PROTOC=/path/to/bin/protoc\n" >&2
        exit 3
    fi

    # Check llvm-strip if stripping enabled
    if [ "$CHECK_ONLY" = false ] && [ "$DO_STRIP" = true ]; then
        if [ -x "$NDK_BIN/llvm-strip" ]; then
            LLVM_STRIP="$NDK_BIN/llvm-strip"
        elif command -v llvm-strip >/dev/null 2>&1; then
            LLVM_STRIP="$(command -v llvm-strip)"
        else
            log_warn "llvm-strip not found in NDK toolchain or PATH. Stripping will be skipped."
            DO_STRIP=false
        fi
    fi

    # Check python3 for validation
    if [ "$CHECK_ONLY" = false ] && [ "$DO_VALIDATE" = true ]; then
        if ! command -v python3 >/dev/null 2>&1; then
            log_warn "python3 not found. ELF validation will be skipped. Install python3 or use --no-validate."
            DO_VALIDATE=false
        elif [ ! -f "$ROOT_DIR/scripts/validate_elf.py" ]; then
            log_warn "Validator script not found at '$ROOT_DIR/scripts/validate_elf.py'. ELF validation will be skipped."
            DO_VALIDATE=false
        fi
    fi
}

# ------------------------------------------------------------------------------
# Target Setup & Compilation
# ------------------------------------------------------------------------------
ensure_rust_target() {
    local target="$1"
    local installed
    installed="$(rustup target list --installed 2>/dev/null || true)"
    if ! echo "$installed" | grep -q "^${target}$"; then
        log_info "Rust target '${target}' is not installed. Installing via rustup..."
        rustup target add "${target}" || {
            log_error "Failed to install rust target '${target}' via rustup."
            exit 1
        }
    fi
}

build_single_target() {
    local target_arch="$1" # aarch64 or x86_64
    local target_triple="${target_arch}-linux-android"

    log_step "Preparing build for target: ${target_triple} (API ${API_LEVEL})"

    ensure_rust_target "$target_triple"

    # Verify Clang compiler wrapper exists in NDK
    local clang_cc="$NDK_BIN/${target_arch}-linux-android${API_LEVEL}-clang"
    local clang_cxx="$NDK_BIN/${target_arch}-linux-android${API_LEVEL}-clang++"
    local ar_tool="$NDK_BIN/llvm-ar"

    if [ ! -f "$clang_cc" ]; then
        log_error "Clang compiler wrapper not found: $clang_cc"
        log_error "The installed NDK ($NDK_PATH) might not support API level $API_LEVEL for $target_arch."
        exit 3
    fi

    # Export NDK toolchain and Cargo target-specific environment variables
    export ANDROID_NDK_HOME="$NDK_PATH"
    export ANDROID_NDK_ROOT="$NDK_PATH"
    export PATH="$NDK_BIN:$PATH"

    if [ "$target_arch" = "aarch64" ]; then
        export CC_aarch64_linux_android="$clang_cc"
        export CXX_aarch64_linux_android="$clang_cxx"
        export AR_aarch64_linux_android="$ar_tool"
        export CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER="$clang_cc"
        export CARGO_TARGET_AARCH64_LINUX_ANDROID_RUSTFLAGS="-C link-arg=-Wl,-z,relro,-z,now,-z,noexecstack -C link-arg=-Wl,-z,max-page-size=16384"
    elif [ "$target_arch" = "x86_64" ]; then
        export CC_x86_64_linux_android="$clang_cc"
        export CXX_x86_64_linux_android="$clang_cxx"
        export AR_x86_64_linux_android="$ar_tool"
        export CARGO_TARGET_X86_64_LINUX_ANDROID_LINKER="$clang_cc"
        export CARGO_TARGET_X86_64_LINUX_ANDROID_RUSTFLAGS="-C link-arg=-Wl,-z,relro,-z,now,-z,noexecstack -C link-arg=-Wl,-z,max-page-size=16384"
    fi

    if [ "$VERBOSE" = true ]; then
        log_info "Build Environment Variables:"
        log_info "  CC_${target_arch}_linux_android = $clang_cc"
        log_info "  CARGO_TARGET_..._LINKER = $clang_cc"
        log_info "  PATH prefix = $NDK_BIN"
    fi

    # Execute Build or Check
    cd "$ROOT_DIR"
    if [ "$CHECK_ONLY" = true ]; then
        log_step "Running 'cargo check' for ${target_triple}..."
        cargo check --target "$target_triple" -p xai-grok-pager-bin || {
            log_error "Cargo check failed for ${target_triple}"
            exit 1
        }
        log_success "Cargo check passed for ${target_triple}"
        return 0
    fi

    log_step "Compiling release binary for ${target_triple}..."
    cargo build --target "$target_triple" -p xai-grok-pager-bin --release || {
        log_error "Cargo build failed for ${target_triple}"
        exit 1
    }

    local binary_path="$ROOT_DIR/target/${target_triple}/release/xai-grok-pager"
    if [ ! -f "$binary_path" ]; then
        log_error "Compiled binary not found at expected path: $binary_path"
        exit 1
    fi
    log_success "Built binary: $binary_path ($(du -h "$binary_path" | cut -f1))"

    # Symbol Stripping
    if [ "$DO_STRIP" = true ]; then
        log_step "Stripping symbols with llvm-strip..."
        "$LLVM_STRIP" --strip-unneeded "$binary_path" || {
            log_error "llvm-strip failed on $binary_path"
            exit 1
        }
        log_success "Stripped binary size: $(du -h "$binary_path" | cut -f1)"
    else
        log_info "Symbol stripping skipped (--no-strip)"
    fi

    # ELF Validation
    if [ "$DO_VALIDATE" = true ]; then
        log_step "Validating ELF compliance (16 KiB alignment & Bionic libc)..."
        python3 "$ROOT_DIR/scripts/validate_elf.py" "$binary_path" \
            --target-arch "$target_arch" \
            --strict-16k \
            --bionic-only || {
            log_error "ELF validation FAILED for $binary_path"
            exit 1
        }
        log_success "ELF validation PASSED for ${target_triple}"
    else
        log_info "ELF validation skipped (--no-validate)"
    fi
}

# ------------------------------------------------------------------------------
# Main Orchestration
# ------------------------------------------------------------------------------
main() {
    parse_args "$@"
    detect_host_tag
    detect_ndk
    check_prerequisites

    local targets=()
    if [ "$ARCH" = "all" ]; then
        targets=("aarch64" "x86_64")
    else
        targets=("$ARCH")
    fi

    log_step "Starting grok-build-termux compilation for: ${targets[*]}"

    for t in "${targets[@]}"; do
        build_single_target "$t"
    done

    printf "\n"
    log_success "================================================================="
    if [ "$CHECK_ONLY" = true ]; then
        log_success "All requested targets checked successfully: ${targets[*]}"
    else
        log_success "All requested targets built and validated: ${targets[*]}"
        for t in "${targets[@]}"; do
            local bin="$ROOT_DIR/target/${t}-linux-android/release/xai-grok-pager"
            printf "  ${COLOR_BOLD}%s${COLOR_RESET}: %s\n" "${t}-linux-android" "$bin"
        done
    fi
    log_success "================================================================="
}

main "$@"
