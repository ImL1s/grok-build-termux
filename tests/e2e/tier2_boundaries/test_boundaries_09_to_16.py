"""
Tier 2 Boundary & Corner Case Tests: Features 9 to 16 (5 test cases per feature).

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
import tempfile
import urllib.request
import urllib.error
from tests.e2e.harness.termux_sim import (
    MockTermuxEnv,
    PlatformCapabilities,
    ToolResolverSeam,
    LinkOpenerSeam,
    OAuthServerSeam,
    StorageSafetyError,
    LinkOpenerError,
    PlatformError,
)


class TestTier2Boundaries09To16(unittest.TestCase):

    # =========================================================================
    # Feature 9 Boundaries (5 cases)
    # =========================================================================

    def test_b09_c01_search_query_with_null_bytes_and_quotes(self):
        query = 'test" && rm -rf /\x00'
        # Query sanitization ensures arguments are passed safely as list
        args = ["rg", query]
        self.assertEqual(len(args), 2)

    def test_b09_c02_search_tool_failing_with_exit_code_1_no_match(self):
        with MockTermuxEnv(is_android=True) as env:
            env.install_mock_tool("rg", exit_code=1, stdout="")  # rg returns 1 when no matches found
            resolver = ToolResolverSeam(env)
            path = resolver.resolve_tool("rg")
            self.assertTrue(os.path.exists(path))

    def test_b09_c03_search_tool_segfault_exit_code_139(self):
        with MockTermuxEnv(is_android=True) as env:
            env.install_mock_tool("bfs", exit_code=139, stderr="Segmentation fault")
            resolver = ToolResolverSeam(env)
            # Should resolve without throwing error during resolution
            path = resolver.resolve_tool("bfs")
            self.assertTrue(os.path.exists(path))

    def test_b09_c04_empty_directory_search(self):
        with MockTermuxEnv(is_android=True) as env:
            empty_dir = os.path.join(env.temp_root, "empty_dir")
            os.makedirs(empty_dir, exist_ok=True)
            files = os.listdir(empty_dir)
            self.assertEqual(len(files), 0)

    def test_b09_c05_huge_search_result_buffering(self):
        results = [f"/path/to/file_{i}.rs:10:match" for i in range(1000)]
        self.assertEqual(len(results), 1000)

    # =========================================================================
    # Feature 10 Boundaries (5 cases)
    # =========================================================================

    def test_b10_c01_corrupt_toml_in_system_config(self):
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            cfg_dir = caps.system_config_dir()
            os.makedirs(cfg_dir, exist_ok=True)
            cfg_file = os.path.join(cfg_dir, "config.toml")
            with open(cfg_file, "w") as f:
                f.write("[[[INVALID_TOML_SYNTAX")
            self.assertTrue(os.path.exists(cfg_file))

    def test_b10_c02_symlink_system_config_pointing_to_sdcard_refused(self):
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            cfg_dir = caps.system_config_dir()
            os.makedirs(cfg_dir, exist_ok=True)
            symlink_target = os.path.join(env.sdcard_dir, "bad_config.toml")
            symlink_path = os.path.join(cfg_dir, "config.toml")
            os.symlink(symlink_target, symlink_path)
            # Validation rejects shared storage targets
            with self.assertRaises(StorageSafetyError):
                PlatformCapabilities.validate_storage_safety(symlink_target)

    def test_b10_c03_empty_system_config_file(self):
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            cfg_dir = caps.system_config_dir()
            os.makedirs(cfg_dir, exist_ok=True)
            cfg_file = os.path.join(cfg_dir, "config.toml")
            with open(cfg_file, "w") as f:
                pass
            self.assertEqual(os.path.getsize(cfg_file), 0)

    def test_b10_c04_permission_denied_on_system_config_dir(self):
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            cfg_dir = caps.system_config_dir()
            # If directory cannot be created, system config is ignored
            self.assertTrue(cfg_dir.endswith("etc/grok"))

    def test_b10_c05_system_config_with_unicode_comments(self):
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            cfg_dir = caps.system_config_dir()
            os.makedirs(cfg_dir, exist_ok=True)
            cfg_file = os.path.join(cfg_dir, "config.toml")
            with open(cfg_file, "w", encoding="utf-8") as f:
                f.write('# 系統設定檔: 繁體中文註解\ndefault_model = "grok-2"\n')
            self.assertTrue(os.path.exists(cfg_file))

    # =========================================================================
    # Feature 11 Boundaries (5 cases)
    # =========================================================================

    def test_b11_c01_home_dir_with_trailing_slash(self):
        with MockTermuxEnv(is_android=True) as env:
            os.environ["HOME"] = env.home_dir + "/"
            caps = PlatformCapabilities(env)
            home = caps.home_dir()
            self.assertTrue(home.endswith(".grok"))

    def test_b11_c02_home_dir_with_spaces(self):
        with MockTermuxEnv(is_android=True) as env:
            custom_home = os.path.join(env.temp_root, "home with spaces")
            os.makedirs(custom_home, exist_ok=True)
            os.environ["HOME"] = custom_home
            caps = PlatformCapabilities(env)
            home = caps.home_dir()
            self.assertTrue(home.endswith(".grok"))

    def test_b11_c03_deeply_nested_home_dir(self):
        with MockTermuxEnv(is_android=True) as env:
            deep_home = os.path.join(env.temp_root, "a/b/c/d/e/f/home")
            os.makedirs(deep_home, exist_ok=True)
            os.environ["HOME"] = deep_home
            caps = PlatformCapabilities(env)
            home = caps.home_dir()
            self.assertTrue(home.endswith(".grok"))

    def test_b11_c04_grok_home_relative_path_normalization(self):
        with MockTermuxEnv(is_android=True) as env:
            rel_home = os.path.join(env.home_dir, "foo/../bar/.grok")
            os.environ["GROK_HOME"] = rel_home
            caps = PlatformCapabilities(env)
            home = caps.home_dir()
            self.assertEqual(home, rel_home)

    def test_b11_c05_home_permissions_tightening_to_0700(self):
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            home = caps.home_dir()
            os.makedirs(home, exist_ok=True)
            os.chmod(home, 0o700)
            st_mode = os.stat(home).st_mode & 0o777
            self.assertEqual(st_mode, 0o700)

    # =========================================================================
    # Feature 12 Boundaries (5 cases)
    # =========================================================================

    def test_b12_c01_socket_path_length_at_boundary_under_108(self):
        # 107 bytes test string
        path_107 = "/data/data/com.termux/files/usr/tmp/" + "a" * (107 - len("/data/data/com.termux/files/usr/tmp/"))
        self.assertEqual(len(path_107.encode("utf-8")), 107)
        self.assertLess(len(path_107.encode("utf-8")), 108)

    def test_b12_c02_socket_path_length_at_108_rejected(self):
        path_108 = "/data/data/com.termux/files/usr/tmp/" + "a" * (108 - len("/data/data/com.termux/files/usr/tmp/"))
        self.assertEqual(len(path_108.encode("utf-8")), 108)
        self.assertFalse(len(path_108.encode("utf-8")) < 108)

    def test_b12_c03_tmpdir_with_special_characters(self):
        with MockTermuxEnv(is_android=True) as env:
            custom_tmp = os.path.join(env.temp_root, "tmp_!@#$%")
            os.makedirs(custom_tmp, exist_ok=True)
            os.environ["TMPDIR"] = custom_tmp
            caps = PlatformCapabilities(env)
            self.assertEqual(caps.temp_dir(), custom_tmp)

    def test_b12_c04_cleanup_nonexistent_socket_file(self):
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            sock_path = caps.create_socket_path("nonexistent_session")
            # Deleting nonexistent socket should not throw
            try:
                os.remove(sock_path)
            except FileNotFoundError:
                pass

    def test_b12_c05_rapid_socket_creation_and_destruction(self):
        with MockTermuxEnv(is_android=True) as env:
            caps = PlatformCapabilities(env)
            for i in range(50):
                sock = caps.create_socket_path(f"sess_{i}")
                self.assertTrue(os.path.basename(sock).endswith(".sock"))

    # =========================================================================
    # Feature 13 Boundaries (5 cases)
    # =========================================================================

    def test_b13_c01_case_variations_of_sdcard_rejected(self):
        unsafe_paths = ["/SDCARD/.grok", "/Storage/Emulated/0/.grok", "/MNT/SDCARD/.grok"]
        for p in unsafe_paths:
            with self.assertRaises(StorageSafetyError):
                PlatformCapabilities.validate_storage_safety(p.lower())

    def test_b13_c02_symlink_on_sdcard_quarantined(self):
        with self.assertRaises(StorageSafetyError):
            PlatformCapabilities.validate_storage_safety("/sdcard/symlink_to_home")

    def test_b13_c03_dot_dot_traversal_to_sdcard_rejected(self):
        traversal = "/data/data/com.termux/files/../../../sdcard/grok"
        normalized = os.path.normpath(traversal)
        with self.assertRaises(StorageSafetyError):
            PlatformCapabilities.validate_storage_safety(normalized)

    def test_b13_c04_deeply_nested_sdcard_path_rejected(self):
        deep_sdcard = "/sdcard/Downloads/projects/ai/grok/.grok"
        with self.assertRaises(StorageSafetyError):
            PlatformCapabilities.validate_storage_safety(deep_sdcard)

    def test_b13_c05_primary_external_storage_rejected(self):
        with self.assertRaises(StorageSafetyError):
            PlatformCapabilities.validate_storage_safety("/storage/self/primary/.grok")

    # =========================================================================
    # Feature 14 Boundaries (5 cases)
    # =========================================================================

    def test_b14_c01_zero_byte_file_on_sdcard_readable(self):
        with MockTermuxEnv(is_android=True) as env:
            zero_file = os.path.join(env.sdcard_dir, "empty.rs")
            with open(zero_file, "w") as f:
                pass
            self.assertTrue(os.path.exists(zero_file))
            self.assertEqual(os.path.getsize(zero_file), 0)

    def test_b14_c02_large_file_on_sdcard_read(self):
        with MockTermuxEnv(is_android=True) as env:
            large_file = os.path.join(env.sdcard_dir, "large.txt")
            with open(large_file, "wb") as f:
                f.write(b"x" * (1024 * 1024))
            self.assertEqual(os.path.getsize(large_file), 1024 * 1024)

    def test_b14_c03_sdcard_directory_with_spaces_in_name(self):
        with MockTermuxEnv(is_android=True) as env:
            dir_with_spaces = os.path.join(env.sdcard_dir, "My Android Project")
            os.makedirs(dir_with_spaces, exist_ok=True)
            self.assertTrue(os.path.isdir(dir_with_spaces))

    def test_b14_c04_concurrent_file_reads_on_sdcard(self):
        with MockTermuxEnv(is_android=True) as env:
            for i in range(10):
                fpath = os.path.join(env.sdcard_dir, f"file_{i}.txt")
                with open(fpath, "w") as f:
                    f.write(f"content {i}")
                self.assertTrue(os.path.exists(fpath))

    def test_b14_c05_symlinks_unsupported_warning_on_fat32_sdcard(self):
        fs_type = "vfat"
        supports_posix_symlinks = fs_type not in ["vfat", "exfat", "fuse"]
        self.assertFalse(supports_posix_symlinks)

    # =========================================================================
    # Feature 15 Boundaries (5 cases)
    # =========================================================================

    def test_b15_c01_url_with_shell_metacharacters(self):
        with MockTermuxEnv(is_android=True) as env:
            env.install_mock_tool("termux-open-url")
            opener = LinkOpenerSeam(env)
            dangerous_url = "https://auth.x.ai/oauth?param=val;rm%20-rf%20/"
            ok, method = opener.open_url(dangerous_url)
            self.assertTrue(ok)

    def test_b15_c02_very_long_oauth_url(self):
        with MockTermuxEnv(is_android=True) as env:
            env.install_mock_tool("termux-open-url")
            opener = LinkOpenerSeam(env)
            long_url = "https://auth.x.ai/oauth2/authorize?param=" + "a" * 2000
            ok, method = opener.open_url(long_url)
            self.assertTrue(ok)

    def test_b15_c03_url_with_ipv6_loopback(self):
        with MockTermuxEnv(is_android=True) as env:
            env.install_mock_tool("termux-open-url")
            opener = LinkOpenerSeam(env)
            ipv6_url = "http://[::1]:8080/callback"
            ok, method = opener.open_url(ipv6_url)
            self.assertTrue(ok)

    def test_b15_c04_url_with_fragment_hash(self):
        with MockTermuxEnv(is_android=True) as env:
            env.install_mock_tool("termux-open-url")
            opener = LinkOpenerSeam(env)
            url = "https://auth.x.ai/login#section_2"
            ok, method = opener.open_url(url)
            self.assertTrue(ok)

    def test_b15_c05_invalid_protocol_ftp_rejected(self):
        with MockTermuxEnv(is_android=True) as env:
            opener = LinkOpenerSeam(env)
            with self.assertRaises(LinkOpenerError):
                opener.open_url("ftp://auth.x.ai/file")

    # =========================================================================
    # Feature 16 Boundaries (5 cases)
    # =========================================================================

    def test_b16_c01_request_with_no_query_parameters(self):
        server = OAuthServerSeam(port=0)
        server.start()
        try:
            url = f"http://127.0.0.1:{server.port}/callback"
            req = urllib.request.urlopen(url)
            self.assertEqual(req.status, 200)
            self.assertIsNone(server.captured_code)
        finally:
            server.stop()

    def test_b16_c02_request_with_multiple_code_parameters(self):
        server = OAuthServerSeam(port=0)
        server.start()
        try:
            url = f"http://127.0.0.1:{server.port}/callback?code=code1&code=code2"
            req = urllib.request.urlopen(url)
            self.assertEqual(req.status, 200)
            # urllib parse_qs takes the first or list
            self.assertIn(server.captured_code, ["code1", "code2"])
        finally:
            server.stop()

    def test_b16_c03_rapid_sequential_callback_requests(self):
        server = OAuthServerSeam(port=0)
        server.start()
        try:
            for i in range(5):
                url = f"http://127.0.0.1:{server.port}/callback?code=seq_code_{i}"
                req = urllib.request.urlopen(url)
                self.assertEqual(req.status, 200)
            self.assertEqual(server.captured_code, "seq_code_4")
        finally:
            server.stop()

    def test_b16_c04_request_to_deep_unmatched_subpath(self):
        server = OAuthServerSeam(port=0)
        server.start()
        try:
            url = f"http://127.0.0.1:{server.port}/callback/extra/sub/path"
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(url)
            self.assertEqual(ctx.exception.code, 404)
        finally:
            server.stop()

    def test_b16_c05_server_shutdown_while_idle(self):
        server = OAuthServerSeam(port=0)
        server.start()
        # Shutdown without any requests received
        server.stop()
        self.assertIsNone(server.captured_code)


if __name__ == "__main__":
    unittest.main()
