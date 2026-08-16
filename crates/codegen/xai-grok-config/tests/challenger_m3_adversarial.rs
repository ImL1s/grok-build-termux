use std::fs;
use std::os::unix::fs::symlink;
use std::path::{Path, PathBuf};
use std::thread;
use tempfile::tempdir;
use xai_grok_config::paths::{
    decode_cwd_from_dirname, encode_cwd_dirname, ensure_sessions_cwd_dir_in,
    sessions_cwd_dir_in,
};
use xai_grok_config::{
    validate_storage_safety, MockEnv, PlatformCapabilities, PlatformKind, SandboxKind,
    StorageSafetyError,
};

#[test]
fn test_challenger_relative_path_traversals() {
    let dangerous_traversals = [
        "/data/data/com.termux/files/home/../../../../sdcard",
        "/data/data/com.termux/files/home/../../../../sdcard/.grok",
        "/data/data/com.termux/files/home/../../../../sdcard/Download/credentials.json",
        "/data/data/com.termux/files/home/../../../../storage/emulated/0/.grok",
        "/data/data/com.termux/files/home/../../../../storage/emulated/0/Download",
        "/data/data/com.termux/files/home/../../../../storage/self/primary/.grok",
        "/data/data/com.termux/files/home/../../../../storage/1234-5678/.grok",
        "/data/data/com.termux/files/home/../../../../mnt/sdcard",
        "/data/data/com.termux/files/home/../../../../mnt/sdcard/.grok",
        "/data/data/com.termux/files/home/../../../../mnt/media_rw/sdcard0",
        "/data/data/com.termux/files/home/../../../../../data/sdcard/creds",
        "/data/data/com.termux/files/home/../../../../../data/media/0/.grok",
        "/data/data/com.termux/files/home/././../../../../sdcard",
        "/data/data/com.termux/files/home/a/b/c/../../../../../../../sdcard/.grok",
        "sdcard/.grok",
        "storage/emulated/0/.grok",
        "mnt/sdcard/keys",
    ];

    for path_str in dangerous_traversals {
        let res = validate_storage_safety(Path::new(path_str));
        assert!(
            res.is_err(),
            "Expected traversal '{path_str}' to be rejected by validate_storage_safety, got {:?}",
            res
        );
        match res.unwrap_err() {
            StorageSafetyError::SharedStorageQuarantine { path, reason } => {
                assert_eq!(path, PathBuf::from(path_str));
                assert!(!reason.is_empty());
            }
        }
    }
}

#[test]
fn test_challenger_case_variations() {
    let case_variants = [
        "/SDCARD",
        "/SDCARD/",
        "/SDCARD/.grok",
        "/SdCard/.grok",
        "/sDcArD/auth.json",
        "/STORAGE/EMULATED/0",
        "/STORAGE/EMULATED/0/.grok",
        "/Storage/Emulated/0/.grok",
        "/StOrAgE/EmUlAtEd/0/Download",
        "/STORAGE/SELF/PRIMARY",
        "/Storage/Self/Primary/.grok",
        "/STORAGE/1234-5678/.grok",
        "/MNT/SDCARD",
        "/MNT/SDCARD/.grok",
        "/Mnt/Sdcard/keys",
        "/MNT/MEDIA_RW/sdcard0",
        "/DATA/SDCARD",
        "/DATA/MEDIA/0",
        "SDCARD",
        "SDCARD/.grok",
        "Storage/Emulated/0/.grok",
        "MNT/SDCARD/keys",
    ];

    for path_str in case_variants {
        let res = validate_storage_safety(Path::new(path_str));
        assert!(
            res.is_err(),
            "Expected case variant '{path_str}' to be quarantined, got {:?}",
            res
        );
    }
}

#[test]
fn test_challenger_dangling_and_existing_symlinks() {
    let tmp = tempdir().expect("create tempdir");

    // 1. Dangling symlink to /sdcard/.grok
    let dangling_link = tmp.path().join("dangling_sdcard");
    symlink("/sdcard/.grok", &dangling_link).expect("create symlink");
    let res = validate_storage_safety(&dangling_link);
    assert!(
        res.is_err(),
        "Dangling symlink pointing to /sdcard must be quarantined"
    );

    // 2. Dangling symlink to /storage/emulated/0/Download
    let dangling_storage = tmp.path().join("dangling_storage");
    symlink("/storage/emulated/0/Download", &dangling_storage).expect("create symlink");
    let res2 = validate_storage_safety(&dangling_storage);
    assert!(
        res2.is_err(),
        "Dangling symlink pointing to /storage/emulated/0 must be quarantined"
    );

    // 3. Symlink pointing to safe real file
    let real_file = tmp.path().join("real_safe_file.json");
    fs::write(&real_file, "{}").expect("write safe file");
    let safe_link = tmp.path().join("safe_symlink");
    symlink(&real_file, &safe_link).expect("create safe symlink");
    let res_safe = validate_storage_safety(&safe_link);
    assert!(
        res_safe.is_ok(),
        "Symlink to safe file must be accepted, got {:?}",
        res_safe
    );
}

#[test]
fn test_challenger_symlink_chains_multi_hop() {
    let tmp = tempdir().expect("create tempdir");
    let link_c = tmp.path().join("chain_c");
    let link_b = tmp.path().join("chain_b");
    let link_a = tmp.path().join("chain_a");

    // Chain: link_a -> link_b -> link_c -> /storage/emulated/0/.grok
    symlink("/storage/emulated/0/.grok", &link_c).expect("create link_c");
    symlink(&link_c, &link_b).expect("create link_b");
    symlink(&link_b, &link_a).expect("create link_a");

    let res = validate_storage_safety(&link_a);
    assert!(
        res.is_err(),
        "Multi-hop symlink chain resolving to shared storage must be quarantined, got {:?}",
        res
    );
}

#[test]
fn test_challenger_ancestor_directory_symlink() {
    let tmp = tempdir().expect("create tempdir");
    let dir_symlink = tmp.path().join("ancestor_sdcard_link");
    symlink("/sdcard", &dir_symlink).expect("create dir symlink");

    // Non-existent target deep under symlinked ancestor
    let child_target = dir_symlink.join("Download/nested/sub/credentials.json");
    let res = validate_storage_safety(&child_target);
    assert!(
        res.is_err(),
        "Target under ancestor symlink to /sdcard must be quarantined, got {:?}",
        res
    );
}

#[test]
fn test_challenger_symlink_recursion_loop() {
    let tmp = tempdir().expect("create tempdir");
    let link_x = tmp.path().join("loop_x");
    let link_y = tmp.path().join("loop_y");

    // Create circular symlink: x -> y and y -> x
    symlink(&link_y, &link_x).expect("create link_x");
    symlink(&link_x, &link_y).expect("create link_y");

    // Must not stack overflow or hang
    let _ = validate_storage_safety(&link_x);
}

#[test]
fn test_challenger_dual_track_workspace_isolation() {
    use std::os::unix::fs::PermissionsExt;

    let tmp_home = tempdir().expect("create tempdir for home");
    let grok_home = tmp_home.path().join(".grok");

    // Simulate workspace located on /sdcard
    let sdcard_workspace = "/sdcard/Download/my-cool-app";

    // 1. Session directory resolution
    let sess_dir = sessions_cwd_dir_in(&grok_home, sdcard_workspace);
    assert!(
        sess_dir.starts_with(&grok_home),
        "Session directory must reside within grok_home"
    );
    assert!(
        !sess_dir.to_string_lossy().starts_with("/sdcard"),
        "Session directory must never be on /sdcard"
    );

    // 2. Session directory creation with 0700 permissions
    let created_dir = ensure_sessions_cwd_dir_in(&grok_home, sdcard_workspace).expect("ensure session dir");
    assert!(created_dir.is_dir());
    let mode = fs::metadata(&created_dir).unwrap().permissions().mode() & 0o777;
    assert_eq!(mode, 0o700, "Session dir must be born 0700");
    let sessions_root_mode = fs::metadata(grok_home.join("sessions")).unwrap().permissions().mode() & 0o777;
    assert_eq!(sessions_root_mode, 0o700, "Sessions root must be 0700");

    // 3. Decoding CWD from dirname
    let recovered_cwd = decode_cwd_from_dirname(&created_dir);
    assert_eq!(
        recovered_cwd.as_deref(),
        Some(sdcard_workspace),
        "Must correctly recover original CWD from session directory"
    );
}

#[test]
fn test_challenger_long_sdcard_workspace_slug_hash_roundtrip() {
    use std::os::unix::fs::PermissionsExt;

    let tmp_home = tempdir().expect("create tempdir for home");
    let grok_home = tmp_home.path().join(".grok");

    // Long path on /sdcard (>255 bytes when URL encoded)
    let long_sdcard_workspace = format!(
        "/sdcard/Download/大型專案目錄/子目錄一/子目錄二/子目錄三/ソースコード/backend/service/{}",
        "submodule-".repeat(15)
    );

    let encoded_name = encode_cwd_dirname(&long_sdcard_workspace);
    assert!(
        encoded_name.len() <= 57,
        "Long dirname must be compact slug-hash <= 57 bytes, got {}",
        encoded_name.len()
    );

    let created_dir = ensure_sessions_cwd_dir_in(&grok_home, &long_sdcard_workspace)
        .expect("create long cwd session dir");
    assert!(created_dir.is_dir());
    let mode = fs::metadata(&created_dir).unwrap().permissions().mode() & 0o777;
    assert_eq!(mode, 0o700, "Long cwd session dir must be 0700");

    let dot_cwd = created_dir.join(".cwd");
    assert!(dot_cwd.is_file(), ".cwd metadata file must be written for hash encoding");
    let content = fs::read_to_string(&dot_cwd).unwrap();
    assert_eq!(content, long_sdcard_workspace);

    let recovered = decode_cwd_from_dirname(&created_dir);
    assert_eq!(recovered.as_deref(), Some(long_sdcard_workspace.as_str()));
}

#[test]
fn test_challenger_concurrency_stress_100_threads() {
    let thread_count = 100;
    let mut handles = Vec::with_capacity(thread_count);

    for t in 0..thread_count {
        let handle = thread::spawn(move || {
            for i in 0..50 {
                let is_termux = (t + i) % 2 == 0;
                let env = if is_termux {
                    MockEnv::builder()
                        .os(PlatformKind::AndroidTermux)
                        .var("PREFIX", format!("/data/data/com.termux.t{t}/files/usr"))
                        .var("HOME", format!("/data/data/com.termux.t{t}/files/home"))
                        .var("TMPDIR", format!("/data/data/com.termux.t{t}/files/usr/tmp"))
                        .build()
                } else {
                    MockEnv::builder()
                        .os(PlatformKind::DesktopLinux)
                        .var("HOME", format!("/home/user{t}"))
                        .build()
                };

                let caps = PlatformCapabilities::probe(&env);
                if is_termux {
                    assert!(caps.is_android_termux());
                    assert_eq!(caps.sandbox_kind(), SandboxKind::PolicyOnly);
                    assert!(caps.system_config_dir().unwrap().to_string_lossy().contains("etc/grok"));
                    let sock = caps.create_socket_path(&format!("sess-{t}-{i}")).unwrap();
                    assert!(sock.to_string_lossy().len() < 108);
                } else {
                    assert!(!caps.is_android_termux());
                    assert_eq!(caps.sandbox_kind(), SandboxKind::KernelEnforced);
                    assert_eq!(caps.system_config_dir().unwrap(), PathBuf::from("/etc/grok"));
                }

                // Storage quarantine checks
                assert!(validate_storage_safety(Path::new("/sdcard/.grok")).is_err());
                assert!(validate_storage_safety(Path::new("/storage/emulated/0/.grok")).is_err());
                assert!(validate_storage_safety(Path::new("/data/data/com.termux/files/home/.grok")).is_ok());
            }
        });
        handles.push(handle);
    }

    for h in handles {
        h.join().expect("Concurrent stress thread panicked");
    }
}

#[test]
fn test_challenger_relative_symlink_to_shared_storage() {
    let tmp = tempdir().expect("create tempdir");
    let subdir = tmp.path().join("sub").join("nested");
    fs::create_dir_all(&subdir).expect("create subdir");

    let rel_link = subdir.join("rel_to_sdcard");
    symlink("../../../sdcard/.grok", &rel_link).expect("create rel symlink");

    let res = validate_storage_safety(&rel_link);
    assert!(
        res.is_err(),
        "Relative symlink to ../../../sdcard must be quarantined, got {:?}",
        res
    );
}

#[test]
fn test_challenger_deep_symlink_chain_bound() {
    let tmp = tempdir().expect("create tempdir");
    let mut prev = tmp.path().join("link_target");
    symlink("/sdcard/.grok", &prev).expect("create root link");

    for i in 0..25 {
        let next_link = tmp.path().join(format!("chain_link_{i}"));
        symlink(&prev, &next_link).expect("create chain link");
        prev = next_link;
    }

    let res = validate_storage_safety(&prev);
    assert!(
        res.is_err(),
        "25-hop symlink chain to /sdcard must be quarantined, got {:?}",
        res
    );
}

#[test]
fn test_challenger_mixed_separators_and_double_slashes() {
    let odd_paths = [
        "//sdcard",
        "///sdcard/.grok",
        "//storage//emulated//0//.grok",
        "/data/data/com.termux/files/home/..//..//..//..//sdcard",
        "/sdcard///credentials.json",
        "/storage/emulated/0///Download///keys",
        "/mnt/sdcard///",
    ];

    for path in odd_paths {
        let res = validate_storage_safety(Path::new(path));
        assert!(
            res.is_err(),
            "Expected odd/duplicate slash path '{path}' to be quarantined, got {:?}",
            res
        );
    }
}

