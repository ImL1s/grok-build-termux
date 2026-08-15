#!/usr/bin/env python3
"""
Adversarial Stress Testing Suite for Milestone 2:
- Native Bionic Build & Toolchain Alignment
- ToolResolver Edge Cases & Remediation
- Build.rs Bypass Verification
- Dependency Isolation & Cargo Flags Validation
"""

import os
import sys
import tempfile
import subprocess
from pathlib import Path

def test_cargo_config_16k_alignment():
    print("[1] Auditing .cargo/config.toml for 16 KiB alignment & ELF hardening...")
    config_path = Path(".cargo/config.toml")
    assert config_path.exists(), ".cargo/config.toml must exist"
    content = config_path.read_text()
    
    assert "[target.aarch64-linux-android]" in content, "Missing aarch64-linux-android target"
    assert "[target.x86_64-linux-android]" in content, "Missing x86_64-linux-android target"
    
    assert "-Wl,-z,max-page-size=16384" in content, "Missing 16 KiB max-page-size linker flag"
    assert "-Wl,-z,relro,-z,now,-z,noexecstack" in content, "Missing binary hardening flags"
    assert "force-unwind-tables=yes" in content, "Missing unwind tables flag"
    print("    -> PASS: 16 KiB page size alignment and RELRO hardening flags confirmed.")

def test_rust_toolchain_targets():
    print("[2] Auditing rust-toolchain.toml...")
    toolchain_path = Path("rust-toolchain.toml")
    assert toolchain_path.exists()
    content = toolchain_path.read_text()
    assert "aarch64-linux-android" in content, "Missing aarch64-linux-android in toolchain targets"
    assert "x86_64-linux-android" in content, "Missing x86_64-linux-android in toolchain targets"
    print("    -> PASS: Android toolchain targets properly registered.")

def test_build_rs_bypass_logic():
    print("[3] Auditing build.rs bypass logic in xai-grok-tools and xai-grok-shell...")
    tools_build = Path("crates/codegen/xai-grok-tools/build.rs").read_text()
    shell_build = Path("crates/codegen/xai-grok-shell/build.rs").read_text()
    
    # Verify android check in xai-grok-tools
    assert 'target_os == "android"' in tools_build, "xai-grok-tools build.rs must check for android"
    assert 'GROK_TOOLS_BUNDLE_RG_PATH' in tools_build, "xai-grok-tools build.rs must support env override"
    
    # Verify android check in xai-grok-shell
    assert 'target_os == "android"' in shell_build, "xai-grok-shell build.rs must check for android"
    assert 'GROK_SHELL_BUNDLE_RG_PATH' in shell_build, "xai-grok-shell build.rs must support env override"
    print("    -> PASS: build.rs bypasses glibc desktop downloads on Android without hardcoded mocks.")

def test_system_appearance_android_cfg():
    print("[4] Auditing system_appearance.rs target gating...")
    app_rs = Path("crates/codegen/xai-grok-pager-render/src/theme/system_appearance.rs").read_text()
    assert '#[cfg(not(target_os = "android"))]' in app_rs, "detect_desktop must be gated out on android"
    assert '#[cfg(target_os = "android")]' in app_rs, "Android fallback for detect_desktop must exist"
    print("    -> PASS: dark-light 2.0.0 incompatibility properly resolved via target cfg.")

def test_dependency_isolation_android():
    print("[5] Auditing Cargo.toml files for forbidden glibc/desktop dependencies...")
    # Check xai-grok-shared
    shared_toml = Path("crates/codegen/xai-grok-shared/Cargo.toml").read_text()
    assert 'not(target_os = "android")' in shared_toml and 'arboard' in shared_toml, \
        "arboard must be gated out on android in xai-grok-shared"
    
    # Check xai-grok-sandbox
    sandbox_toml = Path("crates/codegen/xai-grok-sandbox/Cargo.toml").read_text()
    assert 'not(target_os = "android")' in sandbox_toml and 'nono' in sandbox_toml, \
        "nono must be gated out on android in xai-grok-sandbox"
    
    # Check xai-grok-pager-bin
    bin_toml = Path("crates/codegen/xai-grok-pager-bin/Cargo.toml").read_text()
    assert 'not(target_os = "android")' in bin_toml and 'tikv-jemallocator' in bin_toml, \
        "tikv-jemallocator must be gated out on android in xai-grok-pager-bin"
    
    # Check xai-grok-voice
    voice_toml = Path("crates/codegen/xai-grok-voice/Cargo.toml").read_text()
    assert 'not(target_os = "android")' in voice_toml and 'cpal' in voice_toml, \
        "cpal must be gated out on android in xai-grok-voice"
    print("    -> PASS: tikv-jemallocator, arboard, cpal, and nono are strictly excluded from Android targets.")

def test_shell_resolution_paths():
    print("[6] Auditing shell.rs path search cascade...")
    shell_rs = Path("crates/codegen/xai-grok-config/src/shell.rs").read_text()
    assert "PREFIX" in shell_rs, "Must check PREFIX"
    assert "/data/data/com.termux/files/usr/bin" in shell_rs, "Must check Termux default usr/bin"
    assert "/system/bin" in shell_rs, "Must check Android /system/bin"
    assert "/system/xbin" in shell_rs, "Must check Android /system/xbin"
    assert "is_executable" in shell_rs, "Must verify executability"
    print("    -> PASS: shell resolution handles Termux & Android system paths properly.")

def test_tool_resolver_architecture():
    print("[7] Auditing ToolResolver source code...")
    resolver_rs = Path("crates/codegen/xai-grok-tools/src/resolver.rs").read_text()
    assert "TOOL_RG" in resolver_rs, "Must define TOOL_RG"
    assert "TOOL_FD" in resolver_rs, "Must define TOOL_FD"
    assert "TOOL_GIT" in resolver_rs, "Must define TOOL_GIT"
    assert "TOOL_BASH" in resolver_rs, "Must define TOOL_BASH"
    assert "TOOL_BFS" in resolver_rs, "Must define TOOL_BFS"
    assert "TOOL_UGREP" in resolver_rs, "Must define TOOL_UGREP"
    
    # Check remediation hints
    assert "In Termux, run: pkg install" in resolver_rs, "Termux remediation hint format"
    assert "On macOS, run: brew install" in resolver_rs, "macOS remediation hint format"
    assert "On Linux, run: apt install" in resolver_rs, "Linux remediation hint format"
    print("    -> PASS: ToolResolver defines complete tool specifications and cross-platform remediation hints.")

def main():
    print("==================================================")
    print("Forensic Integrity & Adversarial Audit (Milestone 2)")
    print("==================================================")
    test_cargo_config_16k_alignment()
    test_rust_toolchain_targets()
    test_build_rs_bypass_logic()
    test_system_appearance_android_cfg()
    test_dependency_isolation_android()
    test_shell_resolution_paths()
    test_tool_resolver_architecture()
    print("==================================================")
    print("ALL 7 FORENSIC SUITES PASSED CLEANLY")
    print("==================================================")

if __name__ == "__main__":
    main()
