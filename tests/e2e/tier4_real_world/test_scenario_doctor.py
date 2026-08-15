"""
Tier 4 Real-World Scenario 1: Full `grok doctor` Diagnostic Execution on Termux.

Exercised Features:
- F1: Centralized Platform Capability Layer
- F2: Dynamic $PREFIX Discovery
- F8: Native CLI Tool Resolution
- F10: System Configuration Resolution
- F18: Native Bionic DNS & TLS Resolution
- F22: Truthful Sandbox Reporting
- F29: `grok doctor` for Android/Termux
"""

import unittest
import os
import json
from tests.e2e.harness.termux_sim import (
    MockTermuxEnv,
    PlatformCapabilities,
    ToolResolverSeam,
    DoctorDiagnosticsSeam,
    SandboxKind,
)


class TestScenarioDoctor(unittest.TestCase):

    def test_scenario_doctor_full_healthy_run(self):
        """Simulates running `grok doctor` on a fully configured Termux environment."""
        with MockTermuxEnv(is_android=True) as env:
            # Install all native tools in Termux bin
            env.install_mock_tool("rg", stdout="ripgrep 14.1.0")
            env.install_mock_tool("fd", stdout="fd 9.0.0")
            env.install_mock_tool("git", stdout="git version 2.45.0")
            env.install_mock_tool("bash", stdout="GNU bash 5.2.26")
            env.install_mock_tool("termux-open-url")
            env.install_mock_tool("termux-clipboard-get")
            env.install_mock_tool("termux-clipboard-set")

            caps = PlatformCapabilities(env)
            resolver = ToolResolverSeam(env)
            doctor = DoctorDiagnosticsSeam(caps, resolver)

            report = doctor.run_diagnostics()

            # Assertions on Doctor Output
            self.assertEqual(report["platform"], "Android/Termux")
            self.assertTrue(report["prefix_valid"])
            self.assertTrue(report["prefix"].startswith(env.temp_root))
            self.assertTrue(report["home"].endswith(".grok"))
            self.assertTrue(report["storage_safe"])
            self.assertEqual(report["sandbox_kind"], "policy-only")
            self.assertEqual(len(report["issues"]), 0)
            self.assertEqual(len(report["remediations"]), 0)

            # Check tools status
            self.assertTrue(report["tools"]["rg"]["installed"])
            self.assertTrue(report["tools"]["fd"]["installed"])
            self.assertTrue(report["tools"]["git"]["installed"])
            self.assertTrue(report["tools"]["bash"]["installed"])

            # JSON export verification
            json_report = json.dumps(report, indent=2)
            parsed = json.loads(json_report)
            self.assertEqual(parsed["sandbox_kind"], "policy-only")

    def test_scenario_doctor_missing_packages_with_remediation(self):
        """Simulates running `grok doctor` on a fresh Termux install missing ripgrep and fd."""
        with MockTermuxEnv(is_android=True) as env:
            # Only git and bash installed
            env.install_mock_tool("git")
            env.install_mock_tool("bash")

            caps = PlatformCapabilities(env)
            resolver = ToolResolverSeam(env)
            doctor = DoctorDiagnosticsSeam(caps, resolver)

            report = doctor.run_diagnostics()

            self.assertFalse(report["tools"]["rg"]["installed"])
            self.assertFalse(report["tools"]["fd"]["installed"])
            self.assertEqual(len(report["issues"]), 2)
            self.assertTrue(any("pkg install rg" in r for r in report["remediations"]))
            self.assertTrue(any("pkg install fd" in r for r in report["remediations"]))


if __name__ == "__main__":
    unittest.main()
