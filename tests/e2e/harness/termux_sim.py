"""
Termux & Android Platform Simulation Harness for grok-build-termux E2E Tests.

Provides opaque-box simulation of:
- Termux filesystem layouts ($PREFIX, $HOME, $TMPDIR, /sdcard)
- PlatformCapabilities interface contracts
- CLI tools resolution and mock execution
- OAuth browser handoff & loopback HTTP callbacks
- Termux:API and OSC 52 clipboard protocols
- Policy-only sandbox enforcement
- Diagnostics (grok doctor) and update isolation
"""

import os
import shutil
import tempfile
import json
import urllib.parse
import http.server
import threading
import time
from typing import Dict, List, Optional, Tuple, Any


class SandboxKind:
    KERNEL_ENFORCED = "kernel-enforced"
    POLICY_ONLY = "policy-only"
    NONE = "none"


class StorageSafetyError(Exception):
    pass


class PlatformError(Exception):
    pass


class ClipboardError(Exception):
    pass


class LinkOpenerError(Exception):
    pass


class ToolResolutionError(Exception):
    pass


class MockTermuxEnv:
    """Sets up an isolated directory hierarchy mimicking Termux on Android."""

    def __init__(self, custom_prefix: Optional[str] = None, is_android: bool = True):
        self.temp_root = tempfile.mkdtemp(prefix="termux_e2e_")
        self.is_android = is_android

        # Standard Termux paths within the isolated temp root
        if custom_prefix:
            if custom_prefix.startswith("/"):
                self.prefix_dir = os.path.join(self.temp_root, custom_prefix.lstrip("/"))
            else:
                self.prefix_dir = os.path.join(self.temp_root, custom_prefix)
        else:
            self.prefix_dir = os.path.join(self.temp_root, "data/data/com.termux/files/usr")

        self.home_dir = os.path.join(self.temp_root, "data/data/com.termux/files/home")
        self.tmp_dir = os.path.join(self.prefix_dir, "tmp")
        self.etc_dir = os.path.join(self.prefix_dir, "etc/grok")
        self.bin_dir = os.path.join(self.prefix_dir, "bin")

        # Android shared storage simulation
        self.sdcard_dir = os.path.join(self.temp_root, "sdcard")
        self.emulated_storage_dir = os.path.join(self.temp_root, "storage/emulated/0")

        # Create base directories
        for d in [
            self.prefix_dir,
            self.home_dir,
            self.tmp_dir,
            self.etc_dir,
            self.bin_dir,
            self.sdcard_dir,
            self.emulated_storage_dir,
        ]:
            os.makedirs(d, exist_ok=True)

        self.mock_tools: Dict[str, str] = {}
        self.env_backup: Dict[str, Optional[str]] = {}

    def install_mock_tool(self, name: str, exit_code: int = 0, stdout: str = "", stderr: str = ""):
        """Installs a mock executable tool in $PREFIX/bin."""
        tool_path = os.path.join(self.bin_dir, name)
        with open(tool_path, "w") as f:
            f.write(f"#!/bin/sh\n")
            if stdout:
                f.write(f'printf "%s\\n" "{stdout}"\n')
            if stderr:
                f.write(f'printf "%s\\n" "{stderr}" >&2\n')
            f.write(f"exit {exit_code}\n")
        os.chmod(tool_path, 0o755)
        self.mock_tools[name] = tool_path
        return tool_path

    def __enter__(self):
        self.old_env = os.environ.copy()
        os.environ["PREFIX"] = self.prefix_dir if self.is_android else ""
        os.environ["HOME"] = self.home_dir
        os.environ["TMPDIR"] = self.tmp_dir
        os.environ["PATH"] = self.bin_dir if self.is_android else os.environ.get("PATH", "")
        os.environ["TERMUX_VERSION"] = "0.118.1" if self.is_android else ""
        os.environ.pop("GROK_HOME", None)
        os.environ.pop("GROK_INSTALL_MODE", None)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        os.environ.clear()
        os.environ.update(self.old_env)
        shutil.rmtree(self.temp_root, ignore_errors=True)


class PlatformCapabilities:
    """
    Opaque-box implementation of PlatformCapabilities interface contract (PROJECT.md).
    """

    def __init__(self, env: MockTermuxEnv):
        self.env = env

    def is_android_termux(self) -> bool:
        return self.env.is_android and bool(os.environ.get("PREFIX"))

    def prefix_dir(self) -> str:
        prefix = os.environ.get("PREFIX")
        if not prefix and self.env.is_android:
            raise PlatformError(
                "Environment variable PREFIX is not set. Grok Build requires a valid Termux environment."
            )
        return prefix or "/usr"

    def system_config_dir(self) -> Optional[str]:
        if self.is_android_termux():
            prefix = os.environ.get("PREFIX")
            return os.path.join(prefix, "etc/grok") if prefix else None
        return "/etc/grok"

    def home_dir(self) -> str:
        home = os.environ.get("GROK_HOME")
        if home:
            self.validate_storage_safety(home)
            return home
        user_home = os.environ.get("HOME")
        if not user_home:
            raise PlatformError("HOME environment variable is not set")
        grok_home = os.path.join(user_home, ".grok")
        self.validate_storage_safety(grok_home)
        return grok_home

    def temp_dir(self) -> str:
        tmp = os.environ.get("TMPDIR")
        if tmp:
            return tmp
        if self.is_android_termux():
            prefix = os.environ.get("PREFIX")
            if prefix:
                return os.path.join(prefix, "tmp")
        return "/tmp"

    def create_socket_path(self, session_id: str) -> str:
        """Creates Unix socket path ensuring length < 108 bytes on Termux."""
        tmp = self.temp_dir()
        short_hash = f"{abs(hash(session_id)) % 1000000:06d}"
        sock_name = f"grok-{short_hash}.sock"
        sock_path = os.path.join(tmp, sock_name)
        
        # Check standard Termux socket length (/data/data/com.termux/files/usr/tmp/grok-XXXXXX.sock)
        termux_simulated_path = f"/data/data/com.termux/files/usr/tmp/{sock_name}"
        if len(termux_simulated_path.encode("utf-8")) >= 108:
            raise PlatformError(f"Socket path exceeds 108 bytes: {termux_simulated_path}")
        return sock_path

    def sandbox_kind(self) -> str:
        if self.is_android_termux():
            return SandboxKind.POLICY_ONLY
        return SandboxKind.KERNEL_ENFORCED

    @staticmethod
    def validate_storage_safety(path: str) -> None:
        """
        Refuses /sdcard, /storage/emulated/0, /mnt/sdcard for private credentials.
        """
        normalized = os.path.normpath(str(path)).lower().replace('\\', '/')
        unsafe_prefixes = [
            "/sdcard",
            "/storage",
            "/mnt/sdcard",
            "/mnt/media_rw",
            "/data/sdcard",
            "/data/media",
            "sdcard",
            "storage",
            "mnt/sdcard",
            "mnt/media_rw",
            "data/sdcard",
            "data/media",
        ]
        for unsafe in unsafe_prefixes:
            if (
                normalized == unsafe
                or normalized.startswith(f"{unsafe}/")
                or (unsafe.startswith("/") and normalized.startswith(unsafe))
                or f"/{unsafe.lstrip('/')}" in normalized
            ):
                raise StorageSafetyError(
                    f"GROK_HOME cannot reside on Android shared storage ({path}). "
                    f"Owner-only permissions (0700) are required for credentials."
                )


class ClipboardSeam:
    """Opaque-box implementation of Clipboard interface contract (PROJECT.md)."""

    def __init__(self, env: MockTermuxEnv, allow_termux_api: bool = True):
        self.env = env
        self.allow_termux_api = allow_termux_api
        self.osc52_output: List[str] = []

    def get_text(self) -> Optional[str]:
        if not self.env.is_android:
            return "desktop_clipboard_text"
        if self.allow_termux_api and "termux-clipboard-get" in self.env.mock_tools:
            # Execute mock termux-clipboard-get
            return "android_termux_api_clipboard_text"
        # Graceful fallback without crash
        return None

    def set_text(self, text: str) -> Tuple[bool, str]:
        """Returns (success, method_used)."""
        if not self.env.is_android:
            return True, "desktop_clipboard"
        if self.allow_termux_api and "termux-clipboard-set" in self.env.mock_tools:
            return True, "termux_api"
        # Fallback to OSC 52
        import base64
        b64_val = base64.b64encode(text.encode("utf-8")).decode("utf-8")
        osc52_seq = f"\x1b]52;c;{b64_val}\x07"
        self.osc52_output.append(osc52_seq)
        return True, "osc52"

    def get_image(self) -> Optional[bytes]:
        """Image clipboard is unsupported on Android/Termux without desktop display server."""
        if self.env.is_android:
            return None
        return b"image_bytes"


class LinkOpenerSeam:
    """Opaque-box implementation of LinkOpener interface contract (PROJECT.md)."""

    def __init__(self, env: MockTermuxEnv, allow_termux_open: bool = True):
        self.env = env
        self.allow_termux_open = allow_termux_open
        self.opened_urls: List[str] = []

    def open_url(self, url: str) -> Tuple[bool, str]:
        """Returns (dispatched, method_used)."""
        if not url.startswith("http://") and not url.startswith("https://"):
            raise LinkOpenerError(f"Invalid URL scheme: {url}")

        if self.env.is_android:
            if self.allow_termux_open and "termux-open-url" in self.env.mock_tools:
                self.opened_urls.append(url)
                return True, "termux-open-url"
            return False, "manual_print"
        else:
            self.opened_urls.append(url)
            return True, "desktop_browser"


class ToolResolverSeam:
    """Opaque-box implementation of ToolResolver contract (PROJECT.md)."""

    def __init__(self, env: MockTermuxEnv):
        self.env = env

    def resolve_tool(self, name: str) -> str:
        # 1. Check PATH
        path_env = os.environ.get("PATH")
        if path_env:
            sh_path = shutil.which(name, path=path_env)
            if sh_path:
                return sh_path
        # 2. Check $PREFIX/bin mock tools
        if name in self.env.mock_tools:
            return self.env.mock_tools[name]
        # 3. Check fallback bin_dir
        sh_path = shutil.which(name, path=self.env.bin_dir)
        if sh_path:
            return sh_path
        raise ToolResolutionError(
            f"{name} not found in PATH. In Termux, run: pkg install {name}"
        )


class OAuthServerSeam:
    """Loopback callback HTTP server simulating OAuth authorization code flow."""

    def __init__(self, port: int = 0):
        self.captured_code: Optional[str] = None
        self.captured_state: Optional[str] = None
        self.server: Optional[http.server.HTTPServer] = None
        self.thread: Optional[threading.Thread] = None
        self.port = port

    def start(self):
        outer = self

        class CallbackHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path == "/callback":
                    params = urllib.parse.parse_qs(parsed.query)
                    outer.captured_code = params.get("code", [None])[0]
                    outer.captured_state = params.get("state", [None])[0]
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    self.wfile.write(b"<html><body><h1>Login Successful</h1><p>You can close this tab.</p></body></html>")
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, format, *args):
                pass  # Silence stderr

        self.server = http.server.HTTPServer(("127.0.0.1", self.port), CallbackHandler)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()

    @staticmethod
    def parse_manual_input(user_input: str) -> Tuple[Optional[str], Optional[str]]:
        """Parses manual user input (bare code or full callback URL)."""
        user_input = user_input.strip()
        if not user_input:
            return None, None
        if "code=" in user_input:
            parsed = urllib.parse.urlparse(user_input)
            query = urllib.parse.parse_qs(parsed.query)
            return query.get("code", [None])[0], query.get("state", [None])[0]
        return user_input, None


class DoctorDiagnosticsSeam:
    """Opaque-box implementation of `grok doctor` for Android/Termux."""

    def __init__(self, capabilities: PlatformCapabilities, resolver: ToolResolverSeam):
        self.caps = capabilities
        self.resolver = resolver

    def run_diagnostics(self) -> Dict[str, Any]:
        results: Dict[str, Any] = {
            "platform": "Android/Termux" if self.caps.is_android_termux() else "Desktop Linux/macOS",
            "prefix": None,
            "prefix_valid": False,
            "home": None,
            "storage_safe": False,
            "sandbox_kind": self.caps.sandbox_kind(),
            "tools": {},
            "issues": [],
            "remediations": [],
        }

        try:
            pfx = self.caps.prefix_dir()
            results["prefix"] = pfx
            results["prefix_valid"] = os.path.isdir(pfx)
        except Exception as e:
            results["issues"].append(str(e))
            results["remediations"].append("Set PREFIX environment variable properly in Termux.")

        try:
            home = self.caps.home_dir()
            results["home"] = home
            results["storage_safe"] = True
        except StorageSafetyError as e:
            results["issues"].append(str(e))
            results["remediations"].append("Do not set GROK_HOME to /sdcard or shared storage.")

        # Check required native tools
        required_tools = ["rg", "fd", "git", "bash"]
        for tool in required_tools:
            try:
                resolved = self.resolver.resolve_tool(tool)
                results["tools"][tool] = {"installed": True, "path": resolved}
            except ToolResolutionError as e:
                results["tools"][tool] = {"installed": False, "error": str(e)}
                results["issues"].append(f"Missing required tool: {tool}")
                results["remediations"].append(f"Run: pkg install {tool}")

        return results


class UpdateManagerSeam:
    """Opaque-box implementation of install mode detection and updater isolation."""

    def __init__(self, install_mode: str = "package-managed"):
        self.install_mode = install_mode

    def check_update(self, current_version: str, remote_manifest: Dict[str, Any]) -> Dict[str, Any]:
        if self.install_mode == "package-managed":
            return {
                "action": "delegate_to_pkg",
                "message": "Grok Build was installed via Termux package manager. To update, run: pkg update && pkg upgrade grok-build",
                "can_auto_download": False,
            }
        else:
            # Standalone mode: only allow termux-aarch64 artifacts
            target_asset = remote_manifest.get("assets", {}).get("termux-aarch64")
            if not target_asset:
                return {
                    "action": "no_compatible_asset",
                    "message": "No compatible Termux aarch64 build found in release manifest.",
                    "can_auto_download": False,
                }
            return {
                "action": "download_and_apply",
                "asset_url": target_asset.get("url"),
                "can_auto_download": True,
            }
