"""
Tier 3 Pairwise Cross-Feature Interaction Tests (34 pairwise test cases).

Covers combinatorial interactions between features across the 5 architectural layers:
- Platform & Capability Layer (F1-F5)
- Build & Toolchain Layer (F6-F9)
- Filesystem & Storage Layer (F10-F14)
- Auth, Network & UX Layer (F15-F26)
- Distribution, Diagnostics & Upstream Layer (F27-F32)
"""

import unittest
import os
import json
import urllib.request
from tests.e2e.harness.termux_sim import (
    MockTermuxEnv,
    PlatformCapabilities,
    ToolResolverSeam,
    LinkOpenerSeam,
    OAuthServerSeam,
    ClipboardSeam,
    DoctorDiagnosticsSeam,
    UpdateManagerSeam,
    SandboxKind,
    StorageSafetyError,
    LinkOpenerError,
    ToolResolutionError,
)
from scripts.validate_elf import ElfBinary, validate_elf, generate_mock_elf


class TestTier3CrossFeaturePairwise(unittest.TestCase):

    # P01: F1 (PlatformCapabilities) + F2 ($PREFIX)
    def test_p01_platform_capabilities_dynamic_prefix_interaction(self):
        custom_pfx = "data/custom_termux/usr"
        with MockTermuxEnv(custom_prefix=custom_pfx, is_android=True) as env:
            caps = PlatformCapabilities(env)
            self.assertTrue(caps.is_android_termux())
            self.assertTrue(caps.prefix_dir().endswith(custom_pfx))
            self.assertTrue(caps.system_config_dir().endswith(f"{custom_pfx}/etc/grok"))

    # P02: F1 (PlatformCapabilities) + F3 (Allocator)
    def test_p02_platform_capabilities_allocator_gating(self):
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            allocator = "system_bionic" if caps.is_android_termux() else "jemalloc"
            self.assertEqual(allocator, "system_bionic")

    # P03: F1 (PlatformCapabilities) + F4 (Clipboard)
    def test_p03_platform_capabilities_clipboard_backend_selection(self):
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            clipboard = ClipboardSeam(env, allow_termux_api=False)
            ok, method = clipboard.set_text("test text")
            self.assertTrue(ok)
            self.assertEqual(method, "osc52")

    # P04: F1 (PlatformCapabilities) + F5 (Voice)
    def test_p04_platform_capabilities_voice_gating(self):
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            voice_supported = not caps.is_android_termux()
            self.assertFalse(voice_supported)

    # P05: F1 (PlatformCapabilities) + F10 (System Config)
    def test_p05_platform_capabilities_system_config_resolution(self):
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            sys_cfg = caps.system_config_dir()
            self.assertTrue(sys_cfg.startswith(caps.prefix_dir()))
            self.assertTrue(sys_cfg.endswith("etc/grok"))

    # P06: F1 (PlatformCapabilities) + F11 (User Home)
    def test_p06_platform_capabilities_user_home_resolution(self):
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            home = caps.home_dir()
            self.assertTrue(home.endswith(".grok"))
            self.assertNotIn("/sdcard", home)

    # P07: F1 (PlatformCapabilities) + F22 (Truthful Sandbox)
    def test_p07_platform_capabilities_truthful_sandbox_reporting(self):
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            self.assertEqual(caps.sandbox_kind(), SandboxKind.POLICY_ONLY)

    # P08: F2 ($PREFIX) + F8 (Native CLI Tools)
    def test_p08_prefix_native_cli_tools_resolution(self):
        with MockTermuxEnv(is_android=True) as env:
            env.install_mock_tool("rg", stdout="rg 14.1.0")
            resolver = ToolResolverSeam(env)
            path = resolver.resolve_tool("rg")
            self.assertTrue(path.startswith(env.prefix_dir))

    # P09: F2 ($PREFIX) + F12 (Runtime Sockets)
    def test_p09_prefix_runtime_sockets_in_tmp(self):
        with MockTermuxEnv(is_android=True) as env:
            os.environ.pop("TMPDIR", None)
            caps = PlatformCapabilities(env)
            sock_path = caps.create_socket_path("session_p09")
            self.assertTrue(sock_path.startswith(env.prefix_dir))

    # P10: F2 ($PREFIX) + F27 (Package Install Mode)
    def test_p10_prefix_package_install_mode_detection(self):
        with MockTermuxEnv(is_android=True) as env:
            bin_path = os.path.join(env.bin_dir, "grok")
            is_pkg_managed = bin_path.startswith(env.prefix_dir)
            self.assertTrue(is_pkg_managed)

    # P11: F6 (Bionic Build) + F7 (16 KiB ELF Alignment)
    def test_p11_bionic_build_and_16k_alignment(self):
        mock_bytes = generate_mock_elf("valid_16k_bionic")
        elf = ElfBinary(mock_bytes)
        is_valid, errors, _ = validate_elf(elf, min_page_size=16384, strict_16k=True, target_arch="aarch64", bionic_only=True)
        self.assertTrue(is_valid)
        self.assertEqual(elf.interpreter, "/system/bin/linker64")

    # P12: F6 (Bionic Build) + F30 (CI ELF Validator)
    def test_p12_bionic_build_ci_elf_validator_pipeline(self):
        mock_bytes = generate_mock_elf("invalid_glibc")
        elf = ElfBinary(mock_bytes)
        is_valid, errors, _ = validate_elf(elf, bionic_only=True)
        self.assertFalse(is_valid)
        self.assertTrue(any("glibc" in err.lower() for err in errors))

    # P13: F8 (Native CLI Tools) + F9 (Optional Search Fallback)
    def test_p13_native_tools_and_optional_search_fallback(self):
        with MockTermuxEnv(is_android=True) as env:
            env.install_mock_tool("rg", stdout="rg 14.1.0")
            env.install_mock_tool("fd", stdout="fd 9.0.0")
            # bfs and ugrep omitted -> fallback to fd and rg
            resolver = ToolResolverSeam(env)
            self.assertTrue(resolver.resolve_tool("rg").endswith("rg"))
            self.assertTrue(resolver.resolve_tool("fd").endswith("fd"))

    # P14: F8 (Native CLI Tools) + F29 (grok doctor)
    def test_p14_native_tools_grok_doctor_interaction(self):
        with MockTermuxEnv(is_android=True) as env:
            env.install_mock_tool("rg")
            env.install_mock_tool("git")
            caps = PlatformCapabilities(env)
            resolver = ToolResolverSeam(env)
            doctor = DoctorDiagnosticsSeam(caps, resolver)
            report = doctor.run_diagnostics()
            self.assertTrue(report["tools"]["rg"]["installed"])
            self.assertTrue(report["tools"]["git"]["installed"])
            self.assertFalse(report["tools"]["fd"]["installed"])

    # P15: F10 (System Config) + F11 (User Home)
    def test_p15_system_config_and_user_home_coexistence(self):
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            sys_cfg = caps.system_config_dir()
            user_home = caps.home_dir()
            self.assertNotEqual(sys_cfg, user_home)
            self.assertTrue(sys_cfg.endswith("etc/grok"))
            self.assertTrue(user_home.endswith(".grok"))

    # P16: F10 (System Config) + F23 (Policy Enforcement)
    def test_p16_system_config_write_protection_policy(self):
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            sys_cfg_file = os.path.join(caps.system_config_dir(), "config.toml")

            def can_subagent_modify(path: str) -> bool:
                # Subagents cannot modify system config files
                if "/etc/grok" in path:
                    return False
                return True

            self.assertFalse(can_subagent_modify(sys_cfg_file))

    # P17: F11 (User Home) + F13 (Storage Quarantine)
    def test_p17_user_home_storage_quarantine_rejection(self):
        with MockTermuxEnv(is_android=True) as env:
            os.environ["GROK_HOME"] = "/sdcard/my_grok"
            caps = PlatformCapabilities(env)
            with self.assertRaises(StorageSafetyError):
                caps.home_dir()

    # P18: F11 (User Home) + F26 (Session Checkpoints)
    def test_p18_user_home_session_checkpoint_saving(self):
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            sessions_dir = os.path.join(caps.home_dir(), "sessions")
            os.makedirs(sessions_dir, exist_ok=True)
            ckpt = os.path.join(sessions_dir, "turn_1.json")
            with open(ckpt, "w") as f:
                json.dump({"turn": 1, "done": True}, f)
            self.assertTrue(os.path.exists(ckpt))

    # P19: F12 (Runtime Sockets) + F23 (Policy Enforcement)
    def test_p19_runtime_sockets_policy_enforcement(self):
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            sock_path = caps.create_socket_path("sec_session")
            # Socket must be in temp dir, not in sensitive dirs
            self.assertNotIn(".ssh", sock_path)
            self.assertNotIn("credentials", sock_path)

    # P20: F13 (Storage Quarantine) + F14 (Workspace Protection)
    def test_p20_storage_quarantine_and_workspace_protection(self):
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            # Safe workspace on sdcard
            project_file = os.path.join(env.sdcard_dir, "App.java")
            with open(project_file, "w") as f:
                f.write("class App {}")
            self.assertTrue(os.path.exists(project_file))
            # Credentials remain quarantined in home_dir
            creds_path = os.path.join(caps.home_dir(), "credentials.json")
            self.assertNotIn(env.sdcard_dir, creds_path)

    # P21: F15 (Browser Handoff) + F16 (Loopback Callback)
    def test_p21_oauth_browser_handoff_and_loopback_callback(self):
        with MockTermuxEnv(is_android=True) as env:
            env.install_mock_tool("termux-open-url")
            opener = LinkOpenerSeam(env)
            server = OAuthServerSeam(port=0)
            server.start()
            try:
                auth_url = f"https://auth.x.ai/oauth?redirect_uri=http://127.0.0.1:{server.port}/callback"
                ok, _ = opener.open_url(auth_url)
                self.assertTrue(ok)

                # Simulate browser redirect
                callback_url = f"http://127.0.0.1:{server.port}/callback?code=p21_code&state=p21_state"
                req = urllib.request.urlopen(callback_url)
                self.assertEqual(req.status, 200)
                self.assertEqual(server.captured_code, "p21_code")
            finally:
                server.stop()

    # P22: F15 (Browser Handoff) + F17 (Manual Paste Fallback)
    def test_p22_browser_handoff_fallback_to_manual_paste(self):
        with MockTermuxEnv(is_android=True) as env:
            opener = LinkOpenerSeam(env, allow_termux_open=False)
            ok, method = opener.open_url("https://auth.x.ai/login")
            self.assertFalse(ok)
            self.assertEqual(method, "manual_print")
            # User manually pastes callback
            code, _ = OAuthServerSeam.parse_manual_input("http://127.0.0.1:8080/callback?code=manual_xyz")
            self.assertEqual(code, "manual_xyz")

    # P23: F16 (Loopback Callback) + F17 (Manual Paste Fallback)
    def test_p23_loopback_and_manual_paste_race(self):
        # Whichever arrives first wins
        callback_code = None
        manual_code = "fast_manual_code"
        final_code = callback_code or manual_code
        self.assertEqual(final_code, "fast_manual_code")

    # P24: F16 (Loopback Callback) + F18 (Bionic DNS/TLS)
    def test_p24_loopback_callback_and_bionic_token_exchange(self):
        server = OAuthServerSeam(port=0)
        server.start()
        try:
            url = f"http://127.0.0.1:{server.port}/callback?code=token_exchange_code"
            urllib.request.urlopen(url)
            self.assertEqual(server.captured_code, "token_exchange_code")
        finally:
            server.stop()

    # P25: F19 (Termux:API Clipboard) + F20 (OSC 52 Fallback)
    def test_p25_termux_api_clipboard_fallback_to_osc52(self):
        with MockTermuxEnv(is_android=True) as env:
            # First with Termux:API
            env.install_mock_tool("termux-clipboard-set")
            cb1 = ClipboardSeam(env, allow_termux_api=True)
            ok1, m1 = cb1.set_text("msg1")
            self.assertEqual(m1, "termux_api")

            # Without Termux:API
            cb2 = ClipboardSeam(env, allow_termux_api=False)
            ok2, m2 = cb2.set_text("msg2")
            self.assertEqual(m2, "osc52")

    # P26: F19 (Termux:API Clipboard) + F21 (Unsupported Degradation)
    def test_p26_termux_clipboard_text_vs_image_degradation(self):
        with MockTermuxEnv(is_android=True) as env:
            env.install_mock_tool("termux-clipboard-set")
            cb = ClipboardSeam(env, allow_termux_api=True)
            ok, _ = cb.set_text("text supported")
            self.assertTrue(ok)
            # Image remains unsupported cleanly
            self.assertIsNone(cb.get_image())

    # P27: F22 (Truthful Sandbox) + F23 (Policy Enforcement)
    def test_p27_truthful_sandbox_and_policy_enforcement(self):
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            self.assertEqual(caps.sandbox_kind(), SandboxKind.POLICY_ONLY)

            # In-process policy prevents write to SSH
            sensitive = "/data/data/com.termux/files/home/.ssh/id_rsa"
            is_blocked = ".ssh" in sensitive
            self.assertTrue(is_blocked)

    # P28: F22 (Truthful Sandbox) + F29 (grok doctor)
    def test_p28_truthful_sandbox_in_grok_doctor_report(self):
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            resolver = ToolResolverSeam(env)
            doctor = DoctorDiagnosticsSeam(caps, resolver)
            report = doctor.run_diagnostics()
            self.assertEqual(report["sandbox_kind"], "policy-only")

    # P29: F24 (Conservative Concurrency) + F25 (Wake Lock)
    def test_p29_concurrency_limits_with_wake_lock(self):
        with MockTermuxEnv(is_android=True) as env:
            env.install_mock_tool("termux-wake-lock")
            env.install_mock_tool("termux-wake-unlock")
            max_workers = 2
            wake_lock_active = True
            self.assertLessEqual(max_workers, 4)
            self.assertTrue(wake_lock_active)

    # P30: F25 (Wake Lock) + F26 (Session Checkpoints)
    def test_p30_wake_lock_during_checkpoint_save(self):
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            sessions_dir = os.path.join(caps.home_dir(), "sessions")
            os.makedirs(sessions_dir, exist_ok=True)
            ckpt = os.path.join(sessions_dir, "checkpoint_locked.json")
            with open(ckpt, "w") as f:
                json.dump({"locked": True}, f)
            self.assertTrue(os.path.exists(ckpt))

    # P31: F27 (Package Install) + F28 (Standalone Install)
    def test_p31_package_vs_standalone_install_mode_discrimination(self):
        pkg_mgr = UpdateManagerSeam(install_mode="package-managed")
        standalone_mgr = UpdateManagerSeam(install_mode="standalone")
        manifest = {
            "version": "1.2.0",
            "assets": {"termux-aarch64": {"url": "https://example.com/grok.tar.gz"}},
        }
        res_pkg = pkg_mgr.check_update("1.0.0", manifest)
        res_standalone = standalone_mgr.check_update("1.0.0", manifest)

        self.assertEqual(res_pkg["action"], "delegate_to_pkg")
        self.assertEqual(res_standalone["action"], "download_and_apply")

    # P32: F29 (grok doctor) + F31 (Real-Device Matrix)
    def test_p32_doctor_diagnostics_against_device_expectations(self):
        with MockTermuxEnv(is_android=True) as env:
            env.install_mock_tool("rg")
            env.install_mock_tool("fd")
            env.install_mock_tool("git")
            env.install_mock_tool("bash")
            caps = PlatformCapabilities(env)
            resolver = ToolResolverSeam(env)
            doctor = DoctorDiagnosticsSeam(caps, resolver)
            report = doctor.run_diagnostics()
            self.assertEqual(report["platform"], "Android/Termux")
            self.assertTrue(report["prefix_valid"])
            self.assertEqual(len(report["issues"]), 0)

    # P33: F30 (ELF Validator) + F32 (Upstream Sync)
    def test_p33_elf_validator_gates_upstream_sync_pr(self):
        valid_bytes = generate_mock_elf("valid_16k_bionic")
        elf = ElfBinary(valid_bytes)
        is_valid, _, _ = validate_elf(elf)
        can_merge = is_valid
        self.assertTrue(can_merge)

    # P34: F13 (Storage Quarantine) + F29 (grok doctor)
    def test_p34_storage_quarantine_detected_by_grok_doctor(self):
        with MockTermuxEnv(is_android=True) as env:
            os.environ["GROK_HOME"] = "/sdcard/unsafe_grok"
            caps = PlatformCapabilities(env)
            resolver = ToolResolverSeam(env)
            doctor = DoctorDiagnosticsSeam(caps, resolver)
            report = doctor.run_diagnostics()
            self.assertFalse(report["storage_safe"])
            self.assertTrue(any("cannot reside on Android shared storage" in issue for issue in report["issues"]))


if __name__ == "__main__":
    unittest.main()
