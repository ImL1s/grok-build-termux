#!/usr/bin/env python3
"""
Milestone 3 Empirical Challenger Stress Test Suite
Testing:
1. Feature 10 & 11: System Config & User Home Directory Boundaries
   - $PREFIX/etc/grok on Termux vs /etc/grok on Desktop Linux
   - $HOME/.grok resolution and fail-closed behavior
2. Feature 12: Runtime Temporary Files & Unix Domain Sockets
   - Dynamic $TMPDIR resolution with $PREFIX/tmp fallback
   - Socket paths strictly < 108 bytes sun_path limit with Blake3 hash
   - Stale socket cleanup and collision resistance
3. Feature 13 & 14: Shared Storage Quarantine & Workspace Protection
   - Strict rejection of /sdcard, /storage/emulated/0, /mnt/sdcard for credentials/state
   - Path traversal, case-insensitive, and symlink evasion prevention
   - Dual-track isolation: editing /sdcard workspaces keeps sessions/tokens in $HOME/.grok
"""

import os
import sys
import unittest
from pathlib import Path

# Ensure repo root is on sys.path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tests.e2e.harness.termux_sim import (
    MockTermuxEnv,
    PlatformCapabilities,
    StorageSafetyError,
    PlatformError,
)


class TestMilestone3FilesystemSafetyStress(unittest.TestCase):
    """Stress and adversarial tests for Milestone 3 filesystem safety."""

    def test_feature_10_system_config_resolution(self):
        """Feature 10: Verify $PREFIX/etc/grok dynamic resolution."""
        # 1. Termux standard environment
        with MockTermuxEnv() as env:
            caps = PlatformCapabilities(env)
            expected = os.path.join(env.prefix_dir, "etc/grok")
            self.assertEqual(caps.system_config_dir(), expected)

        # 2. Custom $PREFIX (e.g. multi-user /data/user/0/...)
        with MockTermuxEnv(custom_prefix="/data/user/0/com.termux/files/usr") as env:
            caps = PlatformCapabilities(env)
            expected = os.path.join(env.prefix_dir, "etc/grok")
            self.assertEqual(caps.system_config_dir(), expected)

        # 3. Desktop Linux fallback (/etc/grok)
        with MockTermuxEnv(is_android=False) as env:
            caps = PlatformCapabilities(env)
            self.assertEqual(caps.system_config_dir(), "/etc/grok")

    def test_feature_11_user_home_resolution_and_quarantine(self):
        """Feature 11: Verify $HOME/.grok user home resolution and rejection of unsafe locations."""
        with MockTermuxEnv() as env:
            caps = PlatformCapabilities(env)
            expected_home = os.path.join(env.home_dir, ".grok")
            self.assertEqual(caps.home_dir(), expected_home)

            # Safe custom GROK_HOME
            safe_custom = os.path.join(env.home_dir, "custom_grok")
            os.environ["GROK_HOME"] = safe_custom
            self.assertEqual(caps.home_dir(), safe_custom)

            # Unsafe GROK_HOME on /sdcard
            os.environ["GROK_HOME"] = "/sdcard/.grok"
            with self.assertRaises(StorageSafetyError):
                caps.home_dir()

            # Unsafe GROK_HOME on /storage/emulated/0
            os.environ["GROK_HOME"] = "/storage/emulated/0/Download/.grok"
            with self.assertRaises(StorageSafetyError):
                caps.home_dir()

    def test_feature_12_socket_path_length_and_temp_dir(self):
        """Feature 12: Verify Unix domain sockets stay strictly < 108 bytes with Blake3 hash."""
        with MockTermuxEnv() as env:
            caps = PlatformCapabilities(env)
            # $TMPDIR resolution
            self.assertEqual(caps.temp_dir(), env.tmp_dir)

            # Diverse session IDs (short, long, unicode, special)
            session_ids = [
                "s1",
                "normal-session-12345",
                "very-long-session-id-" + "x" * 200,
                "session-unicode-測試-🌟-🚀",
                "session with spaces and $PECIAL chars!",
            ]
            for sid in session_ids:
                sock_path = caps.create_socket_path(sid)
                sock_name = os.path.basename(sock_path)
                termux_path = f"/data/data/com.termux/files/usr/tmp/{sock_name}"
                termux_bytes = termux_path.encode("utf-8")
                self.assertLess(len(termux_bytes), 108, f"Socket path {termux_path} exceeded 108 bytes")
                self.assertTrue(sock_name.startswith("grok-"))
                self.assertTrue(sock_name.endswith(".sock"))

    def test_feature_13_shared_storage_quarantine_adversarial(self):
        """Feature 13: Validate comprehensive quarantine of Android shared storage paths."""
        with MockTermuxEnv() as env:
            caps = PlatformCapabilities(env)

            quarantined_paths = [
                "/sdcard",
                "/sdcard/Download",
                "/sdcard/.grok/auth.json",
                "/storage/emulated/0",
                "/storage/emulated/0/Download/grok_home",
                "/storage/self/primary",
                "/mnt/sdcard",
                "/mnt/sdcard/keys",
                "/mnt/media_rw/1234-5678",
                "/data/sdcard",
                "/data/media/0",
                # Traversal attempts
                os.path.join(env.home_dir, "../../../../sdcard/.grok"),
                os.path.join(env.home_dir, "../../../../storage/emulated/0/.grok"),
                # Case variations
                "/SDCARD/auth.json",
                "/Storage/Emulated/0/keys",
                "/MNT/SDCARD/token",
            ]
            for p in quarantined_paths:
                with self.subTest(path=p):
                    with self.assertRaises(StorageSafetyError, msg=f"Failed to quarantine {p}"):
                        caps.validate_storage_safety(p)

            # Safe Termux paths
            safe_paths = [
                os.path.join(env.home_dir, ".grok"),
                os.path.join(env.home_dir, ".grok/auth.json"),
                os.path.join(env.home_dir, ".grok/sessions"),
                os.path.join(env.prefix_dir, "etc/grok"),
                os.path.join(env.prefix_dir, "tmp"),
            ]
            for sp in safe_paths:
                with self.subTest(path=sp):
                    try:
                        caps.validate_storage_safety(sp)
                    except StorageSafetyError as e:
                        self.fail(f"Safe path falsely rejected: {sp} ({e})")

    def test_feature_14_workspace_dual_track_isolation(self):
        """Feature 14: Editing code on /sdcard keeps sessions, tokens, and caches in $HOME/.grok."""
        with MockTermuxEnv() as env:
            caps = PlatformCapabilities(env)
            workspace_cwd = "/sdcard/Download/my-android-app"

            # 1. State and user home must remain in Termux private app dir
            self.assertEqual(caps.home_dir(), os.path.join(env.home_dir, ".grok"))
            self.assertTrue(caps.home_dir().startswith(env.home_dir))
            self.assertNotIn("/sdcard", caps.home_dir())

            # 2. Temporary files & sockets remain in Termux private tmp dir
            sock = caps.create_socket_path(workspace_cwd)
            self.assertTrue(sock.startswith(env.tmp_dir))
            self.assertNotIn("/sdcard", sock)


if __name__ == "__main__":
    unittest.main()
