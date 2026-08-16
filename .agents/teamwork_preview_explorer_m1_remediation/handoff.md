# Milestone 1 Remediation Report: Hardened Storage Safety & Lexical Normalization

## 1. Observation

In the empirical challenge report (`teamwork_preview_challenger_m1_1/handoff.md`), three critical security bypass vectors were identified in `crates/codegen/xai-grok-config/src/platform.rs:403-440` (`validate_storage_safety`):

1. **Dangling Symlink Bypass**:
   `validate_storage_safety` previously only inspected `if let Ok(canon) = std::fs::canonicalize(path)`. When a symlink points to Android shared storage (e.g. `/sdcard/.grok`) where the target does not yet exist on disk, `std::fs::canonicalize(path)` returns `Err(NotFound)`. The function silently ignored the `Err` and returned `Ok(())`, allowing unprivileged world-readable directories to be created subsequently.
2. **Lexical Traversal (`..` & `.`) and Relative Prefix Bypass**:
   Paths with dot-dot traversal components (e.g. `/data/data/com.termux/files/home/../../../../sdcard/.grok` or `/data/data/com.termux/files/home/../../../../storage/1234-5678/.grok`) and relative prefixes (e.g. `sdcard/.grok`, `storage/emulated/0/.grok`) were not lexically resolved, bypassing string prefix checks.
3. **Case Sensitivity Bypass**:
   Case variants such as `/SDCARD/.grok`, `/STORAGE/EMULATED/0/.grok`, and `/MNT/SDCARD/.grok` bypassed case-sensitive string matching while resolving to case-insensitive Android shared filesystems (FAT/sdcardfs/FUSE).

---

## 2. Logic Chain

1. **Root Cause Analysis**:
   - `std::fs::canonicalize` requires target existence on the physical filesystem. Security boundaries must hold *prior* to file creation.
   - String prefix checks (`starts_with("/sdcard/")`) fail when relative components (`..`) or alternative casings (`/SDCARD`) are present.
2. **Remediation Architecture**:
   - **Lexical Normalization (`normalize_lexical`)**: Implemented pure in-memory POSIX path resolution iterating over `std::path::Component` (`RootDir`, `CurDir`, `ParentDir`, `Normal`, `Prefix`). It collapses redundant `.` and resolves `..` against prior normal components without touching disk.
   - **Case-Insensitive Prefix & Subsegment Quarantine (`is_quarantined_str`)**: Lowercases normalized paths and verifies against both absolute and relative Android shared storage prefixes (`/sdcard`, `/storage`, `/mnt/sdcard`, `/mnt/media_rw`, `/data/sdcard`, `/data/media`, `sdcard`, `storage`, `mnt/sdcard`, `mnt/media_rw`), plus subsegments (`/storage/`, `/storage/emulated`, `/storage/self`).
   - **Symlink Inode Inspection (`read_link`)**: Checks `symlink_metadata(path)` directly. If `path` is a symlink (even dangling), reads the raw destination via `std::fs::read_link(path)`, resolves relative destinations against the parent directory, and validates the target recursively (bounded by `depth <= 32` against circular links).
   - **Ancestor Symlink Traversal**: If `canonicalize` fails on a non-existent child (e.g. `dir_symlink/sub/credentials.json` where `dir_symlink -> /sdcard`), the function walks up existing ancestor directories, detects symlinked ancestors, and validates the reconstructed path against the quarantine.

---

## 3. Caveats

- Symlink recursion is capped at 32 iterations to prevent denial-of-service via circular symlinks (`a -> b -> a`).
- `normalize_lexical` operates strictly on path syntax. When physical directories exist on disk with complex bind-mounts or intermediate symlinks, step 3 (`std::fs::canonicalize`) and step 4 (ancestor canonicalization) provide secondary verification.
- No caveats regarding platform compatibility: this implementation uses standard library primitives (`std::path`, `std::fs`) without introducing external runtime dependencies.

---

## 4. Conclusion & Exact Proposed Patch

The remediation is complete, self-contained, and verified across 50+ test vectors.

The patch is saved at:
`/Users/iml1s/Documents/mine/grok-build-termux/.agents/teamwork_preview_explorer_m1_remediation/storage_safety_hardening.patch`

### Exact Code Diff

```diff
diff --git a/crates/codegen/xai-grok-config/src/platform.rs b/crates/codegen/xai-grok-config/src/platform.rs
--- a/crates/codegen/xai-grok-config/src/platform.rs
+++ b/crates/codegen/xai-grok-config/src/platform.rs
@@ -1,7 +1,7 @@
 //! Platform capability detection and dynamic environment resolution for Grok.
 
 use std::collections::HashMap;
-use std::path::{Path, PathBuf};
+use std::path::{Component, Path, PathBuf};
 use std::sync::OnceLock;
 use thiserror::Error;
 
@@ -390,44 +390,147 @@ impl PlatformCapabilities {
 /// Known Android shared storage path prefixes and subsegments that lack POSIX DAC permissions.
 const ANDROID_SHARED_STORAGE_PREFIXES: &[&str] = &[
     "/sdcard",
-    "/storage/emulated",
-    "/storage/self",
+    "/storage",
     "/mnt/sdcard",
     "/mnt/media_rw",
-    "/storage",
+    "/data/sdcard",
+    "/data/media",
+    "sdcard",
+    "storage",
+    "mnt/sdcard",
+    "mnt/media_rw",
+    "data/sdcard",
+    "data/media",
 ];
 
+/// Lexically normalize a path by resolving `.` and `..` components without requiring disk access.
+pub fn normalize_lexical(path: &Path) -> PathBuf {
+    let mut normalized = PathBuf::new();
+    let mut is_absolute = false;
+
+    for component in path.components() {
+        match component {
+            Component::Prefix(prefix) => {
+                normalized.push(prefix.as_os_str());
+            }
+            Component::RootDir => {
+                normalized.push(Component::RootDir.as_os_str());
+                is_absolute = true;
+            }
+            Component::CurDir => {
+                // Ignore '.'
+            }
+            Component::ParentDir => {
+                let pop_success = match normalized.components().last() {
+                    Some(Component::Normal(_)) => {
+                        normalized.pop();
+                        true
+                    }
+                    _ => false,
+                };
+                if !pop_success && !is_absolute {
+                    normalized.push(Component::ParentDir.as_os_str());
+                }
+            }
+            Component::Normal(c) => {
+                normalized.push(c);
+            }
+        }
+    }
+    normalized
+}
+
+/// Helper to check if a string representation of a normalized path matches any quarantine prefix or pattern.
+fn is_quarantined_str(norm_str: &str) -> bool {
+    let lower = norm_str.to_lowercase();
+    let lower = lower.replace('\\', "/");
+
+    for prefix in ANDROID_SHARED_STORAGE_PREFIXES {
+        if lower == *prefix
+            || lower.starts_with(&format!("{prefix}/"))
+            || (prefix.starts_with('/') && lower.starts_with(prefix))
+        {
+            return true;
+        }
+    }
+
+    if lower.contains("/sdcard")
+        || lower.contains("/storage/")
+        || lower == "/storage"
+        || lower.contains("/storage/emulated")
+        || lower.contains("/storage/self")
+        || lower.contains("/mnt/sdcard")
+        || lower.contains("/mnt/media_rw")
+    {
+        return true;
+    }
+
+    false
+}
+
 /// Validates that a path is safe for storing private keys, credentials, or state.
 ///
 /// Strictly refuses Android shared storage paths to prevent world-readable leaks.
 pub fn validate_storage_safety(path: &Path) -> Result<(), StorageSafetyError> {
-    let path_str = path.to_string_lossy();
-    let norm = path_str.replace('\\', "/");
-
-    for prefix in ANDROID_SHARED_STORAGE_PREFIXES {
-        if norm == *prefix
-            || norm.starts_with(&format!("{prefix}/"))
-            || norm.starts_with(prefix)
-            || norm.contains("/sdcard")
-            || norm.contains("/storage/emulated/0")
-        {
-            return Err(StorageSafetyError::SharedStorageQuarantine {
-                path: path.to_path_buf(),
-                reason: "Android shared storage does not enforce POSIX user/group permissions and is accessible across apps.",
-            });
-        }
-    }
-
-    // If the path exists on disk, also check its canonicalized target in case of symlinks
+    validate_storage_safety_depth(path, 0)
+}
+
+fn validate_storage_safety_depth(path: &Path, depth: usize) -> Result<(), StorageSafetyError> {
+    if depth > 32 {
+        // Prevent infinite symlink recursion loops
+        return Ok(());
+    }
+
+    // 1. Lexical normalization & check on the provided path
+    let normalized = normalize_lexical(path);
+    let norm_str = normalized.to_string_lossy();
+    if is_quarantined_str(&norm_str) {
+        return Err(StorageSafetyError::SharedStorageQuarantine {
+            path: path.to_path_buf(),
+            reason: "Android shared storage does not enforce POSIX user/group permissions and is accessible across apps.",
+        });
+    }
+
+    // 2. Direct symlink inspection (handles existing AND dangling symlinks)
+    let is_link = path.is_symlink()
+        || std::fs::symlink_metadata(path)
+            .map(|m| m.file_type().is_symlink())
+            .unwrap_or(false);
+
+    if is_link {
+        if let Ok(link_dest) = std::fs::read_link(path) {
+            let resolved_dest = if link_dest.is_relative() {
+                if let Some(parent) = path.parent() {
+                    parent.join(&link_dest)
+                } else {
+                    link_dest
+                }
+            } else {
+                link_dest
+            };
+
+            if let Err(StorageSafetyError::SharedStorageQuarantine { reason, .. }) =
+                validate_storage_safety_depth(&resolved_dest, depth + 1)
+            {
+                return Err(StorageSafetyError::SharedStorageQuarantine {
+                    path: path.to_path_buf(),
+                    reason,
+                });
+            }
+        }
+    }
+
+    // 3. Full disk canonicalization if the target already exists on disk
     if let Ok(canon) = std::fs::canonicalize(path) {
-        let canon_str = canon.to_string_lossy().replace('\\', "/");
-        for prefix in ANDROID_SHARED_STORAGE_PREFIXES {
-            if canon_str == *prefix
-                || canon_str.starts_with(&format!("{prefix}/"))
-                || canon_str.starts_with(prefix)
-                || canon_str.contains("/sdcard")
-                || canon_str.contains("/storage/emulated/0")
-            {
+        let canon_norm = normalize_lexical(&canon);
+        let canon_str = canon_norm.to_string_lossy();
+        if is_quarantined_str(&canon_str) {
+            return Err(StorageSafetyError::SharedStorageQuarantine {
+                path: path.to_path_buf(),
+                reason: "Canonical target resolves to Android shared storage which lacks POSIX permissions.",
+            });
+        }
+    } else {
+        // 4. Ancestor inspection for non-existent targets inside symlinked parent directories
+        let mut current = path;
+        while let Some(parent) = current.parent() {
+            if parent.as_os_str().is_empty() || parent == Path::new("/") {
+                break;
+            }
+
+            let parent_is_link = parent.is_symlink()
+                || std::fs::symlink_metadata(parent)
+                    .map(|m| m.file_type().is_symlink())
+                    .unwrap_or(false);
+
+            if parent_is_link {
+                if let Ok(link_dest) = std::fs::read_link(parent) {
+                    let resolved_dest = if link_dest.is_relative() {
+                        if let Some(p) = parent.parent() {
+                            p.join(&link_dest)
+                        } else {
+                            link_dest
+                        }
+                    } else {
+                        link_dest
+                    };
+
+                    if let Ok(rel) = path.strip_prefix(parent) {
+                        let reconstructed = resolved_dest.join(rel);
+                        if let Err(StorageSafetyError::SharedStorageQuarantine { reason, .. }) =
+                            validate_storage_safety_depth(&reconstructed, depth + 1)
+                        {
+                            return Err(StorageSafetyError::SharedStorageQuarantine {
+                                path: path.to_path_buf(),
+                                reason,
+                            });
+                        }
+                    }
+                }
+            } else if let Ok(canon_parent) = std::fs::canonicalize(parent) {
+                if let Ok(rel) = path.strip_prefix(parent) {
+                    let reconstructed = canon_parent.join(rel);
+                    let canon_norm = normalize_lexical(&reconstructed);
+                    let canon_str = canon_norm.to_string_lossy();
+                    if is_quarantined_str(&canon_str) {
+                        return Err(StorageSafetyError::SharedStorageQuarantine {
+                            path: path.to_path_buf(),
+                            reason: "Canonical target resolves to Android shared storage which lacks POSIX permissions.",
+                        });
+                    }
+                }
+                break;
+            }
+            current = parent;
+        }
+    }
+
     Ok(())
 }
@@ -635,6 +785,11 @@ mod tests {
         assert!(validate_storage_safety(Path::new("/mnt/sdcard/grok")).is_err());
         assert!(validate_storage_safety(Path::new("/storage/self/primary/.grok")).is_err());
         assert!(validate_storage_safety(Path::new("/mnt/media_rw/sdcard0")).is_err());
+        assert!(validate_storage_safety(Path::new("sdcard/.grok")).is_err());
+        assert!(validate_storage_safety(Path::new("storage/emulated/0/.grok")).is_err());
+        assert!(validate_storage_safety(Path::new("/SDCARD/.grok")).is_err());
+        assert!(validate_storage_safety(Path::new("/STORAGE/EMULATED/0/.grok")).is_err());
+        assert!(validate_storage_safety(Path::new("/data/data/com.termux/files/home/../../../../sdcard/.grok")).is_err());
         assert!(validate_storage_safety(Path::new("/data/data/com.termux/files/home/.grok")).is_ok());
         assert!(validate_storage_safety(Path::new("/home/user/.grok")).is_ok());
         assert!(validate_storage_safety(Path::new("/Users/user/.grok")).is_ok());
diff --git a/crates/codegen/xai-grok-config/tests/platform_adversarial.rs b/crates/codegen/xai-grok-config/tests/platform_adversarial.rs
--- a/crates/codegen/xai-grok-config/tests/platform_adversarial.rs
+++ b/crates/codegen/xai-grok-config/tests/platform_adversarial.rs
@@ -191,12 +191,17 @@ fn test_adversarial_dangling_symlink_vulnerability() {
         // Symlink points to non-existent /sdcard/.grok
         symlink("/sdcard/.grok", &symlink_path).expect("Failed to create symlink");
 
-        let res = validate_storage_safety(&symlink_path);
-        println!("Result of validate_storage_safety on dangling symlink to /sdcard/.grok: {:?}", res);
+        let res = validate_storage_safety(&symlink_path);
+        assert!(
+            res.is_err(),
+            "Dangling symlink pointing to /sdcard/.grok must be quarantined"
+        );
+        match res.unwrap_err() {
+            StorageSafetyError::SharedStorageQuarantine { path, reason } => {
+                assert_eq!(path, symlink_path);
+                assert!(!reason.is_empty());
+            }
+        }
     }
 }
 
@@ -207,13 +212,19 @@ fn test_adversarial_path_traversal_vulnerability() {
         "/data/data/com.termux/files/home/../../../../sdcard/.grok",
         "/data/data/com.termux/files/home/../../../../storage/emulated/1/.grok",
         "/data/data/com.termux/files/home/../../../../storage/1234-5678/.grok",
+        "/data/data/com.termux/files/home/././../../../../sdcard",
         "sdcard/.grok",
         "storage/emulated/0/.grok",
     ];
 
     for path in traversal_paths {
         let res = validate_storage_safety(Path::new(path));
-        println!("Result of validate_storage_safety for traversal '{}': {:?}", path, res);
+        assert!(
+            res.is_err(),
+            "Expected traversal path '{}' to be quarantined, got {:?}",
+            path,
+            res
+        );
     }
 }
 
@@ -225,11 +236,19 @@ fn test_adversarial_case_insensitivity_vulnerability() {
         "/STORAGE/EMULATED/0/.grok",
         "/Storage/Emulated/0/.grok",
         "/MNT/SDCARD/.grok",
+        "/Mnt/Media_Rw/test",
+        "SDCARD/.grok",
+        "Storage/Emulated/0/.grok",
     ];
 
     for path in uppercase_paths {
         let res = validate_storage_safety(Path::new(path));
-        println!("Result of validate_storage_safety for case variant '{}': {:?}", path, res);
+        assert!(
+            res.is_err(),
+            "Expected uppercase/case-variant path '{}' to be quarantined, got {:?}",
+            path,
+            res
+        );
     }
 }
```

---

## 5. Verification Method

### 5.1 Standalone Test Harness Verification
The standalone test harness in `.agents/teamwork_preview_explorer_m1_remediation/scratch/test_harness.rs` was compiled and executed:
```bash
rustc .agents/teamwork_preview_explorer_m1_remediation/scratch/test_harness.rs -o .agents/teamwork_preview_explorer_m1_remediation/scratch/test_harness
.agents/teamwork_preview_explorer_m1_remediation/scratch/test_harness
```
Output:
```
Running extended test harness for validate_storage_safety...
✓ All 50 unsafe path variants correctly quarantined
✓ All 10 safe path variants correctly allowed
✓ Dangling symlink to /sdcard/.grok correctly quarantined
✓ Symlink to safe path correctly allowed
✓ Symlink chain correctly quarantined
✓ Non-existent nested path under symlinked directory correctly quarantined

ALL EXTENDED TEST HARNESS ASSERTIONS PASSED!
```

### 5.2 Patch Application & Project Test Verification
Apply the patch and run the full test suite:
```bash
# 1. Verify patch applicability
git apply --check .agents/teamwork_preview_explorer_m1_remediation/storage_safety_hardening.patch

# 2. Apply patch (when executing implementation)
git apply .agents/teamwork_preview_explorer_m1_remediation/storage_safety_hardening.patch

# 3. Run unit and adversarial tests
cargo test -p xai-grok-config
cargo test --test platform_adversarial -- --nocapture

# 4. Verify Android target check
cargo check --target aarch64-linux-android -p xai-grok-config
```
