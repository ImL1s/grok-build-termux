"""
Tier 4 Real-World Scenario 4: Clipboard Read/Write with Termux:API and OSC 52 Fallback.

Exercised Features:
- F4: Desktop Clipboard Gating (arboard)
- F19: Termux:API Text Clipboard
- F20: OSC 52 Terminal Clipboard Fallback
- F21: Unsupported Clipboard / Voice Graceful Degradation
"""

import unittest
import base64
from tests.e2e.harness.termux_sim import (
    MockTermuxEnv,
    ClipboardSeam,
)


class TestScenarioClipboard(unittest.TestCase):

    def test_scenario_clipboard_with_termux_api_available(self):
        """Simulates text clipboard copying and pasting when Termux:API is installed."""
        with MockTermuxEnv(is_android=True) as env:
            env.install_mock_tool("termux-clipboard-get", stdout="Hello from Android Clipboard")
            env.install_mock_tool("termux-clipboard-set", exit_code=0)

            clipboard = ClipboardSeam(env, allow_termux_api=True)

            # Write text
            ok, method = clipboard.set_text("Grok generated code snippet")
            self.assertTrue(ok)
            self.assertEqual(method, "termux_api")

            # Read text
            val = clipboard.get_text()
            self.assertEqual(val, "android_termux_api_clipboard_text")

            # Image copy returns None cleanly
            img = clipboard.get_image()
            self.assertIsNone(img)

    def test_scenario_clipboard_fallback_to_osc52_when_termux_api_absent(self):
        """Simulates text clipboard copying in standard Termux without Termux:API installed."""
        with MockTermuxEnv(is_android=True) as env:
            # Termux:API not installed
            clipboard = ClipboardSeam(env, allow_termux_api=False)

            # Copy text triggers OSC 52 sequence
            text_to_copy = "cargo build --target aarch64-linux-android"
            ok, method = clipboard.set_text(text_to_copy)
            self.assertTrue(ok)
            self.assertEqual(method, "osc52")
            self.assertEqual(len(clipboard.osc52_output), 1)

            # Validate OSC 52 ANSI escape sequence format
            seq = clipboard.osc52_output[0]
            self.assertTrue(seq.startswith("\x1b]52;c;"))
            self.assertTrue(seq.endswith("\x07"))
            b64_str = seq[len("\x1b]52;c;") : -1]
            decoded = base64.b64decode(b64_str).decode("utf-8")
            self.assertEqual(decoded, text_to_copy)

            # Read returns None (OSC 52 cannot read clipboard for security reasons)
            read_val = clipboard.get_text()
            self.assertIsNone(read_val)


if __name__ == "__main__":
    unittest.main()
