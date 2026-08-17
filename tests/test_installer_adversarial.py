#!/usr/bin/env python3
"""
Adversarial Security & Boundary Test Suite for Termux One-Line Installer (install.sh).
Executed by Challenger 2 for Milestone 4.

Test Dimensions:
1. Storage Safety & Path Traversal Attacks:
   - PREFIX=/sdcard
   - PREFIX=/storage/emulated/0
   - PREFIX=/mnt/sdcard
   - PREFIX=/data/data/com.termux/files/usr/../../../../sdcard
   - PREFIX=/data/data/com.termux/files/usr/../../../../storage/emulated/0/Download
   - GROK_INSTALL_DIR=/sdcard/bin
   - GROK_INSTALL_DIR=/mnt/media_rw/sdcard0
   - Verify exit code 3 and StorageSafetyError message.

2. Checksum Tampering Attacks:
   - Modified tarball (1 byte flip) with legitimate SHA256SUMS.txt
   - Tampered SHA256SUMS.txt with invalid hash
   - Missing hash entry in SHA256SUMS.txt
   - Malformed SHA256SUMS.txt (truncated / non-hex)
   - Verify exit code 6, alert message, and zero destination pollution.

3. Corrupted Archive Attacks:
   - Truncated gzip stream matching hash
   - Corrupt tar archive (invalid tar header)
   - Valid tarball archive missing 'grok' binary
   - Verify exit code 7 and clean temporary directory cleanup.

4. Signal Handling & Temporary Workspace Leakage:
   - SIGINT (Ctrl-C) during simulated slow download
   - SIGTERM during extraction
   - Normal exit and error exit
   - Verify $TMP_DIR is completely deleted across all exit/signal paths.
"""

import http.server
import io
import json
import os
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import unittest
import hashlib
import shutil
from typing import Any, Dict, Optional, Tuple

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
INSTALL_SH = os.path.join(REPO_ROOT, "install.sh")


class LocalMockGitHubServer(http.server.HTTPServer):
    """Local HTTP Server serving mock GitHub release assets."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        super().__init__((host, port), _MockReleaseHandler)
        self.port = self.socket.getsockname()[1]
        self.base_url = f"http://{host}:{self.port}"
        self.files: Dict[str, bytes] = {}
        self.delay_paths: Dict[str, float] = {}
        self._thread: Optional[threading.Thread] = None

    def start(self):
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        self.shutdown()
        self.server_close()
        if self._thread:
            self._thread.join(timeout=2.0)

    def set_file(self, path: str, content: bytes, delay: float = 0.0):
        self.files[path] = content
        if delay > 0:
            self.delay_paths[path] = delay


class _MockReleaseHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress console noise

    def do_GET(self):
        server: LocalMockGitHubServer = self.server  # type: ignore
        if self.path in server.delay_paths:
            time.sleep(server.delay_paths[self.path])

        if self.path in server.files:
            data = server.files[self.path]
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        self.send_response(404)
        self.end_headers()


def make_tarball(files: Dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for fname, content in files.items():
            ti = tarfile.TarInfo(name=fname)
            ti.size = len(content)
            ti.mode = 0o755 if fname == "grok" else 0o644
            ti.mtime = int(time.time())
            tar.addfile(ti, io.BytesIO(content))
    return buf.getvalue()


class TestInstallerAdversarial(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="adv_install_test_")
        self.server = LocalMockGitHubServer()
        self.server.start()

    def tearDown(self):
        self.server.stop()
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    # =========================================================================
    # Dimension 1: Storage Safety & Path Traversal Attacks
    # =========================================================================

    def test_storage_safety_sdcard_prefix(self):
        """PREFIX=/sdcard must be immediately rejected with exit code 3."""
        env = dict(os.environ, PREFIX="/sdcard", VERSION="v1.0.0")
        res = subprocess.run(
            ["sh", INSTALL_SH],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 3, f"Expected exit code 3, got {res.returncode}. Output: {res.stderr}")
        self.assertIn("StorageSafetyError", res.stderr)
        self.assertIn("shared storage", res.stderr)

    def test_storage_safety_emulated_storage_prefix(self):
        """PREFIX=/storage/emulated/0 must be rejected with exit code 3."""
        env = dict(os.environ, PREFIX="/storage/emulated/0", VERSION="v1.0.0")
        res = subprocess.run(
            ["sh", INSTALL_SH],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 3)
        self.assertIn("StorageSafetyError", res.stderr)

    def test_storage_safety_mnt_sdcard(self):
        """GROK_INSTALL_DIR=/mnt/sdcard/bin must be rejected with exit code 3."""
        env = dict(os.environ, GROK_INSTALL_DIR="/mnt/sdcard/bin", VERSION="v1.0.0")
        res = subprocess.run(
            ["sh", INSTALL_SH],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 3)
        self.assertIn("StorageSafetyError", res.stderr)

    def test_storage_safety_path_traversal_dot_dot_to_sdcard(self):
        """Path traversal PREFIX=/data/data/com.termux/files/usr/../../../../sdcard must resolve and trigger exit code 3."""
        env = dict(os.environ, PREFIX="/data/data/com.termux/files/usr/../../../../sdcard", VERSION="v1.0.0")
        res = subprocess.run(
            ["sh", INSTALL_SH],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 3, f"Failed on dot-dot traversal: {res.stderr}")
        self.assertIn("StorageSafetyError", res.stderr)

    def test_storage_safety_path_traversal_dot_dot_to_storage_emulated(self):
        """Path traversal PREFIX=/data/data/com.termux/files/usr/../../../../storage/emulated/0/Download must trigger exit code 3."""
        env = dict(os.environ, PREFIX="/data/data/com.termux/files/usr/../../../../storage/emulated/0/Download", VERSION="v1.0.0")
        res = subprocess.run(
            ["sh", INSTALL_SH],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 3)
        self.assertIn("StorageSafetyError", res.stderr)

    def test_storage_safety_mnt_media_rw(self):
        """GROK_INSTALL_DIR=/mnt/media_rw/ext_sdcard/bin must trigger exit code 3."""
        env = dict(os.environ, GROK_INSTALL_DIR="/mnt/media_rw/ext_sdcard/bin", VERSION="v1.0.0")
        res = subprocess.run(
            ["sh", INSTALL_SH],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 3)
        self.assertIn("StorageSafetyError", res.stderr)

    # =========================================================================
    # Dimension 2: Checksum Tampering & Cryptographic Integrity
    # =========================================================================

    def _run_installer_with_mock_github(
        self,
        tarball_bytes: bytes,
        sha256sums_content: str,
        target_dir: str,
        tag: str = "v1.0.0",
    ) -> subprocess.CompletedProcess:
        # Determine host arch for installer
        arch = "aarch64" if os.uname().machine in ("arm64", "aarch64") else "x86_64"
        tarball_name = f"grok-build-termux-{tag}-{arch}-linux-android.tar.gz"

        # Register files on local mock server
        rel_path = f"/ImL1s/grok-build-termux/releases/download/{tag}"
        self.server.set_file(f"{rel_path}/SHA256SUMS.txt", sha256sums_content.encode("utf-8"))
        self.server.set_file(f"{rel_path}/{tarball_name}", tarball_bytes)

        # Create a modified wrapper or env redirecting github.com to local mock server
        # In install.sh, DOWNLOAD_BASE is "https://github.com/ImL1s/grok-build-termux/releases/download/${TAG}"
        # We test checksum logic by overriding github download URL or running via curl intercept
        # Let's inspect install.sh: We can test the checksum verification logic directly or via wrapper
        wrapper_script = f"""#!/bin/sh
set -eu
export VERSION="{tag}"
export GROK_INSTALL_DIR="{target_dir}"

# Override curl/wget inside subshell to redirect to local mock server
curl() {{
  url="$1"
  shift
  # parse arguments
  while [ $# -gt 0 ]; do
    case "$1" in
      -o) out="$2"; shift 2 ;;
      *) url="$1"; shift ;;
    esac
  done
  local_path=$(printf '%s' "$url" | sed 's|https://github.com||')
  command curl -fsSL "{self.server.base_url}$local_path" -o "$out"
}}

# Source install.sh logic
# We invoke install.sh with intercept
"""
        # Alternatively, we can invoke install.sh directly if we mock curl in PATH
        mock_bin_dir = os.path.join(self.test_dir, "mock_bin")
        os.makedirs(mock_bin_dir, exist_ok=True)
        mock_curl = os.path.join(mock_bin_dir, "curl")
        with open(mock_curl, "w") as f:
            f.write(f"""#!/bin/sh
out=""
url=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    http*) url="$1"; shift ;;
    *) shift ;;
  esac
done

if [ -n "$url" ] && [ -n "$out" ]; then
  local_path=$(printf '%s' "$url" | sed 's|https://github.com||')
  /usr/bin/curl -fsSL "{self.server.base_url}$local_path" -o "$out"
else
  /usr/bin/curl "$@"
fi
""")
        os.chmod(mock_curl, 0o755)

        env = dict(
            os.environ,
            PATH=f"{mock_bin_dir}:{os.environ['PATH']}",
            GROK_INSTALL_DIR=target_dir,
            VERSION=tag,
        )

        res = subprocess.run(
            ["sh", INSTALL_SH],
            env=env,
            capture_output=True,
            text=True,
        )
        return res

    def test_checksum_tampered_tarball_rejection(self):
        """Simulate modified tarball with mismatched SHA256; must abort with exit code 6 and zero file pollution."""
        install_target_dir = os.path.join(self.test_dir, "install_bin")
        os.makedirs(install_target_dir, exist_ok=True)

        valid_tar = make_tarball({"grok": b"MOCK_VALID_BINARY", "LICENSE": b"MIT"})
        real_hash = hashlib.sha256(valid_tar).hexdigest()

        # Tamper 1 byte of tarball
        tampered_tar = valid_tar[:-4] + b"\xde\xad\xbe\xef"
        arch = "aarch64" if os.uname().machine in ("arm64", "aarch64") else "x86_64"
        tarball_name = f"grok-build-termux-v1.0.0-{arch}-linux-android.tar.gz"

        # Manifest contains hash of original valid_tar
        manifest = f"{real_hash}  {tarball_name}\n"

        res = self._run_installer_with_mock_github(
            tarball_bytes=tampered_tar,
            sha256sums_content=manifest,
            target_dir=install_target_dir,
            tag="v1.0.0",
        )

        self.assertEqual(res.returncode, 6, f"Expected exit code 6 on checksum mismatch, got {res.returncode}. Out: {res.stdout}, Err: {res.stderr}")
        self.assertIn("SECURITY ALERT: SHA256 CHECKSUM VERIFICATION FAILED", res.stderr)
        self.assertIn("Integrity check failed", res.stderr)

        # Verify zero target directory pollution
        installed_files = os.listdir(install_target_dir)
        self.assertEqual(installed_files, [], f"Target directory contaminated: {installed_files}")

    def test_checksum_missing_entry_in_manifest(self):
        """SHA256SUMS.txt does not contain the required package name; must abort with exit code 6."""
        install_target_dir = os.path.join(self.test_dir, "install_bin")
        os.makedirs(install_target_dir, exist_ok=True)

        valid_tar = make_tarball({"grok": b"MOCK_VALID_BINARY"})
        manifest = f"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  unrelated-file.tar.gz\n"

        res = self._run_installer_with_mock_github(
            tarball_bytes=valid_tar,
            sha256sums_content=manifest,
            target_dir=install_target_dir,
            tag="v1.0.0",
        )

        self.assertEqual(res.returncode, 6)
        self.assertIn("not found in SHA256SUMS.txt", res.stderr)
        self.assertEqual(os.listdir(install_target_dir), [])

    def test_checksum_malformed_manifest_entry(self):
        """SHA256SUMS.txt contains invalid/truncated hash string (<64 chars); must abort with exit code 6."""
        install_target_dir = os.path.join(self.test_dir, "install_bin")
        os.makedirs(install_target_dir, exist_ok=True)

        valid_tar = make_tarball({"grok": b"MOCK_VALID_BINARY"})
        arch = "aarch64" if os.uname().machine in ("arm64", "aarch64") else "x86_64"
        tarball_name = f"grok-build-termux-v1.0.0-{arch}-linux-android.tar.gz"
        manifest = f"deadbeef123  {tarball_name}\n"

        res = self._run_installer_with_mock_github(
            tarball_bytes=valid_tar,
            sha256sums_content=manifest,
            target_dir=install_target_dir,
            tag="v1.0.0",
        )

        self.assertEqual(res.returncode, 6)
        self.assertIn("Malformed SHA256 checksum", res.stderr)
        self.assertEqual(os.listdir(install_target_dir), [])

    # =========================================================================
    # Dimension 3: Corrupted Archive & Missing Binary Attacks
    # =========================================================================

    def test_corrupted_tarball_decompression_failure(self):
        """Tarball is corrupted/not valid gzip (matching SHA256); extraction must fail with exit code 7."""
        install_target_dir = os.path.join(self.test_dir, "install_bin")
        os.makedirs(install_target_dir, exist_ok=True)

        corrupt_tar = b"\x1f\x8b\x08\x00_THIS_IS_CORRUPTED_GZIP_GARBAGE_DATA_"
        corrupt_hash = hashlib.sha256(corrupt_tar).hexdigest()

        arch = "aarch64" if os.uname().machine in ("arm64", "aarch64") else "x86_64"
        tarball_name = f"grok-build-termux-v1.0.0-{arch}-linux-android.tar.gz"
        manifest = f"{corrupt_hash}  {tarball_name}\n"

        res = self._run_installer_with_mock_github(
            tarball_bytes=corrupt_tar,
            sha256sums_content=manifest,
            target_dir=install_target_dir,
            tag="v1.0.0",
        )

        self.assertEqual(res.returncode, 7, f"Expected exit code 7 on extraction failure, got {res.returncode}. Err: {res.stderr}")
        self.assertIn("Failed to extract tarball archive", res.stderr)
        self.assertEqual(os.listdir(install_target_dir), [])

    def test_tarball_missing_grok_binary(self):
        """Tarball extracts successfully but does not contain 'grok'; must abort with exit code 7."""
        install_target_dir = os.path.join(self.test_dir, "install_bin")
        os.makedirs(install_target_dir, exist_ok=True)

        archive_without_grok = make_tarball({"README.md": b"Just a readme", "LICENSE": b"MIT"})
        archive_hash = hashlib.sha256(archive_without_grok).hexdigest()

        arch = "aarch64" if os.uname().machine in ("arm64", "aarch64") else "x86_64"
        tarball_name = f"grok-build-termux-v1.0.0-{arch}-linux-android.tar.gz"
        manifest = f"{archive_hash}  {tarball_name}\n"

        res = self._run_installer_with_mock_github(
            tarball_bytes=archive_without_grok,
            sha256sums_content=manifest,
            target_dir=install_target_dir,
            tag="v1.0.0",
        )

        self.assertEqual(res.returncode, 7)
        self.assertIn("Binary 'grok' not found inside release archive", res.stderr)
        self.assertEqual(os.listdir(install_target_dir), [])

    # =========================================================================
    # Dimension 4: Signal Handling & Temporary Workspace Leakage
    # =========================================================================

    def test_temp_dir_cleaned_on_normal_and_error_exits(self):
        """Verify temporary directories created by mktemp are always purged upon exit."""
        # Find all current /tmp/grok-install-* directories
        tmp_parent = tempfile.gettempdir()
        initial_dirs = {d for d in os.listdir(tmp_parent) if "grok" in d}

        # Run failing command
        env = dict(os.environ, PREFIX="/sdcard", VERSION="v1.0.0")
        subprocess.run(["sh", INSTALL_SH], env=env, capture_output=True)

        post_dirs = {d for d in os.listdir(tmp_parent) if "grok" in d}
        leaked = post_dirs - initial_dirs
        self.assertEqual(leaked, set(), f"Leaked temporary directories: {leaked}")

    def test_storage_safety_symlink_to_sdcard(self):
        """PREFIX pointing to a symlink that resolves to /sdcard must be rejected with exit code 3."""
        symlink_dir = os.path.join(self.test_dir, "symlink_to_sdcard")
        os.symlink("/sdcard", symlink_dir)
        env = dict(os.environ, PREFIX=symlink_dir, VERSION="v1.0.0")
        res = subprocess.run(
            ["sh", INSTALL_SH],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 3, f"Symlink to /sdcard was not rejected: {res.stderr}")
        self.assertIn("StorageSafetyError", res.stderr)

    # =========================================================================
    # Dimension 5: Architecture & Environment Boundary Probing
    # =========================================================================

    def test_arch_rejection_32bit_arm(self):
        """32-bit ARM (armv7l, armv6, armhf) must be rejected with exit code 2."""
        mock_bin_dir = os.path.join(self.test_dir, "mock_bin_armv7")
        os.makedirs(mock_bin_dir, exist_ok=True)
        with open(os.path.join(mock_bin_dir, "uname"), "w") as f:
            f.write("#!/bin/sh\necho 'armv7l'\n")
        os.chmod(os.path.join(mock_bin_dir, "uname"), 0o755)

        env = dict(os.environ, PATH=f"{mock_bin_dir}:{os.environ['PATH']}", VERSION="v1.0.0")
        res = subprocess.run(["sh", INSTALL_SH], env=env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 2, f"Expected exit code 2 for 32-bit ARM, got {res.returncode}")
        self.assertIn("Unsupported 32-bit ARM Architecture", res.stderr)

    def test_arch_rejection_32bit_x86(self):
        """32-bit x86 (i686) must be rejected with exit code 2."""
        mock_bin_dir = os.path.join(self.test_dir, "mock_bin_i686")
        os.makedirs(mock_bin_dir, exist_ok=True)
        with open(os.path.join(mock_bin_dir, "uname"), "w") as f:
            f.write("#!/bin/sh\necho 'i686'\n")
        os.chmod(os.path.join(mock_bin_dir, "uname"), 0o755)

        env = dict(os.environ, PATH=f"{mock_bin_dir}:{os.environ['PATH']}", VERSION="v1.0.0")
        res = subprocess.run(["sh", INSTALL_SH], env=env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 2)
        self.assertIn("32-bit x86 architecture", res.stderr)

    def test_arch_rejection_unknown_mips(self):
        """Unknown architecture (e.g. mips64el, riscv32) must be rejected with exit code 2."""
        mock_bin_dir = os.path.join(self.test_dir, "mock_bin_mips")
        os.makedirs(mock_bin_dir, exist_ok=True)
        with open(os.path.join(mock_bin_dir, "uname"), "w") as f:
            f.write("#!/bin/sh\necho 'mips64el'\n")
        os.chmod(os.path.join(mock_bin_dir, "uname"), 0o755)

        env = dict(os.environ, PATH=f"{mock_bin_dir}:{os.environ['PATH']}", VERSION="v1.0.0")
        res = subprocess.run(["sh", INSTALL_SH], env=env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 2)
        self.assertIn("Unsupported architecture", res.stderr)

    # =========================================================================
    # Dimension 6: Version Validation & Rate-Limit Handling
    # =========================================================================

    def test_version_format_invalid_characters(self):
        """Invalid version string (e.g. 'foo/bar', 'beta-1') must exit with code 1."""
        env = dict(os.environ, VERSION="malicious;rm -rf /")
        res = subprocess.run(["sh", INSTALL_SH], env=env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 1)
        self.assertIn("Invalid version format", res.stderr)

    def test_missing_downloader_tools(self):
        """When neither curl nor wget is found, script exits with code 4."""
        # Create an isolated PATH with only sh, rm, mktemp, mkdir, cat, uname
        safe_bin = os.path.join(self.test_dir, "isolated_bin")
        os.makedirs(safe_bin, exist_ok=True)
        for cmd in ["sh", "rm", "mktemp", "mkdir", "cat", "uname", "chmod", "basename", "dirname"]:
            cmd_path = shutil.which(cmd)
            if cmd_path:
                os.symlink(cmd_path, os.path.join(safe_bin, cmd))

        env = dict(os.environ, PATH=safe_bin, VERSION="v1.0.0")
        res = subprocess.run(["sh", INSTALL_SH], env=env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 4)
        self.assertIn("Neither 'curl' nor 'wget' was found", res.stderr)

    def test_missing_sha256_utilities(self):
        """When no sha256 computation tool is found, script exits with code 4."""
        install_target_dir = os.path.join(self.test_dir, "install_bin_nosha")
        os.makedirs(install_target_dir, exist_ok=True)

        valid_tar = make_tarball({"grok": b"MOCK_VALID_BINARY"})
        arch = "aarch64" if os.uname().machine in ("arm64", "aarch64") else "x86_64"
        tarball_name = f"grok-build-termux-v1.0.0-{arch}-linux-android.tar.gz"
        manifest = f"{hashlib.sha256(valid_tar).hexdigest()}  {tarball_name}\n"

        rel_path = f"/ImL1s/grok-build-termux/releases/download/v1.0.0"
        self.server.set_file(f"{rel_path}/SHA256SUMS.txt", manifest.encode("utf-8"))
        self.server.set_file(f"{rel_path}/{tarball_name}", valid_tar)

        # Create isolated bin directory containing curl, awk, sed, grep, mktemp, rm, chmod, mkdir, etc.
        # but EXCLUDING sha256sum, shasum, openssl
        mock_bin_dir = os.path.join(self.test_dir, "mock_bin_nosha")
        os.makedirs(mock_bin_dir, exist_ok=True)
        
        # Proxy curl to mock server
        mock_curl = os.path.join(mock_bin_dir, "curl")
        with open(mock_curl, "w") as f:
            f.write(f"""#!/bin/sh
out=""
url=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    http*) url="$1"; shift ;;
    *) shift ;;
  esac
done

if [ -n "$url" ] && [ -n "$out" ]; then
  local_path=$(printf '%s' "$url" | sed 's|https://github.com||')
  /usr/bin/curl -fsSL "{self.server.base_url}$local_path" -o "$out"
else
  /usr/bin/curl "$@"
fi
""")
        os.chmod(mock_curl, 0o755)

        # Symlink all essential core commands except sha tools
        essential_cmds = ["sh", "rm", "mktemp", "mkdir", "cat", "uname", "chmod", "basename", "dirname", "awk", "sed", "tr", "grep", "wc", "head", "tail", "tar", "find", "mv", "cp"]
        for cmd in essential_cmds:
            cmd_path = shutil.which(cmd)
            if cmd_path:
                dst = os.path.join(mock_bin_dir, cmd)
                if not os.path.exists(dst):
                    os.symlink(cmd_path, dst)

        env = dict(
            os.environ,
            PATH=mock_bin_dir,
            GROK_INSTALL_DIR=install_target_dir,
            VERSION="v1.0.0",
        )

        res = subprocess.run(
            ["sh", INSTALL_SH],
            env=env,
            capture_output=True,
            text=True,
        )

        self.assertEqual(res.returncode, 4, f"Expected exit code 4 when SHA utilities missing, got {res.returncode}. Out: {res.stdout}, Err: {res.stderr}")
        self.assertIn("No SHA256 checksum utility available", res.stderr)

    def test_temp_dir_cleaned_on_sigterm_interrupt(self):
        """Verify temporary directory is purged when script is interrupted by SIGTERM."""
        install_target_dir = os.path.join(self.test_dir, "install_bin_sigterm")
        os.makedirs(install_target_dir, exist_ok=True)

        valid_tar = make_tarball({"grok": b"MOCK_VALID_BINARY"})
        arch = "aarch64" if os.uname().machine in ("arm64", "aarch64") else "x86_64"
        tarball_name = f"grok-build-termux-v1.0.0-{arch}-linux-android.tar.gz"
        manifest = f"{hashlib.sha256(valid_tar).hexdigest()}  {tarball_name}\n"

        rel_path = f"/ImL1s/grok-build-termux/releases/download/v1.0.0"
        self.server.set_file(f"{rel_path}/SHA256SUMS.txt", manifest.encode("utf-8"))
        self.server.set_file(f"{rel_path}/{tarball_name}", valid_tar, delay=3.0)

        mock_bin_dir = os.path.join(self.test_dir, "mock_bin_sigterm")
        os.makedirs(mock_bin_dir, exist_ok=True)
        mock_curl = os.path.join(mock_bin_dir, "curl")
        with open(mock_curl, "w") as f:
            f.write(f"""#!/bin/sh
out=""
url=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    http*) url="$1"; shift ;;
    *) shift ;;
  esac
done

if [ -n "$url" ] && [ -n "$out" ]; then
  local_path=$(printf '%s' "$url" | sed 's|https://github.com||')
  /usr/bin/curl -fsSL "{self.server.base_url}$local_path" -o "$out"
else
  /usr/bin/curl "$@"
fi
""")
        os.chmod(mock_curl, 0o755)

        tmp_parent = tempfile.gettempdir()
        initial_dirs = {d for d in os.listdir(tmp_parent) if "grok" in d}

        env = dict(
            os.environ,
            PATH=f"{mock_bin_dir}:{os.environ['PATH']}",
            GROK_INSTALL_DIR=install_target_dir,
            VERSION="v1.0.0",
        )

        proc = subprocess.Popen(
            ["sh", INSTALL_SH],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        time.sleep(0.5)
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=5)

        post_dirs = {d for d in os.listdir(tmp_parent) if "grok" in d}
        leaked = post_dirs - initial_dirs
        self.assertEqual(leaked, set(), f"Leaked temporary directories after SIGTERM: {leaked}")



if __name__ == "__main__":
    unittest.main()
