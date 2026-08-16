use std::path::{Component, Path, PathBuf};

#[derive(Debug, PartialEq, Eq)]
pub enum StorageSafetyError {
    SharedStorageQuarantine {
        path: PathBuf,
        reason: &'static str,
    },
}

/// Known Android shared storage path prefixes and subsegments that lack POSIX DAC permissions.
const ANDROID_SHARED_STORAGE_PREFIXES: &[&str] = &[
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
];

/// Lexically normalize a path by resolving `.` and `..` components without requiring disk access.
pub fn normalize_lexical(path: &Path) -> PathBuf {
    let mut normalized = PathBuf::new();
    let mut is_absolute = false;

    for component in path.components() {
        match component {
            Component::Prefix(prefix) => {
                normalized.push(prefix.as_os_str());
            }
            Component::RootDir => {
                normalized.push(Component::RootDir.as_os_str());
                is_absolute = true;
            }
            Component::CurDir => {
                // Ignore '.'
            }
            Component::ParentDir => {
                let pop_success = match normalized.components().last() {
                    Some(Component::Normal(_)) => {
                        normalized.pop();
                        true
                    }
                    _ => false,
                };
                if !pop_success && !is_absolute {
                    normalized.push(Component::ParentDir.as_os_str());
                }
            }
            Component::Normal(c) => {
                normalized.push(c);
            }
        }
    }
    normalized
}

/// Helper to check if a string representation of a normalized path matches any quarantine prefix or pattern.
fn is_quarantined_str(norm_str: &str) -> bool {
    let lower = norm_str.to_lowercase();
    let lower = lower.replace('\\', "/");

    for prefix in ANDROID_SHARED_STORAGE_PREFIXES {
        if lower == *prefix
            || lower.starts_with(&format!("{prefix}/"))
            || (prefix.starts_with('/') && lower.starts_with(prefix))
        {
            return true;
        }
    }

    if lower.contains("/sdcard")
        || lower.contains("/storage/")
        || lower == "/storage"
        || lower.contains("/storage/emulated")
        || lower.contains("/storage/self")
        || lower.contains("/mnt/sdcard")
        || lower.contains("/mnt/media_rw")
    {
        return true;
    }

    false
}

/// Validates that a path is safe for storing private keys, credentials, or state.
///
/// Strictly refuses Android shared storage paths to prevent world-readable leaks.
pub fn validate_storage_safety(path: &Path) -> Result<(), StorageSafetyError> {
    validate_storage_safety_depth(path, 0)
}

fn validate_storage_safety_depth(path: &Path, depth: usize) -> Result<(), StorageSafetyError> {
    if depth > 32 {
        // Prevent infinite symlink recursion loops
        return Ok(());
    }

    // 1. Lexical normalization & check on the provided path
    let normalized = normalize_lexical(path);
    let norm_str = normalized.to_string_lossy();
    if is_quarantined_str(&norm_str) {
        return Err(StorageSafetyError::SharedStorageQuarantine {
            path: path.to_path_buf(),
            reason: "Android shared storage does not enforce POSIX user/group permissions and is accessible across apps.",
        });
    }

    // 2. Direct symlink inspection (handles existing AND dangling symlinks)
    let is_link = path.is_symlink()
        || std::fs::symlink_metadata(path)
            .map(|m| m.file_type().is_symlink())
            .unwrap_or(false);

    if is_link {
        if let Ok(link_dest) = std::fs::read_link(path) {
            let resolved_dest = if link_dest.is_relative() {
                if let Some(parent) = path.parent() {
                    parent.join(&link_dest)
                } else {
                    link_dest
                }
            } else {
                link_dest
            };

            if let Err(StorageSafetyError::SharedStorageQuarantine { reason, .. }) =
                validate_storage_safety_depth(&resolved_dest, depth + 1)
            {
                return Err(StorageSafetyError::SharedStorageQuarantine {
                    path: path.to_path_buf(),
                    reason,
                });
            }
        }
    }

    // 3. Full disk canonicalization if the target already exists on disk
    if let Ok(canon) = std::fs::canonicalize(path) {
        let canon_norm = normalize_lexical(&canon);
        let canon_str = canon_norm.to_string_lossy();
        if is_quarantined_str(&canon_str) {
            return Err(StorageSafetyError::SharedStorageQuarantine {
                path: path.to_path_buf(),
                reason: "Canonical target resolves to Android shared storage which lacks POSIX permissions.",
            });
        }
    } else {
        // 4. If canonicalize failed (e.g. NotFound for non-existent target inside symlinked parent dir),
        // inspect existing ancestor paths for symlinks to shared storage.
        let mut current = path;
        while let Some(parent) = current.parent() {
            if parent.as_os_str().is_empty() || parent == Path::new("/") {
                break;
            }

            let parent_is_link = parent.is_symlink()
                || std::fs::symlink_metadata(parent)
                    .map(|m| m.file_type().is_symlink())
                    .unwrap_or(false);

            if parent_is_link {
                if let Ok(link_dest) = std::fs::read_link(parent) {
                    let resolved_dest = if link_dest.is_relative() {
                        if let Some(p) = parent.parent() {
                            p.join(&link_dest)
                        } else {
                            link_dest
                        }
                    } else {
                        link_dest
                    };

                    if let Ok(rel) = path.strip_prefix(parent) {
                        let reconstructed = resolved_dest.join(rel);
                        if let Err(StorageSafetyError::SharedStorageQuarantine { reason, .. }) =
                            validate_storage_safety_depth(&reconstructed, depth + 1)
                        {
                            return Err(StorageSafetyError::SharedStorageQuarantine {
                                path: path.to_path_buf(),
                                reason,
                            });
                        }
                    }
                }
            } else if let Ok(canon_parent) = std::fs::canonicalize(parent) {
                if let Ok(rel) = path.strip_prefix(parent) {
                    let reconstructed = canon_parent.join(rel);
                    let canon_norm = normalize_lexical(&reconstructed);
                    let canon_str = canon_norm.to_string_lossy();
                    if is_quarantined_str(&canon_str) {
                        return Err(StorageSafetyError::SharedStorageQuarantine {
                            path: path.to_path_buf(),
                            reason: "Canonical target resolves to Android shared storage which lacks POSIX permissions.",
                        });
                    }
                }
                break;
            }
            current = parent;
        }
    }

    Ok(())
}

fn main() {
    println!("Running extended test harness for validate_storage_safety...");

    // Test 1: Quarantined paths
    let unsafe_paths = [
        "/sdcard",
        "/sdcard/",
        "/sdcard/.grok",
        "/sdcard/Download/grok",
        "/sdcard/Android/data",
        "/data/sdcard/grok",
        "/root/sdcard/test",
        "/storage/emulated/0",
        "/storage/emulated/0/",
        "/storage/emulated/0/.grok",
        "/storage/emulated/0/Download",
        "/storage/emulated/10/.grok",
        "/storage/emulated/999/test",
        "/mnt/sdcard",
        "/mnt/sdcard/",
        "/mnt/sdcard/.grok",
        "/mnt/sdcard/sub/path",
        "/storage/self/primary",
        "/storage/self/primary/.grok",
        "/storage/self/0/.grok",
        "/mnt/media_rw",
        "/mnt/media_rw/sdcard0",
        "/mnt/media_rw/usb_disk",
        "/storage/1234-5678/.grok",
        "/storage/ABCD-EF01/Android",
        "/storage/extSdCard/grok",
        // Relative paths
        "sdcard",
        "sdcard/",
        "sdcard/.grok",
        "storage",
        "storage/",
        "storage/emulated/0/.grok",
        "storage/1234-5678/.grok",
        "mnt/sdcard/foo",
        "mnt/media_rw/bar",
        // Traversals
        "/data/data/com.termux/files/home/../../../../sdcard/.grok",
        "/data/data/com.termux/files/home/../../../../storage/emulated/1/.grok",
        "/data/data/com.termux/files/home/../../../../storage/1234-5678/.grok",
        "/data/data/com.termux/files/home/././../../../../sdcard",
        "./sdcard/.",
        "sdcard/../storage/0",
        // Case variations
        "/SDCARD/.grok",
        "/Sdcard/.grok",
        "/STORAGE/EMULATED/0/.grok",
        "/Storage/Emulated/0/.grok",
        "/MNT/SDCARD/.grok",
        "/Mnt/Media_Rw/test",
        "SDCARD/.grok",
        "Storage/Emulated/0/.grok",
        "MNT/SDCARD/test",
    ];

    for path in &unsafe_paths {
        let res = validate_storage_safety(Path::new(path));
        assert!(
            res.is_err(),
            "Expected unsafe path to be quarantined: {}",
            path
        );
        match res.unwrap_err() {
            StorageSafetyError::SharedStorageQuarantine { path: p, reason } => {
                assert_eq!(p, PathBuf::from(path));
                assert!(!reason.is_empty());
            }
        }
    }
    println!("✓ All {} unsafe path variants correctly quarantined", unsafe_paths.len());

    // Test 2: Safe paths
    let safe_paths = [
        "/data/data/com.termux/files/home/.grok",
        "/data/data/com.termux/files/usr/etc/grok",
        "/data/data/com.custom.app/files/home/.grok",
        "/home/developer/.grok",
        "/Users/developer/.grok",
        "/var/lib/grok",
        "/etc/grok",
        "home/.grok",
        "./config/.grok",
        "my_project/.grok",
    ];

    for path in &safe_paths {
        let res = validate_storage_safety(Path::new(path));
        assert!(
            res.is_ok(),
            "Expected safe path to be allowed: {}",
            path
        );
    }
    println!("✓ All {} safe path variants correctly allowed", safe_paths.len());

    // Test 3: Dangling symlinks and nested paths under symlinks
    let tmp_dir = std::env::temp_dir().join(format!("grok_test_ext_{}", std::process::id()));
    let _ = std::fs::create_dir_all(&tmp_dir);
    let dangling_symlink = tmp_dir.join("dangling_link");
    let _ = std::fs::remove_file(&dangling_symlink);

    #[cfg(unix)]
    {
        use std::os::unix::fs::symlink;
        symlink("/sdcard/.grok", &dangling_symlink).expect("symlink creation failed");
        let res = validate_storage_safety(&dangling_symlink);
        assert!(res.is_err(), "Dangling symlink pointing to /sdcard/.grok MUST be quarantined");
        println!("✓ Dangling symlink to /sdcard/.grok correctly quarantined: {:?}", res);

        let safe_symlink = tmp_dir.join("safe_link");
        let _ = std::fs::remove_file(&safe_symlink);
        symlink("/home/developer/.grok", &safe_symlink).expect("symlink creation failed");
        let res_safe = validate_storage_safety(&safe_symlink);
        assert!(res_safe.is_ok(), "Symlink pointing to safe path MUST be allowed");
        println!("✓ Symlink to safe path correctly allowed");

        // Symlink chain: link_a -> link_b -> /sdcard/.grok
        let link_a = tmp_dir.join("chain_a");
        let link_b = tmp_dir.join("chain_b");
        let _ = std::fs::remove_file(&link_a);
        let _ = std::fs::remove_file(&link_b);
        symlink(&link_b, &link_a).unwrap();
        symlink("/sdcard/.grok", &link_b).unwrap();
        let res_chain = validate_storage_safety(&link_a);
        assert!(res_chain.is_err(), "Symlink chain pointing to /sdcard/.grok MUST be quarantined");
        println!("✓ Symlink chain correctly quarantined: {:?}", res_chain);

        // Non-existent nested path under dangling symlinked directory:
        // dir_symlink -> /sdcard
        // path checked: dir_symlink/sub/nested/credentials.json (does not exist on disk)
        let dir_symlink = tmp_dir.join("dir_symlink");
        let _ = std::fs::remove_file(&dir_symlink);
        symlink("/sdcard", &dir_symlink).unwrap();
        let nested_nonexistent = dir_symlink.join("sub/nested/credentials.json");
        let res_nested = validate_storage_safety(&nested_nonexistent);
        assert!(res_nested.is_err(), "Nested non-existent path under symlinked directory to /sdcard MUST be quarantined");
        println!("✓ Non-existent nested path under symlinked directory correctly quarantined: {:?}", res_nested);

        // Cleanup
        let _ = std::fs::remove_file(&dangling_symlink);
        let _ = std::fs::remove_file(&safe_symlink);
        let _ = std::fs::remove_file(&link_a);
        let _ = std::fs::remove_file(&link_b);
        let _ = std::fs::remove_file(&dir_symlink);
        let _ = std::fs::remove_dir_all(&tmp_dir);
    }

    println!("\nALL EXTENDED TEST HARNESS ASSERTIONS PASSED!");
}
