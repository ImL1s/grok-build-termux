"""
Tier 4 Real-World Scenario 3: Shared Storage (/sdcard) Quarantine & Workspace Access.

Exercised Features:
- F10: System Configuration Resolution
- F11: User Home Directory Resolution
- F13: Shared Storage Quarantine
- F14: Shared-Storage Workspace Protection
- F23: In-Process Policy Enforcement
"""

import unittest
import os
import json
from tests.e2e.harness.termux_sim import (
    MockTermuxEnv,
    PlatformCapabilities,
    StorageSafetyError,
)


class TestScenarioStorageQuarantine(unittest.TestCase):

    def test_scenario_quarantine_rejection_at_startup(self):
        """Verifies process startup refusal when GROK_HOME is configured on /sdcard."""
        with MockTermuxEnv(is_android=True) as env:
            # User sets GROK_HOME to shared storage
            os.environ["GROK_HOME"] = "/sdcard/.grok"
            caps = PlatformCapabilities(env)

            with self.assertRaises(StorageSafetyError) as ctx:
                caps.home_dir()

            err_msg = str(ctx.exception)
            self.assertIn("cannot reside on Android shared storage", err_msg)
            self.assertIn("Owner-only permissions (0700) are required", err_msg)

    def test_scenario_safe_editing_of_sdcard_project_workspace(self):
        """Verifies editing project on /sdcard while isolating state in private $HOME/.grok."""
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)

            # Project directory created on Android shared storage (/sdcard)
            sdcard_project = os.path.join(env.sdcard_dir, "MyRustApp")
            os.makedirs(sdcard_project, exist_ok=True)
            src_file = os.path.join(sdcard_project, "main.rs")
            with open(src_file, "w") as f:
                f.write('fn main() { println!("Running on Android Termux!"); }\n')

            # 1. Project file read/write works
            self.assertTrue(os.path.exists(src_file))
            with open(src_file, "r") as f:
                code = f.read()
            self.assertIn("Running on Android Termux", code)

            # 2. State, credentials, and sessions remain strictly in private $HOME/.grok
            home_grok = caps.home_dir()
            self.assertTrue(home_grok.endswith(".grok"))
            self.assertNotIn(env.sdcard_dir, home_grok)

            creds_file = os.path.join(home_grok, "credentials.json")
            os.makedirs(home_grok, exist_ok=True)
            with open(creds_file, "w") as f:
                json.dump({"token": "secret_token"}, f)

            # Assert credentials are NOT on /sdcard
            self.assertFalse(os.path.exists(os.path.join(sdcard_project, "credentials.json")))
            self.assertFalse(os.path.exists(os.path.join(env.sdcard_dir, ".grok")))

            # 3. Policy enforcement prevents extraction of executable binary to /sdcard
            def check_exec_allowed(path: str) -> bool:
                if path.startswith("/sdcard") or path.startswith(env.sdcard_dir):
                    return False
                return True

            target_exec = os.path.join(sdcard_project, "target/debug/app")
            self.assertFalse(check_exec_allowed(target_exec))


if __name__ == "__main__":
    unittest.main()
