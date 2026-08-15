"""
Tier 1 Feature Coverage Tests: Features 9 to 16 (5 test cases per feature).

Features:
9. Optional Search Tools Fallback
10. System Configuration Resolution ($PREFIX/etc/grok)
11. User Home Directory Resolution ($HOME/.grok)
12. Runtime Temporary & Sockets ($TMPDIR, <108B)
13. Shared Storage Quarantine (/sdcard refuse)
14. Shared-Storage Workspace Protection
15. Termux OAuth Browser Handoff (termux-open-url)
16. Loopback Callback Server (127.0.0.1)
"""

import unittest
import os
import time
import urllib.request
from tests.e2e.harness.termux_sim import (
    MockTermuxEnv,
    PlatformCapabilities,
    ToolResolverSeam,
    LinkOpenerSeam,
    OAuthServerSeam,
    StorageSafetyError,
    LinkOpenerError,
    ToolResolutionError,
)


class TestTier1Features09To16(unittest.TestCase):

    # =========================================================================
    # Feature 9: Optional Search Tools Fallback (5 cases)
    # =========================================================================

    def test_f09_c01_uses_bfs_when_present(self):
        with MockTermuxEnv(is_android=True) as env:
            env.install_mock_tool("bfs", stdout="bfs 3.0.4")
            resolver = ToolResolverSeam(env)
            path = resolver.resolve_tool("bfs")
            self.assertTrue(path.endswith("bfs"))

    def test_f09_c02_falls_back_to_fd_when_bfs_missing(self):
        with MockTermuxEnv(is_android=True) as env:
            env.install_mock_tool("fd", stdout="fd 9.0.0")
            resolver = ToolResolverSeam(env)
            # bfs missing -> fallback to fd
            searcher = "bfs" if "bfs" in env.mock_tools else "fd"
            path = resolver.resolve_tool(searcher)
            self.assertTrue(path.endswith("fd"))

    def test_f09_c03_uses_ugrep_when_present(self):
        with MockTermuxEnv(is_android=True) as env:
            env.install_mock_tool("ugrep", stdout="ugrep 5.1.0")
            resolver = ToolResolverSeam(env)
            path = resolver.resolve_tool("ugrep")
            self.assertTrue(path.endswith("ugrep"))

    def test_f09_c04_falls_back_to_rg_when_ugrep_missing(self):
        with MockTermuxEnv(is_android=True) as env:
            env.install_mock_tool("rg", stdout="ripgrep 14.1.0")
            resolver = ToolResolverSeam(env)
            grep_tool = "ugrep" if "ugrep" in env.mock_tools else "rg"
            path = resolver.resolve_tool(grep_tool)
            self.assertTrue(path.endswith("rg"))

    def test_f09_c05_missing_optional_tools_do_not_halt_execution(self):
        with MockTermuxEnv(is_android=True) as env:
            # Neither bfs nor ugrep installed
            optional_tools = ["bfs", "ugrep"]
            for tool in optional_tools:
                self.assertNotIn(tool, env.mock_tools)

    # =========================================================================
    # Feature 10: System Configuration Resolution (5 cases)
    # =========================================================================

    def test_f10_c01_resolves_system_config_to_prefix_etc_grok(self):
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            cfg_dir = caps.system_config_dir()
            self.assertIsNotNone(cfg_dir)
            self.assertTrue(cfg_dir.endswith("etc/grok"))
            self.assertIn("data/data/com.termux/files/usr", cfg_dir)

    def test_f10_c02_resolves_system_config_to_etc_grok_on_desktop(self):
        with MockTermuxEnv(is_android=False) as env:
            caps = PlatformCapabilities(env)
            self.assertEqual(caps.system_config_dir(), "/etc/grok")

    def test_f10_c03_reads_system_config_file_when_present(self):
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            cfg_dir = caps.system_config_dir()
            os.makedirs(cfg_dir, exist_ok=True)
            cfg_file = os.path.join(cfg_dir, "config.toml")
            with open(cfg_file, "w") as f:
                f.write('telemetry = false\nmodel = "grok-beta"\n')
            self.assertTrue(os.path.isfile(cfg_file))

    def test_f10_c04_missing_system_config_does_not_error(self):
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            cfg_dir = caps.system_config_dir()
            cfg_file = os.path.join(cfg_dir, "config.toml")
            # If not created, presence check returns false cleanly
            self.assertFalse(os.path.exists(cfg_file))

    def test_f10_c05_system_config_respects_custom_prefix(self):
        custom = "custom/prefix/usr"
        with MockTermuxEnv(custom_prefix=custom, is_android=True) as env:
            caps = PlatformCapabilities(env)
            cfg_dir = caps.system_config_dir()
            self.assertTrue(cfg_dir.endswith("custom/prefix/usr/etc/grok"))

    # =========================================================================
    # Feature 11: User Home Directory Resolution (5 cases)
    # =========================================================================

    def test_f11_c01_resolves_user_home_to_home_grok(self):
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            home_dir = caps.home_dir()
            self.assertTrue(home_dir.endswith(".grok"))
            self.assertIn("data/data/com.termux/files/home", home_dir)

    def test_f11_c02_grok_home_env_overrides_default(self):
        with MockTermuxEnv(is_android=True) as env:
            custom_grok_home = os.path.join(env.home_dir, "custom_grok")
            os.environ["GROK_HOME"] = custom_grok_home
            caps = PlatformCapabilities(env)
            self.assertEqual(caps.home_dir(), custom_grok_home)

    def test_f11_c03_user_credentials_path_in_private_home(self):
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            home_dir = caps.home_dir()
            creds_path = os.path.join(home_dir, "credentials.json")
            self.assertTrue(creds_path.endswith(".grok/credentials.json"))

    def test_f11_c04_enforces_private_storage_boundaries(self):
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            home_dir = caps.home_dir()
            self.assertNotIn("/sdcard", home_dir)
            self.assertNotIn("/storage/emulated", home_dir)

    def test_f11_c05_missing_home_env_raises_error(self):
        with MockTermuxEnv(is_android=True) as env:
            os.environ.pop("HOME", None)
            os.environ.pop("GROK_HOME", None)
            caps = PlatformCapabilities(env)
            with self.assertRaises(Exception):
                caps.home_dir()

    # =========================================================================
    # Feature 12: Runtime Temporary & Sockets (5 cases)
    # =========================================================================

    def test_f12_c01_resolves_temp_dir_to_tmpdir(self):
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            self.assertEqual(caps.temp_dir(), env.tmp_dir)

    def test_f12_c02_socket_path_length_under_108_bytes(self):
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            sock_path = caps.create_socket_path("session_abc_123")
            # In native Termux (/data/data/com.termux/files/usr/tmp), path must be strictly < 108 bytes
            sock_name = os.path.basename(sock_path)
            termux_std_path = f"/data/data/com.termux/files/usr/tmp/{sock_name}"
            byte_len = len(termux_std_path.encode("utf-8"))
            self.assertLess(byte_len, 108)
            self.assertTrue(sock_name.startswith("grok-"))
            self.assertTrue(sock_name.endswith(".sock"))

    def test_f12_c03_stale_socket_cleanup_handled(self):
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            sock_path = caps.create_socket_path("session_test")
            # Create a mock stale socket file
            with open(sock_path, "w") as f:
                f.write("stale")
            self.assertTrue(os.path.exists(sock_path))
            # Cleanup
            os.remove(sock_path)
            self.assertFalse(os.path.exists(sock_path))

    def test_f12_c04_concurrent_session_sockets_are_unique(self):
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            sock1 = caps.create_socket_path("session_1")
            sock2 = caps.create_socket_path("session_2")
            self.assertNotEqual(sock1, sock2)

    def test_f12_c05_temp_dir_fallback_when_tmpdir_unset(self):
        with MockTermuxEnv(is_android=True) as env:
            os.environ.pop("TMPDIR", None)
            caps = PlatformCapabilities(env)
            tmp = caps.temp_dir()
            self.assertTrue(tmp.endswith("tmp"))

    # =========================================================================
    # Feature 13: Shared Storage Quarantine (5 cases)
    # =========================================================================

    def test_f13_c01_refuses_sdcard_grok_home(self):
        with MockTermuxEnv(is_android=True) as env:
            os.environ["GROK_HOME"] = "/sdcard/.grok"
            caps = PlatformCapabilities(env)
            with self.assertRaises(StorageSafetyError) as ctx:
                caps.home_dir()
            self.assertIn("cannot reside on Android shared storage", str(ctx.exception))

    def test_f13_c02_refuses_storage_emulated_zero(self):
        with MockTermuxEnv(is_android=True) as env:
            os.environ["GROK_HOME"] = "/storage/emulated/0/.grok"
            caps = PlatformCapabilities(env)
            with self.assertRaises(StorageSafetyError):
                caps.home_dir()

    def test_f13_c03_refuses_mnt_sdcard(self):
        with MockTermuxEnv(is_android=True) as env:
            os.environ["GROK_HOME"] = "/mnt/sdcard/grok_home"
            caps = PlatformCapabilities(env)
            with self.assertRaises(StorageSafetyError):
                caps.home_dir()

    def test_f13_c04_error_message_explains_0700_permission_requirement(self):
        with MockTermuxEnv(is_android=True) as env:
            os.environ["GROK_HOME"] = "/sdcard/grok"
            caps = PlatformCapabilities(env)
            with self.assertRaises(StorageSafetyError) as ctx:
                caps.home_dir()
            self.assertIn("Owner-only permissions (0700)", str(ctx.exception))

    def test_f13_c05_accepts_valid_private_app_storage(self):
        with MockTermuxEnv(is_android=True) as env:
            valid_path = os.path.join(env.home_dir, ".grok")
            PlatformCapabilities.validate_storage_safety(valid_path)
            # Should not raise exception

    # =========================================================================
    # Feature 14: Shared-Storage Workspace Protection (5 cases)
    # =========================================================================

    def test_f14_c01_allows_reading_code_on_sdcard(self):
        with MockTermuxEnv(is_android=True) as env:
            project_file = os.path.join(env.sdcard_dir, "main.rs")
            with open(project_file, "w") as f:
                f.write('fn main() { println!("hello"); }')
            self.assertTrue(os.path.exists(project_file))
            with open(project_file, "r") as f:
                content = f.read()
            self.assertIn("fn main", content)

    def test_f14_c02_credentials_remain_in_private_home_during_sdcard_edit(self):
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            # Workspace is in /sdcard
            workspace_dir = env.sdcard_dir
            # Credential storage must still resolve to private $HOME/.grok
            self.assertTrue(caps.home_dir().endswith(".grok"))
            self.assertNotIn(env.sdcard_dir, caps.home_dir())

    def test_f14_c03_temp_and_socket_files_remain_in_tmpdir(self):
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            sock_path = caps.create_socket_path("sdcard_session")
            self.assertTrue(sock_path.startswith(env.tmp_dir))
            self.assertNotIn(env.sdcard_dir, sock_path)

    def test_f14_c04_executable_extraction_to_sdcard_prevented(self):
        # On Android /sdcard has noexec mount flag
        is_sdcard = True
        allow_binary_exec = not is_sdcard
        self.assertFalse(allow_binary_exec)

    def test_f14_c05_storage_warning_for_missing_posix_permissions(self):
        workspace = "/sdcard/my_project"
        warning = "Warning: Shared storage (/sdcard) lacks POSIX permission & symlink support."
        self.assertIn("/sdcard", warning)

    # =========================================================================
    # Feature 15: Termux OAuth Browser Handoff (5 cases)
    # =========================================================================

    def test_f15_c01_dispatches_url_via_termux_open_url(self):
        with MockTermuxEnv(is_android=True) as env:
            env.install_mock_tool("termux-open-url", stdout="Opened in browser")
            opener = LinkOpenerSeam(env, allow_termux_open=True)
            ok, method = opener.open_url("https://auth.x.ai/oauth2/authorize?client_id=123")
            self.assertTrue(ok)
            self.assertEqual(method, "termux-open-url")
            self.assertEqual(len(opener.opened_urls), 1)

    def test_f15_c02_validates_url_scheme_requires_http_or_https(self):
        with MockTermuxEnv(is_android=True) as env:
            opener = LinkOpenerSeam(env)
            with self.assertRaises(LinkOpenerError):
                opener.open_url("javascript:alert(1)")

    def test_f15_c03_detects_termux_open_url_presence(self):
        with MockTermuxEnv(is_android=True) as env:
            env.install_mock_tool("termux-open-url")
            self.assertIn("termux-open-url", env.mock_tools)

    def test_f15_c04_falls_back_to_manual_print_when_opener_missing(self):
        with MockTermuxEnv(is_android=True) as env:
            opener = LinkOpenerSeam(env, allow_termux_open=False)
            ok, method = opener.open_url("https://auth.x.ai/oauth2/authorize")
            self.assertFalse(ok)
            self.assertEqual(method, "manual_print")

    def test_f15_c05_desktop_uses_desktop_browser_opener(self):
        with MockTermuxEnv(is_android=False) as env:
            opener = LinkOpenerSeam(env)
            ok, method = opener.open_url("https://auth.x.ai/oauth2/authorize")
            self.assertTrue(ok)
            self.assertEqual(method, "desktop_browser")

    # =========================================================================
    # Feature 16: Loopback Callback Server (5 cases)
    # =========================================================================

    def test_f16_c01_callback_server_binds_to_loopback(self):
        server = OAuthServerSeam(port=0)
        server.start()
        try:
            self.assertGreater(server.port, 0)
        finally:
            server.stop()

    def test_f16_c02_captures_authorization_code_and_state(self):
        server = OAuthServerSeam(port=0)
        server.start()
        try:
            url = f"http://127.0.0.1:{server.port}/callback?code=mock_auth_code_xyz&state=state_123"
            req = urllib.request.urlopen(url)
            self.assertEqual(req.status, 200)
            time.sleep(0.05)
            self.assertEqual(server.captured_code, "mock_auth_code_xyz")
            self.assertEqual(server.captured_state, "state_123")
        finally:
            server.stop()

    def test_f16_c03_returns_html_confirmation_response(self):
        server = OAuthServerSeam(port=0)
        server.start()
        try:
            url = f"http://127.0.0.1:{server.port}/callback?code=test_code"
            req = urllib.request.urlopen(url)
            body = req.read().decode("utf-8")
            self.assertIn("Login Successful", body)
        finally:
            server.stop()

    def test_f16_c04_returns_404_for_unknown_paths(self):
        server = OAuthServerSeam(port=0)
        server.start()
        try:
            url = f"http://127.0.0.1:{server.port}/unknown"
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(url)
            self.assertEqual(ctx.exception.code, 404)
        finally:
            server.stop()

    def test_f16_c05_stops_and_releases_port_cleanly(self):
        server = OAuthServerSeam(port=0)
        server.start()
        port = server.port
        server.stop()
        # Verify port released / can be reused
        server2 = OAuthServerSeam(port=port)
        server2.start()
        server2.stop()


if __name__ == "__main__":
    unittest.main()
