use std::fs;
use std::os::unix::fs::symlink;
use tempfile::tempdir;
use xai_grok_config::{
    validate_storage_safety, MockEnv, PlatformCapabilities, PlatformKind, SandboxKind,
};

#[test]
fn test_m4_truthful_sandbox_reporting_termux_matrix() {
    // 1. Standard Termux environment
    let env_termux = MockEnv::builder()
        .os_kind(PlatformKind::AndroidTermux)
        .var("PREFIX", "/data/data/com.termux/files/usr")
        .var("HOME", "/data/data/com.termux/files/home")
        .build();
    let caps = PlatformCapabilities::from_env(&env_termux);
    assert_eq!(caps.sandbox_kind(), SandboxKind::PolicyOnly);
    assert_eq!(caps.sandbox_kind().as_str(), "policy-only");

    // 2. Simulated Root User in Termux
    let env_root = MockEnv::builder()
        .os_kind(PlatformKind::AndroidTermux)
        .var("PREFIX", "/data/data/com.termux/files/usr")
        .var("HOME", "/data/data/com.termux/files/home")
        .var("USER", "root")
        .var("UID", "0")
        .build();
    let caps_root = PlatformCapabilities::from_env(&env_root);
    assert_eq!(caps_root.sandbox_kind(), SandboxKind::PolicyOnly);

    // 3. Simulated PRoot Environment in Termux
    let env_proot = MockEnv::builder()
        .os_kind(PlatformKind::AndroidTermux)
        .var("PREFIX", "/data/data/com.termux/files/usr")
        .var("PROOT_TMP_DIR", "/tmp")
        .var("PROOT_LOADER", "/data/data/com.termux/files/usr/bin/proot")
        .build();
    let caps_proot = PlatformCapabilities::from_env(&env_proot);
    assert_eq!(caps_proot.sandbox_kind(), SandboxKind::PolicyOnly);

    // 4. Unsupported Android (outside Termux)
    let env_unsupported = MockEnv::builder()
        .os_kind(PlatformKind::UnsupportedAndroid)
        .build();
    let caps_unsupported = PlatformCapabilities::from_env(&env_unsupported);
    assert_eq!(caps_unsupported.sandbox_kind(), SandboxKind::PolicyOnly);

    // 5. Desktop Linux (Landlock kernel-enforced)
    let env_linux = MockEnv::builder()
        .os_kind(PlatformKind::DesktopLinux)
        .build();
    let caps_linux = PlatformCapabilities::from_env(&env_linux);
    assert_eq!(caps_linux.sandbox_kind(), SandboxKind::KernelEnforced);

    // 6. macOS (Seatbelt kernel-enforced)
    let env_macos = MockEnv::builder()
        .os_kind(PlatformKind::MacOS)
        .build();
    let caps_macos = PlatformCapabilities::from_env(&env_macos);
    assert_eq!(caps_macos.sandbox_kind(), SandboxKind::KernelEnforced);

    // 7. Windows (Disabled)
    let env_windows = MockEnv::builder()
        .os_kind(PlatformKind::Windows)
        .build();
    let caps_windows = PlatformCapabilities::from_env(&env_windows);
    assert_eq!(caps_windows.sandbox_kind(), SandboxKind::Disabled);
}

#[test]
fn test_m4_adversarial_path_traversal_quarantine_depth() {
    let temp = tempdir().unwrap();
    let fake_sdcard = temp.path().join("sdcard");
    fs::create_dir_all(&fake_sdcard).unwrap();

    let safe_app_dir = temp.path().join("data_data_com_termux_files_home");
    fs::create_dir_all(&safe_app_dir).unwrap();

    // 1. Direct symlink to sdcard
    let direct_link = safe_app_dir.join("link_to_sdcard");
    symlink(&fake_sdcard, &direct_link).unwrap();
    assert!(validate_storage_safety(&direct_link).is_err());

    // 2. Nested symlink (chain of 5 symlinks)
    let mut current = direct_link;
    for i in 1..=5 {
        let next_link = safe_app_dir.join(format!("nested_link_{i}"));
        symlink(&current, &next_link).unwrap();
        assert!(validate_storage_safety(&next_link).is_err());
        current = next_link;
    }

    // 3. Symlink pointing to child of sdcard that does not exist yet
    let future_child_link = safe_app_dir.join("link_to_future_sdcard_child");
    symlink(fake_sdcard.join("future_dir").join("keys"), &future_child_link).unwrap();
    assert!(validate_storage_safety(&future_child_link).is_err());
}

#[test]
fn test_m4_adversarial_socket_length_boundaries() {
    let env = MockEnv::builder()
        .os_kind(PlatformKind::AndroidTermux)
        .var("PREFIX", "/data/data/com.termux/files/usr")
        .var("TMPDIR", "/data/data/com.termux/files/usr/tmp")
        .build();
    let caps = PlatformCapabilities::from_env(&env);

    // 1. Normal session ID
    let sock1 = caps.create_socket_path("normal_session_123").unwrap();
    assert!(sock1.to_str().unwrap().len() < 108);
    assert!(sock1.to_str().unwrap().ends_with(".sock"));

    // 2. 100k length session ID
    let huge_id = "x".repeat(100_000);
    let sock2 = caps.create_socket_path(&huge_id).unwrap();
    assert!(sock2.to_str().unwrap().len() < 108);

    // 3. Multibyte UTF-8 session ID
    let utf8_id = "🚀測試_안녕하세요_مرحبا_12345";
    let sock3 = caps.create_socket_path(utf8_id).unwrap();
    assert!(sock3.to_str().unwrap().len() < 108);

    // 4. Excessive TMPDIR prefix causing socket path to exceed 108 bytes
    let long_tmp = format!("/tmp/{}", "a".repeat(100));
    let env_long = MockEnv::builder()
        .os_kind(PlatformKind::AndroidTermux)
        .var("PREFIX", "/data/data/com.termux/files/usr")
        .var("TMPDIR", &long_tmp)
        .build();
    let caps_long = PlatformCapabilities::from_env(&env_long);
    let res = caps_long.create_socket_path("session_test");
    assert!(res.is_err());
}
