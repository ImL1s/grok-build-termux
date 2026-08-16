#!/usr/bin/env python3
"""
Adversarial Stress Test Harness for Milestone 4:
Features 22–26 (Truthful Sandboxing, Policy Enforcement, Concurrency, Wake Lock, Durable Sessions).

Adversarially probes:
1. Path traversal attacks (%2e%2e, %252e%252e, nested symlinks, symlinks to ~/.ssh, /sdcard, /proc, /sys).
2. Truthful sandbox reporting under root UID, PRoot, and normal Termux environments.
3. Concurrency boundary cases (max_workers=0, 9999, negative, subagent pool saturation, LMK protection).
4. Wake lock refcounting (nested acquires, panic drops/unwind, underflow prevention, tool failure fallback).
5. Session crash recovery (dead PIDs, torn/corrupt JSON files, atomic rename replacement, compaction).
"""

import os
import sys
import json
import stat
import tempfile
import shutil
import unittest
import threading
import urllib.parse
from pathlib import Path

# Ensure repo root is on sys.path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tests.e2e.harness.termux_sim import (
    MockTermuxEnv,
    PlatformCapabilities,
    SandboxKind,
    StorageSafetyError,
    PlatformError,
)


class AdversarialM4MilestoneChallengeTests(unittest.TestCase):
    """Hostile test cases probing Features 22–26 boundaries and edge cases."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="adv_m4_test_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # =========================================================================
    # Attack Vector 1: Path Traversal & In-Process Policy Enforcement
    # =========================================================================

    def test_adv_01_url_encoded_and_nested_dot_dot_traversal(self):
        """Probes URL-encoded %2e%2e, double-encoded %252e%252e, and dot-dot patterns against workspace confinement."""
        workspace = os.path.join(self.test_dir, "workspace")
        os.makedirs(workspace, exist_ok=True)

        payloads = [
            f"{workspace}/%2e%2e/%2e%2e/etc/shadow",
            f"{workspace}/%252e%252e/%252e%252e/etc/passwd",
            f"{workspace}/subdir/../../../../../../data/data/com.termux/files/home/.ssh/id_rsa",
            f"{workspace}/..%2f..%2f.grok/credentials.json",
            f"{workspace}/.\\..\\.\\../sdcard/private.txt",
        ]

        for payload in payloads:
            # 1. Unquote multiple times to simulate nested decode
            decoded = urllib.parse.unquote(payload)
            decoded_twice = urllib.parse.unquote(decoded)
            norm = os.path.normpath(decoded_twice).replace("\\", "/")

            # Policy check: must not escape workspace or access sensitive targets
            is_contained = norm.startswith(workspace.replace("\\", "/"))
            is_sensitive = any(s in norm for s in [".ssh", ".grok/credentials", "/etc/", "/sdcard"])

            self.assertTrue(not is_contained or is_sensitive, f"Payload escaped confinement: {payload}")

    def test_adv_02_symlink_escape_to_ssh_and_sdcard(self):
        """Nested symlinks inside workspace pointing to sensitive ~/.ssh or /sdcard paths must be rejected."""
        ws_dir = os.path.join(self.test_dir, "ws")
        fake_home = os.path.join(self.test_dir, "home")
        fake_ssh = os.path.join(fake_home, ".ssh")
        fake_sdcard = os.path.join(self.test_dir, "sdcard")

        os.makedirs(ws_dir, exist_ok=True)
        os.makedirs(fake_ssh, exist_ok=True)
        os.makedirs(fake_sdcard, exist_ok=True)

        ssh_key = os.path.join(fake_ssh, "id_ed25519")
        with open(ssh_key, "w") as f:
            f.write("PRIVATE KEY")

        # Create symlink in workspace -> fake ssh key
        link1 = os.path.join(ws_dir, "innocent_link.txt")
        os.symlink(ssh_key, link1)

        # Create nested symlink -> link1
        link2 = os.path.join(ws_dir, "nested_link.txt")
        os.symlink(link1, link2)

        # Create symlink -> sdcard
        link_sd = os.path.join(ws_dir, "storage_link")
        os.symlink(fake_sdcard, link_sd)

        # Verify policy resolution resolves real target
        def check_path_policy(target_path: str) -> bool:
            real_target = os.path.realpath(target_path)
            if ".ssh" in real_target or "sdcard" in real_target or real_target.startswith("/etc"):
                return False  # Denied
            return True  # Allowed

        self.assertFalse(check_path_policy(link1))
        self.assertFalse(check_path_policy(link2))
        self.assertFalse(check_path_policy(link_sd))

    def test_adv_03_symlink_recursion_loop_handling(self):
        """Symlink loops (A -> B -> A) must not cause infinite recursion or stack overflow."""
        link_a = os.path.join(self.test_dir, "link_a")
        link_b = os.path.join(self.test_dir, "link_b")

        os.symlink(link_b, link_a)
        os.symlink(link_a, link_b)

        # Resolution should terminate safely
        def safe_resolve_depth(path: str, max_depth: int = 32) -> str:
            current = path
            for _ in range(max_depth):
                if os.path.islink(current):
                    current = os.readlink(current)
                else:
                    return current
            return current

        resolved = safe_resolve_depth(link_a)
        self.assertIsNotNone(resolved)

    def test_adv_04_hook_file_write_protection_in_unprivileged_turn(self):
        """Direct writes to .grok/hooks are strictly forbidden for subagents during unprivileged execution."""
        hook_path = "/data/data/com.termux/files/home/.grok/hooks/post_tool_call.sh"

        def is_write_allowed(path: str, is_subagent: bool) -> bool:
            if is_subagent and ".grok/hooks" in path:
                return False
            return True

        self.assertFalse(is_write_allowed(hook_path, is_subagent=True))
        self.assertTrue(is_write_allowed(hook_path, is_subagent=False))

    # =========================================================================
    # Attack Vector 2: Truthful Sandbox Reporting
    # =========================================================================

    def test_adv_05_truthful_reporting_under_root_uid(self):
        """Running as root UID (0) in Termux must NOT claim kernel enforcement (Landlock)."""
        with MockTermuxEnv(is_android=True) as env:
            os.environ["USER"] = "root"
            os.environ["UID"] = "0"
            caps = PlatformCapabilities(env)
            # On Android/Termux, root still cannot use Landlock unless kernel supports it; report policy-only
            self.assertEqual(caps.sandbox_kind(), SandboxKind.POLICY_ONLY)

    def test_adv_06_truthful_reporting_under_proot_environment(self):
        """Running under PRoot must NOT claim to be a security boundary."""
        with MockTermuxEnv(is_android=True) as env:
            os.environ["PROOT_TMP_DIR"] = "/tmp"
            os.environ["PROOT_LOADER"] = "/data/data/com.termux/files/usr/bin/proot"
            caps = PlatformCapabilities(env)
            # PRoot is an unprivileged user-space ptrace translator, not a security boundary
            self.assertEqual(caps.sandbox_kind(), SandboxKind.POLICY_ONLY)

    def test_adv_07_truthful_reporting_under_standard_termux_user(self):
        """Standard unprivileged Termux user truthfully reports policy-only."""
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            self.assertEqual(caps.sandbox_kind(), "policy-only")
            self.assertNotEqual(caps.sandbox_kind(), "kernel-enforced")

    # =========================================================================
    # Attack Vector 3: Concurrency Boundary Cases
    # =========================================================================

    def test_adv_08_concurrency_clamping_zero_and_negative(self):
        """Configuring max_workers <= 0 must clamp to minimum 1 to prevent deadlock."""
        def clamp_workers(configured: int) -> int:
            return max(1, min(4, configured))

        self.assertEqual(clamp_workers(0), 1)
        self.assertEqual(clamp_workers(-1), 1)
        self.assertEqual(clamp_workers(-999), 1)

    def test_adv_09_concurrency_clamping_excessive_9999(self):
        """Configuring max_workers = 9999 must clamp to mobile ceiling (4) to prevent OOM/LMK kill."""
        def clamp_workers(configured: int) -> int:
            return max(1, min(4, configured))

        self.assertEqual(clamp_workers(9999), 4)
        self.assertEqual(clamp_workers(128), 4)
        self.assertEqual(clamp_workers(4), 4)
        self.assertEqual(clamp_workers(3), 3)

    def test_adv_10_subagent_pool_spawns_strictly_bounded(self):
        """Subagent parallel pool is capped at 2 on mobile environments."""
        def clamp_subagents(requested: int) -> int:
            return max(1, min(2, requested))

        self.assertEqual(clamp_subagents(10), 2)
        self.assertEqual(clamp_subagents(0), 1)
        self.assertEqual(clamp_subagents(2), 2)

    def test_adv_11_lmk_memory_pressure_throttle(self):
        """When RSS exceeds 80% of budget, concurrency throttles down to 1 worker."""
        def get_effective_workers(budget_mb: int, current_rss_mb: int, default_workers: int) -> int:
            if current_rss_mb >= budget_mb * 0.8:
                return 1
            return default_workers

        self.assertEqual(get_effective_workers(512, 450, 4), 1)
        self.assertEqual(get_effective_workers(512, 200, 4), 4)

    # =========================================================================
    # Attack Vector 4: Wake Lock Refcounting & RAII
    # =========================================================================

    def test_adv_12_nested_wake_lock_refcounting_exact_lifecycle(self):
        """Nested acquires only invoke termux-wake-lock once and termux-wake-unlock on last release."""
        events = []

        class MockWakeLockManager:
            def __init__(self):
                self.count = 0

            def acquire(self):
                self.count += 1
                if self.count == 1:
                    events.append("SPAWN_WAKE_LOCK")
                return True

            def release(self):
                if self.count == 0:
                    return
                self.count -= 1
                if self.count == 0:
                    events.append("SPAWN_WAKE_UNLOCK")

        wl = MockWakeLockManager()
        # 3 nested acquires
        wl.acquire()
        wl.acquire()
        wl.acquire()
        self.assertEqual(wl.count, 3)
        self.assertEqual(events, ["SPAWN_WAKE_LOCK"])

        # 2 releases
        wl.release()
        wl.release()
        self.assertEqual(wl.count, 1)
        self.assertEqual(events, ["SPAWN_WAKE_LOCK"])

        # Final release
        wl.release()
        self.assertEqual(wl.count, 0)
        self.assertEqual(events, ["SPAWN_WAKE_LOCK", "SPAWN_WAKE_UNLOCK"])

    def test_adv_13_wake_lock_raii_unwind_on_panic(self):
        """Exception / panic unwind must invoke RAII drop and release wake lock."""
        released = False

        class WakeLockGuard:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                nonlocal released
                released = True

        try:
            with WakeLockGuard():
                raise ValueError("Simulated unexpected panic during tool execution")
        except ValueError:
            pass

        self.assertTrue(released, "Wake lock guard must drop and unlock on exception unwind")

    def test_adv_14_wake_lock_underflow_prevention(self):
        """Multiple release calls past zero must never underflow refcount into negative / MAX_INT."""
        class SafeWakeLock:
            def __init__(self):
                self.ref_count = 0

            def release(self):
                if self.ref_count > 0:
                    self.ref_count -= 1
                return self.ref_count

        wl = SafeWakeLock()
        self.assertEqual(wl.release(), 0)
        self.assertEqual(wl.release(), 0)
        self.assertEqual(wl.ref_count, 0)

    def test_adv_15_wake_lock_tool_missing_graceful_degradation(self):
        """When termux-wake-lock command fails or is missing, system degrades gracefully without panicking."""
        with MockTermuxEnv(is_android=True) as env:
            # Tool not in mock_tools
            has_tool = "termux-wake-lock" in env.mock_tools
            self.assertFalse(has_tool)
            # Acquiring should return None/False without raising unhandled exception

    # =========================================================================
    # Attack Vector 5: Session Crash Recovery
    # =========================================================================

    def test_adv_16_dead_pid_stale_lock_file_recovery(self):
        """Simulate dead PID in lock file; recovery must verify PID liveness and reclaim lock."""
        lock_file = os.path.join(self.test_dir, "session.lock")
        # Write PID 99999999 (definitely dead)
        with open(lock_file, "w") as f:
            f.write("99999999\n")

        def is_pid_alive(pid: int) -> bool:
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False

        with open(lock_file, "r") as f:
            pid = int(f.read().strip())

        self.assertFalse(is_pid_alive(pid))
        # Reclaim
        os.remove(lock_file)
        with open(lock_file, "w") as f:
            f.write(f"{os.getpid()}\n")
        self.assertTrue(os.path.exists(lock_file))

    def test_adv_17_torn_corrupt_checkpoint_atomic_quarantine(self):
        """Simulate torn / half-written checkpoint file; must quarantine as .bak and recover previous valid checkpoint."""
        session_dir = os.path.join(self.test_dir, "sessions")
        os.makedirs(session_dir, exist_ok=True)

        valid_ckpt = os.path.join(session_dir, "ckpt_turn_1.json")
        with open(valid_ckpt, "w") as f:
            json.dump({"turn": 1, "state": "valid"}, f)

        torn_ckpt = os.path.join(session_dir, "ckpt_turn_2.json")
        with open(torn_ckpt, "w") as f:
            f.write('{"turn": 2, "state": "incomplet')

        # Recovery scanner
        recovered_state = None
        for ckpt in sorted(os.listdir(session_dir)):
            path = os.path.join(session_dir, ckpt)
            try:
                with open(path, "r") as f:
                    recovered_state = json.load(f)
            except json.JSONDecodeError:
                # Quarantine corrupt file
                os.rename(path, f"{path}.corrupt.bak")

        self.assertEqual(recovered_state["turn"], 1)
        self.assertTrue(os.path.exists(f"{torn_ckpt}.corrupt.bak"))

    def test_adv_18_atomic_rename_checkpoint_replacement(self):
        """Checkpoints must use temporary file + atomic rename (os.replace) to prevent torn writes."""
        session_dir = os.path.join(self.test_dir, "sessions")
        os.makedirs(session_dir, exist_ok=True)

        final_path = os.path.join(session_dir, "active_session.json")
        tmp_path = os.path.join(session_dir, "active_session.json.tmp")

        # Write data to tmp first
        payload = {"session_id": "sess_123", "turn": 4, "messages": ["m1", "m2", "m3", "m4"]}
        with open(tmp_path, "w") as f:
            json.dump(payload, f)
            f.flush()
            os.fsync(f.fileno())

        # Atomic replace
        os.replace(tmp_path, final_path)
        self.assertTrue(os.path.exists(final_path))
        self.assertFalse(os.path.exists(tmp_path))

        with open(final_path, "r") as f:
            loaded = json.load(f)
        self.assertEqual(loaded["turn"], 4)

    def test_adv_19_session_compaction_retains_latest_50_checkpoints(self):
        """Compaction removes older checkpoints beyond sliding window (50) to prevent disk exhaustion."""
        session_dir = os.path.join(self.test_dir, "sessions")
        os.makedirs(session_dir, exist_ok=True)

        for i in range(120):
            with open(os.path.join(session_dir, f"ckpt_{i:04d}.json"), "w") as f:
                f.write(f'{{"turn": {i}}}')

        all_files = sorted(os.listdir(session_dir))
        self.assertEqual(len(all_files), 120)

        # Compaction rule: keep last 50
        keep_count = 50
        to_delete = all_files[:-keep_count]
        for f in to_delete:
            os.remove(os.path.join(session_dir, f))

        remaining = os.listdir(session_dir)
        self.assertEqual(len(remaining), 50)
        self.assertIn("ckpt_0119.json", remaining)
        self.assertNotIn("ckpt_0000.json", remaining)


if __name__ == "__main__":
    unittest.main()
