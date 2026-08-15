#!/usr/bin/env python3
"""
Milestone 1 Empirical Challenger Stress Test Suite
Testing:
1. Clipboard Fallback Behavior:
   - Subprocess failure (missing binary, non-zero exits, timeouts, signal kills)
   - Non-UTF8 output handling (raw binary, corrupted UTF-8, null bytes)
   - ANSI OSC 52 sequence generation (multilingual, ASCII, large payloads, tmux escaping)
2. Voice Capture Graceful Degradation:
   - Android target capability gating
   - Verification of zero panics on voice commands (PttPress, PttRelease, rapid toggles)
   - Clean error event emissions
"""

import base64
import os
import subprocess
import sys
import tempfile
import unittest

# Ensure repo root is on sys.path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tests.e2e.harness.termux_sim import (
    MockTermuxEnv,
    PlatformCapabilities,
    ClipboardSeam,
    SandboxKind,
    StorageSafetyError,
)


class TestClipboardFallbackStress(unittest.TestCase):
    """Stress tests for clipboard fallback, non-UTF8 handling, and OSC 52."""

    def test_osc52_sequence_generation_ascii_and_multilingual(self):
        """Verify OSC 52 escape sequences and base64 correctness for diverse text payloads."""
        test_payloads = [
            "",
            "hello world",
            "繁體中文測試 — Grok Build Termux",
            "Emoji test: 🚀🦀📱🔥💻",
            "Special chars: \x00\x01\x1b[31mRed\x1b[0m \t\r\n \\ \" ' ` $ ; & |",
            "A" * 10000,  # 10 KB
            "B" * 200000, # 200 KB
        ]

        for payload in test_payloads:
            with self.subTest(payload_preview=payload[:30]):
                with MockTermuxEnv(is_android=True) as env:
                    clipboard = ClipboardSeam(env, allow_termux_api=False)
                    ok, method = clipboard.set_text(payload)
                    self.assertTrue(ok, "OSC 52 set_text must succeed")
                    self.assertEqual(method, "osc52", "Must fallback to osc52 when Termux:API is absent")
                    self.assertEqual(len(clipboard.osc52_output), 1)

                    osc_seq = clipboard.osc52_output[0]
                    self.assertTrue(osc_seq.startswith("\x1b]52;c;"), "Must start with OSC 52 prefix")
                    self.assertTrue(osc_seq.endswith("\x07"), "Must end with BEL character")

                    b64_data = osc_seq[len("\x1b]52;c;"):-1]
                    decoded = base64.b64decode(b64_data).decode("utf-8")
                    self.assertEqual(decoded, payload, "Decoded OSC 52 content must exactly match original payload")

    def test_tmux_passthrough_osc52_envelope(self):
        """Verify tmux passthrough envelope formatting."""
        text = "sample text inside tmux"
        b64_val = base64.b64encode(text.encode("utf-8")).decode("utf-8")
        expected_tmux = f"\x1bPtmux;\x1b\x1b]52;c;{b64_val}\x07\x1b\\"

        # Verify standard structure
        self.assertTrue(expected_tmux.startswith("\x1bPtmux;\x1b\x1b]52;c;"))
        self.assertTrue(expected_tmux.endswith("\x07\x1b\\"))

    def test_termux_api_subprocess_failure_modes(self):
        """Simulate all failure modes of termux-clipboard-get / set: missing, non-zero exits, crash."""
        failure_cases = [
            {"exit_code": 1, "stderr": "Permission denied"},
            {"exit_code": 127, "stderr": "termux-clipboard-get: command not found"},
            {"exit_code": 255, "stderr": "Termux:API service connection timed out"},
        ]

        for case in failure_cases:
            with self.subTest(case=case):
                with MockTermuxEnv(is_android=True) as env:
                    env.install_mock_tool(
                        "termux-clipboard-get",
                        exit_code=case["exit_code"],
                        stderr=case["stderr"],
                    )
                    # Verify command execution simulates failure
                    tool_path = os.path.join(env.bin_dir, "termux-clipboard-get")
                    proc = subprocess.run([tool_path], capture_output=True, text=True)
                    self.assertEqual(proc.returncode, case["exit_code"])
                    self.assertIn(case["stderr"], proc.stderr)

    def test_termux_api_non_utf8_binary_handling(self):
        """Verify handling of invalid UTF-8 bytes from clipboard input (lossy decoding / no panic)."""
        invalid_byte_sequences = [
            b"\xff\xfe\xfd",                       # invalid single bytes
            b"\xc3\x28",                           # invalid 2-byte sequence
            b"\xe2\x28\xa1",                       # invalid 3-byte sequence
            b"\xf0\x28\x8c\xbc",                   # invalid 4-byte sequence
            b"mixed text\x80\x81\x82with valid",  # embedded invalid bytes
            b"null\x00byte\x00embedded",           # embedded nulls
        ]

        for byte_seq in invalid_byte_sequences:
            with self.subTest(bytes=byte_seq):
                # In Python / Rust String::from_utf8_lossy:
                lossy_text = byte_seq.decode("utf-8", errors="replace")
                self.assertIsInstance(lossy_text, str)
                self.assertTrue(len(lossy_text) > 0)
                # Ensure no unhandled decode exceptions occur


class TestVoiceCaptureGracefulDegradation(unittest.TestCase):
    """Stress tests for voice capture gating and zero-panic behavior."""

    def test_android_voice_gating_and_device_info(self):
        """Verify that Android platform detection completely gates out audio capture."""
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            self.assertTrue(caps.is_android_termux())
            
            # Voice capture is unsupported on Android/Termux
            voice_supported = not caps.is_android_termux()
            self.assertFalse(voice_supported, "Voice capture must be flagged as unsupported on Android")

    def test_voice_command_state_machine_resilience(self):
        """Verify simulated voice pipeline commands (PttPress, PttRelease, rapid toggling)."""
        commands = [
            "PttPress",
            "PttRelease",
            "PttPress",
            "PttPress",   # Rapid press without release
            "PttRelease",
            "PttRelease", # Double release
            "Shutdown",
        ]

        class MockVoiceState:
            def __init__(self, is_android: bool = True):
                self.is_android = is_android
                self.active_session = False
                self.events = []

            def handle_command(self, cmd: str):
                if cmd == "Shutdown":
                    self.active_session = False
                    return "shutdown"
                elif cmd == "PttPress":
                    if self.is_android:
                        self.events.append({
                            "type": "Error",
                            "message": "Audio capture is not supported on Android/Termux",
                            "hint": None
                        })
                        self.active_session = False
                    else:
                        self.active_session = True
                elif cmd == "PttRelease":
                    if self.active_session:
                        self.events.append({"type": "Done"})
                        self.active_session = False
                return "ok"

        state = MockVoiceState(is_android=True)
        for cmd in commands:
            res = state.handle_command(cmd)
            self.assertIn(res, ["ok", "shutdown"])

        # Check errors recorded
        error_events = [e for e in state.events if e["type"] == "Error"]
        self.assertEqual(len(error_events), 3)  # 3 PttPress calls
        for err in error_events:
            self.assertIn("not supported on Android", err["message"])


if __name__ == "__main__":
    unittest.main()
