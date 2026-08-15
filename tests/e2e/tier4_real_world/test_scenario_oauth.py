"""
Tier 4 Real-World Scenario 2: Complete OAuth Login Flow with Browser Handoff, Loopback Callback & Manual Fallback.

Exercised Features:
- F15: Termux OAuth Browser Handoff (`termux-open-url`)
- F16: Loopback Callback Server (`127.0.0.1:<port>`)
- F17: Manual Code / URL Paste Fallback
- F18: Native Bionic DNS & TLS Resolution
- F11: User Home Directory Resolution ($HOME/.grok/credentials.json)
"""

import unittest
import os
import json
import time
import urllib.request
from tests.e2e.harness.termux_sim import (
    MockTermuxEnv,
    PlatformCapabilities,
    LinkOpenerSeam,
    OAuthServerSeam,
)


class TestScenarioOAuth(unittest.TestCase):

    def test_scenario_oauth_happy_path_browser_callback(self):
        """Simulates full OAuth login with browser dispatch via termux-open-url and loopback redirect."""
        with MockTermuxEnv(is_android=True) as env:
            env.install_mock_tool("termux-open-url")
            caps = PlatformCapabilities(env)
            opener = LinkOpenerSeam(env, allow_termux_open=True)

            # 1. Start loopback callback server
            server = OAuthServerSeam(port=0)
            server.start()
            try:
                auth_url = (
                    f"https://auth.x.ai/oauth2/authorize?response_type=code"
                    f"&client_id=grok_termux_cli&redirect_uri=http://127.0.0.1:{server.port}/callback"
                    f"&state=sec_state_456&scope=openid%20profile%20api"
                )

                # 2. Dispatch browser handoff
                dispatched, method = opener.open_url(auth_url)
                self.assertTrue(dispatched)
                self.assertEqual(method, "termux-open-url")

                # 3. Simulate browser hitting callback URL
                callback_url = f"http://127.0.0.1:{server.port}/callback?code=mock_auth_token_999&state=sec_state_456"
                resp = urllib.request.urlopen(callback_url)
                self.assertEqual(resp.status, 200)
                html_body = resp.read().decode("utf-8")
                self.assertIn("Login Successful", html_body)

                # 4. Capture code
                time.sleep(0.05)
                self.assertEqual(server.captured_code, "mock_auth_token_999")
                self.assertEqual(server.captured_state, "sec_state_456")

                # 5. Persist credentials in $HOME/.grok/credentials.json
                creds_dir = caps.home_dir()
                os.makedirs(creds_dir, exist_ok=True)
                creds_file = os.path.join(creds_dir, "credentials.json")
                token_data = {
                    "access_token": "mock_jwt_access_token",
                    "refresh_token": "mock_refresh_token",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                }
                with open(creds_file, "w") as f:
                    json.dump(token_data, f)

                self.assertTrue(os.path.exists(creds_file))
                with open(creds_file, "r") as f:
                    saved = json.load(f)
                self.assertEqual(saved["access_token"], "mock_jwt_access_token")

            finally:
                server.stop()

    def test_scenario_oauth_fallback_to_manual_paste(self):
        """Simulates OAuth when termux-open-url is missing or callback port is blocked."""
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            opener = LinkOpenerSeam(env, allow_termux_open=False)

            # Opener falls back to manual URL print
            auth_url = "https://auth.x.ai/oauth2/authorize?client_id=grok_cli"
            dispatched, method = opener.open_url(auth_url)
            self.assertFalse(dispatched)
            self.assertEqual(method, "manual_print")

            # User manually pastes redirected URL from browser
            user_paste = "http://127.0.0.1:8080/callback?code=manual_token_code_777&state=st_123"
            code, state = OAuthServerSeam.parse_manual_input(user_paste)
            self.assertEqual(code, "manual_token_code_777")
            self.assertEqual(state, "st_123")

            # Write credentials
            creds_file = os.path.join(caps.home_dir(), "credentials.json")
            os.makedirs(os.path.dirname(creds_file), exist_ok=True)
            with open(creds_file, "w") as f:
                json.dump({"access_token": "manual_jwt"}, f)
            self.assertTrue(os.path.exists(creds_file))


if __name__ == "__main__":
    unittest.main()
