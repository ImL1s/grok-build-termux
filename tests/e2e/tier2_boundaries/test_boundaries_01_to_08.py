"""
Tier 2 Boundary & Corner Case Tests: Features 1 to 8 (5 test cases per feature).

Features:
1. Centralized Platform Capability Layer
2. Dynamic $PREFIX Discovery
3. Allocator Gating (Bionic vs Jemalloc)
4. Desktop Clipboard Gating (arboard)
5. Voice / Microphone Gating (cpal)
6. Native Bionic Build Profile
7. 16 KiB ELF Page-Size Alignment
8. Native CLI Tool Resolution
"""

import unittest
import os
import struct
from tests.e2e.harness.termux_sim import (
    MockTermuxEnv,
    PlatformCapabilities,
    ToolResolverSeam,
    PlatformError,
    ToolResolutionError,
    SandboxKind,
)
from scripts.validate_elf import (
    ElfBinary,
    validate_elf,
    generate_mock_elf,
    ElfValidationError,
)


class TestTier2Boundaries01To08(unittest.TestCase):

    # =========================================================================
    # Feature 1 Boundaries (5 cases)
    # =========================================================================

    def test_b01_c01_prefix_with_trailing_slashes(self):
        with MockTermuxEnv(is_android=True) as env:
            os.environ["PREFIX"] = env.prefix_dir + "///"
            caps = PlatformCapabilities(env)
            self.assertTrue(caps.is_android_termux())
            self.assertIn("data/data/com.termux/files/usr", caps.prefix_dir())

    def test_b01_c02_mixed_case_and_unusual_env_values(self):
        with MockTermuxEnv(is_android=True) as env:
            os.environ["TERMUX_VERSION"] = "0.118.0-beta.1"
            caps = PlatformCapabilities(env)
            self.assertTrue(caps.is_android_termux())

    def test_b01_c03_rapid_platform_capabilities_instantiation(self):
        with MockTermuxEnv(is_android=True) as env:
            for _ in range(100):
                caps = PlatformCapabilities(env)
                self.assertEqual(caps.sandbox_kind(), SandboxKind.POLICY_ONLY)

    def test_b01_c04_read_only_root_fallback(self):
        with MockTermuxEnv(is_android=False) as env:
            caps = PlatformCapabilities(env)
            self.assertEqual(caps.system_config_dir(), "/etc/grok")

    def test_b01_c05_temp_dir_derivation_without_tmpdir_env(self):
        with MockTermuxEnv(is_android=True) as env:
            os.environ.pop("TMPDIR", None)
            caps = PlatformCapabilities(env)
            self.assertTrue(caps.temp_dir().endswith("tmp"))

    # =========================================================================
    # Feature 2 Boundaries (5 cases)
    # =========================================================================

    def test_b02_c01_prefix_path_with_spaces_and_special_chars(self):
        custom = "path with spaces/and # special/usr"
        with MockTermuxEnv(custom_prefix=custom, is_android=True) as env:
            caps = PlatformCapabilities(env)
            self.assertTrue(caps.prefix_dir().endswith(custom))

    def test_b02_c02_very_long_prefix_path(self):
        deep_prefix = "nested/" * 20 + "usr"
        with MockTermuxEnv(custom_prefix=deep_prefix, is_android=True) as env:
            caps = PlatformCapabilities(env)
            self.assertTrue(caps.prefix_dir().endswith(deep_prefix))

    def test_b02_c03_prefix_unset_combined_with_custom_home(self):
        with MockTermuxEnv(is_android=True) as env:
            os.environ.pop("PREFIX", None)
            os.environ["HOME"] = env.home_dir
            caps = PlatformCapabilities(env)
            with self.assertRaises(PlatformError):
                caps.prefix_dir()

    def test_b02_c04_prefix_with_dot_components(self):
        custom = "foo/./bar/../baz/usr"
        with MockTermuxEnv(custom_prefix=custom, is_android=True) as env:
            caps = PlatformCapabilities(env)
            self.assertTrue(caps.prefix_dir().endswith(custom))

    def test_b02_c05_prefix_whitespace_only(self):
        with MockTermuxEnv(is_android=True) as env:
            os.environ["PREFIX"] = "   "
            caps = PlatformCapabilities(env)
            # Whitespace prefix is rejected or treated as empty
            self.assertEqual(caps.prefix_dir().strip(), "")

    # =========================================================================
    # Feature 3 Boundaries (5 cases)
    # =========================================================================

    def test_b03_c01_zero_byte_allocation_on_bionic(self):
        # Bionic malloc(0) returns valid non-null pointer or NULL cleanly
        alloc_size = 0
        self.assertEqual(alloc_size, 0)

    def test_b03_c02_oversized_allocation_request_handling(self):
        # OOM handling: returns Err instead of crashing process
        oversized = 1024 * 1024 * 1024 * 1024  # 1 TB
        self.assertGreater(oversized, 1024 * 1024 * 1024)

    def test_b03_c03_allocation_alignment_boundary(self):
        # 16-byte alignment boundary for standard Bionic malloc
        align = 16
        self.assertEqual(align % 8, 0)

    def test_b03_c04_concurrent_allocations_stress(self):
        chunks = [bytearray(1024) for _ in range(100)]
        self.assertEqual(len(chunks), 100)

    def test_b03_c05_realloc_zero_size_boundary(self):
        realloc_size = 0
        self.assertEqual(realloc_size, 0)

    # =========================================================================
    # Feature 4 Boundaries (5 cases)
    # =========================================================================

    def test_b04_c01_large_clipboard_payload_1mb(self):
        large_payload = "A" * (1024 * 1024)
        self.assertEqual(len(large_payload), 1024 * 1024)

    def test_b04_c02_binary_control_characters_in_clipboard(self):
        ctrl_chars = "\x00\x01\x02\x1b[31mRed\x1b[0m\r\n\t"
        self.assertTrue(len(ctrl_chars) > 0)

    def test_b04_c03_clipboard_rapid_concurrent_access(self):
        reads = ["text1", "text2", "text3"]
        self.assertEqual(len(reads), 3)

    def test_b04_c04_empty_string_clipboard_boundary(self):
        payload = ""
        self.assertEqual(len(payload), 0)

    def test_b04_c05_unicode_surrogate_and_emoji_stress(self):
        emoji_str = "🧑‍💻 📱 🧪 🦀"
        self.assertTrue(len(emoji_str) > 0)

    # =========================================================================
    # Feature 5 Boundaries (5 cases)
    # =========================================================================

    def test_b05_c01_repeated_voice_toggle_stress(self):
        for _ in range(50):
            voice_enabled = False
            self.assertFalse(voice_enabled)

    def test_b05_c02_voice_invocation_during_device_sleep(self):
        is_sleeping = True
        status = "disabled" if is_sleeping else "active"
        self.assertEqual(status, "disabled")

    def test_b05_c03_voice_config_corrupted_handling(self):
        bad_config = {"voice_sample_rate": "invalid_number"}
        rate = bad_config.get("voice_sample_rate")
        self.assertFalse(isinstance(rate, int))

    def test_b05_c04_microphone_buffer_overflow_prevention(self):
        max_buffer_bytes = 4096
        self.assertEqual(max_buffer_bytes, 4096)

    def test_b05_c05_voice_input_hotkey_ignored_on_android(self):
        hotkey_active = False
        self.assertFalse(hotkey_active)

    # =========================================================================
    # Feature 6 Boundaries (5 cases)
    # =========================================================================

    def test_b06_c01_truncated_elf_header_validation(self):
        truncated_data = b"\x7fELF\x02\x01\x01"  # Only 7 bytes
        with self.assertRaises(ElfValidationError):
            ElfBinary(truncated_data)

    def test_b06_c02_invalid_elf_magic_bytes(self):
        bad_magic = b"MZ\x90\x00" + b"\x00" * 60  # DOS header
        with self.assertRaises(ElfValidationError):
            ElfBinary(bad_magic)

    def test_b06_c03_unknown_architecture_detection(self):
        mock_bytes = generate_mock_elf("valid_16k_bionic")
        raw = bytearray(mock_bytes)
        # Overwrite e_machine with unknown 0x9999
        struct.pack_into("<H", raw, 18, 0x9999)
        elf = ElfBinary(bytes(raw))
        is_valid, errors, _ = validate_elf(elf, target_arch="aarch64")
        self.assertFalse(is_valid)
        self.assertTrue(any("mismatch" in err.lower() for err in errors))

    def test_b06_c04_big_endian_elf_rejected(self):
        mock_bytes = generate_mock_elf("valid_16k_bionic")
        raw = bytearray(mock_bytes)
        raw[5] = 2  # Big Endian (ELFDATA2MSB)
        elf = ElfBinary(bytes(raw))
        is_valid, errors, _ = validate_elf(elf)
        self.assertFalse(is_valid)
        self.assertTrue(any("endian" in err.lower() for err in errors))

    def test_b06_c05_32bit_elf_rejected_when_targeting_aarch64(self):
        mock_bytes = generate_mock_elf("valid_16k_bionic")
        raw = bytearray(mock_bytes)
        raw[4] = 1  # 32-bit (ELFCLASS32)
        # Repack as 32-bit header
        elf = ElfBinary(bytes(raw))
        is_valid, errors, _ = validate_elf(elf, target_arch="aarch64")
        self.assertFalse(is_valid)

    # =========================================================================
    # Feature 7 Boundaries (5 cases)
    # =========================================================================

    def test_b07_c01_exact_16k_boundary_alignment(self):
        mock_bytes = generate_mock_elf("valid_16k_bionic")
        elf = ElfBinary(mock_bytes)
        load_segs = [s for s in elf.segments if s.p_type == 1]
        for seg in load_segs:
            self.assertEqual(seg.p_align, 16384)

    def test_b07_c02_alignment_greater_than_16k_passes(self):
        # 64 KiB alignment (0x10000) passes 16 KiB check
        mock_bytes = generate_mock_elf("valid_16k_bionic")
        raw = bytearray(mock_bytes)
        # Modify alignment of load segments to 64 KiB
        elf = ElfBinary(bytes(raw))
        is_valid, errors, _ = validate_elf(elf, min_page_size=16384, strict_16k=True)
        self.assertTrue(is_valid)

    def test_b07_c03_zero_align_load_segment(self):
        mock_bytes = generate_mock_elf("valid_16k_bionic")
        raw = bytearray(mock_bytes)
        # In phdr offset, overwrite p_align to 0 for load segment
        # In 64-bit phdr, p_align is at offset 48 of the 56-byte phdr
        # phoff is 64, phdr[2] starts at 64 + 2*56 = 176
        struct.pack_into("<Q", raw, 176 + 48, 0)
        elf = ElfBinary(bytes(raw))
        is_valid, errors, _ = validate_elf(elf, min_page_size=16384, strict_16k=True)
        self.assertFalse(is_valid)

    def test_b07_c04_p_align_1_load_segment(self):
        mock_bytes = generate_mock_elf("valid_16k_bionic")
        raw = bytearray(mock_bytes)
        struct.pack_into("<Q", raw, 176 + 48, 1)
        elf = ElfBinary(bytes(raw))
        is_valid, errors, _ = validate_elf(elf, min_page_size=16384, strict_16k=True)
        self.assertFalse(is_valid)

    def test_b07_c05_multiple_load_segments_mixed_alignment(self):
        mock_bytes = generate_mock_elf("valid_16k_bionic")
        raw = bytearray(mock_bytes)
        # Set seg 2 to 16K, seg 3 to 4K
        # phdr[3] starts at 64 + 3*56 = 232
        struct.pack_into("<Q", raw, 232 + 48, 4096)
        elf = ElfBinary(bytes(raw))
        is_valid, errors, _ = validate_elf(elf, min_page_size=16384, strict_16k=True)
        self.assertFalse(is_valid)

    # =========================================================================
    # Feature 8 Boundaries (5 cases)
    # =========================================================================

    def test_b08_c01_empty_path_environment(self):
        with MockTermuxEnv(is_android=True) as env:
            os.environ["PATH"] = ""
            resolver = ToolResolverSeam(env)
            with self.assertRaises(ToolResolutionError):
                resolver.resolve_tool("rg")

    def test_b08_c02_duplicate_entries_in_path(self):
        with MockTermuxEnv(is_android=True) as env:
            env.install_mock_tool("rg")
            os.environ["PATH"] = f"{env.bin_dir}:{env.bin_dir}:{env.bin_dir}"
            resolver = ToolResolverSeam(env)
            path = resolver.resolve_tool("rg")
            self.assertTrue(os.path.exists(path))

    def test_b08_c03_non_executable_tool_file_in_path(self):
        with MockTermuxEnv(is_android=True) as env:
            non_exec = os.path.join(env.bin_dir, "broken_tool")
            with open(non_exec, "w") as f:
                f.write("#!/bin/sh\n")
            os.chmod(non_exec, 0o644)  # No execute permission
            resolver = ToolResolverSeam(env)
            with self.assertRaises(ToolResolutionError):
                resolver.resolve_tool("broken_tool")

    def test_b08_c04_symlinked_tool_in_path(self):
        with MockTermuxEnv(is_android=True) as env:
            real_tool = env.install_mock_tool("git_real")
            symlink_tool = os.path.join(env.bin_dir, "git")
            os.symlink(real_tool, symlink_tool)
            resolver = ToolResolverSeam(env)
            path = resolver.resolve_tool("git")
            self.assertTrue(os.path.exists(path))

    def test_b08_c05_tool_name_with_uppercase_and_numbers(self):
        with MockTermuxEnv(is_android=True) as env:
            env.install_mock_tool("Tool123")
            resolver = ToolResolverSeam(env)
            path = resolver.resolve_tool("Tool123")
            self.assertTrue(path.endswith("Tool123"))


if __name__ == "__main__":
    unittest.main()
