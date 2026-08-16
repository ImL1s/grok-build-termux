use std::path::PathBuf;
use xai_grok_config::{MockEnv, PlatformCapabilities, PlatformError, PlatformKind};

#[test]
fn test_socket_path_exact_107_bytes_accepted() {
    // Exact 107-byte path:
    // sock_name is "grok-" (5) + 8 hex chars + ".sock" (5) = 18 bytes
    // joined with tmp: tmp.len() + 1 ('/') + 18 = tmp.len() + 19
    // To achieve exactly 107 bytes: tmp.len() = 107 - 19 = 88 bytes.
    let base = "/tmp/a";
    let padding = "x".repeat(88 - base.len());
    let tmp_88 = format!("{base}{padding}");
    assert_eq!(tmp_88.len(), 88);

    let env = MockEnv::builder()
        .os(PlatformKind::AndroidTermux)
        .var("PREFIX", "/data/data/com.termux/files/usr")
        .var("TMPDIR", &tmp_88)
        .build();
    let caps = PlatformCapabilities::probe(&env);

    let sock = caps.create_socket_path("session_test").expect("107 bytes must be accepted");
    let path_str = sock.to_string_lossy();
    assert_eq!(path_str.len(), 107, "Expected exactly 107 bytes");
}

#[test]
fn test_socket_path_exact_108_bytes_rejected() {
    // Exact 108-byte path:
    // tmp.len() + 19 = 108 -> tmp.len() = 89 bytes.
    let base = "/tmp/a";
    let padding = "x".repeat(89 - base.len());
    let tmp_89 = format!("{base}{padding}");
    assert_eq!(tmp_89.len(), 89);

    let env = MockEnv::builder()
        .os(PlatformKind::AndroidTermux)
        .var("PREFIX", "/data/data/com.termux/files/usr")
        .var("TMPDIR", &tmp_89)
        .build();
    let caps = PlatformCapabilities::probe(&env);

    let err = caps.create_socket_path("session_test").expect_err("108 bytes must be rejected");
    match err {
        PlatformError::SocketPathTooLong(path) => {
            assert_eq!(path.len(), 108, "Expected rejected path to be 108 bytes");
        }
        other => panic!("Expected SocketPathTooLong, got {:?}", other),
    }
}

#[test]
fn test_socket_path_exact_109_bytes_rejected() {
    let base = "/tmp/a";
    let padding = "x".repeat(90 - base.len());
    let tmp_90 = format!("{base}{padding}");
    assert_eq!(tmp_90.len(), 90);

    let env = MockEnv::builder()
        .os(PlatformKind::AndroidTermux)
        .var("PREFIX", "/data/data/com.termux/files/usr")
        .var("TMPDIR", &tmp_90)
        .build();
    let caps = PlatformCapabilities::probe(&env);

    let err = caps.create_socket_path("session_test").expect_err("109 bytes must be rejected");
    match err {
        PlatformError::SocketPathTooLong(path) => {
            assert_eq!(path.len(), 109, "Expected rejected path to be 109 bytes");
        }
        other => panic!("Expected SocketPathTooLong, got {:?}", other),
    }
}

#[test]
fn test_socket_path_blake3_compression_invariance() {
    let env = MockEnv::builder()
        .os(PlatformKind::AndroidTermux)
        .var("PREFIX", "/data/data/com.termux/files/usr")
        .build();
    let caps = PlatformCapabilities::probe(&env);

    let very_long = "very_long_session_id_".repeat(500);
    let session_inputs = [
        "",
        "s",
        "normal_session_12345",
        very_long.as_str(),
        "測試_會話_🚀_🔥_🌟_Unicode_Session",
        "session with spaces and symbols !@#$%^&*()_+-=[]{}|;:,.<>?",
        "\0\r\n\t",
    ];

    for sid in session_inputs {
        let sock = caps.create_socket_path(sid).expect("Valid socket creation");
        let file_name = sock.file_name().unwrap().to_str().unwrap();
        assert!(file_name.starts_with("grok-"));
        assert!(file_name.ends_with(".sock"));
        assert_eq!(file_name.len(), 18, "Filename must always be 18 bytes: 'grok-' + 8 hex + '.sock'");
        assert!(sock.to_string_lossy().len() < 108);
    }
}

#[test]
fn test_tmpdir_fallback_and_whitespace_filtering() {
    // 1. Explicit TMPDIR
    let env1 = MockEnv::builder()
        .os(PlatformKind::AndroidTermux)
        .var("PREFIX", "/data/data/com.termux/files/usr")
        .var("TMPDIR", "/custom/tmp")
        .build();
    let caps1 = PlatformCapabilities::probe(&env1);
    assert_eq!(caps1.temp_dir(), PathBuf::from("/custom/tmp"));

    // 2. Unset TMPDIR on Termux
    let env2 = MockEnv::builder()
        .os(PlatformKind::AndroidTermux)
        .var("PREFIX", "/data/data/com.termux/files/usr")
        .build();
    let caps2 = PlatformCapabilities::probe(&env2);
    assert_eq!(caps2.temp_dir(), PathBuf::from("/data/data/com.termux/files/usr/tmp"));

    // 3. Unset TMPDIR on Desktop
    let env3 = MockEnv::builder()
        .os(PlatformKind::DesktopLinux)
        .build();
    let caps3 = PlatformCapabilities::probe(&env3);
    assert_eq!(caps3.temp_dir(), PathBuf::from("/tmp"));

    // 4. Empty string TMPDIR
    let env4 = MockEnv::builder()
        .os(PlatformKind::AndroidTermux)
        .var("PREFIX", "/data/data/com.termux/files/usr")
        .var("TMPDIR", "")
        .build();
    let caps4 = PlatformCapabilities::probe(&env4);
    assert_eq!(caps4.temp_dir(), PathBuf::from("/data/data/com.termux/files/usr/tmp"));

    // 5. Whitespace TMPDIR
    let env5 = MockEnv::builder()
        .os(PlatformKind::AndroidTermux)
        .var("PREFIX", "/data/data/com.termux/files/usr")
        .var("TMPDIR", "   \t\n  ")
        .build();
    let caps5 = PlatformCapabilities::probe(&env5);
    assert_eq!(caps5.temp_dir(), PathBuf::from("/data/data/com.termux/files/usr/tmp"));
}
