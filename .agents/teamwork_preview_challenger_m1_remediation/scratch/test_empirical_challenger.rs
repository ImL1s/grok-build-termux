use std::path::{Path, PathBuf};
use tempfile::tempdir;
use xai_grok_config::{validate_storage_safety, StorageSafetyError};

fn main() {
    println!("=== Empirical Challenger Verification Suite ===");
    let mut passed = 0;
    let mut total = 0;

    macro_rules! check_reject {
        ($path_expr:expr, $desc:expr) => {
            total += 1;
            let p = Path::new($path_expr);
            let res = validate_storage_safety(p);
            match res {
                Err(StorageSafetyError::SharedStorageQuarantine { ref path, reason: _ }) => {
                    passed += 1;
                    println!("[PASS] REJECT (expected): {} ({})", $desc, path.display());
                }
                Ok(_) => {
                    println!("[FAIL] UNEXPECTED ACCEPTANCE: {} ({})", $desc, p.display());
                    panic!("Failed: path should have been quarantined: {}", p.display());
                }
            }
        };
    }

    macro_rules! check_accept {
        ($path_expr:expr, $desc:expr) => {
            total += 1;
            let p = Path::new($path_expr);
            let res = validate_storage_safety(p);
            match res {
                Ok(_) => {
                    passed += 1;
                    println!("[PASS] ACCEPT (expected): {} ({})", $desc, p.display());
                }
                Err(e) => {
                    println!("[FAIL] UNEXPECTED REJECTION: {} ({}): {:?}", $desc, p.display(), e);
                    panic!("Failed: path should have been accepted: {}", p.display());
                }
            }
        };
    }

    // 1. Lexical `..` Traversals
    println!("\n--- 1. Lexical `..` Traversal Attacks ---");
    check_reject!("/data/data/com.termux/files/home/../../../../storage/emulated/0/.grok", "Deep .. traversal to /storage/emulated/0");
    check_reject!("/data/data/com.termux/files/home/../../../../sdcard/.grok", "Deep .. traversal to /sdcard");
    check_reject!("/data/data/com.termux/files/usr/../home/../../../../sdcard/keys", "Mixed usr/home .. traversal to /sdcard");
    check_reject!("/data/data/com.termux/files/home/././../../../../storage/1234-5678/.grok", "Dots + .. traversal to /storage/OTG");
    check_reject!("/data/data/com.termux/files/home/subdir/../../../../../mnt/sdcard/grok", "Nested subdirs .. traversal to /mnt/sdcard");
    check_reject!("/data/data/com.termux/files/home/../../../../data/sdcard/credentials", ".. traversal to /data/sdcard");
    check_reject!("/data/data/com.termux/files/home/../../../../../data/media/0/state", ".. 5 levels traversal to /data/media");
    check_reject!("/data/data/com.termux/files/home/../../../../../data/sdcard/state", ".. 5 levels traversal to /data/sdcard");
    check_reject!("/data/data/com.termux/files/home/../../../../mnt/media_rw/usb", ".. traversal to /mnt/media_rw");
    check_reject!("/data/user/0/com.termux/files/home/../../../../../../storage/emulated/0/.grok", "Multi-user .. traversal to /storage/emulated/0");
    check_reject!("/data/user/0/com.termux/files/home/../../../../../../sdcard/.grok", "Multi-user .. traversal to /sdcard");
    check_reject!("///data//data//com.termux//files/home/../../../../sdcard/.grok", "Redundant slashes + traversal to /sdcard");
    check_reject!("/data/data/com.termux/files/home/../../../../SDCARD/credentials", "Traversal + uppercase SDCARD");
    check_reject!("/data/data/com.termux/files/home/../../../../Storage/Emulated/0/keys", "Traversal + titlecase Storage/Emulated/0");

    // 2. Relative Path Prefixes
    println!("\n--- 2. Relative Path Attacks ---");
    check_reject!("sdcard/.grok", "Relative sdcard/.grok");
    check_reject!("sdcard/credentials.json", "Relative sdcard/credentials.json");
    check_reject!("storage/emulated/0/.grok", "Relative storage/emulated/0/.grok");
    check_reject!("storage/self/primary/.grok", "Relative storage/self/primary/.grok");
    check_reject!("mnt/sdcard/keys", "Relative mnt/sdcard/keys");
    check_reject!("mnt/media_rw/sdcard0", "Relative mnt/media_rw/sdcard0");
    check_reject!("data/sdcard/test", "Relative data/sdcard/test");
    check_reject!("data/media/0/grok", "Relative data/media/0/grok");
    check_reject!("./sdcard/foo", "Relative ./sdcard/foo");
    check_reject!("./storage/emulated/0/secret", "Relative ./storage/emulated/0/secret");
    check_reject!("sub/../../sdcard/secret", "Relative traversal sub/../../sdcard/secret");
    check_reject!("sub/../../storage/emulated/0/keys", "Relative traversal sub/../../storage/emulated/0/keys");

    // 3. Case Variations
    println!("\n--- 3. Case Variation Attacks ---");
    check_reject!("/SDCARD/.grok", "Uppercase /SDCARD/.grok");
    check_reject!("/Sdcard/.grok", "Titlecase /Sdcard/.grok");
    check_reject!("/sDcaRd/credentials", "Mixed case /sDcaRd/credentials");
    check_reject!("/STORAGE/EMULATED/0/.grok", "Uppercase /STORAGE/EMULATED/0/.grok");
    check_reject!("/Storage/Emulated/0/.grok", "Titlecase /Storage/Emulated/0/.grok");
    check_reject!("/sToRaGe/EmUlAtEd/0/.grok", "Mixed case /sToRaGe/EmUlAtEd/0/.grok");
    check_reject!("/STORAGE/SELF/PRIMARY/.grok", "Uppercase /STORAGE/SELF/PRIMARY/.grok");
    check_reject!("/MNT/SDCARD/.grok", "Uppercase /MNT/SDCARD/.grok");
    check_reject!("/Mnt/Media_Rw/usb", "Titlecase /Mnt/Media_Rw/usb");
    check_reject!("SDCARD/.grok", "Relative uppercase SDCARD/.grok");
    check_reject!("Storage/Emulated/0/.grok", "Relative titlecase Storage/Emulated/0/.grok");
    check_reject!("Mnt/Sdcard/keys", "Relative titlecase Mnt/Sdcard/keys");
    check_reject!("DATA/SDCARD/keys", "Relative uppercase DATA/SDCARD/keys");

    // 4. Dangling Symlinks & Symlink Chains
    println!("\n--- 4. Dangling Symlinks & Symlink Chains ---");
    let tmp = tempdir().expect("create tempdir");
    
    // Direct dangling symlink to /sdcard/.grok
    let dangling_sdcard = tmp.path().join("dangling_sdcard");
    std::os::unix::fs::symlink("/sdcard/.grok", &dangling_sdcard).expect("symlink");
    total += 1;
    match validate_storage_safety(&dangling_sdcard) {
        Err(StorageSafetyError::SharedStorageQuarantine { path, .. }) => {
            passed += 1;
            assert_eq!(path, dangling_sdcard);
            println!("[PASS] REJECT (expected): Dangling symlink -> /sdcard/.grok");
        }
        res => panic!("Expected dangling symlink to be rejected, got {:?}", res),
    }

    // Direct dangling symlink to /storage/emulated/0/keys
    let dangling_storage = tmp.path().join("dangling_storage");
    std::os::unix::fs::symlink("/storage/emulated/0/keys", &dangling_storage).expect("symlink");
    total += 1;
    match validate_storage_safety(&dangling_storage) {
        Err(StorageSafetyError::SharedStorageQuarantine { path, .. }) => {
            passed += 1;
            assert_eq!(path, dangling_storage);
            println!("[PASS] REJECT (expected): Dangling symlink -> /storage/emulated/0/keys");
        }
        res => panic!("Expected dangling symlink to be rejected, got {:?}", res),
    }

    // Direct dangling symlink to uppercase /SDCARD/test
    let dangling_upper = tmp.path().join("dangling_upper");
    std::os::unix::fs::symlink("/SDCARD/test", &dangling_upper).expect("symlink");
    total += 1;
    match validate_storage_safety(&dangling_upper) {
        Err(StorageSafetyError::SharedStorageQuarantine { path, .. }) => {
            passed += 1;
            assert_eq!(path, dangling_upper);
            println!("[PASS] REJECT (expected): Dangling symlink -> /SDCARD/test");
        }
        res => panic!("Expected dangling symlink to be rejected, got {:?}", res),
    }

    // Direct dangling symlink with relative target "../../../sdcard/.grok"
    let dangling_rel = tmp.path().join("dangling_rel");
    std::os::unix::fs::symlink("../../../sdcard/.grok", &dangling_rel).expect("symlink");
    total += 1;
    match validate_storage_safety(&dangling_rel) {
        Err(StorageSafetyError::SharedStorageQuarantine { path, .. }) => {
            passed += 1;
            assert_eq!(path, dangling_rel);
            println!("[PASS] REJECT (expected): Dangling symlink with relative target -> ../../../sdcard/.grok");
        }
        res => panic!("Expected relative dangling symlink to be rejected, got {:?}", res),
    }

    // Symlink chain: link_c -> link_b -> link_a -> /sdcard/.grok
    let link_a = tmp.path().join("link_a");
    let link_b = tmp.path().join("link_b");
    let link_c = tmp.path().join("link_c");
    std::os::unix::fs::symlink("/sdcard/.grok", &link_a).expect("symlink a");
    std::os::unix::fs::symlink(&link_a, &link_b).expect("symlink b");
    std::os::unix::fs::symlink(&link_b, &link_c).expect("symlink c");
    total += 1;
    match validate_storage_safety(&link_c) {
        Err(StorageSafetyError::SharedStorageQuarantine { path, .. }) => {
            passed += 1;
            assert_eq!(path, link_c);
            println!("[PASS] REJECT (expected): 3-hop Symlink chain link_c -> link_b -> link_a -> /sdcard/.grok");
        }
        res => panic!("Expected symlink chain to be rejected, got {:?}", res),
    }

    // Ancestor directory symlink: dir_symlink -> /sdcard, testing dir_symlink/sub/file
    let dir_symlink = tmp.path().join("dir_symlink");
    std::os::unix::fs::symlink("/sdcard", &dir_symlink).expect("dir symlink");
    let deep_child = dir_symlink.join("nonexistent_subdir").join("creds.json");
    total += 1;
    match validate_storage_safety(&deep_child) {
        Err(StorageSafetyError::SharedStorageQuarantine { path, .. }) => {
            passed += 1;
            assert_eq!(path, deep_child);
            println!("[PASS] REJECT (expected): Nonexistent child under ancestor symlink to /sdcard");
        }
        res => panic!("Expected ancestor symlink child to be rejected, got {:?}", res),
    }

    // Ancestor directory symlink with titlecase /Storage/Emulated/0
    let dir_symlink_storage = tmp.path().join("dir_symlink_storage");
    std::os::unix::fs::symlink("/Storage/Emulated/0", &dir_symlink_storage).expect("dir symlink storage");
    let deep_child_storage = dir_symlink_storage.join("app").join("keys.pem");
    total += 1;
    match validate_storage_safety(&deep_child_storage) {
        Err(StorageSafetyError::SharedStorageQuarantine { path, .. }) => {
            passed += 1;
            assert_eq!(path, deep_child_storage);
            println!("[PASS] REJECT (expected): Nonexistent child under ancestor symlink to /Storage/Emulated/0");
        }
        res => panic!("Expected ancestor symlink child to be rejected, got {:?}", res),
    }

    // Symlink loop (circular recursion stress): link_x -> link_y -> link_x
    let link_x = tmp.path().join("link_x");
    let link_y = tmp.path().join("link_y");
    std::os::unix::fs::symlink(&link_y, &link_x).expect("symlink x");
    std::os::unix::fs::symlink(&link_x, &link_y).expect("symlink y");
    total += 1;
    // Circular symlink not pointing to sdcard should safely terminate without overflow
    let _ = validate_storage_safety(&link_x);
    passed += 1;
    println!("[PASS] SAFE TERMINATION: Circular symlink loop (recursion depth cap handled without stack overflow)");

    // 5. Legitimate Termux Paths
    println!("\n--- 5. Legitimate Termux Paths ---");
    check_accept!("/data/data/com.termux/files/home/.grok", "Standard Termux $HOME/.grok");
    check_accept!("/data/data/com.termux/files/usr/tmp", "Standard Termux $PREFIX/tmp");
    check_accept!("/data/data/com.termux/files/usr/etc/grok", "Standard Termux $PREFIX/etc/grok");
    check_accept!("/data/data/com.termux/files/home/workspace/project", "Termux project directory");
    check_accept!("/data/data/com.termux/files/home/workspace/grok-build", "Termux workspace directory");
    check_accept!("/data/user/0/com.termux/files/home/.grok", "Secondary user Termux home");
    check_accept!("/home/developer/.grok", "Linux user home");
    check_accept!("/Users/developer/.grok", "macOS user home");
    check_accept!("/tmp/grok-socket-12345", "Tmp socket path");
    check_accept!("/var/lib/grok", "Linux /var/lib/grok");

    // 6. Safe Symlinks to Legitimate Destinations
    println!("\n--- 6. Safe Symlinks to Legitimate Paths ---");
    let real_dir = tmp.path().join("real_private_dir");
    std::fs::create_dir(&real_dir).expect("create real dir");
    let safe_symlink = tmp.path().join("safe_link");
    std::os::unix::fs::symlink(&real_dir, &safe_symlink).expect("create safe symlink");
    total += 1;
    match validate_storage_safety(&safe_symlink) {
        Ok(_) => {
            passed += 1;
            println!("[PASS] ACCEPT (expected): Symlink pointing to legitimate private directory");
        }
        Err(e) => panic!("Expected safe symlink to be accepted, got {:?}", e),
    }

    println!("\n=======================================================");
    println!("ALL EMPIRICAL CHALLENGE TESTS PASSED: {}/{} tests OK", passed, total);
    println!("=======================================================");
}
