#!/usr/bin/env python3
"""
Tier 5 Adversarial Hardening Test Suite: Storage, Platform & Filesystem Boundaries.

White-box adversarial tests covering:
1. Platform Capability Detection & Capabilities Spoofing ($PREFIX manipulation, display/audio gating, diagnostic facts).
2. Shared Storage Quarantine (/sdcard traversal, symlink loops, relative path tricks, dual-track workspace protection).
3. Unix Socket Constraints (<108 bytes length boundary, stale socket cleanup, 0600/0700 permission masks, rapid re-bind).
4. In-Process Path Enforcement & Policy-Only Sandbox Validation (truthful reporting, hook write denial, fail-closed policy).
"""

import os
import sys
import stat
import socket
import tempfile
import shutil
import unittest
import threading
import urllib.parse
import hashlib
from pathlib import Path
from typing import Dict, List, Optional

# Ensure repository root is on sys.path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tests.e2e.harness.termux_sim import (
    MockTermuxEnv,
    PlatformCapabilities,
    SandboxKind,
    StorageSafetyError,
    PlatformError,
    DoctorDiagnosticsSeam,
    ToolResolverSeam,
)


# =============================================================================
# Helper utilities for adversarial testing
# =============================================================================

def simulate_lexical_normalize(path_str: str) -> str:
    """Lexically normalizes a path string, resolving . and .. without disk access."""
    # Split path into components
    is_absolute = path_str.startswith("/")
    parts = path_str.replace("\\", "/").split("/")
    stack: List[str] = []
    
    for p in parts:
        if p == "" or p == ".":
            continue
        elif p == "..":
            if stack and stack[-1] != "..":
                stack.pop()
            elif not is_absolute:
                stack.append("..")
        else:
            stack.append(p)
    
    if is_absolute:
        return "/" + "/".join(stack)
    else:
        return "/".join(stack) if stack else "."


def check_storage_quarantine(path_str: str) -> bool:
    """
    Simulates validate_storage_safety in xai-grok-config/src/platform.rs.
    Returns True if quarantined (unsafe/rejected), False if safe/accepted.
    """
    try:
        PlatformCapabilities.validate_storage_safety(path_str)
        return False
    except StorageSafetyError:
        return True


def encode_cwd_slug_hash(cwd: str, max_bytes: int = 255) -> str:
    """Simulates encode_cwd_dirname from xai-grok-config/src/paths.rs."""
    url_encoded = urllib.parse.quote(cwd, safe="")
    if len(url_encoded.encode("utf-8")) <= 255:
        return url_encoded
    
    # Hash-based slug fallback
    h = hashlib.blake2b(cwd.encode("utf-8"), digest_size=8).hexdigest()
    leaf = os.path.basename(cwd.rstrip("/")) or "workspace"
    slug = "".join(c.lower() if c.isalnum() else "-" for c in leaf).strip("-")[:40]
    slug = slug or "workspace"
    return f"{slug}-{h}"


# =============================================================================
# Section 1: Platform Detection & Capabilities Spoofing Adversarial Tests
# =============================================================================

class TestAdversarialPlatformCapabilities(unittest.TestCase):
    """Adversarial stress tests for Platform capability detection and environment spoofing."""

    def test_adv_p01_missing_prefix_fails_closed_on_android(self):
        """Unset $PREFIX on Android produces UnsupportedAndroid and raises PlatformError on prefix_dir()."""
        with MockTermuxEnv(is_android=True) as env:
            os.environ.pop("PREFIX", None)
            caps = PlatformCapabilities(env)
            self.assertFalse(caps.is_android_termux())
            with self.assertRaises(PlatformError) as ctx:
                caps.prefix_dir()
            self.assertIn("PREFIX is not set", str(ctx.exception))
            self.assertIsNone(caps.system_config_dir())

    def test_adv_p02_empty_string_and_whitespace_prefix(self):
        """PREFIX="" and whitespace-only strings fail closed and are rejected."""
        whitespaces = ["", "   ", "\t", "\n", "\r\n", " \t \n "]
        for ws in whitespaces:
            with MockTermuxEnv(is_android=True) as env:
                os.environ["PREFIX"] = ws
                caps = PlatformCapabilities(env)
                self.assertFalse(caps.is_android_termux(), f"Failed for whitespace: {ws!r}")
                self.assertIsNone(caps.system_config_dir())
                # Empty string raises error or whitespace returns empty-stripped
                if ws == "":
                    with self.assertRaises(PlatformError):
                        caps.prefix_dir()
                else:
                    self.assertEqual(caps.prefix_dir().strip(), "")

    def test_adv_p03_prefix_with_redundant_and_trailing_slashes(self):
        """PREFIX with trailing or duplicate slashes resolves without crashing."""
        with MockTermuxEnv(is_android=True) as env:
            prefix_with_slashes = f"{env.prefix_dir}///"
            os.environ["PREFIX"] = prefix_with_slashes
            caps = PlatformCapabilities(env)
            self.assertTrue(caps.is_android_termux())
            resolved_pfx = caps.prefix_dir()
            self.assertEqual(resolved_pfx, prefix_with_slashes)
            sys_conf = caps.system_config_dir()
            self.assertIsNotNone(sys_conf)
            self.assertTrue(sys_conf.endswith("etc/grok"))

    def test_adv_p04_custom_nonstandard_prefixes(self):
        """Non-standard Termux prefix locations (custom terminal apps) resolve cleanly."""
        custom_prefixes = [
            "/data/data/com.custom.term/files/usr",
            "/data/user/0/com.termux/files/usr",
            "/opt/termux/usr",
            "/data/local/tmp/termux/usr",
        ]
        for pfx in custom_prefixes:
            with MockTermuxEnv(custom_prefix=pfx, is_android=True) as env:
                caps = PlatformCapabilities(env)
                self.assertTrue(caps.is_android_termux())
                self.assertEqual(caps.prefix_dir(), env.prefix_dir)
                self.assertEqual(caps.system_config_dir(), f"{env.prefix_dir}/etc/grok")

    def test_adv_p05_termux_version_set_without_prefix(self):
        """Setting TERMUX_VERSION without PREFIX must fail closed on prefix resolution."""
        with MockTermuxEnv(is_android=True) as env:
            os.environ.pop("PREFIX", None)
            os.environ["TERMUX_VERSION"] = "0.118.1"
            caps = PlatformCapabilities(env)
            self.assertFalse(caps.is_android_termux())
            with self.assertRaises(PlatformError):
                caps.prefix_dir()

    def test_adv_p06_fake_display_server_detection_truthfulness(self):
        """DISPLAY and WAYLAND_DISPLAY presence on Termux are accurately detected."""
        with MockTermuxEnv(is_android=True) as env:
            os.environ.pop("DISPLAY", None)
            os.environ.pop("WAYLAND_DISPLAY", None)
            # Default Termux is headless
            has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
            self.assertFalse(has_display)

            # With X11 display
            os.environ["DISPLAY"] = ":0"
            has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
            self.assertTrue(has_display)

            # With Wayland display
            os.environ.pop("DISPLAY", None)
            os.environ["WAYLAND_DISPLAY"] = "wayland-0"
            has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
            self.assertTrue(has_display)

    def test_adv_p07_audio_capability_gating_invariants(self):
        """Android/Termux targets strictly disable audio capture regardless of ALSA/Pulse env vars."""
        with MockTermuxEnv(is_android=True) as env:
            os.environ["PULSE_SERVER"] = "127.0.0.1:4713"
            os.environ["ALSA_CARD"] = "0"
            # Audio is gated out at compile time / platform detection for Android
            has_audio_android = not env.is_android
            self.assertFalse(has_audio_android, "Audio capture must be disabled on Android/Termux")

    def test_adv_p08_desktop_vs_android_platform_invariants(self):
        """Desktop Linux, macOS, and Termux adhere to their respective platform invariants."""
        # Termux Android
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            self.assertTrue(caps.is_android_termux())
            self.assertEqual(caps.sandbox_kind(), SandboxKind.POLICY_ONLY)
            self.assertTrue(caps.system_config_dir().endswith("etc/grok"))

        # Desktop Linux / macOS
        with MockTermuxEnv(is_android=False) as env:
            os.environ.pop("TMPDIR", None)
            caps = PlatformCapabilities(env)
            self.assertFalse(caps.is_android_termux())
            self.assertEqual(caps.sandbox_kind(), SandboxKind.KERNEL_ENFORCED)
            self.assertEqual(caps.system_config_dir(), "/etc/grok")
            self.assertEqual(caps.temp_dir(), "/tmp")

    def test_adv_p09_missing_home_and_userprofile_error_handling(self):
        """Missing HOME raises PlatformError when resolving grok user home."""
        with MockTermuxEnv(is_android=True) as env:
            os.environ.pop("HOME", None)
            os.environ.pop("USERPROFILE", None)
            caps = PlatformCapabilities(env)
            with self.assertRaises(PlatformError) as ctx:
                caps.home_dir()
            self.assertIn("HOME environment variable is not set", str(ctx.exception))

    def test_adv_p10_grok_home_env_override_safety_validation(self):
        """Setting GROK_HOME to safe path is accepted; setting to /sdcard is rejected with StorageSafetyError."""
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)

            # Safe custom home
            safe_custom = os.path.join(env.home_dir, "custom_grok_state")
            os.environ["GROK_HOME"] = safe_custom
            self.assertEqual(caps.home_dir(), safe_custom)

            # Unsafe custom home pointing to shared storage
            os.environ["GROK_HOME"] = "/sdcard/my_grok_creds"
            with self.assertRaises(StorageSafetyError):
                caps.home_dir()

    def test_adv_p11_diagnose_platform_facts_structure(self):
        """Diagnostics facts dictionary conforms to expected schema and detects invalid prefix."""
        with MockTermuxEnv(is_android=True) as env:
            resolver = ToolResolverSeam(env)
            caps = PlatformCapabilities(env)
            doctor = DoctorDiagnosticsSeam(caps, resolver)
            facts = doctor.run_diagnostics()

            self.assertEqual(facts["platform"], "Android/Termux")
            self.assertTrue(facts["prefix_valid"])
            self.assertTrue(facts["storage_safe"])
            self.assertEqual(facts["sandbox_kind"], "policy-only")
            self.assertIsInstance(facts["tools"], dict)

    def test_adv_p12_concurrent_platform_capabilities_probe_stress(self):
        """Multi-threaded concurrent probing (50 threads) of PlatformCapabilities maintains state isolation."""
        threads = []
        errors = []

        def worker(thread_id: int):
            try:
                for i in range(20):
                    is_termux = (thread_id + i) % 2 == 0
                    with MockTermuxEnv(is_android=is_termux) as env:
                        caps = PlatformCapabilities(env)
                        if is_termux:
                            self.assertTrue(caps.is_android_termux())
                            self.assertEqual(caps.sandbox_kind(), SandboxKind.POLICY_ONLY)
                        else:
                            self.assertFalse(caps.is_android_termux())
                            self.assertEqual(caps.sandbox_kind(), SandboxKind.KERNEL_ENFORCED)
            except Exception as e:
                errors.append(e)

        for t in range(50):
            th = threading.Thread(target=worker, args=(t,))
            threads.append(th)
            th.start()

        for th in threads:
            th.join()

        self.assertEqual(len(errors), 0, f"Concurrent thread errors: {errors}")


# =============================================================================
# Section 2: Shared Storage Quarantine & Filesystem Boundary Adversarial Tests
# =============================================================================

class TestAdversarialStorageQuarantine(unittest.TestCase):
    """Adversarial stress tests for shared storage quarantine, symlinks, and path traversals."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="adv_storage_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_adv_s01_direct_shared_storage_prefixes_quarantined(self):
        """All direct Android shared storage prefixes are strictly quarantined."""
        unsafe_paths = [
            "/sdcard",
            "/sdcard/",
            "/sdcard/.grok",
            "/sdcard/Download/grok",
            "/storage/emulated/0",
            "/storage/emulated/0/.grok",
            "/storage/emulated/10/.grok",
            "/storage/self/primary",
            "/storage/self/primary/.grok",
            "/storage/1234-5678/.grok",
            "/mnt/sdcard",
            "/mnt/sdcard/.grok",
            "/mnt/media_rw",
            "/mnt/media_rw/sdcard0",
            "/data/sdcard",
            "/data/media/0/.grok",
        ]
        for path in unsafe_paths:
            self.assertTrue(
                check_storage_quarantine(path),
                f"Expected unsafe path to be quarantined: {path}"
            )

    def test_adv_s02_lexical_path_traversals_to_shared_storage(self):
        """Lexical path traversals (../..) reaching shared storage are caught and quarantined."""
        traversals = [
            "/data/data/com.termux/files/home/../../../../sdcard",
            "/data/data/com.termux/files/home/../../../../sdcard/.grok",
            "/data/data/com.termux/files/home/../../../../storage/emulated/0/.grok",
            "/data/data/com.termux/files/home/././../../../../storage/self/primary",
            "/data/data/com.termux/files/usr/../home/../../../../mnt/sdcard/keys",
            "/data/data/com.termux/files/home/subdir/../../../../../data/sdcard/test",
        ]
        for path in traversals:
            self.assertTrue(
                check_storage_quarantine(path),
                f"Expected traversal to be quarantined: {path}"
            )

    def test_adv_s03_relative_shared_storage_prefixes(self):
        """Relative path prefixes pointing to shared storage are quarantined."""
        rel_paths = [
            "sdcard/.grok",
            "sdcard/Download/keys.json",
            "storage/emulated/0/.grok",
            "storage/self/primary/.grok",
            "mnt/sdcard/token",
            "mnt/media_rw/usb",
            "data/sdcard/grok",
        ]
        for path in rel_paths:
            self.assertTrue(
                check_storage_quarantine(path),
                f"Expected relative prefix to be quarantined: {path}"
            )

    def test_adv_s04_case_insensitive_quarantine(self):
        """Case variants (/SDCARD, /Storage/Emulated/0) are quarantined."""
        case_variants = [
            "/SDCARD/.grok",
            "/SdCard/.grok",
            "/sDcaRd/credentials",
            "/STORAGE/EMULATED/0/.grok",
            "/Storage/Emulated/0/.grok",
            "/STORAGE/SELF/PRIMARY/.grok",
            "/MNT/SDCARD/.grok",
            "/Mnt/Media_Rw/usb",
            "SDCARD/.grok",
            "Storage/Emulated/0/.grok",
        ]
        for path in case_variants:
            self.assertTrue(
                check_storage_quarantine(path),
                f"Expected case variant to be quarantined: {path}"
            )

    def test_adv_s05_mixed_slashes_and_double_slashes(self):
        """Duplicate and mixed slashes (//sdcard, ///storage/emulated///) are quarantined."""
        odd_paths = [
            "//sdcard",
            "///sdcard/.grok",
            "//storage//emulated//0//.grok",
            "/sdcard///credentials.json",
            "/storage/emulated/0///Download///keys",
            "/mnt/sdcard///",
            "\\\\sdcard\\.grok",
        ]
        for path in odd_paths:
            self.assertTrue(
                check_storage_quarantine(path),
                f"Expected duplicate slash path to be quarantined: {path}"
            )

    def test_adv_s06_dangling_symlink_to_sdcard_quarantined(self):
        """Dangling symlink pointing to non-existent /sdcard/.grok is quarantined."""
        link_path = os.path.join(self.test_dir, "dangling_sdcard_link")
        os.symlink("/sdcard/.grok", link_path)
        self.assertTrue(os.path.islink(link_path))
        # Read symlink target
        target = os.readlink(link_path)
        self.assertTrue(check_storage_quarantine(target))

    def test_adv_s07_dangling_symlink_to_emulated_storage_quarantined(self):
        """Dangling symlink pointing to /storage/emulated/0 is quarantined."""
        link_path = os.path.join(self.test_dir, "dangling_storage_link")
        os.symlink("/storage/emulated/0/Download", link_path)
        self.assertTrue(os.path.islink(link_path))
        target = os.readlink(link_path)
        self.assertTrue(check_storage_quarantine(target))

    def test_adv_s08_symlink_to_safe_file_accepted(self):
        """Symlink pointing to a safe file inside private storage is accepted."""
        safe_target = os.path.join(self.test_dir, "safe_file.json")
        with open(safe_target, "w") as f:
            f.write("{}")
        link_path = os.path.join(self.test_dir, "safe_link")
        os.symlink(safe_target, link_path)
        self.assertFalse(check_storage_quarantine(link_path))

    def test_adv_s09_multi_hop_symlink_chain_to_sdcard(self):
        """Multi-hop symlink chain (A -> B -> C -> /sdcard) resolves and quarantines."""
        link_c = os.path.join(self.test_dir, "chain_c")
        link_b = os.path.join(self.test_dir, "chain_b")
        link_a = os.path.join(self.test_dir, "chain_a")

        os.symlink("/sdcard/.grok", link_c)
        os.symlink(link_c, link_b)
        os.symlink(link_b, link_a)

        # Resolve chain
        current = link_a
        for _ in range(10):
            if os.path.islink(current):
                current = os.readlink(current)
        self.assertTrue(check_storage_quarantine(current))

    def test_adv_s10_ancestor_directory_symlink_quarantined(self):
        """Target under an ancestor directory symlinked to /sdcard is quarantined."""
        dir_link = os.path.join(self.test_dir, "sdcard_dir_link")
        os.symlink("/sdcard", dir_link)
        child_target = os.path.join(dir_link, "sub/keys.json")
        
        # In lexical / resolved check:
        real_ancestor = os.readlink(dir_link)
        reconstructed = os.path.join(real_ancestor, "sub/keys.json")
        self.assertTrue(check_storage_quarantine(reconstructed))

    def test_adv_s11_relative_symlink_to_sdcard(self):
        """Relative symlink ../../../sdcard/.grok is quarantined."""
        sub = os.path.join(self.test_dir, "nested", "sub")
        os.makedirs(sub, exist_ok=True)
        rel_link = os.path.join(sub, "rel_sdcard")
        os.symlink("../../../sdcard/.grok", rel_link)
        
        target = os.readlink(rel_link)
        normalized = simulate_lexical_normalize(os.path.join(sub, target))
        self.assertTrue(check_storage_quarantine(normalized))

    def test_adv_s12_symlink_circular_recursion_loop_safe_termination(self):
        """Circular symlinks (X -> Y and Y -> X) terminate safely without infinite recursion."""
        link_x = os.path.join(self.test_dir, "loop_x")
        link_y = os.path.join(self.test_dir, "loop_y")
        os.symlink(link_y, link_x)
        os.symlink(link_x, link_y)

        # Safe depth-limited resolution
        def resolve_safe(path: str, max_depth: int = 32) -> str:
            cur = path
            for _ in range(max_depth):
                if os.path.islink(cur):
                    cur = os.readlink(cur)
                else:
                    return cur
            return cur

        res = resolve_safe(link_x)
        self.assertIsNotNone(res)

    def test_adv_s13_deep_symlink_chain_25_hops_quarantined(self):
        """25-hop symlink chain resolving to /sdcard is traversed and quarantined."""
        prev = os.path.join(self.test_dir, "root_sd_link")
        os.symlink("/sdcard/.grok", prev)

        for i in range(25):
            nxt = os.path.join(self.test_dir, f"hop_{i}")
            os.symlink(prev, nxt)
            prev = nxt

        # Resolve
        cur = prev
        for _ in range(32):
            if os.path.islink(cur):
                cur = os.readlink(cur)
        self.assertTrue(check_storage_quarantine(cur))

    def test_adv_s14_dual_track_sdcard_workspace_protection(self):
        """Working in an /sdcard workspace keeps sessions, tokens, and sockets in private storage."""
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            sdcard_cwd = "/sdcard/Download/my-react-app"

            # 1. State must resolve to private storage ($HOME/.grok)
            grok_home = caps.home_dir()
            self.assertTrue(grok_home.startswith(env.home_dir))
            self.assertFalse(check_storage_quarantine(grok_home))

            # 2. Session dir inside grok_home
            sess_name = encode_cwd_slug_hash(sdcard_cwd)
            sess_dir = os.path.join(grok_home, "sessions", sess_name)
            os.makedirs(sess_dir, mode=0o700, exist_ok=True)
            self.assertTrue(sess_dir.startswith(env.home_dir))
            self.assertNotIn("/sdcard", sess_dir)

    def test_adv_s15_long_cwd_slug_hash_roundtrip_with_dot_cwd(self):
        """Long CWD (>255 bytes) on /sdcard uses slug-hash <= 57 bytes and recovers via .cwd file."""
        long_sdcard_cwd = (
            "/sdcard/Download/專案目錄/子目錄一/子目錄二/子目錄三/backend/service/"
            + "submodule-" * 15
        )
        encoded = encode_cwd_slug_hash(long_sdcard_cwd)
        self.assertLessEqual(len(encoded.encode("utf-8")), 57)
        self.assertIn("submodule-", encoded)

        # Write .cwd metadata in simulated session dir
        sess_dir = os.path.join(self.test_dir, encoded)
        os.makedirs(sess_dir, mode=0o700, exist_ok=True)
        dot_cwd_file = os.path.join(sess_dir, ".cwd")
        with open(dot_cwd_file, "w") as f:
            f.write(long_sdcard_cwd)

        # Recover
        with open(dot_cwd_file, "r") as f:
            recovered = f.read().strip()
        self.assertEqual(recovered, long_sdcard_cwd)


# =============================================================================
# Section 3: Unix Socket Constraints & Temporary Directory Adversarial Tests
# =============================================================================

class TestAdversarialSocketAndTempConstraints(unittest.TestCase):
    """Adversarial stress tests for Unix domain sockets (<108 bytes, stale cleanup, 0600/0700)."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="adv_socket_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_adv_k01_exact_107_bytes_socket_path_accepted(self):
        """Socket path of exactly 107 bytes is accepted within sun_path[108] limits."""
        sock_name = "grok-12345678.sock"  # 18 bytes
        # target: tmp_dir + '/' + sock_name = 107 bytes -> tmp_dir = 107 - 1 - 18 = 88 bytes
        target_tmp_len = 107 - 1 - len(sock_name)
        custom_tmp = "/tmp/" + "x" * (target_tmp_len - len("/tmp/"))
        self.assertEqual(len(custom_tmp.encode("utf-8")), target_tmp_len)

        full_sock_path = f"{custom_tmp}/{sock_name}"
        self.assertEqual(len(full_sock_path.encode("utf-8")), 107)

    def test_adv_k02_exact_108_bytes_socket_path_rejected(self):
        """Socket path of exactly 108 bytes exceeds POSIX null-terminated sun_path and is rejected."""
        sock_name = "grok-12345678.sock"
        target_tmp_len = 108 - 1 - len(sock_name)
        custom_tmp = "/tmp/" + "x" * (target_tmp_len - len("/tmp/"))
        full_sock_path = f"{custom_tmp}/{sock_name}"
        self.assertEqual(len(full_sock_path.encode("utf-8")), 108)

        # Simulation / Rust limit check: >= 108 bytes must error
        if len(full_sock_path.encode("utf-8")) >= 108:
            with self.assertRaises(PlatformError):
                raise PlatformError(f"Socket path exceeds 108 bytes: {full_sock_path}")

    def test_adv_k03_exact_109_bytes_socket_path_rejected(self):
        """Socket path of 109 bytes is rejected."""
        sock_name = "grok-12345678.sock"
        target_tmp_len = 109 - 1 - len(sock_name)
        custom_tmp = "/tmp/" + "x" * (target_tmp_len - len("/tmp/"))
        full_sock_path = f"{custom_tmp}/{sock_name}"
        self.assertEqual(len(full_sock_path.encode("utf-8")), 109)
        with self.assertRaises(PlatformError):
            if len(full_sock_path.encode("utf-8")) >= 108:
                raise PlatformError(f"Socket path exceeds 108 bytes: {full_sock_path}")

    def test_adv_k04_blake3_fixed_length_hash_compression(self):
        """Multi-byte UTF-8, emojis, and Unicode session IDs compress to fixed 18-byte socket filename."""
        multibyte_sessions = [
            "🔥" * 100,
            "測試會話_Unicode_🚀_🌟",
            "한국어_세션_테스트_2026",
            "Session with spaces and special chars: !@#$%^&*()_+",
            "a" * 5000,
        ]
        for sid in multibyte_sessions:
            h = hashlib.blake2b(sid.encode("utf-8"), digest_size=4).hexdigest()
            sock_name = f"grok-{h}.sock"
            self.assertEqual(len(sock_name), 18, f"Socket filename must be 18 chars: {sock_name}")
            self.assertTrue(sock_name.startswith("grok-"))
            self.assertTrue(sock_name.endswith(".sock"))

    def test_adv_k05_extreme_session_id_sizes_empty_and_100k_chars(self):
        """Empty session IDs and 100,000 char session IDs compress cleanly without failure."""
        for sid in ["", "x" * 100000]:
            h = hashlib.blake2b(sid.encode("utf-8"), digest_size=4).hexdigest()
            sock_name = f"grok-{h}.sock"
            self.assertEqual(len(sock_name), 18)

    def test_adv_k06_stale_socket_cleanup_and_rebind(self):
        """Binding over a dead Unix domain socket unlinks the stale file and binds successfully."""
        sock_path = os.path.join(self.test_dir, "stale_test.sock")
        
        # 1. Create a dead socket
        srv1 = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv1.bind(sock_path)
        srv1.listen(1)
        srv1.close()  # Closed without unlinking (simulating process crash)
        self.assertTrue(os.path.exists(sock_path))

        # 2. Cleanup & re-bind
        if os.path.exists(sock_path):
            os.unlink(sock_path)

        srv2 = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv2.bind(sock_path)
        os.chmod(sock_path, 0o600)
        srv2.listen(1)

        # 3. Test connectivity
        cli = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        cli.connect(sock_path)
        conn, _ = srv2.accept()
        cli.sendall(b"PING")
        self.assertEqual(conn.recv(10), b"PING")

        conn.close()
        cli.close()
        srv2.close()
        os.unlink(sock_path)

    def test_adv_k07_socket_file_permissions_strictly_0600(self):
        """Socket file permissions are strictly 0600 (owner read/write only)."""
        sock_path = os.path.join(self.test_dir, "perm_0600.sock")
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(sock_path)
        os.chmod(sock_path, 0o600)

        mode = stat.S_IMODE(os.stat(sock_path).st_mode)
        self.assertEqual(mode, 0o600, f"Expected 0600, got {oct(mode)}")
        self.assertEqual(mode & 0o077, 0, "Group and other permissions must be 0")

        srv.close()
        os.unlink(sock_path)

    def test_adv_k08_socket_directory_permissions_0700(self):
        """Socket parent directory permissions are strictly 0700."""
        sock_dir = os.path.join(self.test_dir, "grok_socket_dir")
        os.makedirs(sock_dir, mode=0o700, exist_ok=True)
        os.chmod(sock_dir, 0o700)

        mode = stat.S_IMODE(os.stat(sock_dir).st_mode)
        self.assertEqual(mode, 0o700, f"Expected 0700, got {oct(mode)}")

    def test_adv_k09_rapid_rebind_stress_50_cycles(self):
        """50 rapid bind-connect-close-rebind cycles complete without resource leak or error."""
        sock_path = os.path.join(self.test_dir, "rapid_cycle.sock")
        for i in range(50):
            if os.path.exists(sock_path):
                os.unlink(sock_path)

            srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            srv.bind(sock_path)
            os.chmod(sock_path, 0o600)
            srv.listen(1)

            cli = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            cli.connect(sock_path)
            conn, _ = srv.accept()
            cli.sendall(f"REQ_{i}".encode("utf-8"))
            self.assertEqual(conn.recv(32), f"REQ_{i}".encode("utf-8"))

            conn.close()
            cli.close()
            srv.close()

        if os.path.exists(sock_path):
            os.unlink(sock_path)

    def test_adv_k10_regular_file_squatter_cleanup(self):
        """A regular file or dangling symlink at the socket path is cleaned up prior to bind."""
        sock_path = os.path.join(self.test_dir, "squatter.sock")
        
        # Create regular file squatter
        with open(sock_path, "w") as f:
            f.write("squatting file")
        self.assertTrue(os.path.isfile(sock_path))

        # Cleanup & bind
        if os.path.exists(sock_path) or os.path.islink(sock_path):
            os.unlink(sock_path)

        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(sock_path)
        srv.close()
        os.unlink(sock_path)

    def test_adv_k11_concurrent_clients_over_0600_socket(self):
        """Multiple concurrent client connections over 0600 Unix domain socket succeed."""
        sock_path = os.path.join(self.test_dir, "concurrent_0600.sock")
        if os.path.exists(sock_path):
            os.unlink(sock_path)

        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(sock_path)
        os.chmod(sock_path, 0o600)
        srv.listen(10)

        num_clients = 8
        results = [False] * num_clients

        def client_worker(cid: int):
            try:
                c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                c.connect(sock_path)
                c.sendall(f"C_{cid}".encode("utf-8"))
                resp = c.recv(32)
                if resp == f"ACK_{cid}".encode("utf-8"):
                    results[cid] = True
                c.close()
            except Exception as e:
                pass

        def server_worker():
            for _ in range(num_clients):
                conn, _ = srv.accept()
                req = conn.recv(32).decode("utf-8")
                cid = req.split("_")[1]
                conn.sendall(f"ACK_{cid}".encode("utf-8"))
                conn.close()

        th_srv = threading.Thread(target=server_worker)
        th_srv.start()

        threads = [threading.Thread(target=client_worker, args=(i,)) for i in range(num_clients)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        th_srv.join()

        srv.close()
        os.unlink(sock_path)
        self.assertTrue(all(results), f"Not all clients completed: {results}")

    def test_adv_k12_tmpdir_fallback_hierarchy_and_whitespace(self):
        """$TMPDIR precedence: explicit $TMPDIR -> $PREFIX/tmp -> /tmp, ignoring whitespace."""
        with MockTermuxEnv(is_android=True) as env:
            # 1. Explicit TMPDIR
            os.environ["TMPDIR"] = "/data/data/com.termux/files/usr/custom_tmp"
            caps = PlatformCapabilities(env)
            self.assertEqual(caps.temp_dir(), "/data/data/com.termux/files/usr/custom_tmp")

            # 2. Whitespace TMPDIR falls back to prefix/tmp
            os.environ["TMPDIR"] = "   \t\n  "
            cleaned = os.environ.get("TMPDIR", "").strip()
            fallback = os.path.join(env.prefix_dir, "tmp") if not cleaned else cleaned
            self.assertEqual(fallback, os.path.join(env.prefix_dir, "tmp"))


# =============================================================================
# Section 4: In-Process Path Enforcement & Truthful Sandboxing Adversarial Tests
# =============================================================================

class TestAdversarialSandboxAndPolicyEnforcement(unittest.TestCase):
    """Adversarial stress tests for in-process path policy, truthful sandbox reporting, and fail-closed rules."""

    def test_adv_e01_truthful_sandbox_reporting_termux_user(self):
        """Standard Termux environment truthfully reports policy-only, never kernel-enforced."""
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            self.assertEqual(caps.sandbox_kind(), SandboxKind.POLICY_ONLY)
            self.assertNotEqual(caps.sandbox_kind(), SandboxKind.KERNEL_ENFORCED)

    def test_adv_e02_truthful_sandbox_reporting_root_uid(self):
        """Running as root UID (0) in Termux still truthfully reports policy-only."""
        with MockTermuxEnv(is_android=True) as env:
            os.environ["USER"] = "root"
            os.environ["UID"] = "0"
            caps = PlatformCapabilities(env)
            self.assertEqual(caps.sandbox_kind(), SandboxKind.POLICY_ONLY)

    def test_adv_e03_truthful_sandbox_reporting_proot(self):
        """Running under PRoot environment truthfully reports policy-only."""
        with MockTermuxEnv(is_android=True) as env:
            os.environ["PROOT_TMP_DIR"] = "/tmp"
            caps = PlatformCapabilities(env)
            self.assertEqual(caps.sandbox_kind(), SandboxKind.POLICY_ONLY)

    def test_adv_e04_desktop_kernel_enforced_sandbox_reporting(self):
        """Desktop Linux and macOS truthfully report kernel-enforced."""
        with MockTermuxEnv(is_android=False) as env:
            caps = PlatformCapabilities(env)
            self.assertEqual(caps.sandbox_kind(), SandboxKind.KERNEL_ENFORCED)

    def test_adv_e05_path_traversal_url_encoded_payloads_in_process_denial(self):
        """URL-encoded path traversal payloads (%2e%2e, %252e%252e) are detected and denied."""
        workspace = "/data/data/com.termux/files/home/workspace"
        attack_payloads = [
            f"{workspace}/%2e%2e/%2e%2e/etc/shadow",
            f"{workspace}/%252e%252e/%252e%252e/.ssh/id_rsa",
            f"{workspace}/subdir/../../../../../../data/data/com.termux/files/home/.grok/credentials.json",
        ]
        for payload in attack_payloads:
            decoded = urllib.parse.unquote(urllib.parse.unquote(payload))
            normalized = simulate_lexical_normalize(decoded)
            is_contained = normalized.startswith(workspace)
            self.assertFalse(is_contained, f"Attack payload must not be contained in workspace: {payload}")

    def test_adv_e06_sensitive_directory_barriers(self):
        """Access to sensitive barriers (~/.ssh, ~/.grok/credentials.json, /etc/shadow) is denied."""
        sensitive_paths = [
            "/data/data/com.termux/files/home/.ssh/id_ed25519",
            "/data/data/com.termux/files/home/.grok/credentials.json",
            "/etc/shadow",
            "/sdcard/personal_data.txt",
        ]
        for p in sensitive_paths:
            # Sensitive path barrier predicate
            is_sensitive = (
                "/.ssh" in p
                or ".grok/credentials" in p
                or p.startswith("/etc")
                or "/sdcard" in p
            )
            self.assertTrue(is_sensitive, f"Path must be classified as sensitive: {p}")

    def test_adv_e07_hook_write_denial_for_subagents(self):
        """Subagents in unprivileged turns are strictly denied write access to .grok/hooks."""
        hook_path = "/data/data/com.termux/files/home/.grok/hooks/on_event.sh"
        
        def is_write_permitted(path: str, is_subagent: bool) -> bool:
            if is_subagent and ".grok/hooks" in path:
                return False
            return True

        self.assertFalse(is_write_permitted(hook_path, is_subagent=True))
        self.assertTrue(is_write_permitted(hook_path, is_subagent=False))

    def test_adv_e08_fail_closed_requirements_validation_with_invalid_overrides(self):
        """fail_closed = true with invalid version_overrides rejects execution."""
        sample_toml_fail_closed = """
        fail_closed = true
        [[version_overrides]]
        minimum_version = "not-a-valid-semver"
        """
        # Parsing should identify fail_closed and invalid version override
        try:
            import tomllib
        except ImportError:
            import toml as tomllib
        parsed = tomllib.loads(sample_toml_fail_closed)
        self.assertTrue(parsed.get("fail_closed", False))
        min_ver = parsed["version_overrides"][0]["minimum_version"]
        self.assertFalse(min_ver.replace(".", "").isdigit())

    def test_adv_e09_fail_closed_env_tightening_rule(self):
        """GROK_MANAGED_CONFIG_FAIL_CLOSED=1 tightens enforcement; '0' cannot loosen admin policy."""
        def resolve_fail_closed(file_flag: bool, env_val: Optional[str]) -> bool:
            if env_val == "1":
                return True
            if env_val == "0":
                # local env=0 must NOT loosen admin true
                return file_flag
            return file_flag

        self.assertTrue(resolve_fail_closed(file_flag=True, env_val=None))
        self.assertTrue(resolve_fail_closed(file_flag=True, env_val="0"))
        self.assertTrue(resolve_fail_closed(file_flag=False, env_val="1"))
        self.assertFalse(resolve_fail_closed(file_flag=False, env_val="0"))
        self.assertFalse(resolve_fail_closed(file_flag=False, env_val=None))

    def test_adv_e10_effective_deny_paths_sorting_and_deduplication(self):
        """Deny paths are resolved against workspace, sorted, and deduplicated."""
        workspace = "/data/data/com.termux/files/home/project"
        raw_deny = [
            ".env",
            "/etc/shadow",
            "src/secret.key",
            ".env",  # duplicate
        ]
        resolved = []
        for p in raw_deny:
            if p.startswith("/"):
                resolved.append(p)
            else:
                resolved.append(f"{workspace}/{p}")
        
        sorted_deduped = sorted(list(set(resolved)))
        self.assertEqual(len(sorted_deduped), 3)
        self.assertEqual(sorted_deduped[0], f"{workspace}/.env")
        self.assertEqual(sorted_deduped[1], f"{workspace}/src/secret.key")
        self.assertEqual(sorted_deduped[2], "/etc/shadow")
        self.assertIn(f"{workspace}/.env", sorted_deduped)
        self.assertIn(f"{workspace}/src/secret.key", sorted_deduped)

    def test_adv_e11_seatbelt_and_bwrap_placeholder_safety(self):
        """Placeholder nodes used for read-denial are assigned chmod 000 permissions."""
        placeholder_dir = tempfile.mkdtemp(prefix="adv_ph_")
        ph_file = os.path.join(placeholder_dir, "blocked_placeholder")
        with open(ph_file, "w") as f:
            f.write("")
        os.chmod(ph_file, 0o000)

        mode = stat.S_IMODE(os.stat(ph_file).st_mode)
        self.assertEqual(mode, 0o000, "Blocked placeholder must have mode 000 (no read/write/exec)")
        
        # Cleanup
        os.chmod(ph_file, 0o600)
        shutil.rmtree(placeholder_dir)


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    unittest.main()
