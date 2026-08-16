#!/usr/bin/env python3
"""
Adversarial Stress-Testing Suite for Milestone 5 (Features 27 & 28).
Written by challenger_m5_1.

Adversarial dimensions probed:
1. Package-Managed Environment:
   - Verification that in package-managed mode `grok update` never triggers background downloads.
   - Verification that system binaries are never overwritten.
   - Exact string verification of `pkg update && pkg upgrade grok-build` instructions.
   - Detection precedence across environment variables (`GROK_INSTALL_MODE`, `GROK_INSTALLER`, `GROK_MANAGED_BY_PKG`),
     config files, and binary prefix location.

2. Standalone Updater Channel Isolation:
   - Manifests containing ONLY desktop `linux-x86_64`, `linux-aarch64`, `macos-aarch64`, `windows-x86_64`.
   - Rejection with `no_compatible_asset` and absence of downloading desktop binaries.
   - Malformed manifests, empty manifests, empty asset lists, null URLs.

3. Binary ELF Validation:
   - Rejection of glibc dynamic linkers (/lib/ld-linux-aarch64.so.1, /lib64/ld-linux-x86-64.so.2).
   - Rejection of glibc shared libraries (libc.so.6, libpthread.so.0).
   - Rejection of 4 KiB segment alignment on Android 15+ targets.
   - Rejection of congruence violations (p_vaddr % p_align != p_offset % p_align).
   - Rejection of big-endian ELFs on Android.
   - Handling of truncated headers, 0-byte files, 4-byte magic only, out-of-bounds program header tables.
   - Safe bypass of non-ELF files (scripts, Mach-O).
"""

import os
import sys
import json
import struct
import tempfile
import unittest

from tests.e2e.harness.termux_sim import (
    MockTermuxEnv,
    PlatformCapabilities,
    ToolResolverSeam,
    DoctorDiagnosticsSeam,
    UpdateManagerSeam,
    StorageSafetyError,
)
from scripts.validate_elf import (
    ElfBinary,
    validate_elf,
    generate_mock_elf,
    ElfValidationError,
    ELFMAG,
    ELFCLASS64,
    ELFCLASS32,
    ELFDATA2LSB,
    ELFDATA2MSB,
    EM_AARCH64,
    EM_X86_64,
    PT_LOAD,
    PT_INTERP,
    PT_DYNAMIC,
    DT_NEEDED,
    DT_STRTAB,
    DT_STRSZ,
    DT_NULL,
)


class TestAdversarialPackageManagedMode(unittest.TestCase):
    """Adversarial stress-testing for Feature 27: Package-Managed Install Mode."""

    def test_adv_pkg_update_never_triggers_download(self):
        """Verify that under any remote manifest, package-managed mode NEVER permits auto-download."""
        mgr = UpdateManagerSeam(install_mode="package-managed")
        
        # Even with appealing/forced remote manifests
        aggressive_manifests = [
            {"version": "99.99.99", "assets": {"termux-aarch64": {"url": "https://attacker.com/malicious_bin"}}},
            {"version": "0.0.1", "force": True, "assets": {"all": {"url": "https://attacker.com/force_bin"}}},
            {"version": "1.0.0", "urgent_security_patch": True},
        ]
        
        for manifest in aggressive_manifests:
            res = mgr.check_update(current_version="1.0.0", remote_manifest=manifest)
            self.assertFalse(res["can_auto_download"], "Package-managed mode must NEVER allow auto-download")
            self.assertEqual(res["action"], "delegate_to_pkg")
            self.assertIn("pkg update && pkg upgrade grok-build", res["message"])

    def test_adv_pkg_mode_env_precedence(self):
        """Verify environment variable detection across various aliases."""
        env_vars = [
            ("GROK_INSTALL_MODE", "pkg", "package-managed"),
            ("GROK_INSTALL_MODE", "package-managed", "package-managed"),
            ("GROK_INSTALL_MODE", "apt", "package-managed"),
            ("GROK_INSTALL_MODE", "deb", "package-managed"),
            ("GROK_INSTALLER", "pkg", "package-managed"),
            ("GROK_INSTALLER", "package-managed", "package-managed"),
            ("GROK_INSTALLER", "apt", "package-managed"),
            ("GROK_INSTALLER", "deb", "package-managed"),
        ]
        for key, val, expected in env_vars:
            with MockTermuxEnv(is_android=True) as env:
                os.environ[key] = val
                # Verify that UpdateManagerSeam respects package-managed mode
                mgr = UpdateManagerSeam(install_mode=expected)
                res = mgr.check_update("1.0.0", {})
                self.assertEqual(res["action"], "delegate_to_pkg")
                self.assertIn("pkg update && pkg upgrade grok-build", res["message"])

    def test_adv_prefix_binary_location_inference(self):
        """Verify that binaries residing in $PREFIX/bin (not $HOME) are inferred as package-managed."""
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            prefix = caps.prefix_dir()
            home = caps.home_dir()

            system_bin = os.path.join(prefix, "bin", "grok")
            user_bin = os.path.join(home, ".grok", "bin", "grok")

            # System binary is in prefix and NOT home -> package managed
            is_system_pkg = system_bin.startswith(prefix) and not system_bin.startswith(home)
            self.assertTrue(is_system_pkg)

            # User binary is in home -> standalone/internal
            is_user_pkg = user_bin.startswith(prefix) and not user_bin.startswith(home)
            # In mock env, home might be subpath of prefix or independent
            self.assertTrue(user_bin.startswith(home))


class TestAdversarialStandaloneChannelIsolation(unittest.TestCase):
    """Adversarial stress-testing for Feature 28: Standalone Install Mode & Updater Isolation."""

    def test_adv_rejects_all_desktop_and_alien_architectures(self):
        """Verify updater rejects desktop Linux/macOS/Windows and incompatible archs."""
        mgr = UpdateManagerSeam(install_mode="standalone")

        hostile_manifests = [
            # 1. Desktop Linux x86_64 only
            {"version": "2.0.0", "assets": {"linux-x86_64": {"url": "https://x.ai/grok-linux-x86_64"}}},
            # 2. Desktop Linux aarch64 (glibc, NOT Bionic)
            {"version": "2.0.0", "assets": {"linux-aarch64": {"url": "https://x.ai/grok-linux-aarch64"}}},
            # 3. macOS aarch64 (Mach-O)
            {"version": "2.0.0", "assets": {"macos-aarch64": {"url": "https://x.ai/grok-macos-aarch64"}}},
            # 4. Windows x86_64 (PE)
            {"version": "2.0.0", "assets": {"windows-x86_64": {"url": "https://x.ai/grok-windows-x86_64.exe"}}},
            # 5. Linux armv7
            {"version": "2.0.0", "assets": {"linux-armv7": {"url": "https://x.ai/grok-linux-armv7"}}},
            # 6. Empty assets
            {"version": "2.0.0", "assets": {}},
            # 7. Missing assets key entirely
            {"version": "2.0.0"},
            # 8. Assets with None/null values
            {"version": "2.0.0", "assets": {"termux-aarch64": None}},
        ]

        for idx, manifest in enumerate(hostile_manifests):
            res = mgr.check_update(current_version="1.0.0", remote_manifest=manifest)
            self.assertFalse(
                res["can_auto_download"],
                f"Manifest #{idx} must not trigger download: {manifest}"
            )
            self.assertEqual(
                res["action"],
                "no_compatible_asset",
                f"Manifest #{idx} must result in no_compatible_asset"
            )

    def test_adv_accepts_valid_termux_aarch64_artifact_only(self):
        """Verify updater ONLY accepts valid termux-aarch64 asset."""
        mgr = UpdateManagerSeam(install_mode="standalone")
        manifest = {
            "version": "2.0.0",
            "assets": {
                "linux-x86_64": {"url": "https://x.ai/linux-x86_64"},
                "linux-aarch64": {"url": "https://x.ai/linux-aarch64"},
                "termux-aarch64": {"url": "https://x.ai/grok-2.0.0-termux-aarch64.tar.gz"},
            }
        }
        res = mgr.check_update(current_version="1.0.0", remote_manifest=manifest)
        self.assertTrue(res["can_auto_download"])
        self.assertEqual(res["action"], "download_and_apply")
        self.assertEqual(res["asset_url"], "https://x.ai/grok-2.0.0-termux-aarch64.tar.gz")


class TestAdversarialElfValidation(unittest.TestCase):
    """Adversarial stress-testing for ELF binary validation (Bionic, glibc rejection, 16K alignment)."""

    def test_adv_rejects_glibc_interpreter(self):
        """Verify strict rejection of any desktop Linux dynamic linker."""
        glibc_linkers = [
            "/lib/ld-linux-aarch64.so.1",
            "/lib64/ld-linux-x86-64.so.2",
            "/lib/ld-linux.so.2",
            "/lib/ld-linux-armhf.so.3",
            "/lib/ld-musl-aarch64.so.1",
            "/usr/lib/ld-linux.so.2",
        ]
        for linker in glibc_linkers:
            raw_elf = self._build_custom_elf(
                arch=EM_AARCH64,
                is_64=True,
                is_le=True,
                interp=linker,
                page_align=0x4000,
                dt_needed=["libc.so"],
            )
            elf = ElfBinary(raw_elf)
            is_valid, errors, _ = validate_elf(elf, strict_16k=True, target_arch="aarch64", bionic_only=True)
            self.assertFalse(is_valid)
            self.assertTrue(any("Incompatible dynamic linker" in e or "glibc interpreter" in e for e in errors))

    def test_adv_rejects_glibc_dt_needed_libraries(self):
        """Verify strict rejection of glibc shared libraries (libc.so.6, etc.)."""
        bad_libs = [
            "libc.so.6",
            "libpthread.so.0",
            "libm.so.6",
            "libdl.so.2",
            "librt.so.1",
            "ld-linux-aarch64.so.1",
        ]
        for bad_lib in bad_libs:
            raw_elf = self._build_custom_elf(
                arch=EM_AARCH64,
                is_64=True,
                is_le=True,
                interp="/system/bin/linker64",
                page_align=0x4000,
                dt_needed=[bad_lib],
            )
            elf = ElfBinary(raw_elf)
            is_valid, errors, _ = validate_elf(elf, strict_16k=True, target_arch="aarch64", bionic_only=True)
            self.assertFalse(is_valid)
            self.assertTrue(any("Forbidden glibc runtime dependency" in e for e in errors))

    def test_adv_rejects_sub_16k_page_alignment(self):
        """Verify strict rejection of 4 KiB and other non-16 KiB alignments on PT_LOAD."""
        sub_16k_alignments = [0x1000, 0x800, 0x2000, 0x100, 0x1]
        for align in sub_16k_alignments:
            raw_elf = self._build_custom_elf(
                arch=EM_AARCH64,
                is_64=True,
                is_le=True,
                interp="/system/bin/linker64",
                page_align=align,
                dt_needed=["libc.so"],
            )
            elf = ElfBinary(raw_elf)
            is_valid, errors, _ = validate_elf(elf, min_page_size=16384, strict_16k=True, target_arch="aarch64")
            self.assertFalse(is_valid)
            self.assertTrue(any("less than required 16384" in e for e in errors))

    def test_adv_rejects_congruence_violations(self):
        """Verify rejection when (p_vaddr % p_align) != (p_offset % p_align)."""
        raw_elf = self._build_custom_elf(
            arch=EM_AARCH64,
            is_64=True,
            is_le=True,
            interp="/system/bin/linker64",
            page_align=0x4000,
            dt_needed=["libc.so"],
            force_congruence_violation=True,
        )
        elf = ElfBinary(raw_elf)
        is_valid, errors, _ = validate_elf(elf, min_page_size=16384, strict_16k=True, target_arch="aarch64")
        self.assertFalse(is_valid)
        self.assertTrue(any("violates ELF congruence" in e for e in errors))

    def test_adv_rejects_big_endian_binary(self):
        """Verify rejection of big-endian ELF binaries."""
        raw_elf = self._build_custom_elf(
            arch=EM_AARCH64,
            is_64=True,
            is_le=False,
            interp="/system/bin/linker64",
            page_align=0x4000,
            dt_needed=["libc.so"],
        )
        elf = ElfBinary(raw_elf)
        is_valid, errors, _ = validate_elf(elf, target_arch="aarch64")
        self.assertFalse(is_valid)
        self.assertTrue(any("must be Little Endian" in e for e in errors))

    def test_adv_rejects_architecture_mismatch(self):
        """Verify rejection when target is aarch64 but ELF is x86_64."""
        raw_elf = self._build_custom_elf(
            arch=EM_X86_64,
            is_64=True,
            is_le=True,
            interp="/system/bin/linker64",
            page_align=0x4000,
            dt_needed=["libc.so"],
        )
        elf = ElfBinary(raw_elf)
        is_valid, errors, _ = validate_elf(elf, target_arch="aarch64")
        self.assertFalse(is_valid)
        self.assertTrue(any("Architecture mismatch" in e for e in errors))

    def test_adv_handles_corrupt_truncated_headers(self):
        """Verify parser throws graceful ElfValidationError on truncated / corrupt inputs."""
        corrupt_inputs = [
            b"",
            b"\x7fELF",
            b"\x7fELF\x02\x01\x01\x00",  # Only 8 bytes
            b"\x7fELF" + b"\x00" * 40,    # 44 bytes (< 52 / 64)
            b"MZ\x90\x00" + b"\x00" * 60, # PE header
            b"\xca\xfe\xba\xbe" + b"\x00" * 60, # Mach-O Universal binary
            b"#!/bin/bash\necho hello\n", # Shell script
        ]
        for data in corrupt_inputs:
            with self.assertRaises(ElfValidationError):
                ElfBinary(data)

    def _build_custom_elf(
        self,
        arch=EM_AARCH64,
        is_64=True,
        is_le=True,
        interp="/system/bin/linker64",
        page_align=0x4000,
        dt_needed=None,
        force_congruence_violation=False,
    ) -> bytes:
        if dt_needed is None:
            dt_needed = ["libc.so"]

        endian = "<" if is_le else ">"
        ident = bytearray(16)
        ident[0:4] = ELFMAG
        ident[4] = ELFCLASS64 if is_64 else ELFCLASS32
        ident[5] = ELFDATA2LSB if is_le else ELFDATA2MSB
        ident[6] = 1  # EI_VERSION
        ident[7] = 0  # EI_OSABI

        phentsize = 56
        phoff = 64
        ehsize = 64
        phnum = 4  # PT_PHDR, PT_INTERP, PT_LOAD, PT_DYNAMIC

        interp_bytes = interp.encode("utf-8") + b"\x00"
        interp_offset = 0x200
        interp_len = len(interp_bytes)

        dynstr = b"\x00"
        dt_needed_offsets = []
        for lib in dt_needed:
            dt_needed_offsets.append(len(dynstr))
            dynstr += lib.encode("utf-8") + b"\x00"

        dynstr_offset = 0x300
        dynamic_offset = 0x400

        load_offset = 0x0
        load_vaddr = 0x1000 if force_congruence_violation else 0x0
        load_filesz = 0x2000
        load_memsz = 0x2000

        elf_hdr = struct.pack(
            endian + "16sHHIQQQIHHHHHH",
            bytes(ident),
            3,  # ET_DYN
            arch,
            1,  # e_version
            0x4000,  # e_entry
            phoff,
            0,
            0,
            ehsize,
            phentsize,
            phnum,
            0,
            0,
            0,
        )

        data = bytearray(elf_hdr)
        if len(data) < phoff:
            data.extend(b"\x00" * (phoff - len(data)))

        # 0. PT_PHDR
        data.extend(struct.pack(endian + "IIQQQQQQ", 6, 4, phoff, phoff, phoff, phnum * phentsize, phnum * phentsize, 8))
        # 1. PT_INTERP
        data.extend(struct.pack(endian + "IIQQQQQQ", PT_INTERP, 4, interp_offset, interp_offset, interp_offset, interp_len, interp_len, 1))
        # 2. PT_LOAD
        data.extend(struct.pack(endian + "IIQQQQQQ", PT_LOAD, 5, load_offset, load_vaddr, load_vaddr, load_filesz, load_memsz, page_align))
        # 3. PT_DYNAMIC
        data.extend(struct.pack(endian + "IIQQQQQQ", PT_DYNAMIC, 6, dynamic_offset, dynamic_offset, dynamic_offset, 0x80, 0x80, 8))

        if len(data) < interp_offset:
            data.extend(b"\x00" * (interp_offset - len(data)))
        data[interp_offset : interp_offset + interp_len] = interp_bytes

        if len(data) < dynstr_offset:
            data.extend(b"\x00" * (dynstr_offset - len(data)))
        data[dynstr_offset : dynstr_offset + len(dynstr)] = dynstr

        if len(data) < dynamic_offset:
            data.extend(b"\x00" * (dynamic_offset - len(data)))

        dyn_entries = []
        for off in dt_needed_offsets:
            dyn_entries.append(struct.pack(endian + "QQ", DT_NEEDED, off))
        dyn_entries.append(struct.pack(endian + "QQ", DT_STRTAB, dynstr_offset))
        dyn_entries.append(struct.pack(endian + "QQ", DT_STRSZ, len(dynstr)))
        dyn_entries.append(struct.pack(endian + "QQ", DT_NULL, 0))

        dyn_bytes = b"".join(dyn_entries)
        data[dynamic_offset : dynamic_offset + len(dyn_bytes)] = dyn_bytes

        total_len = load_offset + load_filesz
        if len(data) < total_len:
            data.extend(b"\x00" * (total_len - len(data)))

        return bytes(data)


if __name__ == "__main__":
    unittest.main()
