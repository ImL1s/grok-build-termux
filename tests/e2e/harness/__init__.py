"""Harness package for grok-build-termux E2E tests."""
from .termux_sim import (
    MockTermuxEnv,
    PlatformCapabilities,
    ClipboardSeam,
    LinkOpenerSeam,
    ToolResolverSeam,
    OAuthServerSeam,
    DoctorDiagnosticsSeam,
    UpdateManagerSeam,
    SandboxKind,
    StorageSafetyError,
    PlatformError,
    ClipboardError,
    LinkOpenerError,
    ToolResolutionError,
)

__all__ = [
    "MockTermuxEnv",
    "PlatformCapabilities",
    "ClipboardSeam",
    "LinkOpenerSeam",
    "ToolResolverSeam",
    "OAuthServerSeam",
    "DoctorDiagnosticsSeam",
    "UpdateManagerSeam",
    "SandboxKind",
    "StorageSafetyError",
    "PlatformError",
    "ClipboardError",
    "LinkOpenerError",
    "ToolResolutionError",
]
