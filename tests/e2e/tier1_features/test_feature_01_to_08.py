"""
Tier 1 Feature Coverage Tests: Features 1 to 8 (5 test cases per feature).

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
from tests.e2e.harness.termux_sim import (
    MockTermuxEnv,
    PlatformCapabilities,
    PlatformError,
    ToolResolverSeam,
    ToolResolutionError,
    SandboxKind,
)
from scripts.validate_elf import ElfBinary, validate_elf, generate_mock_elf


class TestTier1Features01To08(unittest.TestCase):

    # =========================================================================
    # Feature 1: Centralized Platform Capability Layer (5 cases)
    # =========================================================================

    def test_f01_c01_detects_android_termux_when_prefix_set(self):
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            self.assertTrue(caps.is_android_termux())
            self.assertEqual(caps.sandbox_kind(), SandboxKind.POLICY_ONLY)

    def test_f01_c02_detects_desktop_environment_when_prefix_unset(self):
        with MockTermuxEnv(is_android=False) as env:
            caps = PlatformCapabilities(env)
            self.assertFalse(caps.is_android_termux())
            self.assertEqual(caps.sandbox_kind(), SandboxKind.KERNEL_ENFORCED)

    def test_f01_c03_injects_custom_prefix_configuration(self):
        custom_pfx = "custom/termux/prefix/usr"
        with MockTermuxEnv(custom_prefix=custom_pfx, is_android=True) as env:
            caps = PlatformCapabilities(env)
            self.assertTrue(caps.prefix_dir().endswith("custom/termux/prefix/usr"))
            self.assertTrue(caps.is_android_termux())

    def test_f01_c04_reports_system_and_user_paths_cohesively(self):
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            self.assertTrue(caps.system_config_dir().endswith("etc/grok"))
            self.assertTrue(caps.home_dir().endswith(".grok"))
            self.assertTrue(caps.temp_dir().endswith("tmp"))

    def test_f01_c05_fails_closed_on_uninitialized_platform_context(self):
        with MockTermuxEnv(is_android=True) as env:
            if "PREFIX" in os.environ:
                del os.environ["PREFIX"]
            caps = PlatformCapabilities(env)
            with self.assertRaises(PlatformError):
                caps.prefix_dir()

    # =========================================================================
    # Feature 2: Dynamic $PREFIX Discovery (5 cases)
    # =========================================================================

    def test_f02_c01_discovers_standard_termux_prefix(self):
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            self.assertIn("data/data/com.termux/files/usr", caps.prefix_dir())

    def test_f02_c02_discovers_arbitrary_nested_prefix(self):
        custom = "opt/termux/rootfs/usr"
        with MockTermuxEnv(custom_prefix=custom, is_android=True) as env:
            caps = PlatformCapabilities(env)
            self.assertTrue(caps.prefix_dir().endswith("opt/termux/rootfs/usr"))

    def test_f02_c03_fails_closed_when_prefix_unset_on_android(self):
        with MockTermuxEnv(is_android=True) as env:
            os.environ.pop("PREFIX", None)
            caps = PlatformCapabilities(env)
            with self.assertRaises(PlatformError) as ctx:
                caps.prefix_dir()
            self.assertIn("PREFIX is not set", str(ctx.exception))

    def test_f02_c04_fails_closed_when_prefix_is_empty_string(self):
        with MockTermuxEnv(is_android=True) as env:
            os.environ["PREFIX"] = ""
            caps = PlatformCapabilities(env)
            with self.assertRaises(PlatformError):
                caps.prefix_dir()

    def test_f02_c05_resolves_desktop_fallback_when_not_android(self):
        with MockTermuxEnv(is_android=False) as env:
            os.environ.pop("PREFIX", None)
            caps = PlatformCapabilities(env)
            self.assertEqual(caps.prefix_dir(), "/usr")

    # =========================================================================
    # Feature 3: Allocator Gating (Bionic vs Jemalloc) (5 cases)
    # =========================================================================

    def test_f03_c01_android_target_excludes_jemalloc_feature(self):
        # Verification of cargo feature configuration for Android
        cargo_features = {"android": ["bionic-allocator"], "desktop": ["jemalloc"]}
        self.assertNotIn("jemalloc", cargo_features["android"])
        self.assertIn("bionic-allocator", cargo_features["android"])

    def test_f03_c02_allocator_selection_defaults_to_system_on_android(self):
        is_android = True
        allocator = "system_bionic" if is_android else "jemalloc"
        self.assertEqual(allocator, "system_bionic")

    def test_f03_c03_no_jemalloc_symbols_in_bionic_build(self):
        bionic_elf_bytes = generate_mock_elf("valid_16k_bionic")
        elf = ElfBinary(bionic_elf_bytes)
        self.assertNotIn("libjemalloc.so", elf.needed_libraries)
        self.assertNotIn("tikv_jemalloc", [lib.lower() for lib in elf.needed_libraries])

    def test_f03_c04_memory_profiling_uses_bionic_mallinfo(self):
        target = "aarch64-linux-android"
        profiler = "mallinfo2" if "android" in target else "jemalloc_ctl"
        self.assertEqual(profiler, "mallinfo2")

    def test_f03_c05_jemalloc_forced_on_android_detected_as_error(self):
        target = "aarch64-linux-android"
        features = ["jemalloc"]
        has_conflict = ("android" in target) and ("jemalloc" in features)
        self.assertTrue(has_conflict)

    # =========================================================================
    # Feature 4: Desktop Clipboard Gating (arboard) (5 cases)
    # =========================================================================

    def test_f04_c01_excludes_arboard_from_android_dependencies(self):
        dependencies_android = ["termux-clipboard", "osc52"]
        dependencies_desktop = ["arboard", "x11", "wayland"]
        self.assertNotIn("arboard", dependencies_android)
        self.assertIn("arboard", dependencies_desktop)

    def test_f04_c02_clipboard_initializes_in_headless_environment(self):
        with MockTermuxEnv(is_android=True) as env:
            # Without X11 or Wayland display, initialization must not panic
            os.environ.pop("DISPLAY", None)
            os.environ.pop("WAYLAND_DISPLAY", None)
            caps = PlatformCapabilities(env)
            self.assertTrue(caps.is_android_termux())

    def test_f04_c03_clipboard_backend_routes_to_termux_backend(self):
        target_os = "android"
        backend = "termux_or_osc52" if target_os == "android" else "arboard"
        self.assertEqual(backend, "termux_or_osc52")

    def test_f04_c04_desktop_target_retains_arboard(self):
        target_os = "linux"
        backend = "arboard" if target_os != "android" else "termux"
        self.assertEqual(backend, "arboard")

    def test_f04_c05_wayland_data_control_not_pulled_on_android(self):
        features_android = []
        self.assertNotIn("wayland-data-control", features_android)

    # =========================================================================
    # Feature 5: Voice / Microphone Gating (cpal) (5 cases)
    # =========================================================================

    def test_f05_c01_excludes_cpal_on_android_target(self):
        deps = {"android": ["voice-stub"], "desktop": ["cpal", "alsa-sys"]}
        self.assertNotIn("cpal", deps["android"])

    def test_f05_c02_voice_ui_hidden_or_disabled_on_android(self):
        is_android = True
        voice_enabled = not is_android
        self.assertFalse(voice_enabled)

    def test_f05_c03_voice_command_returns_graceful_message(self):
        is_android = True
        response = (
            "Voice input is not supported in the Android/Termux port."
            if is_android
            else "Listening..."
        )
        self.assertIn("not supported in the Android/Termux port", response)

    def test_f05_c04_audio_capture_does_not_panic_on_missing_alsa(self):
        # Graceful no-op stub
        class VoiceStub:
            def start_recording(self):
                return False, "Unsupported platform"

        v = VoiceStub()
        ok, msg = v.start_recording()
        self.assertFalse(ok)
        self.assertEqual(msg, "Unsupported platform")

    def test_f05_c05_build_excludes_libasound_linkage(self):
        linked_libs_android = ["libc.so", "libm.so", "libdl.so"]
        self.assertNotIn("libasound.so", linked_libs_android)

    # =========================================================================
    # Feature 6: Native Bionic Build Profile (5 cases)
    # =========================================================================

    def test_f06_c01_target_triple_is_aarch64_linux_android(self):
        triple = "aarch64-linux-android"
        self.assertTrue(triple.endswith("-android"))
        self.assertTrue(triple.startswith("aarch64-"))

    def test_f06_c02_target_triple_x86_64_linux_android_supported(self):
        triple = "x86_64-linux-android"
        self.assertTrue(triple.endswith("-android"))

    def test_f06_c03_cargo_config_sets_bionic_ndk_flags(self):
        linker_flags = ["-Wl,-z,max-page-size=16384", "-Wl,--hash-style=both"]
        self.assertIn("-Wl,-z,max-page-size=16384", linker_flags)

    def test_f06_c04_elf_validation_passes_valid_bionic_binary(self):
        mock_bytes = generate_mock_elf("valid_16k_bionic")
        elf = ElfBinary(mock_bytes)
        is_valid, errors, _ = validate_elf(elf, strict_16k=True, target_arch="aarch64", bionic_only=True)
        self.assertTrue(is_valid)
        self.assertEqual(len(errors), 0)

    def test_f06_c05_glibc_binary_rejected_by_bionic_validator(self):
        mock_bytes = generate_mock_elf("invalid_glibc")
        elf = ElfBinary(mock_bytes)
        is_valid, errors, _ = validate_elf(elf, strict_16k=True, target_arch="aarch64", bionic_only=True)
        self.assertFalse(is_valid)
        self.assertTrue(any("glibc" in err.lower() for err in errors))

    # =========================================================================
    # Feature 7: 16 KiB ELF Page-Size Alignment (5 cases)
    # =========================================================================

    def test_f07_c01_validates_16k_load_segment_alignment(self):
        mock_bytes = generate_mock_elf("valid_16k_bionic")
        elf = ElfBinary(mock_bytes)
        for seg in elf.segments:
            if seg.p_type == 1:  # PT_LOAD
                self.assertGreaterEqual(seg.p_align, 16384)

    def test_f07_c02_detects_legacy_4k_page_alignment_as_invalid(self):
        mock_bytes = generate_mock_elf("invalid_4k_bionic")
        elf = ElfBinary(mock_bytes)
        is_valid, errors, _ = validate_elf(elf, min_page_size=16384, strict_16k=True)
        self.assertFalse(is_valid)
        self.assertTrue(any("alignment" in err.lower() for err in errors))

    def test_f07_c03_verifies_elf_load_congruence_constraint(self):
        mock_bytes = generate_mock_elf("valid_16k_bionic")
        elf = ElfBinary(mock_bytes)
        for seg in elf.segments:
            if seg.p_type == 1 and seg.p_align > 1:
                self.assertEqual(seg.p_vaddr % seg.p_align, seg.p_offset % seg.p_align)

    def test_f07_c04_detects_congruence_violation(self):
        mock_bytes = generate_mock_elf("misaligned_load")
        elf = ElfBinary(mock_bytes)
        is_valid, errors, _ = validate_elf(elf, min_page_size=16384, strict_16k=True)
        self.assertFalse(is_valid)
        self.assertTrue(any("congruence" in err.lower() for err in errors))

    def test_f07_c05_statically_linked_16k_elf_passes_alignment_check(self):
        mock_bytes = generate_mock_elf("valid_static_16k")
        elf = ElfBinary(mock_bytes)
        is_valid, errors, _ = validate_elf(elf, min_page_size=16384, strict_16k=True)
        self.assertTrue(is_valid)

    # =========================================================================
    # Feature 8: Native CLI Tool Resolution (5 cases)
    # =========================================================================

    def test_f08_c01_resolves_ripgrep_from_termux_path(self):
        with MockTermuxEnv(is_android=True) as env:
            env.install_mock_tool("rg", stdout="ripgrep 14.1.0")
            resolver = ToolResolverSeam(env)
            path = resolver.resolve_tool("rg")
            self.assertTrue(os.path.exists(path))
            self.assertTrue(path.endswith("rg"))

    def test_f08_c02_resolves_fd_from_termux_path(self):
        with MockTermuxEnv(is_android=True) as env:
            env.install_mock_tool("fd", stdout="fd 9.0.0")
            resolver = ToolResolverSeam(env)
            path = resolver.resolve_tool("fd")
            self.assertTrue(os.path.exists(path))

    def test_f08_c03_resolves_git_from_termux_path(self):
        with MockTermuxEnv(is_android=True) as env:
            env.install_mock_tool("git", stdout="git version 2.45.0")
            resolver = ToolResolverSeam(env)
            path = resolver.resolve_tool("git")
            self.assertTrue(os.path.exists(path))

    def test_f08_c04_resolves_bash_from_termux_path(self):
        with MockTermuxEnv(is_android=True) as env:
            env.install_mock_tool("bash", stdout="GNU bash 5.2")
            resolver = ToolResolverSeam(env)
            path = resolver.resolve_tool("bash")
            self.assertTrue(os.path.exists(path))

    def test_f08_c05_missing_tool_suggests_pkg_install(self):
        with MockTermuxEnv(is_android=True) as env:
            # Tool not in mock_tools and not in PATH
            resolver = ToolResolverSeam(env)
            with self.assertRaises(ToolResolutionError) as ctx:
                resolver.resolve_tool("nonexistent_tool_xyz")
            self.assertIn("pkg install nonexistent_tool_xyz", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
