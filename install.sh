#!/bin/sh
# =============================================================================
# Grok Build for Termux — Production One-Line Installer
#
# Target Architectures : aarch64-linux-android, x86_64-linux-android
# Requirements        : 64-bit Android Bionic libc, 16 KiB ELF alignment
# Usage               : curl -sSL https://raw.githubusercontent.com/ImL1s/grok-build-termux/main/install.sh | bash
# Manual Version Spec : VERSION=v1.0.0 curl -sSL ... | bash
#                       bash install.sh v1.0.0
# =============================================================================

set -eu

# -----------------------------------------------------------------------------
# 1. Colors & Logging (POSIX compliant, TTY & NO_COLOR aware)
# -----------------------------------------------------------------------------
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ] && [ "${TERM:-}" != "dumb" ]; then
  C_RESET='\033[0m'
  C_BOLD='\033[1m'
  C_RED='\033[1;31m'
  C_GREEN='\033[1;32m'
  C_YELLOW='\033[1;33m'
  C_CYAN='\033[1;36m'
else
  C_RESET=''
  C_BOLD=''
  C_RED=''
  C_GREEN=''
  C_YELLOW=''
  C_CYAN=''
fi

info()    { printf "%b==>%b %s\n" "${C_CYAN}${C_BOLD}" "${C_RESET}" "$*"; }
success() { printf "%b==>%b %s\n" "${C_GREEN}${C_BOLD}" "${C_RESET}" "$*"; }
warn()    { printf "%bWARNING:%b %s\n" "${C_YELLOW}${C_BOLD}" "${C_RESET}" "$*" >&2; }
error()   { printf "%bERROR:%b %s\n" "${C_RED}${C_BOLD}" "${C_RESET}" "$*" >&2; }
die()     { code="$1"; shift; error "$*"; exit "$code"; }

# -----------------------------------------------------------------------------
# 2. Cleanup Trap & Secure Temporary Workspace
# -----------------------------------------------------------------------------
TMP_DIR="$(mktemp -d 2>/dev/null || mktemp -d -t 'grok-install-XXXXXX')"
[ -n "$TMP_DIR" ] && [ -d "$TMP_DIR" ] || die 1 "Failed to create secure temporary directory."
chmod 700 "$TMP_DIR" 2>/dev/null || true

cleanup() {
  exit_code=$?
  trap - EXIT INT TERM HUP
  if [ -n "${TMP_DIR:-}" ] && [ -d "$TMP_DIR" ]; then
    rm -rf "$TMP_DIR"
  fi
  exit "$exit_code"
}
trap cleanup EXIT INT TERM HUP

# -----------------------------------------------------------------------------
# 3. Architecture & Platform Detection
# -----------------------------------------------------------------------------
detect_arch() {
  RAW_ARCH="$(uname -m 2>/dev/null || echo "unknown")"
  case "$RAW_ARCH" in
    aarch64*|arm64*|armv8*|armv9*|AARCH64*|ARM64*)
      ARCH="aarch64"
      TARGET="aarch64-linux-android"
      ;;
    x86_64*|amd64*|x64*|X86_64*|AMD64*)
      ARCH="x86_64"
      TARGET="x86_64-linux-android"
      ;;
    armv7*|armv6*|armv5*|armhf*|armel*|arm*|ARM*)
      printf "\n%bUnsupported 32-bit ARM Architecture Detected:%b %s\n\n" "${C_RED}${C_BOLD}" "${C_RESET}" "$RAW_ARCH" >&2
      printf "grok-build-termux requires a 64-bit Android Bionic environment (aarch64 or x86_64).\n" >&2
      printf "32-bit ARM is unsupported due to 64-bit atomic operations, memory space, and 16 KiB ELF alignment requirements.\n\n" >&2
      printf "%bRemedy:%b If your device has a 64-bit CPU, install the official 64-bit Termux build from F-Droid:\n" "${C_YELLOW}${C_BOLD}" "${C_RESET}" >&2
      printf "  https://github.com/termux/termux-app/releases\n\n" >&2
      die 2 "Architecture $RAW_ARCH is unsupported."
      ;;
    i386*|i486*|i586*|i686*|x86|ia32|X86)
      die 2 "32-bit x86 architecture ($RAW_ARCH) is unsupported. 64-bit (x86_64) is required."
      ;;
    *)
      die 2 "Unsupported architecture: $RAW_ARCH. Supported architectures: aarch64, x86_64."
      ;;
  esac
}

# -----------------------------------------------------------------------------
# 4. Storage Safety Quarantine
# -----------------------------------------------------------------------------
canonicalize_path() {
  p="$1"
  if command -v realpath >/dev/null 2>&1; then
    realpath -m "$p" 2>/dev/null || realpath "$p" 2>/dev/null || printf '%s' "$p"
  elif command -v readlink >/dev/null 2>&1; then
    readlink -f "$p" 2>/dev/null || printf '%s' "$p"
  else
    printf '%s' "$p"
  fi
}

validate_storage_safety() {
  target_path="$1"
  canonical_path="$(canonicalize_path "$target_path")"
  lower_path=$(printf '%s' "$canonical_path" | tr '[:upper:]' '[:lower:]' | sed 's|\\|/|g')
  raw_lower=$(printf '%s' "$target_path" | tr '[:upper:]' '[:lower:]' | sed 's|\\|/|g')

  case "$lower_path" in
    /sdcard*|/storage*|/mnt/sdcard*|/mnt/media_rw*|/data/sdcard*|/data/media*|sdcard*|storage*|mnt/sdcard*|mnt/media_rw*|data/sdcard*|data/media*)
      die 3 "StorageSafetyError: Target installation path ($target_path) cannot reside on Android shared storage. Android shared storage (/sdcard, /storage/emulated/0) is mounted 'noexec' and lacks POSIX permissions. Please install into internal Termux storage (e.g., \$PREFIX/bin or ~/.grok/bin)."
      ;;
  esac

  case "$raw_lower" in
    *sdcard*|*storage/emulated*)
      die 3 "StorageSafetyError: Target path ($target_path) resolves to Android shared storage. Please install into internal Termux storage (e.g., \$PREFIX/bin or ~/.grok/bin)."
      ;;
  esac
}

# -----------------------------------------------------------------------------
# 5. Installation Directory & Environment Resolution
# -----------------------------------------------------------------------------
resolve_install_dir() {
  if [ -n "${GROK_INSTALL_DIR:-}" ]; then
    INSTALL_DIR="$GROK_INSTALL_DIR"
    IS_TERMUX=0
  elif [ -n "${PREFIX:-}" ]; then
    INSTALL_DIR="${PREFIX}/bin"
    IS_TERMUX=1
  elif [ -d "/data/data/com.termux/files/usr" ]; then
    PREFIX="/data/data/com.termux/files/usr"
    INSTALL_DIR="${PREFIX}/bin"
    IS_TERMUX=1
  elif [ -n "${HOME:-}" ]; then
    INSTALL_DIR="${HOME}/.grok/bin"
    IS_TERMUX=0
  else
    INSTALL_DIR="/usr/local/bin"
    IS_TERMUX=0
  fi
  validate_storage_safety "$INSTALL_DIR"
}

# -----------------------------------------------------------------------------
# 6. HTTP Downloader Probing & Helper
# -----------------------------------------------------------------------------
detect_downloader() {
  if command -v curl >/dev/null 2>&1; then
    DOWNLOADER="curl"
  elif command -v wget >/dev/null 2>&1; then
    DOWNLOADER="wget"
  else
    die 4 "Neither 'curl' nor 'wget' was found. In Termux, run: pkg install -y curl"
  fi
}

download_file() {
  url="$1"
  output="$2"
  if [ "$DOWNLOADER" = "curl" ]; then
    curl -fsSL -H "User-Agent: grok-termux-installer" -o "$output" "$url"
  else
    wget -q -O "$output" --user-agent="grok-termux-installer" "$url"
  fi
}

# -----------------------------------------------------------------------------
# 7. Checksum Computation Helper (sha256sum -> shasum -> openssl)
# -----------------------------------------------------------------------------
compute_sha256() {
  target_file="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$target_file" | awk '{print tolower($1)}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$target_file" | awk '{print tolower($1)}'
  elif command -v openssl >/dev/null 2>&1; then
    openssl dgst -sha256 "$target_file" | sed -e 's/.*= //' -e 's/.* //' | tr '[:upper:]' '[:lower:]'
  else
    die 4 "No SHA256 checksum utility available (sha256sum, shasum, or openssl required). In Termux: pkg install -y coreutils"
  fi
}

# -----------------------------------------------------------------------------
# 8. Version Resolution (Manual Spec -> GitHub REST API -> HTTP 302 Redirect)
# -----------------------------------------------------------------------------
resolve_version() {
  explicit_ver="${1:-${VERSION:-}}"
  if [ -n "$explicit_ver" ]; then
    TAG="$explicit_ver"
    case "$TAG" in
      [0-9]*) TAG="v$TAG" ;;
    esac
    case "$TAG" in
      v[0-9]*) ;;
      *) die 1 "Invalid version format: $TAG (expected vX.Y.Z or X.Y.Z)" ;;
    esac
    return 0
  fi

  info "Resolving latest release tag from GitHub..."
  repo="ImL1s/grok-build-termux"
  api_url="https://api.github.com/repos/${repo}/releases/latest"
  api_file="$TMP_DIR/release_latest.json"

  # 1. Attempt GitHub REST API
  TAG=""
  if [ "$DOWNLOADER" = "curl" ]; then
    if curl -fsSL -H "Accept: application/vnd.github.v3+json" -H "User-Agent: grok-termux-installer" "$api_url" -o "$api_file" 2>/dev/null; then
      TAG="$(sed -n -E 's/.*"tag_name"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p' "$api_file" | head -n 1 | tr -d '[:space:]')"
    fi
  else
    if wget -q -O "$api_file" --header="Accept: application/vnd.github.v3+json" --user-agent="grok-termux-installer" "$api_url" 2>/dev/null; then
      TAG="$(sed -n -E 's/.*"tag_name"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p' "$api_file" | head -n 1 | tr -d '[:space:]')"
    fi
  fi

  # 2. Attempt HTTP redirect fallback (rate-limit bypass)
  if [ -z "$TAG" ]; then
    info "GitHub API unavailable or rate-limited; trying HTTP redirect fallback..."
    web_url="https://github.com/${repo}/releases/latest"
    if [ "$DOWNLOADER" = "curl" ]; then
      eff_url="$(curl -sIL -o /dev/null -w '%{url_effective}' "$web_url" 2>/dev/null || true)"
    else
      eff_url="$(wget --max-redirect=0 --spider --server-response "$web_url" 2>&1 | awk -F': ' 'tolower($1) ~ /location/{print $2}' | tr -d '\r' | tail -n 1)"
    fi
    TAG="$(printf '%s' "$eff_url" | sed -n 's|.*/releases/tag/||p; s|.*/tag/||p' | tr -d '\r\n[:space:]')"
  fi

  if [ -z "$TAG" ] || [ "$TAG" = "latest" ]; then
    die 5 "Unable to resolve latest release tag from GitHub. You can specify a version explicitly, e.g.: VERSION=v1.0.0 curl -sSL https://raw.githubusercontent.com/${repo}/main/install.sh | bash"
  fi
}

# -----------------------------------------------------------------------------
# 9. Main Installation Flow
# -----------------------------------------------------------------------------
main() {
  info "Initializing Grok Build for Termux Installer..."
  detect_downloader
  detect_arch
  info "Detected architecture: $ARCH ($TARGET)"
  resolve_install_dir
  info "Installation target: $INSTALL_DIR/grok"
  resolve_version "${1:-}"
  info "Target release version: $TAG"

  TARBALL_NAME="grok-build-termux-${TAG}-${TARGET}.tar.gz"
  DOWNLOAD_BASE="https://github.com/ImL1s/grok-build-termux/releases/download/${TAG}"
  TARBALL_URL="${DOWNLOAD_BASE}/${TARBALL_NAME}"
  SUMS_URL="${DOWNLOAD_BASE}/SHA256SUMS.txt"

  info "Downloading checksum manifest (SHA256SUMS.txt)..."
  download_file "$SUMS_URL" "$TMP_DIR/SHA256SUMS.txt" || die 5 "Failed to download SHA256SUMS.txt from $SUMS_URL"

  expected_hash=$(awk -v fname="$TARBALL_NAME" '
    BEGIN { fname_star = "*" fname }
    {
      gsub(/\r/, "", $0)
      if ($0 ~ /^#/ || NF < 2) next
      hash = tolower($1)
      if ($2 == fname || $2 == fname_star || $NF == fname || $NF == fname_star) {
        print hash
        exit
      }
    }
  ' "$TMP_DIR/SHA256SUMS.txt")

  [ -n "$expected_hash" ] || die 6 "Package '$TARBALL_NAME' not found in SHA256SUMS.txt."

  hash_len=$(printf '%s' "$expected_hash" | wc -c | tr -d '[:space:]')
  [ "$hash_len" -eq 64 ] || die 6 "Malformed SHA256 checksum ($expected_hash) in SHA256SUMS.txt."

  info "Downloading release package ($TARBALL_NAME)..."
  download_file "$TARBALL_URL" "$TMP_DIR/$TARBALL_NAME" || die 5 "Failed to download release archive: $TARBALL_URL"

  info "Verifying SHA256 cryptographic checksum..."
  actual_hash="$(compute_sha256 "$TMP_DIR/$TARBALL_NAME")"

  if [ "$actual_hash" != "$expected_hash" ]; then
    error "============================================================"
    error " SECURITY ALERT: SHA256 CHECKSUM VERIFICATION FAILED!"
    error "============================================================"
    error " File:     $TARBALL_NAME"
    error " Expected: $expected_hash"
    error " Actual:   $actual_hash"
    error " The downloaded archive may be corrupted or tampered with."
    die 6 "Integrity check failed. Installation aborted."
  fi
  success "Cryptographic integrity verified: $actual_hash"

  info "Unpacking release archive safely..."
  EXTRACT_DIR="$TMP_DIR/extracted"
  mkdir -p "$EXTRACT_DIR" || die 7 "Failed to create extraction temporary directory."
  tar -xzf "$TMP_DIR/$TARBALL_NAME" -C "$EXTRACT_DIR" || die 7 "Failed to extract tarball archive."

  SRC_BIN=""
  if [ -f "$EXTRACT_DIR/grok" ]; then
    SRC_BIN="$EXTRACT_DIR/grok"
  else
    found_bin="$(find "$EXTRACT_DIR" -name "grok" -type f 2>/dev/null | head -n 1)"
    if [ -n "$found_bin" ] && [ -f "$found_bin" ]; then
      SRC_BIN="$found_bin"
    fi
  fi

  [ -n "$SRC_BIN" ] && [ -f "$SRC_BIN" ] || die 7 "Binary 'grok' not found inside release archive."

  info "Installing grok to $INSTALL_DIR..."
  mkdir -p "$INSTALL_DIR" || die 8 "Failed to create installation directory: $INSTALL_DIR"

  TMP_DEST="${INSTALL_DIR}/grok.tmp.$$"
  cp "$SRC_BIN" "$TMP_DEST" || die 8 "Failed to copy binary to staging path: $TMP_DEST"
  chmod 0755 "$TMP_DEST" || die 8 "Failed to set executable mode (0755) on $TMP_DEST"
  mv -f "$TMP_DEST" "${INSTALL_DIR}/grok" || die 8 "Failed to atomically install ${INSTALL_DIR}/grok"

  success "Grok binary successfully installed to ${INSTALL_DIR}/grok"

  # Post-install verification
  info "Performing post-installation verification..."
  binary_path="${INSTALL_DIR}/grok"
  [ -x "$binary_path" ] || die 8 "Installed binary is not executable: $binary_path"

  if "$binary_path" --version >/dev/null 2>&1; then
    INSTALLED_VER="$("$binary_path" --version 2>/dev/null || true)"
    success "Verified executable: $INSTALLED_VER"
    if "$binary_path" doctor >/dev/null 2>&1; then
      info "Environment diagnostics passed (grok doctor)."
    fi
  else
    success "Binary installed successfully at $binary_path (mode: 0755)."
    warn "Direct execution verification skipped (host platform cannot directly execute Android target binary)."
  fi

  # PATH verification & guidance
  case ":$PATH:" in
    *":$INSTALL_DIR:"*) ;;
    *)
      warn "$INSTALL_DIR is not in your \$PATH."
      printf "\nTo use grok from anywhere, add the following to your shell profile (~/.bashrc or ~/.zshrc):\n"
      printf "    export PATH=\"%s:\$PATH\"\n\n" "$INSTALL_DIR"
      ;;
  esac

  # Termux prerequisites guidance
  if [ "${IS_TERMUX:-0}" = "1" ]; then
    MISSING_PKGS=""
    command -v rg >/dev/null 2>&1 || MISSING_PKGS="${MISSING_PKGS} ripgrep"
    command -v fd >/dev/null 2>&1 || command -v fdfind >/dev/null 2>&1 || MISSING_PKGS="${MISSING_PKGS} fd"
    command -v git >/dev/null 2>&1 || MISSING_PKGS="${MISSING_PKGS} git"

    if [ -n "$MISSING_PKGS" ]; then
      info "Recommended Termux helper packages for full functionality:"
      printf "    pkg install -y%s\n\n" "$MISSING_PKGS"
    fi
  fi

  success "Installation complete! Run 'grok --help' or 'grok' to get started."
}

main "$@"
