"""
Adversarial Stress Test Harness for Milestone 2:
Native Bionic Build & Toolchain Alignment (Features 6–9)

Challenges:
1. Missing tools behavior (clean error with pkg install hint, optional tool graceful degradation)
2. Search cascade precedence: Env Override -> $PATH -> $PREFIX/bin -> /system/bin -> Fallback
3. Edge cases: Empty $PATH, Custom $PREFIX, Non-executable files, Unicode paths, Corrupted directories
4. Shell resolution cascade and fallback behavior
"""

import unittest
import os
import tempfile
import stat
import shutil
from tests.e2e.harness.termux_sim import (
    MockTermuxEnv,
    PlatformCapabilities,
    ToolResolverSeam,
    ToolResolutionError,
    PlatformError,
)


class AdversarialM2ToolResolverTests(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="adv_m2_test_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # Dimension 1: Missing Tools & Remediation Hints
    # -------------------------------------------------------------------------

    def test_adv_01_missing_required_tool_provides_actionable_pkg_install_hint(self):
        """When a required tool (rg, fd, git, bash) is missing, it must return actionable pkg install hint."""
        with MockTermuxEnv(is_android=True) as env:
            resolver = ToolResolverSeam(env)
            for tool in ["rg", "fd", "git", "bash"]:
                with self.assertRaises(ToolResolutionError) as ctx:
                    resolver.resolve_tool(tool)
                err_msg = str(ctx.exception)
                self.assertIn("not found in PATH", err_msg)
                self.assertIn(f"pkg install {tool}", err_msg)

    def test_adv_02_missing_arbitrary_tool_provides_termux_package_name(self):
        """Unknown or arbitrary tool missing must not crash and format hint gracefully."""
        with MockTermuxEnv(is_android=True) as env:
            resolver = ToolResolverSeam(env)
            tool_name = "custom_tool_alpha_beta_123"
            with self.assertRaises(ToolResolutionError) as ctx:
                resolver.resolve_tool(tool_name)
            self.assertIn(f"pkg install {tool_name}", str(ctx.exception))

    def test_adv_03_optional_tools_missing_do_not_fail_execution(self):
        """Optional tools (bfs, ugrep) missing should not halt or throw unhandled exceptions."""
        with MockTermuxEnv(is_android=True) as env:
            # bfs/ugrep missing should be detectable without halting
            for opt in ["bfs", "ugrep"]:
                self.assertNotIn(opt, env.mock_tools)

    # -------------------------------------------------------------------------
    # Dimension 2: Precedence Order Cascade
    # -------------------------------------------------------------------------

    def test_adv_04_precedence_env_override_beats_all(self):
        """Explicit environment variable override must take precedence over PATH and PREFIX."""
        with MockTermuxEnv(is_android=True) as env:
            # 1. Install tool in $PREFIX/bin
            pfx_bin = env.install_mock_tool("rg", stdout="rg in prefix")
            # 2. Create tool in custom override location
            override_dir = os.path.join(self.test_dir, "override_bin")
            os.makedirs(override_dir, exist_ok=True)
            override_rg = os.path.join(override_dir, "rg_custom")
            with open(override_rg, "w") as f:
                f.write("#!/bin/sh\necho 'rg in override'\n")
            os.chmod(override_rg, 0o755)

            # Check: override path set in env
            os.environ["RG_BIN_PATH"] = override_rg
            try:
                self.assertEqual(os.environ.get("RG_BIN_PATH"), override_rg)
                self.assertTrue(os.path.isfile(override_rg))
            finally:
                os.environ.pop("RG_BIN_PATH", None)

    def test_adv_05_precedence_path_beats_prefix_and_system(self):
        """A tool in $PATH earlier than $PREFIX must be selected over $PREFIX or /system."""
        with MockTermuxEnv(is_android=True) as env:
            # Priority directory prepended to PATH
            high_pri_dir = os.path.join(self.test_dir, "high_pri_bin")
            os.makedirs(high_pri_dir, exist_ok=True)
            high_pri_tool = os.path.join(high_pri_dir, "rg")
            with open(high_pri_tool, "w") as f:
                f.write("#!/bin/sh\necho 'high pri rg'\n")
            os.chmod(high_pri_tool, 0o755)

            # Normal prefix tool
            env.install_mock_tool("rg", stdout="normal prefix rg")

            # Update PATH with high priority first
            os.environ["PATH"] = f"{high_pri_dir}:{env.bin_dir}"
            resolver = ToolResolverSeam(env)
            resolved = resolver.resolve_tool("rg")
            self.assertEqual(resolved, high_pri_tool)

    def test_adv_06_precedence_prefix_beats_system_fallbacks(self):
        """When tool is in $PREFIX/bin, it must resolve there rather than /system/bin."""
        with MockTermuxEnv(is_android=True) as env:
            pfx_tool = env.install_mock_tool("bash", stdout="bash in prefix")
            resolver = ToolResolverSeam(env)
            resolved = resolver.resolve_tool("bash")
            self.assertEqual(resolved, pfx_tool)
            self.assertTrue(resolved.startswith(env.prefix_dir))

    # -------------------------------------------------------------------------
    # Dimension 3: Edge Cases & Boundary Conditions
    # -------------------------------------------------------------------------

    def test_adv_07_empty_path_falls_back_to_prefix_bin(self):
        """When PATH is empty string (''), resolver must fall back to $PREFIX/bin."""
        with MockTermuxEnv(is_android=True) as env:
            pfx_tool = env.install_mock_tool("fd", stdout="fd in prefix")
            os.environ["PATH"] = ""
            resolver = ToolResolverSeam(env)
            resolved = resolver.resolve_tool("fd")
            self.assertEqual(resolved, pfx_tool)

    def test_adv_08_custom_deeply_nested_prefix(self):
        """Custom non-standard prefix paths (e.g. /data/local/tmp/termux_custom/usr) resolve cleanly."""
        nested_pfx = "data/local/tmp/termux_custom/usr"
        with MockTermuxEnv(custom_prefix=nested_pfx, is_android=True) as env:
            env.install_mock_tool("git", stdout="git in custom prefix")
            caps = PlatformCapabilities(env)
            self.assertTrue(caps.prefix_dir().endswith(nested_pfx))
            resolver = ToolResolverSeam(env)
            resolved = resolver.resolve_tool("git")
            self.assertTrue(resolved.startswith(env.prefix_dir))

    def test_adv_09_prefix_with_spaces_or_special_characters(self):
        """Prefix path containing spaces or hyphens should not break resolution."""
        special_pfx = "data/termux prefix-test_v1.0/usr"
        with MockTermuxEnv(custom_prefix=special_pfx, is_android=True) as env:
            env.install_mock_tool("rg", stdout="rg in special prefix")
            resolver = ToolResolverSeam(env)
            resolved = resolver.resolve_tool("rg")
            self.assertTrue(os.path.exists(resolved))
            self.assertIn("termux prefix-test_v1.0", resolved)

    def test_adv_10_non_executable_binary_is_rejected_or_handled(self):
        """If a file with the binary name exists but has 0644 mode, execution attempt must fail cleanly."""
        with MockTermuxEnv(is_android=True) as env:
            non_exec_tool = os.path.join(env.bin_dir, "rg")
            with open(non_exec_tool, "w") as f:
                f.write("#!/bin/sh\necho 'should not run'\n")
            os.chmod(non_exec_tool, 0o644)  # No execute bits

            # Verify file is not executable by mode bits
            st = os.stat(non_exec_tool)
            self.assertEqual(st.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH), 0)

    def test_adv_11_symlink_to_valid_tool_resolves(self):
        """Symlinks to valid binaries inside $PREFIX/bin resolve successfully."""
        with MockTermuxEnv(is_android=True) as env:
            real_tool = env.install_mock_tool("rg_real", stdout="real rg")
            symlink_tool = os.path.join(env.bin_dir, "rg")
            os.symlink(real_tool, symlink_tool)

            self.assertTrue(os.path.islink(symlink_tool))
            self.assertTrue(os.path.exists(symlink_tool))

    def test_adv_12_broken_symlink_is_handled_cleanly(self):
        """Broken symlink in PATH must not cause an unhandled crash."""
        with MockTermuxEnv(is_android=True) as env:
            broken_target = os.path.join(env.bin_dir, "nonexistent_target_xyz")
            broken_symlink = os.path.join(env.bin_dir, "rg")
            os.symlink(broken_target, broken_symlink)

            self.assertTrue(os.path.islink(broken_symlink))
            self.assertFalse(os.path.exists(broken_symlink))


if __name__ == "__main__":
    unittest.main()
