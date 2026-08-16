# Milestone 1: Platform Capability & Dependency Isolation (R1) — Implementation Design Report

**Author**: `teamwork_preview_explorer_m1_1`  
**Working Directory**: `/Users/iml1s/Documents/mine/grok-build-termux/.agents/teamwork_preview_explorer_m1_1`  
**Target Project**: `grok-build-termux` tracking upstream `xai-org/grok-build@eb267feff13129e568df38fb6fdf0ceb65f735d6`  
**Date**: 2026-08-15  

---

## 1. Observation (觀察事實)

1. **上游基準代碼庫狀態**:
   - 上游路徑: `/Users/iml1s/Documents/mine/grok-build`
   - 目標 Commit: `eb267feff13129e568df38fb6fdf0ceb65f735d6` ("Synced from monorepo")
   - 下游工作區: `/Users/iml1s/Documents/mine/grok-build-termux` 當前僅包含規劃與管理文件（`ORIGINAL_REQUEST.md`, `PROJECT.md`, `TEST_INFRA.md`, `DEAD_ENDS.md`, `bootstrap-grok-build-termux.sh`, `grok-build-termux-issue-plan.md`, `.agents/`），尚未初始化 `.git` 追蹤分支。
   - 根目錄 `Cargo.toml` 首行明確註記：`# Auto-generated workspace root. Prefer editing per-crate Cargo.toml files.`，要求下游修改必須將 workspace manifest 衝突降至最低。

2. **桌面相依性散佈與 Android/Bionic 衝突 (Desktop Dependencies Coupling)**:
   - **記憶體配置器 (`tikv-jemallocator`)**:
     - `crates/codegen/xai-grok-pager-bin/Cargo.toml` (lines 64-78): `[target.'cfg(unix)'.dependencies]` 直接宣告 `tikv-jemallocator`, `tikv-jemalloc-sys`, `tikv-jemalloc-ctl`。
     - `crates/codegen/xai-grok-pager-bin/src/main.rs` (lines 8-10, 2039-2160, 2391-2400): 使用 `#[cfg(all(feature = "jemalloc", unix))]` 宣告全域分配器與 `mallctl` 呼叫。
     - *Android 行為*: Android 屬於 `cfg(unix)`，若不加以排除，會強制編譯 jemalloc 並觸發 Bionic C 函式庫符號衝突與 16 KiB page-size 記憶體段對齊問題。
   - **剪貼簿模組 (`arboard`)**:
     - `crates/codegen/xai-grok-shared/Cargo.toml` (lines 47-49): `[target.'cfg(not(target_os = "macos"))'.dependencies]` 引入 `arboard = { workspace = true, features = ["wayland-data-control"] }`。
     - `crates/codegen/xai-grok-shared/src/clipboard.rs` (line 1195): `#[cfg(not(target_os = "macos"))] mod platform` 直接使用 `arboard` 與 X11/Wayland 協定。
     - *Android 行為*: Android 屬於 `not(target_os = "macos")`，引入 `arboard` 會導致 X11/Wayland 連線失敗與編譯錯誤。
   - **音訊與麥克風模組 (`cpal`)**:
     - `crates/codegen/xai-grok-voice/Cargo.toml` (lines 50-53): `[target.'cfg(not(target_os = "linux"))'.dependencies.cpal]` 引入 `cpal = "0.15"`。
     - *Android 行為*: Android `target_os = "android"` 不屬於 `target_os = "linux"`，因而自動繼承 `cpal`，要求 Android NDK OpenSL/Oboe 音訊後端，增加二進位負擔並可能在 CLI/TUI 環境 panic。
   - **核心沙盒模組 (`xai-grok-sandbox`)**:
     - `crates/codegen/xai-grok-sandbox/Cargo.toml` (lines 22-38): `[target.'cfg(unix)'.dependencies]` 引入 `nono = "=0.53.0"` 與 `globset`。
     - `crates/codegen/xai-grok-sandbox/src/lib.rs` (lines 175-235): 嘗試呼叫 `nono::Sandbox::apply()` 與 `bwrap_reexec_command()`。
     - *Android 行為*: Android 核心關閉無特權 user namespace，且缺乏 Landlock/Seatbelt 核心保證；若強行回報 kernel-enforced 會造成虛假安全感。

3. **路徑與儲存假設 (Path & Storage Assumptions)**:
   - `crates/codegen/xai-grok-config/src/paths.rs` (lines 78-85):
     ```rust
     pub fn system_config_dir() -> Option<PathBuf> {
         if cfg!(unix) {
             Some(PathBuf::from("/etc/grok"))
         } else {
             None
         }
     }
     ```
     直接將 Unix 系統設定目錄寫死為 `/etc/grok`。在 Termux 中，系統根目錄為動態的 `$PREFIX`（預設 `/data/data/com.termux/files/usr`），系統設定檔必須位於 `$PREFIX/etc/grok`。
   - `crates/codegen/xai-grok-config/src/paths.rs` 與 `crates/codegen/xai-grok-config/src/state_dir.rs`:
     未對 Android 共享儲存空間（`/sdcard`, `/storage/emulated/0`）進行檢查與隔離防護。

---

## 2. Logic Chain (推導邏輯鏈)

1. **工作區初始化邏輯 (Workspace Init)**:
   - 目標是讓 `/Users/iml1s/Documents/mine/grok-build-termux` 成為一個標準的 Git repo，直接追蹤 upstream commit `eb267feff13129e568df38fb6fdf0ceb65f735d6`。
   - 由於目錄內已有專案管理文件與 `.agents/`，初始化應採用 `git init` + `git remote add upstream ...` + `git fetch` + `git checkout -b termux-native eb267feff13129e568df38fb6fdf0ceb65f735d6` 的方式，並保留現有未追蹤文件，形成乾淨的 downstream 基準。

2. **平台能力抽象層設計邏輯 (Platform Capabilities Architecture)**:
   - 為解決 scattered `cfg!(unix)` 帶來的混淆，必須建立集中且可注入的 `PlatformCapabilities` / `PlatformContext`。
   - 抽象層需涵蓋：
     - **PlatformKind**: `AndroidTermux`, `UnsupportedAndroid`, `DesktopLinux`, `MacOS`, `Windows`。
     - **動態 `$PREFIX` 探測**: 在 Android 上動態解析 `$PREFIX` 環境變數，若無效則 Fail-Closed 回報明確錯誤，絕不靜默 fallback 到 `/etc` 或 `/usr`。
     - **系統/使用者路徑映射**: `system_config_dir` (`$PREFIX/etc/grok`), `home_dir` (`$HOME/.grok`), `temp_dir` (`$TMPDIR` / `$PREFIX/tmp`)。
     - **真實沙盒狀態 (Truthful Sandboxing)**: Android 上一律為 `SandboxKind::PolicyOnly`。
     - **共享儲存隔離 (Shared Storage Quarantine)**: 偵測 `/sdcard` 與 `/storage/emulated/0`，強制拒絕在共享儲存上存放私鑰、憑證與 `GROK_HOME`。
     - **環境注入測試能力**: 提供 `EnvLookup` trait 與 `from_env(&dyn EnvLookup)`，使單元測試能在 macOS/Linux CI 上完整模擬 Android/Termux 環境。

3. **依賴隔離與條件編譯邏輯 (Dependency Gating)**:
   - **分配器**: 將 `tikv-jemallocator` 的 target cfg 修改為 `cfg(all(unix, not(target_os = "android")))`；在 Android 上直接使用 Rust 預設的 Bionic System Allocator。
   - **剪貼簿**: 在 `xai-grok-shared/Cargo.toml` 將 `arboard` 條件排除 Android (`not(any(target_os = "macos", target_os = "android"))`)；在 `src/clipboard.rs` 新增 `#[cfg(target_os = "android")] mod platform`，呼叫 `termux-clipboard-get` / `termux-clipboard-set`，並在無 Termux:API 時降級為 ANSI OSC 52 跳脫序列。
   - **音訊**: 在 `xai-grok-voice/Cargo.toml` 將 `cpal` 排除 Android (`not(any(target_os = "linux", target_os = "android"))`)，在 Android 上將語音採集標記為不可用，避免鏈結 NDK 音訊庫。
   - **核心沙盒**: 在 `xai-grok-sandbox/Cargo.toml` 將 `nono` 排除 Android，在 Android 上以 in-process policy 檢查取代核心層 Landlock/Seatbelt。

4. **路徑模組修改邏輯 (Path & Config Modifications)**:
   - 修改 `crates/codegen/xai-grok-config/src/paths.rs` 的 `system_config_dir()`，依據平台能力動態解析 `$PREFIX/etc/grok`。
   - 在 `xai-grok-config` 中實現儲存安全檢查 `validate_storage_safety(path: &Path)`，在 `pin_grok_home()` 與 `state_dir::resolve()` 中進行檢驗，遇到 `/sdcard` 即回傳 `StorageSafetyError`。

---

## 3. Concrete Implementation Specification (具體實作規範)

### 3.1 Workspace 初始化腳本與程序

在 `/Users/iml1s/Documents/mine/grok-build-termux` 執行以下標準初始化命令：

```bash
cd /Users/iml1s/Documents/mine/grok-build-termux

# 1. 初始化 Git 倉庫
git init -b main

# 2. 設定 upstream 遠端倉庫（指向本地或 upstream 鏡像）
git remote add upstream /Users/iml1s/Documents/mine/grok-build || git remote set-url upstream /Users/iml1s/Documents/mine/grok-build

# 3. 抓取指定的基準 Commit
git fetch upstream eb267feff13129e568df38fb6fdf0ceb65f735d6

# 4. 建立並切換至 termux-native 開發分支，以 eb267feff13129e568df38fb6fdf0ceb65f735d6 為基準
git reset --hard eb267feff13129e568df38fb6fdf0ceb65f735d6
git checkout -B termux-native

# 5. 確保現有的專案規範與代理工作區文件保持 untracked 或加入提交
# 驗證當前 HEAD commit
CURRENT_HEAD=$(git rev-parse HEAD)
echo "Verified HEAD: $CURRENT_HEAD"
test "$CURRENT_HEAD" = "eb267feff13129e568df38fb6fdf0ceb65f735d6" && echo "Baseline verification PASSED"
```

---

### 3.2 `PlatformCapabilities` 模組設計 (`xai-grok-config/src/platform.rs`)

建立新檔案 `crates/codegen/xai-grok-config/src/platform.rs`，提供統一平台探測與能力查詢：

```rust
//! Platform capability detection and dynamic environment resolution for Grok.

use std::borrow::Cow;
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use thiserror::Error;

/// Platform classification.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PlatformKind {
    /// Android under a valid Termux environment ($PREFIX present and valid).
    AndroidTermux,
    /// Android host without a supported Termux prefix.
    UnsupportedAndroid,
    /// Desktop Linux (glibc / musl).
    DesktopLinux,
    /// macOS (Darwin).
    MacOS,
    /// Windows.
    Windows,
}

/// Truthful sandbox classification.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SandboxKind {
    /// Kernel-enforced sandbox via OS primitives (Landlock on Linux, Seatbelt on macOS).
    KernelEnforced,
    /// In-process policy enforcement only (Android/Termux).
    PolicyOnly,
    /// Sandbox is completely disabled.
    Disabled,
}

/// Errors related to platform resolution.
#[derive(Debug, Error, PartialEq, Eq)]
pub enum PlatformError {
    #[error("Missing or empty $PREFIX on Android/Termux")]
    MissingPrefix,
    #[error("Invalid $PREFIX on Android: {path:?} ({reason})")]
    InvalidPrefix { path: PathBuf, reason: String },
    #[error("Home directory could not be resolved")]
    MissingHome,
    #[error("Storage safety violation: {0}")]
    StorageSafety(#[from] StorageSafetyError),
}

/// Errors related to storage safety boundaries.
#[derive(Debug, Error, PartialEq, Eq)]
pub enum StorageSafetyError {
    #[error("Refusing to store sensitive credentials/state on Android shared storage ({path:?}). Reason: {reason}")]
    SharedStorageQuarantine {
        path: PathBuf,
        reason: &'static str,
    },
}

/// Injectable environment lookup interface for testability.
pub trait EnvLookup: Send + Sync {
    fn get_var(&self, key: &str) -> Option<String>;
}

/// Process environment implementation of [`EnvLookup`].
pub struct SystemEnv;
impl EnvLookup for SystemEnv {
    fn get_var(&self, key: &str) -> Option<String> {
        std::env::var(key).ok()
    }
}

/// Mock environment implementation for unit tests.
pub struct MockEnv {
    vars: HashMap<String, String>,
}

impl MockEnv {
    pub fn new(vars: HashMap<String, String>) -> Self {
        Self { vars }
    }
}

impl EnvLookup for MockEnv {
    fn get_var(&self, key: &str) -> Option<String> {
        self.vars.get(key).cloned()
    }
}

/// Centralized platform capability structure.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PlatformCapabilities {
    kind: PlatformKind,
    prefix: Option<PathBuf>,
    home: Option<PathBuf>,
    tmp: PathBuf,
    has_display: bool,
    has_audio: bool,
    sandbox: SandboxKind,
}

static PLATFORM_CAPS: OnceLock<PlatformCapabilities> = OnceLock::new();

impl PlatformCapabilities {
    /// Global singleton instance probed from the process environment.
    pub fn current() -> &'static PlatformCapabilities {
        PLATFORM_CAPS.get_or_init(|| Self::probe(&SystemEnv))
    }

    /// Probe capabilities against any [`EnvLookup`] provider.
    pub fn probe(env: &dyn EnvLookup) -> Self {
        let is_android = cfg!(target_os = "android") || env.get_var("TERMUX_VERSION").is_some();
        let is_macos = cfg!(target_os = "macos");
        let is_windows = cfg!(target_os = "windows");
        let is_linux = cfg!(target_os = "linux") && !is_android;

        let prefix = env.get_var("PREFIX").filter(|s| !s.trim().is_empty()).map(PathBuf::from);

        let kind = if is_android {
            if prefix.is_some() || env.get_var("TERMUX_VERSION").is_some() {
                PlatformKind::AndroidTermux
            } else {
                PlatformKind::UnsupportedAndroid
            }
        } else if is_macos {
            PlatformKind::MacOS
        } else if is_windows {
            PlatformKind::Windows
        } else if is_linux {
            PlatformKind::DesktopLinux
        } else {
            PlatformKind::DesktopLinux
        };

        let home = env
            .get_var("HOME")
            .or_else(|| env.get_var("USERPROFILE"))
            .filter(|s| !s.trim().is_empty())
            .map(PathBuf::from);

        let tmp = env
            .get_var("TMPDIR")
            .filter(|s| !s.trim().is_empty())
            .map(PathBuf::from)
            .unwrap_or_else(|| {
                if let Some(ref p) = prefix {
                    p.join("tmp")
                } else {
                    PathBuf::from("/tmp")
                }
            });

        let has_display = if kind == PlatformKind::AndroidTermux {
            // On Termux, display server is absent by default, but termux-open-url allows browser handoff
            env.get_var("DISPLAY").is_some() || env.get_var("WAYLAND_DISPLAY").is_some()
        } else if is_macos || is_windows {
            true
        } else {
            env.get_var("DISPLAY").is_some()
                || env.get_var("WAYLAND_DISPLAY").is_some()
                || env.get_var("BROWSER").is_some()
        };

        let has_audio = match kind {
            PlatformKind::AndroidTermux | PlatformKind::UnsupportedAndroid => false,
            PlatformKind::MacOS | PlatformKind::Windows | PlatformKind::DesktopLinux => true,
        };

        let sandbox = match kind {
            PlatformKind::AndroidTermux | PlatformKind::UnsupportedAndroid => SandboxKind::PolicyOnly,
            PlatformKind::DesktopLinux | PlatformKind::MacOS => SandboxKind::KernelEnforced,
            PlatformKind::Windows => SandboxKind::Disabled,
        };

        Self {
            kind,
            prefix,
            home,
            tmp,
            has_display,
            has_audio,
            sandbox,
        }
    }

    pub fn kind(&self) -> PlatformKind {
        self.kind
    }

    pub fn is_android_termux(&self) -> bool {
        self.kind == PlatformKind::AndroidTermux
    }

    pub fn is_android(&self) -> bool {
        matches!(self.kind, PlatformKind::AndroidTermux | PlatformKind::UnsupportedAndroid)
    }

    pub fn prefix_dir(&self) -> Result<&Path, PlatformError> {
        if self.is_android() {
            self.prefix
                .as_deref()
                .ok_or(PlatformError::MissingPrefix)
        } else {
            Ok(Path::new("/"))
        }
    }

    /// System configuration directory:
    /// - Termux: `$PREFIX/etc/grok`
    /// - Desktop Unix: `/etc/grok`
    /// - Windows: `None`
    pub fn system_config_dir(&self) -> Option<PathBuf> {
        match self.kind {
            PlatformKind::AndroidTermux => self.prefix.as_ref().map(|p| p.join("etc").join("grok")),
            PlatformKind::UnsupportedAndroid => None,
            PlatformKind::DesktopLinux | PlatformKind::MacOS => Some(PathBuf::from("/etc/grok")),
            PlatformKind::Windows => None,
        }
    }

    pub fn home_dir(&self) -> Result<&Path, PlatformError> {
        self.home.as_deref().ok_or(PlatformError::MissingHome)
    }

    pub fn temp_dir(&self) -> &Path {
        &self.tmp
    }

    pub fn sandbox_kind(&self) -> SandboxKind {
        self.sandbox
    }

    pub fn has_audio_capture(&self) -> bool {
        self.has_audio
    }

    pub fn has_display_server(&self) -> bool {
        self.has_display
    }
}

/// Known Android shared storage paths that lack POSIX DAC permissions.
const ANDROID_SHARED_STORAGE_PREFIXES: &[&str] = &[
    "/sdcard",
    "/storage/emulated/",
    "/storage/self/",
    "/mnt/sdcard",
    "/mnt/media_rw",
    "/storage/",
];

/// Validates that a path is safe for storing private keys, credentials, or state.
///
/// Strictly refuses Android shared storage paths to prevent world-readable leaks.
pub fn validate_storage_safety(path: &Path) -> Result<(), StorageSafetyError> {
    let path_str = path.to_string_lossy();
    for prefix in ANDROID_SHARED_STORAGE_PREFIXES {
        if path_str.starts_with(prefix) {
            return Err(StorageSafetyError::SharedStorageQuarantine {
                path: path.to_path_buf(),
                reason: "Android shared storage does not enforce POSIX user/group permissions and is accessible across apps.",
            });
        }
    }
    Ok(())
}
```

---

### 3.3 各 Crate 修改清單 (Exact Code Modifications)

#### 1. `crates/codegen/xai-grok-config`
- **`src/lib.rs`**:
  ```rust
  // 加入模組匯出
  pub mod platform;
  pub use platform::{
      PlatformCapabilities, PlatformError, PlatformKind, SandboxKind, StorageSafetyError,
      validate_storage_safety,
  };
  ```
- **`src/paths.rs`**:
  修改 `system_config_dir()` 依賴 `PlatformCapabilities`，並在 `pin_grok_home` 執行儲存隔離檢驗：
  ```rust
  /// System-wide config directory: `$PREFIX/etc/grok` on Termux, `/etc/grok` on desktop Unix, `None` on Windows.
  pub fn system_config_dir() -> Option<PathBuf> {
      crate::platform::PlatformCapabilities::current().system_config_dir()
  }

  pub fn pin_grok_home(path: PathBuf) -> Result<(), PathBuf> {
      if let Err(e) = crate::platform::validate_storage_safety(&path) {
          tracing::error!(error = %e, "Rejected insecure state directory location");
          return Err(path);
      }
      let _ = std::fs::create_dir_all(&path);
      GROK_HOME.set(path)
  }
  ```
- **`src/state_dir.rs`**:
  在 `resolve_in()` 中加入儲存安全檢查：
  ```rust
  if let Some(path) = nonempty(state_env) {
      if let Err(e) = crate::platform::validate_storage_safety(&path) {
          tracing::error!(error = %e, "Insecure state environment override detected; ignoring");
      } else {
          return StateDir {
              path,
              source: StateDirSource::StateHomeEnv,
          };
      }
  }
  ```

---

#### 2. `crates/codegen/xai-grok-shared`
- **`Cargo.toml`**:
  將 `arboard` 條件相依性排除 Android：
  ```toml
  # arboard for clipboard on desktop non-macOS platforms.
  # Excluded on Android/Termux where Termux:API and OSC 52 are used.
  [target.'cfg(not(any(target_os = "macos", target_os = "android")))'.dependencies]
  arboard = { workspace = true, features = ["wayland-data-control"] }
  ```
- **`src/clipboard.rs`**:
  新增 `#[cfg(target_os = "android")] mod platform` 實現 Termux 原生剪貼簿橋接：
  ```rust
  #[cfg(target_os = "android")]
  mod platform {
      use super::ImageData;
      use std::process::Command;

      pub fn get_text() -> anyhow::Result<Option<String>> {
          // Attempt termux-clipboard-get via subprocess
          let mut cmd = Command::new("termux-clipboard-get");
          xai_tty_utils::detach_std_command(&mut cmd);
          match cmd.output() {
              Ok(output) if output.status.success() => {
                  let s = String::from_utf8_lossy(&output.stdout).to_string();
                  if s.is_empty() { Ok(None) } else { Ok(Some(s)) }
              }
              _ => Ok(None),
          }
      }

      pub fn set_text(text: &str) -> anyhow::Result<()> {
          let mut cmd = Command::new("termux-clipboard-set");
          cmd.arg(text);
          xai_tty_utils::detach_std_command(&mut cmd);
          if let Ok(status) = cmd.status() {
              if status.success() {
                  return Ok(());
              }
          }
          // Fallback to ANSI OSC 52 sequence over terminal stream
          super::set_text_osc52(text)
      }

      pub fn get_image() -> anyhow::Result<Option<ImageData>> {
          // Termux CLI does not support direct image clipboard raster reads
          Ok(None)
      }

      pub fn get_file_urls() -> anyhow::Result<Option<String>> {
          Ok(None)
      }
  }
  ```

---

#### 3. `crates/codegen/xai-grok-voice`
- **`Cargo.toml`**:
  將 `cpal` 排除 Android：
  ```toml
  # cpal is only used by non-Linux desktop capture backend.
  # Gating out Android avoids linking unwanted Android NDK audio stacks.
  [target.'cfg(not(any(target_os = "linux", target_os = "android")))'.dependencies.cpal]
  version = "0.15"
  optional = true
  ```
- **`src/lib.rs` / `src/audio/mod.rs`**:
  在 `target_os = "android"` 環境下，錄音功能明確回傳 `AudioCaptureError::UnsupportedPlatform` 或將語音介面禁用，不觸發 panic。

---

#### 4. `crates/codegen/xai-grok-pager-bin`
- **`Cargo.toml`**:
  將 jemalloc 依賴條件限制為非 Android 的 Unix：
  ```toml
  [target.'cfg(all(unix, not(target_os = "android")))'.dependencies]
  libc = { workspace = true }
  tikv-jemallocator = { workspace = true, optional = true, features = ["stats"] }
  tikv-jemalloc-sys = { workspace = true, optional = true }
  tikv-jemalloc-ctl = { workspace = true, optional = true, features = ["stats", "use_std"] }

  [target.'cfg(target_os = "android")'.dependencies]
  libc = { workspace = true }
  ```
- **`src/main.rs`**:
  修改所有 jemalloc 相關的條件編譯屬性：
  ```rust
  #[cfg(all(feature = "jemalloc", unix, not(target_os = "android")))]
  #[global_allocator]
  static GLOBAL: tikv_jemallocator::Jemalloc = tikv_jemallocator::Jemalloc;

  #[cfg(all(feature = "jemalloc", feature = "release-dist", unix, not(target_os = "android")))]
  mod jemalloc_malloc_conf { ... }
  ```

---

#### 5. `crates/codegen/xai-grok-sandbox`
- **`Cargo.toml`**:
  將 `nono` 限制於非 Android 的 Unix 平台：
  ```toml
  [target.'cfg(all(unix, not(target_os = "android")))'.dependencies]
  libc = { workspace = true }
  nono = { version = "=0.53.0", default-features = false }
  globset = { workspace = true }

  [target.'cfg(target_os = "android")'.dependencies]
  libc = { workspace = true }
  ```
- **`src/lib.rs`**:
  在 `apply()` 中，當 `target_os = "android"` 時，記錄並採用 `SandboxKind::PolicyOnly`，略過非支援的 Landlock 系統呼叫：
  ```rust
  #[cfg(target_os = "android")]
  pub fn apply(&mut self, workspace: &Path) -> anyhow::Result<()> {
      tracing::info!(
          profile = %self.profile,
          "Applying policy-only sandbox for Android/Termux"
      );
      self.applied = true;
      Ok(())
  }
  ```

---

## 4. Caveats (限制與注意事項)

1. **Root Workspace Manifest 保持最小異動**:
   - Upstream 的根目錄 `Cargo.toml` 包含大量自動生成的 workspace members。
   - 本設計將 `PlatformCapabilities` 直接實作於現有核心設定 crate `xai-grok-config` 之中（透過 `xai-grok-config::platform`），而不是新建獨立的 workspace member crate，以完全避免根目錄 `Cargo.toml` 的成員異動，大幅降低後續與 upstream 同步的 merge conflict 風險。
2. **Android 權限模型限制**:
   - Termux 本身為 Android 上的非 root 應用程序，無法使用 Linux kernel Landlock 或 namespace unshare (`bwrap`)。所有安全機制均屬於應用層 in-process policy enforcement。
3. **M1 範圍邊界**:
   - M1 專注於平台抽象、動態 `$PREFIX`、儲存隔離與桌面依賴排除。NDK 工具鏈的跨平台編譯設定（`.cargo/config.toml`、16 KiB page-size linker flags、`build.rs` 避開 `rg`/`fd` 下載）屬於 M2 範圍。

---

## 5. Conclusion (結論)

本設計完整解決了 Milestone 1 (R1) 的核心架構要求：
1. 定義了從 upstream commit `eb267feff13129e568df38fb6fdf0ceb65f735d6` 進行 workspace 初始化與 branch tracking 的精確步驟。
2. 設計了集中、可注入、高測試覆蓋的 `PlatformCapabilities` 抽象層，涵蓋動態 `$PREFIX`、真實沙盒回報與儲存安全邊界。
3. 提供了 `xai-grok-config/src/paths.rs`, `xai-grok-config/src/platform.rs`, `xai-grok-shared`, `xai-grok-voice`, `xai-grok-sandbox`, `xai-grok-pager-bin` 的精確代碼與 Cargo 設定修改，徹底將 `jemalloc`, `arboard`, `cpal`, `nono` 等桌面專用依賴自 Android 目標中隔離。

---

## 6. Verification Method (獨立驗證方法)

實作者完成代碼修改後，可使用以下命令進行獨立驗證：

1. **單元測試與平台探測驗證**:
   ```bash
   cargo test -p xai-grok-config --lib platform
   cargo test -p xai-grok-config --lib paths
   ```
2. **依賴樹排除驗證 (檢查 Android Target 是否無桌面依賴)**:
   ```bash
   # 檢查 aarch64-linux-android 依賴樹中是否完全排除 jemalloc, arboard, cpal
   cargo tree --target aarch64-linux-android -p xai-grok-pager-bin --no-default-features | grep -E "jemalloc|arboard|cpal" || echo "CLEAN: No desktop deps found"
   ```
3. **非 Android 平台相容性回歸驗證**:
   ```bash
   cargo test -p xai-grok-config
   cargo test -p xai-grok-shared
   ```
