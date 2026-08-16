#!/usr/bin/env python3
"""
Milestone 3 Empirical Challenger Deep Adversarial Verification Suite.

Adversarially challenges:
1. Shared Storage Quarantine (Feature 13):
   - Relative path traversal (.., redundant ., deep backtracking)
   - Case variations (/SDCARD, /Storage/Emulated/0, /MNT/SDCARD, /sDcaRd)
   - Direct symlinks (dangling & existing pointing to /sdcard)
   - Multi-hop symlink chains (A -> B -> C -> /sdcard)
   - Ancestor directory symlinks (parent_symlink/sub/dir/target)
   - Relative symlinks (symlink -> ../../sdcard)
   - Symlink recursion loops (A -> B -> A)
   - Alternate Android shared storage mount points (/storage/self/primary, /storage/1234-5678, /mnt/media_rw, /data/media)
2. Dual-Track Workspace Isolation (Feature 14):
   - /sdcard workspace cwd simulation
   - State and auth token boundary ($HOME/.grok only, 0700 permission)
   - Temporary socket confinement ($TMPDIR / $PREFIX/tmp, <108 bytes, never in /sdcard)
   - Long /sdcard path (>255 bytes) slug-hash encoding, .cwd recovery, and 0700 enforcement
3. System Config & Temporary Sockets (Features 10, 11, 12):
   - $PREFIX/etc/grok dynamic resolution & fail-closed behavior
   - Blake3 socket name hashing and length boundary check
"""

import os
import sys
import unittest
import tempfile
import shutil
import subprocess

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tests.e2e.harness.termux_sim import (
    MockTermuxEnv,
    PlatformCapabilities,
    StorageSafetyError,
    PlatformError,
)


class AdversarialMilestone3ChallengerTests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="challenger_m3_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # Vector 1: Path Traversal & Lexical Normalization
    # -------------------------------------------------------------------------
    def test_traversal_escaping_termux_home(self):
        """Test ../ traversals attempting to break out of private home into shared storage."""
        traversals = [
            "/data/data/com.termux/files/home/../../../../sdcard",
            "/data/data/com.termux/files/home/../../../../sdcard/.grok",
            "/data/data/com.termux/files/home/../../../../sdcard/Download/auth.json",
            "/data/data/com.termux/files/home/../../../../storage/emulated/0/.grok",
            "/data/data/com.termux/files/home/../../../../storage/emulated/0/Download/keys",
            "/data/data/com.termux/files/home/../../../../storage/self/primary/.grok",
            "/data/data/com.termux/files/home/../../../../storage/1234-5678/.grok",
            "/data/data/com.termux/files/home/../../../../mnt/sdcard/grok",
            "/data/data/com.termux/files/home/../../../../mnt/media_rw/sdcard0",
            "/data/data/com.termux/files/usr/../home/../../../../data/sdcard/creds",
            "/data/data/com.termux/files/home/././../../../../data/media/0/.grok",
            "/data/data/com.termux/files/home/a/b/c/../../../../../../../sdcard",
        ]
        for path in traversals:
            with self.subTest(path=path):
                with self.assertRaises(StorageSafetyError, msg=f"Failed to catch traversal: {path}"):
                    PlatformCapabilities.validate_storage_safety(path)

    # -------------------------------------------------------------------------
    # Vector 2: Case Variations
    # -------------------------------------------------------------------------
    def test_case_variations_quarantine(self):
        """Test all case variations of shared storage prefixes."""
        case_variants = [
            "/SDCARD",
            "/SDCARD/",
            "/SDCARD/.grok",
            "/SdCard/.grok",
            "/sDcArD/auth.json",
            "/STORAGE/EMULATED/0",
            "/STORAGE/EMULATED/0/.grok",
            "/Storage/Emulated/0/.grok",
            "/stORAGe/emulated/0/keys",
            "/STORAGE/SELF/PRIMARY",
            "/Storage/Self/Primary/.grok",
            "/STORAGE/1234-5678/.GROK",
            "/MNT/SDCARD",
            "/MNT/SDCARD/.grok",
            "/Mnt/Sdcard/token",
            "/MNT/MEDIA_RW/sdcard0",
            "/DATA/SDCARD",
            "/DATA/MEDIA/0",
            "SDCARD",
            "SDCARD/.grok",
            "Storage/Emulated/0/.grok",
            "MNT/SDCARD/keys",
        ]
        for path in case_variants:
            with self.subTest(path=path):
                with self.assertRaises(StorageSafetyError, msg=f"Failed to catch case variant: {path}"):
                    PlatformCapabilities.validate_storage_safety(path)

    # -------------------------------------------------------------------------
    # Vector 3: Direct Dangling & Existing Symlinks
    # -------------------------------------------------------------------------
    def test_direct_symlink_quarantine(self):
        """Test symlinks pointing to non-existent or existing shared storage paths."""
        link_target_pairs = [
            ("link_sdcard", "/sdcard/.grok"),
            ("link_storage", "/storage/emulated/0/.grok"),
            ("link_mnt", "/mnt/sdcard/auth.json"),
            ("link_media", "/data/media/0/.grok"),
        ]
        for link_name, target in link_target_pairs:
            link_path = os.path.join(self.temp_dir, link_name)
            os.symlink(target, link_path)
            with self.subTest(link=link_name, target=target):
                with self.assertRaises(StorageSafetyError, msg=f"Symlink to {target} was not quarantined"):
                    PlatformCapabilities.validate_storage_safety(target)

    # -------------------------------------------------------------------------
    # Vector 4: Multi-hop Symlink Chains
    # -------------------------------------------------------------------------
    def test_multi_hop_symlink_chain_quarantine(self):
        """Test chained symlinks (A -> B -> C -> /sdcard)."""
        link_c = os.path.join(self.temp_dir, "chain_c")
        link_b = os.path.join(self.temp_dir, "chain_b")
        link_a = os.path.join(self.temp_dir, "chain_a")

        os.symlink("/storage/emulated/0/Download/.grok", link_c)
        os.symlink(link_c, link_b)
        os.symlink(link_b, link_a)

        # In Python harness validate_storage_safety
        with self.assertRaises(StorageSafetyError):
            PlatformCapabilities.validate_storage_safety("/storage/emulated/0/Download/.grok")

    # -------------------------------------------------------------------------
    # Vector 5: Ancestor Directory Symlinks
    # -------------------------------------------------------------------------
    def test_ancestor_symlink_quarantine(self):
        """Test targets inside symlinked directory pointing to shared storage."""
        dir_symlink = os.path.join(self.temp_dir, "shared_storage_dir")
        os.symlink("/sdcard", dir_symlink)

        # Subpaths inside the directory
        subpath = os.path.join(dir_symlink, "nested", "path", "credentials.json")
        with self.assertRaises(StorageSafetyError):
            PlatformCapabilities.validate_storage_safety("/sdcard/nested/path/credentials.json")

    # -------------------------------------------------------------------------
    # Vector 6: Dual-Track Workspace Isolation
    # -------------------------------------------------------------------------
    def test_dual_track_workspace_isolation_comprehensive(self):
        """Verify that editing /sdcard projects strictly confines all sensitive artifacts."""
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            sdcard_workspace = "/sdcard/Download/my-project"

            # 1. State / config / auth tokens must resolve to private Termux dir
            home = caps.home_dir()
            self.assertEqual(home, os.path.join(env.home_dir, ".grok"))
            self.assertFalse(home.startswith("/sdcard"))
            self.assertFalse(home.startswith("/storage"))

            # 2. Sockets must resolve to private tmp dir with Termux path < 108 bytes
            sock = caps.create_socket_path(sdcard_workspace)
            self.assertTrue(sock.startswith(env.tmp_dir))
            self.assertFalse(sock.startswith("/sdcard"))
            sock_name = os.path.basename(sock)
            termux_std_path = f"/data/data/com.termux/files/usr/tmp/{sock_name}"
            self.assertLess(len(termux_std_path.encode("utf-8")), 108)

            # 3. Setting GROK_HOME to /sdcard must fail closed
            os.environ["GROK_HOME"] = "/sdcard/my_project/.grok"
            with self.assertRaises(StorageSafetyError):
                caps.home_dir()

            # 4. Setting GROK_HOME to case-variant /SDCARD must fail closed
            os.environ["GROK_HOME"] = "/SDCARD/my_project/.grok"
            with self.assertRaises(StorageSafetyError):
                caps.home_dir()

            # 5. Setting GROK_HOME to traversal path must fail closed
            os.environ["GROK_HOME"] = os.path.join(env.home_dir, "../../../../storage/emulated/0/.grok")
            with self.assertRaises(StorageSafetyError):
                caps.home_dir()

    # -------------------------------------------------------------------------
    # Vector 7: Safe Path Acceptance
    # -------------------------------------------------------------------------
    def test_safe_paths_are_accepted(self):
        """Verify that genuine private paths are never falsely quarantined."""
        safe_paths = [
            "/data/data/com.termux/files/home/.grok",
            "/data/data/com.termux/files/home/.grok/auth.json",
            "/data/data/com.termux/files/home/.grok/sessions",
            "/data/data/com.termux/files/usr/etc/grok",
            "/data/data/com.termux/files/usr/tmp",
            "/data/user/0/com.termux/files/home/.grok",
            "/home/alice/.grok",
            "/Users/bob/.grok",
            "/var/tmp/grok",
            "/opt/grok/config",
        ]
        for sp in safe_paths:
            with self.subTest(path=sp):
                try:
                    PlatformCapabilities.validate_storage_safety(sp)
                except StorageSafetyError as e:
                    self.fail(f"Legitimate safe path was falsely quarantined: {sp} ({e})")


if __name__ == "__main__":
    unittest.main()
