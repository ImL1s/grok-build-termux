"""
Tier 4 Real-World Scenario 6: Package-Managed vs Standalone Update Gating.

Exercised Features:
- F27: Package-Managed Install Mode
- F28: Standalone Install Mode & Updater Isolation
"""

import unittest
from tests.e2e.harness.termux_sim import (
    UpdateManagerSeam,
)


class TestScenarioInstallUpdateGating(unittest.TestCase):

    def test_scenario_package_managed_grok_update_workflow(self):
        """Simulates `grok update` when installed via Termux apt/pkg repository."""
        mgr = UpdateManagerSeam(install_mode="package-managed")

        release_manifest = {
            "version": "1.5.0",
            "assets": {
                "linux-x86_64": {"url": "https://github.com/xai-org/grok-build/releases/linux.tar.gz"},
                "termux-aarch64": {"url": "https://github.com/ImL1s/grok-build-termux/releases/termux.tar.gz"},
            },
        }

        result = mgr.check_update(current_version="1.0.0", remote_manifest=release_manifest)

        # Assertions
        self.assertEqual(result["action"], "delegate_to_pkg")
        self.assertFalse(result["can_auto_download"])
        self.assertIn("pkg update && pkg upgrade grok-build", result["message"])

    def test_scenario_standalone_grok_update_workflow_with_channel_filtering(self):
        """Simulates `grok update` in standalone mode, rejecting upstream Linux releases."""
        mgr = UpdateManagerSeam(install_mode="standalone")

        # 1. Upstream release only contains desktop linux binaries
        desktop_only_manifest = {
            "version": "1.5.0",
            "assets": {
                "linux-x86_64": {"url": "https://github.com/xai-org/grok-build/releases/linux-x86_64.tar.gz"},
                "linux-aarch64": {"url": "https://github.com/xai-org/grok-build/releases/linux-aarch64.tar.gz"},
            },
        }

        res_desktop = mgr.check_update(current_version="1.0.0", remote_manifest=desktop_only_manifest)
        self.assertFalse(res_desktop["can_auto_download"])
        self.assertEqual(res_desktop["action"], "no_compatible_asset")

        # 2. Downstream Termux release contains termux-aarch64 binary
        termux_manifest = {
            "version": "1.5.0",
            "assets": {
                "termux-aarch64": {
                    "url": "https://github.com/ImL1s/grok-build-termux/releases/download/v1.5.0/grok-1.5.0-termux-aarch64.tar.gz",
                    "sha256": "abcdef1234567890",
                }
            },
        }

        res_termux = mgr.check_update(current_version="1.0.0", remote_manifest=termux_manifest)
        self.assertTrue(res_termux["can_auto_download"])
        self.assertEqual(res_termux["action"], "download_and_apply")
        self.assertIn("termux-aarch64", res_termux["asset_url"])


if __name__ == "__main__":
    unittest.main()
