use std::path::{Path, PathBuf};
use std::thread;
use tempfile::tempdir;
use xai_grok_config::{
    validate_storage_safety, MockEnv, PlatformCapabilities, PlatformError, PlatformKind,
    SandboxKind, StorageSafetyError,
};

#[test]
fn test_adversarial_unset_prefix_on_android() {
    let env = MockEnv::builder()
        .os(PlatformKind::AndroidTermux)
        .var("HOME", "/data/data/com.termux/files/home")
        .build();

    let caps = PlatformCapabilities::probe(&env);
    assert!(!caps.is_android_termux());
    assert!(caps.is_android());
    assert_eq!(caps.kind(), PlatformKind::UnsupportedAndroid);
    assert_eq!(caps.prefix_dir(), Err(PlatformError::MissingPrefix));
    assert_eq!(caps.system_config_dir(), None);
    assert_eq!(caps.sandbox_kind(), SandboxKind::PolicyOnly);
}

#[test]
fn test_adversarial_empty_string_prefix_on_android() {
    let env = MockEnv::builder()
        .os(PlatformKind::AndroidTermux)
        .var("PREFIX", "")
        .var("HOME", "/data/data/com.termux/files/home")
        .build();

    let caps = PlatformCapabilities::probe(&env);
    assert!(!caps.is_android_termux());
    assert!(caps.is_android());
    assert_eq!(caps.kind(), PlatformKind::UnsupportedAndroid);
    assert_eq!(caps.prefix_dir(), Err(PlatformError::MissingPrefix));
    assert_eq!(caps.system_config_dir(), None);
}

#[test]
fn test_adversarial_whitespace_prefix_on_android() {
    let whitespaces = ["   ", "\t", "\n", "\r\n", " \t \n "];
    for ws in whitespaces {
        let env = MockEnv::builder()
            .os(PlatformKind::AndroidTermux)
            .var("PREFIX", ws)
            .var("HOME", "/data/data/com.termux/files/home")
            .build();

        let caps = PlatformCapabilities::probe(&env);
        assert!(!caps.is_android_termux(), "Failed for whitespace string: {:?}", ws);
        assert!(caps.is_android());
        assert_eq!(caps.kind(), PlatformKind::UnsupportedAndroid);
        assert_eq!(caps.prefix_dir(), Err(PlatformError::MissingPrefix));
        assert_eq!(caps.system_config_dir(), None);
    }
}

#[test]
fn test_adversarial_custom_prefix_variations() {
    let custom_prefixes = [
        "/data/data/com.termux/files/usr",
        "/data/data/com.myterminal/files/usr",
        "/data/user/0/com.termux/files/usr",
        "/opt/termux/usr",
        "/custom/root/usr",
    ];

    for pfx in custom_prefixes {
        let env = MockEnv::builder()
            .os(PlatformKind::AndroidTermux)
            .var("PREFIX", pfx)
            .var("HOME", "/data/data/com.termux/files/home")
            .build();

        let caps = PlatformCapabilities::probe(&env);
        assert!(caps.is_android_termux());
        assert_eq!(caps.prefix_dir().unwrap(), Path::new(pfx));
        assert_eq!(
            caps.system_config_dir(),
            Some(PathBuf::from(format!("{pfx}/etc/grok")))
        );
        assert_eq!(caps.bin_dir().unwrap(), PathBuf::from(format!("{pfx}/bin")));
    }
}

#[test]
fn test_adversarial_trailing_slashes_in_prefix() {
    let env = MockEnv::builder()
        .os(PlatformKind::AndroidTermux)
        .var("PREFIX", "/data/data/com.termux/files/usr///")
        .var("HOME", "/data/data/com.termux/files/home")
        .build();

    let caps = PlatformCapabilities::probe(&env);
    assert!(caps.is_android_termux());
    assert_eq!(
        caps.prefix_dir().unwrap(),
        Path::new("/data/data/com.termux/files/usr///")
    );
    assert_eq!(
        caps.system_config_dir(),
        Some(PathBuf::from("/data/data/com.termux/files/usr///etc/grok"))
    );
}

#[test]
fn test_adversarial_storage_quarantine_all_variations() {
    let unsafe_paths = [
        // /sdcard variations
        "/sdcard",
        "/sdcard/",
        "/sdcard/.grok",
        "/sdcard/Download/grok",
        "/sdcard/Android/data",
        "/data/sdcard/grok",
        "/root/sdcard/test",
        // /storage/emulated/0 variations
        "/storage/emulated/0",
        "/storage/emulated/0/",
        "/storage/emulated/0/.grok",
        "/storage/emulated/0/Download",
        "/storage/emulated/10/.grok",
        "/storage/emulated/999/test",
        // /mnt/sdcard variations
        "/mnt/sdcard",
        "/mnt/sdcard/",
        "/mnt/sdcard/.grok",
        "/mnt/sdcard/sub/path",
        // /storage/self variations
        "/storage/self/primary",
        "/storage/self/primary/.grok",
        "/storage/self/0/.grok",
        // /mnt/media_rw variations
        "/mnt/media_rw",
        "/mnt/media_rw/sdcard0",
        "/mnt/media_rw/usb_disk",
        // /storage variations (OTG / SD cards)
        "/storage/1234-5678/.grok",
        "/storage/ABCD-EF01/Android",
        "/storage/extSdCard/grok",
    ];

    for path in unsafe_paths {
        let res = validate_storage_safety(Path::new(path));
        assert!(
            res.is_err(),
            "Expected unsafe path to be quarantined and rejected: {}",
            path
        );
        match res.unwrap_err() {
            StorageSafetyError::SharedStorageQuarantine { path: p, reason } => {
                assert_eq!(p, PathBuf::from(path));
                assert!(!reason.is_empty());
            }
        }
    }
}

#[test]
fn test_adversarial_safe_paths_allowed() {
    let safe_paths = [
        "/data/data/com.termux/files/home/.grok",
        "/data/data/com.termux/files/usr/etc/grok",
        "/data/data/com.custom.app/files/home/.grok",
        "/home/developer/.grok",
        "/Users/developer/.grok",
        "/var/lib/grok",
        "/etc/grok",
    ];

    for path in safe_paths {
        let res = validate_storage_safety(Path::new(path));
        assert!(
            res.is_ok(),
            "Expected safe path to be accepted without quarantine error: {}",
            path
        );
    }
}

#[test]
fn test_adversarial_dangling_symlink_vulnerability() {
    let tmp_dir = tempdir().expect("Failed to create temporary directory");
    let symlink_path = tmp_dir.path().join("dangling_link");

    #[cfg(unix)]
    {
        use std::os::unix::fs::symlink;
        // Symlink points to non-existent /sdcard/.grok
        symlink("/sdcard/.grok", &symlink_path).expect("Failed to create symlink");

        let res = validate_storage_safety(&symlink_path);
        assert!(
            res.is_err(),
            "Dangling symlink pointing to /sdcard/.grok must be quarantined"
        );
        match res.unwrap_err() {
            StorageSafetyError::SharedStorageQuarantine { path, reason } => {
                assert_eq!(path, symlink_path);
                assert!(!reason.is_empty());
            }
        }
    }
}

#[test]
fn test_adversarial_path_traversal_vulnerability() {
    // Path traversal attempting to reach shared storage
    let traversal_paths = [
        "/data/data/com.termux/files/home/../../../../sdcard/.grok",
        "/data/data/com.termux/files/home/../../../../storage/emulated/1/.grok",
        "/data/data/com.termux/files/home/../../../../storage/1234-5678/.grok",
        "/data/data/com.termux/files/home/././../../../../sdcard",
        "sdcard/.grok",
        "storage/emulated/0/.grok",
    ];

    for path in traversal_paths {
        let res = validate_storage_safety(Path::new(path));
        assert!(
            res.is_err(),
            "Expected traversal path '{}' to be quarantined, got {:?}",
            path,
            res
        );
    }
}

#[test]
fn test_adversarial_case_insensitivity_vulnerability() {
    let uppercase_paths = [
        "/SDCARD/.grok",
        "/Sdcard/.grok",
        "/STORAGE/EMULATED/0/.grok",
        "/Storage/Emulated/0/.grok",
        "/MNT/SDCARD/.grok",
        "/Mnt/Media_Rw/test",
        "SDCARD/.grok",
        "Storage/Emulated/0/.grok",
    ];

    for path in uppercase_paths {
        let res = validate_storage_safety(Path::new(path));
        assert!(
            res.is_err(),
            "Expected uppercase/case-variant path '{}' to be quarantined, got {:?}",
            path,
            res
        );
    }
}

#[test]
fn test_adversarial_ancestor_symlink_quarantine() {
    let tmp_dir = tempdir().expect("Failed to create temporary directory");
    let dir_symlink = tmp_dir.path().join("shared_storage_link");

    #[cfg(unix)]
    {
        use std::os::unix::fs::symlink;
        symlink("/sdcard", &dir_symlink).expect("Failed to create directory symlink");

        // Test non-existent child under symlinked directory
        let child_path = dir_symlink.join("my_app/credentials.json");
        let res = validate_storage_safety(&child_path);
        assert!(
            res.is_err(),
            "Path under symlinked ancestor to /sdcard must be quarantined, got {:?}",
            res
        );
    }
}

#[test]
fn test_adversarial_symlink_chain_quarantine() {
    let tmp_dir = tempdir().expect("Failed to create temporary directory");
    let link_a = tmp_dir.path().join("link_a");
    let link_b = tmp_dir.path().join("link_b");

    #[cfg(unix)]
    {
        use std::os::unix::fs::symlink;
        symlink("/storage/emulated/0/.grok", &link_a).expect("Failed to create link_a");
        symlink(&link_a, &link_b).expect("Failed to create link_b");

        let res = validate_storage_safety(&link_b);
        assert!(
            res.is_err(),
            "Symlink chain resolving to shared storage must be quarantined, got {:?}",
            res
        );
    }
}

#[test]
fn test_adversarial_mock_env_concurrency_stress() {
    let thread_count = 50;
    let iterations_per_thread = 100;
    let mut handles = Vec::with_capacity(thread_count);

    for t in 0..thread_count {
        let handle = thread::spawn(move || {
            for i in 0..iterations_per_thread {
                let is_termux = (t + i) % 2 == 0;
                let os_kind = if is_termux {
                    PlatformKind::AndroidTermux
                } else {
                    PlatformKind::DesktopLinux
                };
                let prefix_val = format!("/data/data/com.termux.thread{t}/files/usr");
                let home_val = format!("/data/data/com.termux.thread{t}/files/home");

                let mut builder = MockEnv::builder().os(os_kind);
                if is_termux {
                    builder = builder.var("PREFIX", &prefix_val);
                }
                builder = builder.var("HOME", &home_val);
                let env = builder.build();

                let caps = PlatformCapabilities::probe(&env);

                if is_termux {
                    assert!(caps.is_android_termux());
                    assert_eq!(caps.prefix_dir().unwrap(), Path::new(&prefix_val));
                    assert_eq!(
                        caps.system_config_dir(),
                        Some(PathBuf::from(format!("{prefix_val}/etc/grok")))
                    );
                    assert_eq!(caps.sandbox_kind(), SandboxKind::PolicyOnly);
                } else {
                    assert!(!caps.is_android_termux());
                    assert_eq!(caps.system_config_dir(), Some(PathBuf::from("/etc/grok")));
                    assert_eq!(caps.sandbox_kind(), SandboxKind::KernelEnforced);
                }
            }
        });
        handles.push(handle);
    }

    for handle in handles {
        handle.join().expect("Concurrent thread panicked");
    }
}

#[test]
fn test_adversarial_socket_path_length_boundaries() {
    // Normal length prefix: socket path fits within 108 bytes
    let env_normal = MockEnv::builder()
        .os(PlatformKind::AndroidTermux)
        .var("PREFIX", "/data/data/com.termux/files/usr")
        .var("TMPDIR", "/data/data/com.termux/files/usr/tmp")
        .build();
    let caps_normal = PlatformCapabilities::probe(&env_normal);
    let sock = caps_normal.create_socket_path("session_abc_123").unwrap();
    assert!(sock.to_string_lossy().len() < 108);

    // Overly long prefix causing socket path to exceed 108 bytes
    let long_prefix = format!("/data/data/{}/files/usr", "a".repeat(90));
    let long_tmp = format!("{long_prefix}/tmp");
    let env_long = MockEnv::builder()
        .os(PlatformKind::AndroidTermux)
        .var("PREFIX", &long_prefix)
        .var("TMPDIR", &long_tmp)
        .build();
    let caps_long = PlatformCapabilities::probe(&env_long);
    let err = caps_long.create_socket_path("session_abc_123").unwrap_err();
    match err {
        PlatformError::SocketPathTooLong(p) => {
            assert!(p.len() >= 108);
        }
        other => panic!("Expected SocketPathTooLong, got {:?}", other),
    }
}

#[test]
fn test_adversarial_grok_home_override_storage_safety() {
    // Attempt to set GROK_HOME to /sdcard
    let env = MockEnv::builder()
        .os(PlatformKind::AndroidTermux)
        .var("PREFIX", "/data/data/com.termux/files/usr")
        .var("HOME", "/data/data/com.termux/files/home")
        .var("GROK_HOME", "/sdcard/my_grok_home")
        .build();
    let caps = PlatformCapabilities::probe(&env);
    assert_eq!(
        caps.home_dir(),
        Err(PlatformError::StorageSafety(
            StorageSafetyError::SharedStorageQuarantine {
                path: PathBuf::from("/sdcard/my_grok_home"),
                reason: "Android shared storage does not enforce POSIX user/group permissions and is accessible across apps.",
            }
        ))
    );

    // Legitimate GROK_HOME override
    let env_safe = MockEnv::builder()
        .os(PlatformKind::AndroidTermux)
        .var("PREFIX", "/data/data/com.termux/files/usr")
        .var("HOME", "/data/data/com.termux/files/home")
        .var("GROK_HOME", "/data/data/com.termux/files/home/custom_grok")
        .build();
    let caps_safe = PlatformCapabilities::probe(&env_safe);
    assert_eq!(
        caps_safe.home_dir().unwrap(),
        PathBuf::from("/data/data/com.termux/files/home/custom_grok")
    );
}
