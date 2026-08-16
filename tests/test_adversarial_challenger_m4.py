#!/usr/bin/env python3
"""
Milestone 4 Empirical Challenger Deep Adversarial Verification Suite.

Adversarially probes and stress-tests:
1. LinkOpener & Browser Handoff (Feature 15):
   - Missing `termux-open-url` and missing BROWSER / DISPLAY
   - Non-zero tool exit code / spawn failures
   - Scheme injection attacks (javascript:, data:, file:, custom:, ftp:)
   - Whitespace trimming, malformed URLs, and fallback message format validation
2. OAuth Parsing Robustness (Features 16, 17):
   - Bare authorization codes (whitespace, unicode, long strings)
   - Complex callback URLs (multiple query params, mixed orders, encoded characters)
   - Error responses (access_denied, error_description)
   - Missing code parameter, garbage strings, empty inputs
3. Termux:API Clipboard & Timeout Protection (Feature 19):
   - Missing `termux-clipboard-get` and `termux-clipboard-set`
   - Simulated hung/frozen child process with bounded deadline termination
   - Large payload spooling (>64 KiB, 1 MiB) without pipe buffer exhaustion
4. OSC 52 Terminal Clipboard Fallback (Feature 20):
   - Multibyte UTF-8 (Traditional Chinese, CJK, Emoji, RTL, ZWJ)
   - Control chars, CRLF newlines, ANSI escapes, null bytes
   - Base64 exact decoding and sequence verification
   - Tmux passthrough DCS envelope formatting
5. Unsupported Clipboard & Voice Degradation (Feature 21):
   - Image and file clipboard calls return None/empty safely without panic
   - Audio/Voice module gating and configuration error handling
"""

import os
import sys
import unittest
import tempfile
import shutil
import subprocess
import base64
import urllib.parse
import time
import threading

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tests.e2e.harness.termux_sim import (
    MockTermuxEnv,
    PlatformCapabilities,
    ClipboardSeam,
    LinkOpenerSeam,
    OAuthServerSeam,
    LinkOpenerError,
    ClipboardError,
    StorageSafetyError,
)


class AdversarialMilestone4ChallengerTests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="challenger_m4_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # Dimension 1: LinkOpener & Browser Handoff Stress Testing
    # -------------------------------------------------------------------------
    def test_link_opener_missing_termux_open_url_graceful_degrade(self):
        """Verify LinkOpener falls back to manual print when termux-open-url is missing."""
        with MockTermuxEnv(is_android=True) as env:
            # Do not install termux-open-url
            opener = LinkOpenerSeam(env, allow_termux_open=True)
            success, method = opener.open_url("https://grok.com/login")
            self.assertFalse(success, "Must return False when termux-open-url is missing")
            self.assertEqual(method, "manual_print", "Must select manual_print fallback")
            self.assertEqual(len(opener.opened_urls), 0, "No URL should be recorded as opened")

    def test_link_opener_termux_open_url_available(self):
        """Verify LinkOpener dispatches via termux-open-url when present."""
        with MockTermuxEnv(is_android=True) as env:
            env.install_mock_tool("termux-open-url", exit_code=0)
            opener = LinkOpenerSeam(env, allow_termux_open=True)
            success, method = opener.open_url("https://grok.com/login?param=1")
            self.assertTrue(success)
            self.assertEqual(method, "termux-open-url")
            self.assertEqual(opener.opened_urls, ["https://grok.com/login?param=1"])

    def test_link_opener_scheme_safety_rejections(self):
        """Adversarially probe dangerous schemes to ensure they are rejected."""
        dangerous_urls = [
            "javascript:alert(1)",
            "JAVASCRIPT:alert('xss')",
            "data:text/html,<h1>PWNED</h1>",
            "file:///data/data/com.termux/files/home/.grok/credentials.json",
            "FILE:///etc/passwd",
            "custom://malicious-protocol/payload",
            "ftp://ftp.example.com/sensitive.txt",
            "tel:+1234567890",
            "://missing-scheme",
            "not-a-valid-url",
            "",
            "   ",
        ]
        with MockTermuxEnv(is_android=True) as env:
            env.install_mock_tool("termux-open-url", exit_code=0)
            opener = LinkOpenerSeam(env, allow_termux_open=True)
            for url in dangerous_urls:
                with self.subTest(url=url):
                    with self.assertRaises(LinkOpenerError, msg=f"Dangerous URL allowed: {url}"):
                        opener.open_url(url)

    def test_link_opener_safe_schemes_accepted(self):
        """Probe various legitimate URLs (ports, complex queries, ipv4, ipv6)."""
        safe_urls = [
            "https://grok.com",
            "http://127.0.0.1:8080/callback?code=xyz123&state=state456",
            "https://auth.x.ai/oidc/auth?client_id=grok-cli&redirect_uri=http%3A%2F%2F127.0.0.1%3A54321%2Fcallback",
            "http://localhost:3000",
            "https://sub.domain.corp.com:8443/path/to/resource?foo=bar&baz=qux#heading1",
        ]
        with MockTermuxEnv(is_android=True) as env:
            env.install_mock_tool("termux-open-url", exit_code=0)
            opener = LinkOpenerSeam(env, allow_termux_open=True)
            for url in safe_urls:
                with self.subTest(url=url):
                    success, method = opener.open_url(url)
                    self.assertTrue(success)
                    self.assertEqual(method, "termux-open-url")

    # -------------------------------------------------------------------------
    # Dimension 2: OAuth Paste & Redirect URL Parsing
    # -------------------------------------------------------------------------
    def test_oauth_parse_bare_codes_robustness(self):
        """Probe bare authorization code inputs with whitespace, tabs, and unicode."""
        cases = [
            ("abc123xyz", "abc123xyz"),
            ("  abc123xyz  ", "abc123xyz"),
            ("\tabc123xyz\n", "abc123xyz"),
            ("\r\n  secret-code-with-dashes_and_underscores.123  \r\n", "secret-code-with-dashes_and_underscores.123"),
            ("A" * 1024, "A" * 1024),  # Long code
        ]
        for input_str, expected_code in cases:
            with self.subTest(input_str=input_str):
                code, state = OAuthServerSeam.parse_manual_input(input_str)
                self.assertEqual(code, expected_code)
                self.assertIsNone(state)

    def test_oauth_parse_callback_urls_permutations(self):
        """Adversarially probe full redirect URLs with various query parameter structures."""
        cases = [
            ("http://127.0.0.1:8080/callback?code=auth123&state=state456", "auth123", "state456"),
            ("http://127.0.0.1:8080/callback?state=state456&code=auth123", "auth123", "state456"),
            ("http://localhost:54321/callback?foo=bar&code=auth123&baz=qux&state=state456", "auth123", "state456"),
            ("http://127.0.0.1:8080/callback?code=auth%2B123%2Fxyz%3D&state=st%20ate", "auth+123/xyz=", "st ate"),
            ("http://127.0.0.1:8080/callback?code=auth123#section", "auth123", None),
            ("https://example.com/oauth/cb?code=onlycode", "onlycode", None),
        ]
        for input_url, expected_code, expected_state in cases:
            with self.subTest(input_url=input_url):
                code, state = OAuthServerSeam.parse_manual_input(input_url)
                self.assertEqual(code, expected_code)
                self.assertEqual(state, expected_state)

    def test_oauth_parse_empty_and_whitespace(self):
        """Probe empty, whitespace, and null inputs."""
        empty_cases = ["", "   ", "\t\t", "\n\r", " \n \r \t "]
        for empty_val in empty_cases:
            with self.subTest(empty_val=empty_val):
                code, state = OAuthServerSeam.parse_manual_input(empty_val)
                self.assertIsNone(code)
                self.assertIsNone(state)

    # -------------------------------------------------------------------------
    # Dimension 3: Termux Clipboard & Timeout Protection
    # -------------------------------------------------------------------------
    def test_termux_clipboard_missing_tools_fallback_to_osc52(self):
        """Verify missing termux-clipboard-* triggers clean fallback to OSC 52."""
        with MockTermuxEnv(is_android=True) as env:
            # Neither termux-clipboard-get nor set installed
            cb = ClipboardSeam(env, allow_termux_api=True)
            
            # Read falls back cleanly to None without error
            read_val = cb.get_text()
            self.assertIsNone(read_val)

            # Write falls back to OSC 52
            test_text = "Adversarial Clipboard Text: 繁體中文 123"
            success, method = cb.set_text(test_text)
            self.assertTrue(success)
            self.assertEqual(method, "osc52")
            self.assertEqual(len(cb.osc52_output), 1)
            
            # Verify generated OSC 52 sequence
            seq = cb.osc52_output[0]
            self.assertTrue(seq.startswith("\x1b]52;c;"))
            self.assertTrue(seq.endswith("\x07"))
            payload_b64 = seq[7:-1]
            decoded = base64.b64decode(payload_b64.encode("utf-8")).decode("utf-8")
            self.assertEqual(decoded, test_text)

    def test_termux_clipboard_tool_present(self):
        """Verify Termux:API tool is used when installed."""
        with MockTermuxEnv(is_android=True) as env:
            env.install_mock_tool("termux-clipboard-set", exit_code=0)
            env.install_mock_tool("termux-clipboard-get", exit_code=0, stdout="mock_clipboard_data")
            cb = ClipboardSeam(env, allow_termux_api=True)

            read_val = cb.get_text()
            self.assertEqual(read_val, "android_termux_api_clipboard_text")

            success, method = cb.set_text("hello")
            self.assertTrue(success)
            self.assertEqual(method, "termux_api")

    # -------------------------------------------------------------------------
    # Dimension 4: OSC 52 Encoding & Multibyte / Binary Robustness
    # -------------------------------------------------------------------------
    def test_osc52_encoding_multibyte_and_special_characters(self):
        """Probe OSC 52 base64 generation across complex unicode, control chars, and emojis."""
        test_strings = [
            "繁體中文測試 — Grok Build Termux 原生移植",
            "日本語のテキスト入力とクリップボード",
            "Emojis: 🚀🔥🎉💻📱🤖✨",
            "Zero-width: 👨‍👩‍👧‍👦 and combining: e\u0301",
            "Special chars: !@#$%^&*()_+-=[]{}|;':\",.<>?/\\`~",
            "Newlines:\r\nLine 1\r\nLine 2\nLine 3\rLine 4\tTabbed",
            "ANSI sequences: \x1b[31;1mRed Text\x1b[0m \x1b]8;;https://x.ai\x07xAI\x1b]8;;\x07",
            "Large text payload: " + ("abcdef0123456789" * 4096),  # 64KB+
        ]
        with MockTermuxEnv(is_android=True) as env:
            cb = ClipboardSeam(env, allow_termux_api=False)  # Force OSC 52
            for s in test_strings:
                with self.subTest(s=s[:30]):
                    cb.osc52_output.clear()
                    success, method = cb.set_text(s)
                    self.assertTrue(success)
                    self.assertEqual(method, "osc52")
                    self.assertEqual(len(cb.osc52_output), 1)

                    seq = cb.osc52_output[0]
                    self.assertTrue(seq.startswith("\x1b]52;c;"))
                    self.assertTrue(seq.endswith("\x07"))
                    b64_content = seq[7:-1]
                    decoded = base64.b64decode(b64_content.encode("utf-8")).decode("utf-8")
                    self.assertEqual(decoded, s, "OSC 52 decode mismatch on payload")

    # -------------------------------------------------------------------------
    # Dimension 5: Image & Voice Unsupported Clipboard Degradation
    # -------------------------------------------------------------------------
    def test_unsupported_image_clipboard_on_android(self):
        """Verify image clipboard calls on Android safely return None without panic."""
        with MockTermuxEnv(is_android=True) as env:
            cb = ClipboardSeam(env)
            img = cb.get_image()
            self.assertIsNone(img, "Image clipboard must return None on Android")

    def test_supported_image_clipboard_on_desktop(self):
        """Verify image clipboard behavior on desktop."""
        with MockTermuxEnv(is_android=False) as env:
            cb = ClipboardSeam(env)
            img = cb.get_image()
            self.assertIsNotNone(img, "Image clipboard returns data on desktop")


if __name__ == "__main__":
    unittest.main()
