//! Adversarial integration tests for ToolResolver (Milestone 2).

use std::fs;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use tempfile::tempdir;
use xai_grok_tools::resolver::{
    ToolRequirement, ToolResolutionError, ToolResolver, ToolSpec,
};

#[test]
fn test_adversarial_remediation_hints_by_name() {
    let rg_hint = ToolResolver::remediation_hint_for_name("rg");
    assert!(rg_hint.contains("ripgrep"));

    let fd_hint = ToolResolver::remediation_hint_for_name("fd");
    assert!(fd_hint.contains("fd"));

    let git_hint = ToolResolver::remediation_hint_for_name("git");
    assert!(rg_hint.contains("pkg install") || rg_hint.contains("brew install") || rg_hint.contains("apt install"));
    assert!(git_hint.contains("git"));

    let custom_hint = ToolResolver::remediation_hint_for_name("custom_pkg_123");
    assert!(custom_hint.contains("custom_pkg_123"));
}

#[test]
fn test_adversarial_missing_tool_fails_cleanly_with_structured_error() {
    let bad_name = "definitely_nonexistent_binary_xyz_999";
    let res = ToolResolver::resolve_tool(bad_name);
    assert!(res.is_err());
    let err = res.unwrap_err();
    match err {
        ToolResolutionError::MissingRequiredTool { name, remediation } => {
            assert_eq!(name, bad_name);
            assert!(remediation.contains(bad_name));
        }
        other => panic!("Unexpected error variant: {other:?}"),
    }
}

#[test]
fn test_adversarial_env_override_takes_top_precedence() {
    let dir = tempdir().unwrap();
    let fake_rg = dir.path().join("fake_rg");
    fs::write(&fake_rg, b"#!/bin/sh\necho fake rg\n").unwrap();
    #[cfg(unix)]
    fs::set_permissions(&fake_rg, fs::Permissions::from_mode(0o755)).unwrap();

    let custom_spec = ToolSpec {
        binary_name: "rg",
        termux_package: "ripgrep",
        debian_package: "ripgrep",
        brew_package: "ripgrep",
        requirement: ToolRequirement::Required,
        env_override: Some("TEST_CUSTOM_RG_BIN_OVERRIDE"),
    };

    unsafe {
        std::env::set_var("TEST_CUSTOM_RG_BIN_OVERRIDE", fake_rg.to_str().unwrap());
    }
    let resolved = ToolResolver::resolve(&custom_spec).unwrap();
    assert_eq!(resolved, fake_rg);
    unsafe {
        std::env::remove_var("TEST_CUSTOM_RG_BIN_OVERRIDE");
    }
}

#[test]
fn test_adversarial_invalid_env_override_falls_through() {
    let custom_spec = ToolSpec {
        binary_name: "sh",
        termux_package: "sh",
        debian_package: "sh",
        brew_package: "sh",
        requirement: ToolRequirement::Required,
        env_override: Some("TEST_INVALID_OVERRIDE_PATH_XYZ"),
    };

    unsafe {
        std::env::set_var("TEST_INVALID_OVERRIDE_PATH_XYZ", "/path/to/nonexistent/override/sh");
    }
    let resolved = ToolResolver::resolve(&custom_spec);
    unsafe {
        std::env::remove_var("TEST_INVALID_OVERRIDE_PATH_XYZ");
    }

    #[cfg(unix)]
    assert!(resolved.is_ok());
}

#[test]
fn test_adversarial_optional_tools_never_error() {
    let nonexistent_opt_spec = ToolSpec {
        binary_name: "nonexistent_optional_searcher",
        termux_package: "nonexistent_optional_searcher",
        debian_package: "nonexistent_optional_searcher",
        brew_package: "nonexistent_optional_searcher",
        requirement: ToolRequirement::Optional,
        env_override: None,
    };

    let opt_res = ToolResolver::resolve_optional(&nonexistent_opt_spec);
    assert_eq!(opt_res, None);
}
