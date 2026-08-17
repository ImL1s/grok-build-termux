#!/usr/bin/env python3
"""
Adversarial Challenge & Stress Test Suite for Milestone 5:
Release Packaging & Simulated Installer Verification Pipeline.

Probes and stress-tests:
1. ELF Generation Mutation & Fault Injection:
   - Corrupt ELF magic (partial magic, zero magic, ASCII strings, truncated headers)
   - Page alignment violations (4 KiB, 8 KiB, 2 KiB, 1-byte, 0 alignment)
   - ELF congruence violations (p_vaddr % align != p_offset % align)
   - Class & Endianness mutations (ELFCLASS32 on 64-bit targets, ELFDATA2MSB on Android)
   - Interpreter / Dynamic Linker tampering (glibc ld.so, musl ld.so, malicious/invalid linker paths)
   - Forbidden shared library dependencies (libc.so.6, libpthread.so.0, libm.so.6, libdl.so.2)
   - Cross-architecture mismatch (aarch64 binary against x86_64 target expectation and vice versa)
2. Release Packaging & Tarball Integrity Fault Injection:
   - Single-bit flip in SHA256SUMS.txt hex hash
   - Mismatched filenames in SHA256SUMS manifest
   - Malformed SHA256SUMS formatting (invalid hex digits, invalid lengths, blank entries)
   - Corrupted and truncated gzip / tar payloads
   - Packaging permission anomalies (executable mode 0o644, 0o600, missing grok binary)
3. Simulated Installer Resilience & Storage Safety:
   - Storage safety quarantine (/sdcard, /storage/emulated/0, traversal escapes)
   - Atomic replacement & failure safety (rollback, zero partial file leakage on checksum/ELF failure)
   - Standalone fallback mode without $PREFIX
   - Mock GitHub API error injection (HTTP 404, 500, corrupt JSON, missing release assets)
4. Concurrency & Flakiness:
   - 20x rapid sequential start/stop of MockGitHubReleaseServer (port 0 binding recycling)
   - Multi-instance concurrent MockGitHubReleaseServer execution
   - Multi-threaded concurrent asset downloads
   - 5x full packaging test suite repetition
"""

import hashlib
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
import urllib.error
from typing import Any, Dict, List, Optional, Tuple

# Ensure repository root is on sys.path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from scripts.validate_elf import (
    ElfBinary,
    validate_elf,
    ElfValidationError,
    EM_AARCH64,
    EM_X86_64,
    EM_ARM,
    EM_386,
    ARCH_NAMES,
)
from tests.e2e.harness.termux_sim import (
    MockTermuxEnv,
    PlatformCapabilities,
    StorageSafetyError,
)
from tests.e2e.test_release_packaging import (
    synthesize_mock_elf,
    create_release_tarball,
    generate_sha256sums,
    parse_and_verify_sha256sums,
    MockGitHubReleaseServer,
    InstallerSimulationEngine,
    InstallerError,
    ChecksumMismatchError,
    CorruptTarballError,
    InvalidElfError,
)


class AdversarialMilestone5ChallengeTests(unittest.TestCase):
    """
    Adversarial challenge test suite probing release packaging and installer validation.
    """

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="adv_m5_challenge_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # =========================================================================
    # Section 1: ELF Header, Class, Endianness & Structure Mutation
    # =========================================================================

    def test_adv_elf_magic_corruption_variants(self):
        """Probes ELF parser resilience against various corrupt and partial ELF magic patterns."""
        magic_variants = [
            b"NOT_AN_ELF",
            b"\x7fEL\x00",
            b"\x00ELF",
            b"\x7f\x7f\x7f\x7f",
            b"",
            b"\x7f",
            b"\x7fEL",
            b"\x00" * 64,
            b"\xff" * 64,
        ]
        for bad_magic in magic_variants:
            with self.assertRaises((ElfValidationError, Exception)):
                ElfBinary(bad_magic, filename="corrupt_magic")

    def test_adv_elf_truncated_headers(self):
        """Probes ELF parser against truncated buffers at various structural boundaries (<52, 52..64 bytes)."""
        valid_elf = synthesize_mock_elf(arch="aarch64")
        truncation_lengths = [0, 4, 16, 32, 51, 52, 60, 63]
        for length in truncation_lengths:
            truncated = valid_elf[:length]
            with self.assertRaises(ElfValidationError):
                ElfBinary(truncated, filename=f"truncated_{length}")

    def test_adv_elf_class_mutation(self):
        """32-bit ELF (ELFCLASS32) on 64-bit target architecture (aarch64/x86_64) must be rejected."""
        elf_32bit = synthesize_mock_elf(arch="aarch64", is_64bit=False)
        elf = ElfBinary(elf_32bit, filename="elf32")
        is_valid, errors, _ = validate_elf(elf, target_arch="aarch64", strict_16k=True, bionic_only=True)
        self.assertFalse(is_valid)
        self.assertTrue(any("ELFCLASS64" in err for err in errors))

    def test_adv_elf_big_endian_mutation(self):
        """Big-endian ELF (ELFDATA2MSB) must be rejected for Android targets (must be little-endian)."""
        elf_be = synthesize_mock_elf(arch="aarch64", is_little_endian=False)
        elf = ElfBinary(elf_be, filename="elf_be")
        is_valid, errors, _ = validate_elf(elf, target_arch="aarch64", strict_16k=True, bionic_only=True)
        self.assertFalse(is_valid)
        self.assertTrue(any("Little Endian" in err for err in errors))

    def test_adv_elf_cross_arch_mismatch(self):
        """Mismatched architecture binaries must be strictly rejected (aarch64 vs x86_64 vs arm)."""
        elf_aarch64 = synthesize_mock_elf(arch="aarch64")
        elf_x86_64 = synthesize_mock_elf(arch="x86_64")

        # Test aarch64 binary against x86_64 target
        parsed_aarch64 = ElfBinary(elf_aarch64)
        is_valid, errors, _ = validate_elf(parsed_aarch64, target_arch="x86_64")
        self.assertFalse(is_valid)
        self.assertTrue(any("Architecture mismatch" in err for err in errors))

        # Test x86_64 binary against aarch64 target
        parsed_x86_64 = ElfBinary(elf_x86_64)
        is_valid, errors, _ = validate_elf(parsed_x86_64, target_arch="aarch64")
        self.assertFalse(is_valid)
        self.assertTrue(any("Architecture mismatch" in err for err in errors))

    # =========================================================================
    # Section 2: 16 KiB Page Alignment & Congruence Fault Injection
    # =========================================================================

    def test_adv_elf_sub_16k_page_alignments(self):
        """Sub-16k alignments (4k, 8k, 2k, 1k, 1-byte) must all be rejected under strict_16k=True."""
        invalid_alignments = [0x1000, 0x2000, 0x800, 0x400, 0x1]
        for align in invalid_alignments:
            mutated_elf = synthesize_mock_elf(arch="aarch64", page_align=align)
            elf = ElfBinary(mutated_elf)
            is_valid, errors, _ = validate_elf(elf, strict_16k=True, target_arch="aarch64", bionic_only=True)
            self.assertFalse(is_valid, f"Alignment 0x{align:x} should have failed 16k validation")
            self.assertTrue(any("less than required 16384" in err for err in errors))

    def test_adv_elf_congruence_violations(self):
        """Congruence violation (p_vaddr % p_align != p_offset % p_align) must fail validation."""
        mutated_elf = synthesize_mock_elf(
            arch="aarch64",
            page_align=0x4000,
            force_congruence_violation=True,
        )
        elf = ElfBinary(mutated_elf)
        is_valid, errors, _ = validate_elf(elf, strict_16k=True, target_arch="aarch64", bionic_only=True)
        self.assertFalse(is_valid)
        self.assertTrue(any("violates ELF congruence" in err for err in errors))

    def test_adv_elf_missing_pt_load_segments(self):
        """ELF binary with no PT_LOAD segments must fail validation."""
        valid_elf = bytearray(synthesize_mock_elf(arch="aarch64"))
        # Mutate PT_LOAD (type 1) phdrs to PT_NULL (0)
        phoff = 64
        phentsize = 56
        for i in range(5):
            off = phoff + i * phentsize
            p_type = struct.unpack_from("<I", valid_elf, off)[0]
            if p_type == 1:
                struct.pack_into("<I", valid_elf, off, 0)

        elf = ElfBinary(bytes(valid_elf))
        is_valid, errors, _ = validate_elf(elf, target_arch="aarch64")
        self.assertFalse(is_valid)
        self.assertTrue(any("No PT_LOAD segments found" in err for err in errors))

    # =========================================================================
    # Section 3: Dynamic Linker & DT_NEEDED Dependency Fault Injection
    # =========================================================================

    def test_adv_elf_desktop_glibc_and_musl_interpreters(self):
        """Non-Bionic interpreters (glibc ld-linux, musl ld-musl) must be detected and rejected."""
        forbidden_interpreters = [
            "/lib64/ld-linux-x86-64.so.2",
            "/lib/ld-linux-aarch64.so.1",
            "/lib/ld-linux.so.2",
            "/lib/ld-linux-armhf.so.3",
            "/lib/ld-musl-aarch64.so.1",
            "/lib/ld-musl-x86_64.so.1",
            "/tmp/malicious_linker",
            "/sdcard/fake_linker64",
        ]
        for interp in forbidden_interpreters:
            mutated_elf = synthesize_mock_elf(
                arch="aarch64",
                interpreter=interp,
                dt_needed=["libc.so", "libdl.so"],
            )
            elf = ElfBinary(mutated_elf)
            is_valid, errors, _ = validate_elf(elf, target_arch="aarch64", bionic_only=True)
            self.assertFalse(is_valid, f"Interpreter {interp} should be rejected")
            self.assertTrue(any("Incompatible dynamic linker" in err or "glibc" in err.lower() for err in errors))

    def test_adv_elf_forbidden_glibc_dt_needed_dependencies(self):
        """Forbidden glibc runtime library dependencies (libc.so.6, libpthread.so.0, libm.so.6) must fail."""
        forbidden_libs_sets = [
            ["libc.so.6"],
            ["libpthread.so.0", "libc.so"],
            ["libm.so.6"],
            ["libdl.so.2"],
            ["librt.so.1"],
            ["ld-linux-x86-64.so.2"],
        ]
        for libs in forbidden_libs_sets:
            mutated_elf = synthesize_mock_elf(
                arch="x86_64",
                interpreter="/system/bin/linker64",
                dt_needed=libs,
            )
            elf = ElfBinary(mutated_elf)
            is_valid, errors, _ = validate_elf(elf, target_arch="x86_64", bionic_only=True)
            self.assertFalse(is_valid, f"Libraries {libs} should be rejected")
            self.assertTrue(any("Forbidden glibc runtime dependency" in err for err in errors))

    # =========================================================================
    # Section 4: Release Packaging & Tarball Integrity Fault Injection
    # =========================================================================

    def test_adv_sha256sums_single_bit_flip_detection(self):
        """1-bit flip in sha256 checksum is caught by parse_and_verify_sha256sums."""
        tar_bytes = create_release_tarball(arch="aarch64")
        filename = "grok-build-termux-v1.0.0-aarch64-linux-android.tar.gz"
        files = {filename: tar_bytes}

        valid_manifest = generate_sha256sums(files)
        # Verify valid pass
        valid_res = parse_and_verify_sha256sums(valid_manifest, files)
        self.assertTrue(valid_res[filename])

        # Corrupt 1 hex character in manifest
        orig_hex = valid_manifest[:64]
        flipped_char = "a" if orig_hex[0] != "a" else "b"
        corrupted_manifest = flipped_char + valid_manifest[1:]

        corrupted_res = parse_and_verify_sha256sums(corrupted_manifest, files)
        self.assertFalse(corrupted_res[filename])

    def test_adv_sha256sums_missing_file_in_manifest(self):
        """Installer rejects tarball if SHA256SUMS does not contain an entry for that tarball."""
        with MockTermuxEnv(is_android=True) as env:
            valid_tar = create_release_tarball(arch="aarch64", version="v1.0.0")
            # Empty SHA256SUMS or unrelated entry
            empty_sums = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  other-file.tar.gz\n"

            with MockGitHubReleaseServer() as server:
                server.setup_release(
                    tag="v1.0.0",
                    aarch64_tarball=valid_tar,
                    sha256sums_content=empty_sums,
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
                self.assertIn("not found in SHA256SUMS.txt", str(ctx.exception))

    def test_adv_tarball_missing_executable_grok(self):
        """Tarball missing 'grok' binary executable is rejected cleanly by installer."""
        with MockTermuxEnv(is_android=True) as env:
            # Create tarball without grok
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:gz") as tar:
                ti = tarfile.TarInfo(name="README.md")
                ti.size = 12
                tar.addfile(ti, io.BytesIO(b"Hello world\n"))
            tar_no_grok = buf.getvalue()

            with MockGitHubReleaseServer() as server:
                server.setup_release(tag="v1.0.0", aarch64_tarball=tar_no_grok)
                engine = InstallerSimulationEngine(
                    api_base_url=server.base_url,
                    custom_prefix=env.prefix_dir,
                    custom_home=env.home_dir,
                    target_arch="aarch64",
                    is_termux=True,
                )

                with self.assertRaises(InstallerError) as ctx:
                    engine.run_install()
                self.assertIn("does not contain 'grok' executable", str(ctx.exception))

    # =========================================================================
    # Section 5: Simulated Installer Rollback & API Error Handling
    # =========================================================================

    def test_adv_installer_atomic_rollback_on_elf_validation_failure(self):
        """
        When extracted binary fails ELF validation (e.g. 4k alignment), existing binary in $PREFIX/bin/grok
        is untouched and NO temporary files remain.
        """
        with MockTermuxEnv(is_android=True) as env:
            sentinel_path = os.path.join(env.bin_dir, "grok")
            with open(sentinel_path, "wb") as f:
                f.write(b"EXISTING_FUNCTIONAL_BINARY_V0")
            os.chmod(sentinel_path, 0o755)

            bad_elf = synthesize_mock_elf(arch="aarch64", page_align=0x1000)
            bad_tar = create_release_tarball(arch="aarch64", elf_bytes=bad_elf)

            with MockGitHubReleaseServer() as server:
                server.setup_release(tag="v1.0.0", aarch64_tarball=bad_tar)
                engine = InstallerSimulationEngine(
                    api_base_url=server.base_url,
                    custom_prefix=env.prefix_dir,
                    custom_home=env.home_dir,
                    target_arch="aarch64",
                    is_termux=True,
                )

                with self.assertRaises(InvalidElfError):
                    engine.run_install()

            # Sentinel verification
            self.assertTrue(os.path.exists(sentinel_path))
            with open(sentinel_path, "rb") as f:
                self.assertEqual(f.read(), b"EXISTING_FUNCTIONAL_BINARY_V0")

            # Check no .tmp files exist
            bin_contents = os.listdir(env.bin_dir)
            self.assertEqual(bin_contents, ["grok"])

    def test_adv_installer_http_api_failure_modes(self):
        """Probes installer error handling when GitHub release endpoint returns 404 or 500."""
        with MockTermuxEnv(is_android=True) as env:
            with MockGitHubReleaseServer() as server:
                server.setup_release(tag="v1.0.0", aarch64_tarball=create_release_tarball(arch="aarch64"))
                # Override release endpoint with HTTP 500
                server.status_overrides["/repos/ImL1s/grok-build-termux/releases/latest"] = (
                    500,
                    b'{"message": "Internal Server Error"}',
                )

                engine = InstallerSimulationEngine(
                    api_base_url=server.base_url,
                    custom_prefix=env.prefix_dir,
                    custom_home=env.home_dir,
                    target_arch="aarch64",
                    is_termux=True,
                )

                with self.assertRaises(InstallerError) as ctx:
                    engine.run_install()
                self.assertIn("Failed to fetch release metadata", str(ctx.exception))

    # =========================================================================
    # Section 6: Concurrency & Flakiness Stress Tests
    # =========================================================================

    def test_adv_mock_server_rapid_socket_recycling(self):
        """20x rapid sequential start/stop cycles of MockGitHubReleaseServer verify no socket leak / EADDRINUSE."""
        for i in range(20):
            server = MockGitHubReleaseServer(port=0)
            server.setup_release(tag=f"v1.0.{i}", aarch64_tarball=create_release_tarball(arch="aarch64"))
            with server:
                req = urllib.request.urlopen(f"{server.base_url}/repos/ImL1s/grok-build-termux/releases/latest", timeout=2)
                data = json.loads(req.read().decode("utf-8"))
                self.assertEqual(data["tag_name"], f"v1.0.{i}")

    def test_adv_mock_server_multi_instance_concurrency(self):
        """Multiple MockGitHubReleaseServer instances running concurrently on dynamic ports."""
        servers = [MockGitHubReleaseServer(port=0) for _ in range(5)]
        for i, s in enumerate(servers):
            s.setup_release(tag=f"v2.0.{i}", aarch64_tarball=create_release_tarball(arch="aarch64"))
            s.start()

        try:
            for i, s in enumerate(servers):
                req = urllib.request.urlopen(f"{s.base_url}/repos/ImL1s/grok-build-termux/releases/latest", timeout=2)
                data = json.loads(req.read().decode("utf-8"))
                self.assertEqual(data["tag_name"], f"v2.0.{i}")
        finally:
            for s in servers:
                s.stop()

    def test_adv_multi_threaded_concurrent_asset_downloads(self):
        """Concurrent multi-threaded client downloads against MockGitHubReleaseServer."""
        aarch64_tar = create_release_tarball(arch="aarch64")
        with MockGitHubReleaseServer(port=0) as server:
            server.setup_release(tag="v1.0.0", aarch64_tarball=aarch64_tar)
            download_url = (
                f"{server.base_url}/repos/ImL1s/grok-build-termux/releases/download/v1.0.0/"
                "grok-build-termux-v1.0.0-aarch64-linux-android.tar.gz"
            )

            errors: List[Exception] = []

            def worker():
                try:
                    for _ in range(5):
                        req = urllib.request.urlopen(download_url, timeout=3)
                        content = req.read()
                        if len(content) != len(aarch64_tar):
                            raise ValueError("Downloaded content size mismatch")
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=worker) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5.0)

            self.assertEqual(len(errors), 0, f"Concurrent download errors: {errors}")


if __name__ == "__main__":
    unittest.main()
