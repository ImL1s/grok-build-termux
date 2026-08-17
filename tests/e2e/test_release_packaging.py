#!/usr/bin/env python3
"""
E2E Test Suite: Release Packaging & Simulated Installer Verification Pipeline (Milestone 5).

Covers the complete 6-stage release verification pipeline:
1. Multi-arch 64-bit ELF binary synthesis (aarch64 / x86_64) with 16 KiB PT_LOAD page alignment
   and Bionic dynamic linker (/system/bin/linker64).
2. Tarball packaging (.tar.gz structure, permissions: 0o755 for binaries, 0o644 for docs).
3. SHA256SUMS.txt generation, format compliance, and cryptographic integrity verification.
4. Extraction and staging validation against scripts/validate_elf.py.
5. Simulated Termux ($PREFIX) and Standalone ($HOME) installer execution via Mock GitHub API Server.
6. Adversarial hardening (checksum tampering, corrupt tarballs, legacy 4 KiB ELFs, desktop glibc ELFs,
   and /sdcard storage quarantine).

Grand Total: 13 test cases.
"""

import http.server
import io
import json
import os
import shutil
import stat
import struct
import sys
import tarfile
import tempfile
import threading
import time
import unittest
import urllib.request
import hashlib
from typing import Any, Dict, List, Optional, Tuple

# Ensure repository root is on sys.path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from scripts.validate_elf import (
    ElfBinary,
    validate_elf,
    ARCH_NAMES,
    ARCH_BY_NAME,
    EM_AARCH64,
    EM_X86_64,
)
from tests.e2e.harness.termux_sim import (
    MockTermuxEnv,
    PlatformCapabilities,
    StorageSafetyError,
)


# ---------------------------------------------------------------------------
# 1. Multi-Arch Mock ELF Synthesis Engine
# ---------------------------------------------------------------------------

def synthesize_mock_elf(
    arch: str = "aarch64",
    page_align: int = 0x4000,
    interpreter: Optional[str] = "/system/bin/linker64",
    dt_needed: Optional[List[str]] = None,
    force_congruence_violation: bool = False,
    corrupt_magic: bool = False,
    is_64bit: bool = True,
    is_little_endian: bool = True,
) -> bytes:
    """
    Synthesizes bit-exact 64-bit ELF binaries for aarch64 (EM_AARCH64=183)
    and x86_64 (EM_X86_64=62) with Android 15+ 16 KiB PT_LOAD alignment and
    Bionic dynamic linking structures.
    """
    if corrupt_magic:
        return b"NOT_AN_ELF_BINARY_HEADER"

    if dt_needed is None:
        dt_needed = ["libc.so", "libdl.so"]

    endian = "<" if is_little_endian else ">"
    e_machine = EM_AARCH64 if arch == "aarch64" else EM_X86_64

    # 1. ELF Header (64 bytes for ELFCLASS64)
    ident = bytearray(16)
    ident[0:4] = b"\x7fELF"
    ident[4] = 2 if is_64bit else 1   # ELFCLASS64 / ELFCLASS32
    ident[5] = 1 if is_little_endian else 2  # ELFDATA2LSB / ELFDATA2MSB
    ident[6] = 1  # EV_CURRENT
    ident[7] = 0  # ELFOSABI_SYSV

    phentsize = 56
    phoff = 64
    ehsize = 64

    has_interp = interpreter is not None
    phnum = 5 if has_interp else 4

    elf_hdr = struct.pack(
        endian + "16sHHIQQQIHHHHHH",
        bytes(ident),
        3,          # e_type = ET_DYN (PIE / Shared Object)
        e_machine,  # e_machine
        1,          # e_version
        0x4000,     # e_entry
        phoff,      # e_phoff
        0,          # e_shoff
        0,          # e_flags
        ehsize,
        phentsize,
        phnum,
        0, 0, 0,
    )

    data = bytearray(elf_hdr)
    if len(data) < phoff:
        data.extend(b"\x00" * (phoff - len(data)))

    # Layout offsets
    interp_offset = 0x200
    interp_bytes = (interpreter.encode("utf-8") + b"\x00") if has_interp else b""
    interp_len = len(interp_bytes)

    dynstr_offset = 0x300
    dynstr = b"\x00"
    dt_offsets = []
    for lib in dt_needed:
        dt_offsets.append(len(dynstr))
        dynstr += lib.encode("utf-8") + b"\x00"

    dynamic_offset = 0x400

    load1_offset = 0x0
    load1_vaddr = 0x1000 if force_congruence_violation else 0x0
    load1_filesz = 0x1000
    load1_memsz = 0x1000

    load2_offset = 0x4000
    load2_vaddr = 0x4000
    load2_filesz = 0x1000
    load2_memsz = 0x1000

    # 2. Program Headers
    # 0: PT_PHDR (6)
    data.extend(
        struct.pack(
            endian + "IIQQQQQQ",
            6, 4, phoff, phoff, phoff, phnum * phentsize, phnum * phentsize, 8
        )
    )
    # 1: PT_INTERP (3)
    if has_interp:
        data.extend(
            struct.pack(
                endian + "IIQQQQQQ",
                3, 4, interp_offset, interp_offset, interp_offset, interp_len, interp_len, 1
            )
        )
    # 2: PT_LOAD 1 (RX)
    data.extend(
        struct.pack(
            endian + "IIQQQQQQ",
            1, 5, load1_offset, load1_vaddr, load1_vaddr, load1_filesz, load1_memsz, page_align
        )
    )
    # 3: PT_LOAD 2 (RW)
    data.extend(
        struct.pack(
            endian + "IIQQQQQQ",
            1, 6, load2_offset, load2_vaddr, load2_vaddr, load2_filesz, load2_memsz, page_align
        )
    )
    # 4: PT_DYNAMIC (2)
    data.extend(
        struct.pack(
            endian + "IIQQQQQQ",
            2, 6, dynamic_offset, dynamic_offset, dynamic_offset, 0x80, 0x80, 8
        )
    )

    # 3. Payload Sections
    if has_interp:
        if len(data) < interp_offset:
            data.extend(b"\x00" * (interp_offset - len(data)))
        data[interp_offset : interp_offset + interp_len] = interp_bytes

    if len(data) < dynstr_offset:
        data.extend(b"\x00" * (dynstr_offset - len(data)))
    data[dynstr_offset : dynstr_offset + len(dynstr)] = dynstr

    if len(data) < dynamic_offset:
        data.extend(b"\x00" * (dynamic_offset - len(data)))

    dyn_entries = []
    for off in dt_offsets:
        dyn_entries.append(struct.pack(endian + "QQ", 1, off))  # DT_NEEDED
    dyn_entries.append(struct.pack(endian + "QQ", 5, dynstr_offset))  # DT_STRTAB
    dyn_entries.append(struct.pack(endian + "QQ", 10, len(dynstr)))   # DT_STRSZ
    dyn_entries.append(struct.pack(endian + "QQ", 0, 0))              # DT_NULL
    dyn_bytes = b"".join(dyn_entries)
    data[dynamic_offset : dynamic_offset + len(dyn_bytes)] = dyn_bytes

    total_len = load2_offset + load2_filesz
    if len(data) < total_len:
        data.extend(b"\x00" * (total_len - len(data)))

    return bytes(data)


# ---------------------------------------------------------------------------
# 2. Release Packaging Utilities
# ---------------------------------------------------------------------------

def create_release_tarball(
    arch: str = "aarch64",
    version: str = "v1.0.0",
    elf_bytes: Optional[bytes] = None,
    custom_files: Optional[Dict[str, Tuple[bytes, int]]] = None,
) -> bytes:
    """
    Creates a standardized release .tar.gz archive containing:
    - grok (executable, mode 0o755)
    - LICENSE (mode 0o644)
    - README.md (mode 0o644)
    """
    if elf_bytes is None:
        elf_bytes = synthesize_mock_elf(arch=arch)

    files = {
        "grok": (elf_bytes, 0o755),
        "LICENSE": (b"Apache-2.0 / MIT License\n", 0o644),
        "README.md": (f"# grok-build-termux {version} ({arch})\n".encode("utf-8"), 0o644),
    }
    if custom_files:
        files.update(custom_files)

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for fname, (content, mode) in files.items():
            ti = tarfile.TarInfo(name=fname)
            ti.size = len(content)
            ti.mode = mode
            ti.mtime = int(time.time())
            tar.addfile(ti, io.BytesIO(content))

    return buf.getvalue()


def generate_sha256sums(files_dict: Dict[str, bytes]) -> str:
    """
    Generates standard GNU SHA256SUMS text manifest from a mapping of filename -> bytes.
    Format: '<sha256_hex>  <filename>\n'
    """
    lines = []
    for filename in sorted(files_dict.keys()):
        h = hashlib.sha256(files_dict[filename]).hexdigest().lower()
        lines.append(f"{h}  {filename}")
    return "\n".join(lines) + "\n"


def parse_and_verify_sha256sums(
    manifest_text: str, files_dict: Dict[str, bytes]
) -> Dict[str, bool]:
    """
    Parses SHA256SUMS manifest and verifies hash integrity against files_dict.
    Returns mapping of filename -> True/False.
    """
    results: Dict[str, bool] = {}
    for line in manifest_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("  ", 1)
        if len(parts) != 2:
            continue
        expected_hash, fname = parts[0].strip().lower(), parts[1].strip()
        if fname in files_dict:
            actual_hash = hashlib.sha256(files_dict[fname]).hexdigest().lower()
            results[fname] = (actual_hash == expected_hash)
        else:
            results[fname] = False
    return results


# ---------------------------------------------------------------------------
# 3. In-Process Mock GitHub Release Server
# ---------------------------------------------------------------------------

class MockGitHubReleaseHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Silence stdout logging in tests

    def do_GET(self):
        server: "MockGitHubReleaseServer" = self.server  # type: ignore
        server.request_log.append({
            "path": self.path,
            "headers": dict(self.headers),
            "method": "GET",
        })

        if self.path in server.status_overrides:
            code, body = server.status_overrides[self.path]
            self.send_response(code)
            self.end_headers()
            if body:
                self.wfile.write(body if isinstance(body, bytes) else body.encode("utf-8"))
            return

        # Route 1: Latest release
        if self.path == "/repos/ImL1s/grok-build-termux/releases/latest":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(server.latest_release).encode("utf-8"))
            return

        # Route 2: Tagged release
        if self.path.startswith("/repos/ImL1s/grok-build-termux/releases/tags/"):
            tag = self.path.split("/")[-1]
            if tag in server.tagged_releases:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(server.tagged_releases[tag]).encode("utf-8"))
                return
            self.send_response(404)
            self.end_headers()
            return

        # Route 3: File downloads
        for route_prefix, file_data in server.files.items():
            if self.path == route_prefix or self.path.endswith("/" + os.path.basename(route_prefix)):
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(file_data)))
                self.end_headers()
                self.wfile.write(file_data)
                return

        self.send_response(404)
        self.end_headers()


class MockGitHubReleaseServer(http.server.HTTPServer):
    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        super().__init__((host, port), MockGitHubReleaseHandler)
        self.server_port = self.socket.getsockname()[1]
        self.base_url = f"http://{host}:{self.server_port}"
        self.latest_release: Dict[str, Any] = {}
        self.tagged_releases: Dict[str, Dict[str, Any]] = {}
        self.files: Dict[str, bytes] = {}
        self.status_overrides: Dict[str, Tuple[int, Optional[bytes]]] = {}
        self.request_log: List[Dict[str, Any]] = []
        self._thread: Optional[threading.Thread] = None

    def setup_release(
        self,
        tag: str = "v1.0.0",
        aarch64_tarball: Optional[bytes] = None,
        x86_64_tarball: Optional[bytes] = None,
        sha256sums_content: Optional[str] = None,
    ):
        assets = []
        download_prefix = f"/repos/ImL1s/grok-build-termux/releases/download/{tag}"
        files_for_sums = {}

        if aarch64_tarball is not None:
            name = f"grok-build-termux-{tag}-aarch64-linux-android.tar.gz"
            self.files[f"{download_prefix}/{name}"] = aarch64_tarball
            files_for_sums[name] = aarch64_tarball
            assets.append({
                "name": name,
                "browser_download_url": f"{self.base_url}{download_prefix}/{name}",
                "size": len(aarch64_tarball),
            })

        if x86_64_tarball is not None:
            name = f"grok-build-termux-{tag}-x86_64-linux-android.tar.gz"
            self.files[f"{download_prefix}/{name}"] = x86_64_tarball
            files_for_sums[name] = x86_64_tarball
            assets.append({
                "name": name,
                "browser_download_url": f"{self.base_url}{download_prefix}/{name}",
                "size": len(x86_64_tarball),
            })

        if sha256sums_content is not None:
            sums_text = sha256sums_content
        else:
            sums_text = generate_sha256sums(files_for_sums)

        sums_bytes = sums_text.encode("utf-8")
        self.files[f"{download_prefix}/SHA256SUMS.txt"] = sums_bytes
        assets.append({
            "name": "SHA256SUMS.txt",
            "browser_download_url": f"{self.base_url}{download_prefix}/SHA256SUMS.txt",
            "size": len(sums_bytes),
        })

        release_json = {
            "tag_name": tag,
            "name": f"Release {tag}",
            "draft": False,
            "prerelease": False,
            "assets": assets,
        }
        self.latest_release = release_json
        self.tagged_releases[tag] = release_json

    def start(self):
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        self.shutdown()
        self.server_close()
        if self._thread:
            self._thread.join(timeout=2.0)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


# ---------------------------------------------------------------------------
# 4. Installer Simulation Engine
# ---------------------------------------------------------------------------

class InstallerError(Exception):
    pass


class ChecksumMismatchError(InstallerError):
    pass


class CorruptTarballError(InstallerError):
    pass


class InvalidElfError(InstallerError):
    pass


class InstallerSimulationEngine:
    """
    Opaque-box simulation engine for Termux ($PREFIX) and Standalone ($HOME) grok installer.
    Executes identical protocol steps as install.sh:
    1. Environment & storage safety validation
    2. GitHub API release discovery
    3. Tarball & checksum download
    4. SHA256 integrity verification
    5. Safe tar extraction in staging
    6. ELF binary validation (16 KiB alignment & Bionic dynamic linker)
    7. Atomic binary placement with 0o755 permissions
    """

    def __init__(
        self,
        api_base_url: str,
        custom_prefix: Optional[str] = None,
        custom_home: Optional[str] = None,
        target_arch: str = "aarch64",
        is_termux: bool = True,
    ):
        self.api_base_url = api_base_url
        self.target_arch = target_arch
        self.is_termux = is_termux
        self.prefix = custom_prefix if custom_prefix is not None else ("/data/data/com.termux/files/usr" if is_termux else "")
        self.home = custom_home or "/data/data/com.termux/files/home"
        self.installed_path: Optional[str] = None

    def run_install(self, version_tag: Optional[str] = None) -> Dict[str, Any]:
        # 1. Storage safety validation
        if self.prefix:
            PlatformCapabilities.validate_storage_safety(self.prefix)
        if self.home:
            PlatformCapabilities.validate_storage_safety(self.home)

        # 2. Determine target binary directory
        if self.is_termux and self.prefix:
            bin_dir = os.path.join(self.prefix, "bin")
        else:
            bin_dir = os.path.join(self.home, ".grok", "bin")

        os.makedirs(bin_dir, exist_ok=True)
        target_binary = os.path.join(bin_dir, "grok")

        # 3. Fetch release metadata from Mock API
        rel_url = f"{self.api_base_url}/repos/ImL1s/grok-build-termux/releases/latest"
        if version_tag:
            rel_url = f"{self.api_base_url}/repos/ImL1s/grok-build-termux/releases/tags/{version_tag}"

        try:
            req = urllib.request.urlopen(rel_url, timeout=5)
            rel_meta = json.loads(req.read().decode("utf-8"))
        except Exception as e:
            raise InstallerError(f"Failed to fetch release metadata from {rel_url}: {e}")

        tag = rel_meta.get("tag_name", "latest")

        # 4. Locate matching tarball & SHA256SUMS.txt in assets
        expected_arch_suffix = f"{self.target_arch}-linux-android"
        tarball_asset = None
        sums_asset = None
        for asset in rel_meta.get("assets", []):
            name = asset.get("name", "")
            if name.endswith(".tar.gz") and expected_arch_suffix in name:
                tarball_asset = asset
            elif name == "SHA256SUMS.txt" or name == "SHA256SUMS":
                sums_asset = asset

        if not tarball_asset:
            raise InstallerError(f"No release asset found for architecture {self.target_arch}")
        if not sums_asset:
            raise InstallerError("No SHA256SUMS.txt found in release assets")

        # 5. Fetch and parse SHA256SUMS.txt
        try:
            sums_req = urllib.request.urlopen(sums_asset["browser_download_url"], timeout=5)
            sums_text = sums_req.read().decode("utf-8")
        except Exception as e:
            raise InstallerError(f"Failed to download SHA256SUMS.txt: {e}")

        expected_hashes: Dict[str, str] = {}
        for line in sums_text.splitlines():
            line = line.strip()
            if line and "  " in line:
                h, fname = line.split("  ", 1)
                expected_hashes[fname.strip()] = h.strip().lower()

        tarball_name = tarball_asset["name"]
        expected_hash = expected_hashes.get(tarball_name)
        if not expected_hash:
            raise ChecksumMismatchError(f"Asset '{tarball_name}' not found in SHA256SUMS.txt")

        # 6. Download tarball into memory / temporary buffer
        try:
            tar_req = urllib.request.urlopen(tarball_asset["browser_download_url"], timeout=5)
            tar_bytes = tar_req.read()
        except Exception as e:
            raise InstallerError(f"Failed to download tarball asset: {e}")

        # 7. Checksum validation before extraction
        actual_hash = hashlib.sha256(tar_bytes).hexdigest().lower()
        if actual_hash != expected_hash:
            raise ChecksumMismatchError(
                f"Checksum mismatch for {tarball_name}: expected {expected_hash}, got {actual_hash}"
            )

        # 8. Unpack tarball safely
        try:
            tar = tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz")
        except Exception as e:
            raise CorruptTarballError(f"Failed to decompress tarball archive: {e}")

        extracted_binary_bytes: Optional[bytes] = None
        try:
            for member in tar.getmembers():
                if member.name == "grok" or member.name.endswith("/grok"):
                    f = tar.extractfile(member)
                    if f is not None:
                        extracted_binary_bytes = f.read()
                        break
        except Exception as e:
            raise CorruptTarballError(f"Corrupted tarball stream during extraction: {e}")

        if not extracted_binary_bytes:
            raise InstallerError("Tarball archive does not contain 'grok' executable")

        # 9. Verify ELF binary (16 KiB alignment & Bionic linker)
        elf = ElfBinary(extracted_binary_bytes, filename="grok")
        is_valid, errors, _ = validate_elf(
            elf,
            min_page_size=16384,
            strict_16k=True,
            target_arch=self.target_arch,
            bionic_only=True,
        )
        if not is_valid:
            raise InvalidElfError(f"Extracted binary failed ELF validation: {errors}")

        # 10. Atomic write to destination binary path with 0o755 permissions
        tmp_target = f"{target_binary}.tmp.{os.getpid()}"
        with open(tmp_target, "wb") as f:
            f.write(extracted_binary_bytes)
        os.chmod(tmp_target, 0o755)
        os.replace(tmp_target, target_binary)

        self.installed_path = target_binary
        return {
            "status": "success",
            "tag": tag,
            "installed_path": target_binary,
            "arch": self.target_arch,
            "is_termux": self.is_termux,
        }


# ---------------------------------------------------------------------------
# 5. Milestone 5 Test Suite (13 Test Cases)
# ---------------------------------------------------------------------------

class TestReleasePackaging(unittest.TestCase):
    """
    Milestone 5: Release Packaging Dry-Run & Installer Verification Test Suite.
    """

    def test_tarball_packaging_structure_aarch64(self):
        """
        Stage 2 (aarch64): Verify tarball packaging structure, naming, and file permissions.
        """
        tar_bytes = create_release_tarball(arch="aarch64", version="v1.0.0")
        self.assertGreater(len(tar_bytes), 0)

        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tar:
            members = {m.name: m for m in tar.getmembers()}
            self.assertIn("grok", members)
            self.assertIn("LICENSE", members)
            self.assertIn("README.md", members)

            grok_m = members["grok"]
            self.assertEqual(grok_m.mode & 0o777, 0o755)
            self.assertGreater(grok_m.size, 0)

            lic_m = members["LICENSE"]
            self.assertEqual(lic_m.mode & 0o777, 0o644)

            readme_m = members["README.md"]
            self.assertEqual(readme_m.mode & 0o777, 0o644)

    def test_tarball_packaging_structure_x86_64(self):
        """
        Stage 2 (x86_64): Verify x86_64 tarball packaging structure, naming, and file permissions.
        """
        tar_bytes = create_release_tarball(arch="x86_64", version="v1.0.0")
        self.assertGreater(len(tar_bytes), 0)

        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tar:
            members = {m.name: m for m in tar.getmembers()}
            self.assertIn("grok", members)
            self.assertIn("LICENSE", members)
            self.assertIn("README.md", members)

            grok_m = members["grok"]
            self.assertEqual(grok_m.mode & 0o777, 0o755)
            self.assertGreater(grok_m.size, 0)

            lic_m = members["LICENSE"]
            self.assertEqual(lic_m.mode & 0o777, 0o644)

            readme_m = members["README.md"]
            self.assertEqual(readme_m.mode & 0o777, 0o644)

    def test_sha256sums_generation_and_verification(self):
        """
        Stage 3: Verify SHA256SUMS.txt generation format and cryptographic verification integrity.
        """
        aarch64_tar = create_release_tarball(arch="aarch64", version="v1.0.0")
        x86_64_tar = create_release_tarball(arch="x86_64", version="v1.0.0")

        files = {
            "grok-build-termux-v1.0.0-aarch64-linux-android.tar.gz": aarch64_tar,
            "grok-build-termux-v1.0.0-x86_64-linux-android.tar.gz": x86_64_tar,
        }

        sums_text = generate_sha256sums(files)
        lines = sums_text.strip().splitlines()
        self.assertEqual(len(lines), 2)

        for line in lines:
            parts = line.split("  ")
            self.assertEqual(len(parts), 2)
            self.assertEqual(len(parts[0]), 64)
            int(parts[0], 16)  # Must be valid hex

        # Check verification of intact files
        verification = parse_and_verify_sha256sums(sums_text, files)
        self.assertTrue(all(verification.values()))

        # Tampering detection: modify 1 byte in aarch64_tar
        tampered_files = dict(files)
        tampered_files["grok-build-termux-v1.0.0-aarch64-linux-android.tar.gz"] = aarch64_tar[:-1] + b"\xff"
        tampered_verification = parse_and_verify_sha256sums(sums_text, tampered_files)
        self.assertFalse(tampered_verification["grok-build-termux-v1.0.0-aarch64-linux-android.tar.gz"])
        self.assertTrue(tampered_verification["grok-build-termux-v1.0.0-x86_64-linux-android.tar.gz"])

    def test_extracted_elf_binary_16k_alignment_aarch64(self):
        """
        Stage 4 & 5 (aarch64): Extract binary from aarch64 tarball and validate 16 KiB alignment and Bionic dynamic linker.
        """
        tar_bytes = create_release_tarball(arch="aarch64", version="v1.0.0")
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tar:
            f = tar.extractfile("grok")
            self.assertIsNotNone(f)
            elf_bytes = f.read()

        elf = ElfBinary(elf_bytes, filename="grok-aarch64")
        is_valid, errors, _ = validate_elf(
            elf,
            min_page_size=16384,
            strict_16k=True,
            target_arch="aarch64",
            bionic_only=True,
        )

        self.assertTrue(is_valid, f"Validation errors: {errors}")
        self.assertEqual(errors, [])
        self.assertEqual(elf.e_machine, EM_AARCH64)
        self.assertTrue(elf.is_64bit)
        self.assertEqual(elf.interpreter, "/system/bin/linker64")

        load_segments = [s for s in elf.segments if s.p_type == 1]
        self.assertGreater(len(load_segments), 0)
        for seg in load_segments:
            self.assertEqual(seg.p_align, 0x4000)
            self.assertEqual(seg.p_vaddr % seg.p_align, seg.p_offset % seg.p_align)

    def test_extracted_elf_binary_16k_alignment_x86_64(self):
        """
        Stage 4 & 5 (x86_64): Extract binary from x86_64 tarball and validate 16 KiB alignment and Bionic dynamic linker.
        """
        tar_bytes = create_release_tarball(arch="x86_64", version="v1.0.0")
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tar:
            f = tar.extractfile("grok")
            self.assertIsNotNone(f)
            elf_bytes = f.read()

        elf = ElfBinary(elf_bytes, filename="grok-x86_64")
        is_valid, errors, _ = validate_elf(
            elf,
            min_page_size=16384,
            strict_16k=True,
            target_arch="x86_64",
            bionic_only=True,
        )

        self.assertTrue(is_valid, f"Validation errors: {errors}")
        self.assertEqual(errors, [])
        self.assertEqual(elf.e_machine, EM_X86_64)
        self.assertTrue(elf.is_64bit)
        self.assertEqual(elf.interpreter, "/system/bin/linker64")

        load_segments = [s for s in elf.segments if s.p_type == 1]
        self.assertGreater(len(load_segments), 0)
        for seg in load_segments:
            self.assertEqual(seg.p_align, 0x4000)
            self.assertEqual(seg.p_vaddr % seg.p_align, seg.p_offset % seg.p_align)

    def test_simulated_installer_termux_aarch64_happy_path(self):
        """
        Stage 6 (Termux aarch64): Simulated Termux install flow installs cleanly to $PREFIX/bin/grok.
        """
        with MockTermuxEnv(is_android=True) as env:
            aarch64_tar = create_release_tarball(arch="aarch64", version="v1.0.0")
            x86_64_tar = create_release_tarball(arch="x86_64", version="v1.0.0")

            with MockGitHubReleaseServer() as server:
                server.setup_release(
                    tag="v1.0.0",
                    aarch64_tarball=aarch64_tar,
                    x86_64_tarball=x86_64_tar,
                )

                engine = InstallerSimulationEngine(
                    api_base_url=server.base_url,
                    custom_prefix=env.prefix_dir,
                    custom_home=env.home_dir,
                    target_arch="aarch64",
                    is_termux=True,
                )

                receipt = engine.run_install()
                self.assertEqual(receipt["status"], "success")
                self.assertEqual(receipt["tag"], "v1.0.0")
                self.assertEqual(receipt["installed_path"], os.path.join(env.bin_dir, "grok"))

                installed_bin = os.path.join(env.bin_dir, "grok")
                self.assertTrue(os.path.exists(installed_bin))
                st = os.stat(installed_bin)
                self.assertEqual(st.st_mode & 0o777, 0o755)

                with open(installed_bin, "rb") as f:
                    installed_elf = ElfBinary(f.read())
                valid, errs, _ = validate_elf(
                    installed_elf, strict_16k=True, target_arch="aarch64", bionic_only=True
                )
                self.assertTrue(valid)

    def test_simulated_installer_termux_x86_64_happy_path(self):
        """
        Stage 6 (Termux x86_64): Simulated Termux install flow installs cleanly to $PREFIX/bin/grok.
        """
        with MockTermuxEnv(is_android=True) as env:
            aarch64_tar = create_release_tarball(arch="aarch64", version="v1.0.0")
            x86_64_tar = create_release_tarball(arch="x86_64", version="v1.0.0")

            with MockGitHubReleaseServer() as server:
                server.setup_release(
                    tag="v1.0.0",
                    aarch64_tarball=aarch64_tar,
                    x86_64_tarball=x86_64_tar,
                )

                engine = InstallerSimulationEngine(
                    api_base_url=server.base_url,
                    custom_prefix=env.prefix_dir,
                    custom_home=env.home_dir,
                    target_arch="x86_64",
                    is_termux=True,
                )

                receipt = engine.run_install()
                self.assertEqual(receipt["status"], "success")
                self.assertEqual(receipt["installed_path"], os.path.join(env.bin_dir, "grok"))

                installed_bin = os.path.join(env.bin_dir, "grok")
                self.assertTrue(os.path.exists(installed_bin))
                st = os.stat(installed_bin)
                self.assertEqual(st.st_mode & 0o777, 0o755)

                with open(installed_bin, "rb") as f:
                    installed_elf = ElfBinary(f.read())
                valid, errs, _ = validate_elf(
                    installed_elf, strict_16k=True, target_arch="x86_64", bionic_only=True
                )
                self.assertTrue(valid)

    def test_simulated_installer_standalone_fallback(self):
        """
        Stage 6 (Standalone Fallback): When $PREFIX is unset, falls back to $HOME/.grok/bin/grok.
        """
        with MockTermuxEnv(is_android=False) as env:
            aarch64_tar = create_release_tarball(arch="aarch64", version="v1.0.0")

            with MockGitHubReleaseServer() as server:
                server.setup_release(
                    tag="v1.0.0",
                    aarch64_tarball=aarch64_tar,
                )

                engine = InstallerSimulationEngine(
                    api_base_url=server.base_url,
                    custom_prefix="",
                    custom_home=env.home_dir,
                    target_arch="aarch64",
                    is_termux=False,
                )

                receipt = engine.run_install()
                expected_bin = os.path.join(env.home_dir, ".grok", "bin", "grok")
                self.assertEqual(receipt["status"], "success")
                self.assertEqual(receipt["installed_path"], expected_bin)
                self.assertTrue(os.path.exists(expected_bin))

                st = os.stat(expected_bin)
                self.assertEqual(st.st_mode & 0o777, 0o755)

    def test_adversarial_checksum_mismatch_aborts_install(self):
        """
        Adversarial: Tampered tarball checksum in SHA256SUMS.txt aborts installation immediately.
        Invariant: Existing binary in $PREFIX/bin/grok is untouched, no temp files left behind.
        """
        with MockTermuxEnv(is_android=True) as env:
            sentinel_path = os.path.join(env.bin_dir, "grok")
            with open(sentinel_path, "wb") as f:
                f.write(b"PREVIOUS_GOOD_BINARY_CONTENT")
            os.chmod(sentinel_path, 0o755)

            valid_tar = create_release_tarball(arch="aarch64", version="v1.0.0")
            tampered_sums = (
                "0000000000000000000000000000000000000000000000000000000000000000  "
                "grok-build-termux-v1.0.0-aarch64-linux-android.tar.gz\n"
            )

            with MockGitHubReleaseServer() as server:
                server.setup_release(
                    tag="v1.0.0",
                    aarch64_tarball=valid_tar,
                    sha256sums_content=tampered_sums,
                )

                engine = InstallerSimulationEngine(
                    api_base_url=server.base_url,
                    custom_prefix=env.prefix_dir,
                    custom_home=env.home_dir,
                    target_arch="aarch64",
                    is_termux=True,
                )

                with self.assertRaises(ChecksumMismatchError) as ctx:
                    engine.run_install()

                self.assertIn("Checksum mismatch", str(ctx.exception))

            # Safety Invariants
            self.assertTrue(os.path.exists(sentinel_path))
            with open(sentinel_path, "rb") as f:
                self.assertEqual(f.read(), b"PREVIOUS_GOOD_BINARY_CONTENT")

            bin_files = os.listdir(env.bin_dir)
            self.assertEqual(bin_files, ["grok"])

    def test_adversarial_corrupt_tarball_fails_safely(self):
        """
        Adversarial: Truncated or malformed tarball stream causes clean decompression abort.
        """
        with MockTermuxEnv(is_android=True) as env:
            # Gzip magic followed by random truncated garbage
            corrupt_tar = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\xff" + b"TRUNCATED_GARBAGE_PAYLOAD"

            with MockGitHubReleaseServer() as server:
                server.setup_release(
                    tag="v1.0.0",
                    aarch64_tarball=corrupt_tar,
                )

                engine = InstallerSimulationEngine(
                    api_base_url=server.base_url,
                    custom_prefix=env.prefix_dir,
                    custom_home=env.home_dir,
                    target_arch="aarch64",
                    is_termux=True,
                )

                with self.assertRaises(CorruptTarballError) as ctx:
                    engine.run_install()

                self.assertIn("decompress", str(ctx.exception).lower())

            # Safety Invariant: Target binary directory has no partial files
            self.assertEqual(os.listdir(env.bin_dir), [])

    def test_adversarial_legacy_4k_elf_rejected_in_packaging(self):
        """
        Adversarial: Legacy 4 KiB aligned ELF binary is rejected during packaging validation.
        """
        mock_4k_elf = synthesize_mock_elf(arch="aarch64", page_align=0x1000)
        elf = ElfBinary(mock_4k_elf, filename="mock_4k")

        is_valid, errors, _ = validate_elf(
            elf,
            min_page_size=16384,
            strict_16k=True,
            target_arch="aarch64",
            bionic_only=True,
        )

        self.assertFalse(is_valid)
        self.assertTrue(any("is less than required 16384" in err for err in errors))

        # Test installer rejection of 4k tarball
        with MockTermuxEnv(is_android=True) as env:
            tar_4k = create_release_tarball(arch="aarch64", version="v1.0.0", elf_bytes=mock_4k_elf)
            with MockGitHubReleaseServer() as server:
                server.setup_release(tag="v1.0.0", aarch64_tarball=tar_4k)
                engine = InstallerSimulationEngine(
                    api_base_url=server.base_url,
                    custom_prefix=env.prefix_dir,
                    custom_home=env.home_dir,
                    target_arch="aarch64",
                    is_termux=True,
                )
                with self.assertRaises(InvalidElfError) as ctx:
                    engine.run_install()
                self.assertIn("failed ELF validation", str(ctx.exception))

            self.assertEqual(os.listdir(env.bin_dir), [])

    def test_adversarial_glibc_elf_rejected_in_packaging(self):
        """
        Adversarial: Desktop Linux glibc ELF is rejected for Android Bionic packaging.
        """
        mock_glibc_elf = synthesize_mock_elf(
            arch="x86_64",
            interpreter="/lib64/ld-linux-x86-64.so.2",
            dt_needed=["libc.so.6"],
        )
        elf = ElfBinary(mock_glibc_elf, filename="mock_glibc")

        is_valid, errors, _ = validate_elf(
            elf,
            min_page_size=16384,
            strict_16k=True,
            target_arch="x86_64",
            bionic_only=True,
        )

        self.assertFalse(is_valid)
        self.assertTrue(any("glibc" in err.lower() for err in errors))

        # Test installer rejection of glibc tarball
        with MockTermuxEnv(is_android=True) as env:
            tar_glibc = create_release_tarball(arch="x86_64", version="v1.0.0", elf_bytes=mock_glibc_elf)
            with MockGitHubReleaseServer() as server:
                server.setup_release(tag="v1.0.0", x86_64_tarball=tar_glibc)
                engine = InstallerSimulationEngine(
                    api_base_url=server.base_url,
                    custom_prefix=env.prefix_dir,
                    custom_home=env.home_dir,
                    target_arch="x86_64",
                    is_termux=True,
                )
                with self.assertRaises(InvalidElfError) as ctx:
                    engine.run_install()
                self.assertIn("failed ELF validation", str(ctx.exception))

            self.assertEqual(os.listdir(env.bin_dir), [])

    def test_adversarial_install_to_sdcard_quarantine(self):
        """
        Adversarial: Attempts to install to /sdcard or /storage/emulated/0 trigger StorageSafetyError.
        """
        unsafe_targets = [
            "/sdcard",
            "/sdcard/bin",
            "/storage/emulated/0",
            "/storage/emulated/0/grok",
            "/mnt/sdcard",
            "/data/data/com.termux/files/usr/../../../../sdcard",
        ]

        with MockGitHubReleaseServer() as server:
            server.setup_release(tag="v1.0.0")

            for unsafe_path in unsafe_targets:
                engine = InstallerSimulationEngine(
                    api_base_url=server.base_url,
                    custom_prefix=unsafe_path,
                    custom_home=unsafe_path,
                    target_arch="aarch64",
                    is_termux=False,
                )

                with self.assertRaises(StorageSafetyError) as ctx:
                    engine.run_install()

                self.assertIn("cannot reside on Android shared storage", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
